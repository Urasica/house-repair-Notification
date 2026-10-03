from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Catalog as CatalogRow
from app.domain.constants import ErrorCode
from app.schemas.catalog import Catalog, CatalogDefinition


async def load_definition(
    session: AsyncSession,
    version: str | None = None,
) -> tuple[CatalogRow, CatalogDefinition] | None:
    query = select(CatalogRow).where(
        CatalogRow.status == "PUBLISHED", CatalogRow.published_at <= datetime.now(UTC)
    )
    if version is not None:
        query = query.where(CatalogRow.version == version)
    row = await session.scalar(
        query.order_by(CatalogRow.published_at.desc(), CatalogRow.version.desc()).limit(1)
    )
    if row is None:
        return None
    try:
        definition = CatalogDefinition.model_validate(row.payload_json)
        if definition.review.state != "COMPLETE_VERIFIED" or definition.version != row.version:
            return None
        return row, definition
    except ValidationError:
        return None


def public_catalog(row: CatalogRow, definition: CatalogDefinition) -> Catalog:
    return Catalog(
        version=row.version,
        published_at=row.published_at,
        housing_types=definition.housing_types,
        rooms=definition.rooms,
        facilities=definition.facilities,
        symptoms=definition.symptoms,
    )


async def load_catalog(session: AsyncSession, version: str | None = None) -> Catalog | None:
    loaded = await load_definition(session, version)
    return public_catalog(*loaded) if loaded else None


async def require_latest_catalog(session: AsyncSession, version: str) -> CatalogDefinition:
    loaded = await load_definition(session)
    if loaded is None:
        raise AppError(ErrorCode.CATALOG_NOT_READY, "증상 목록을 준비하고 있어요.", 503)
    row, definition = loaded
    if row.version != version:
        raise AppError(
            ErrorCode.CATALOG_UPDATED,
            "목록이 바뀌었어요. 최신 목록으로 시작해 주세요.",
            409,
            {"catalogVersion": row.version},
        )
    return definition


def publication_allowed(definition: CatalogDefinition, settings: Settings):
    if definition.review.state != "COMPLETE_VERIFIED":
        raise AppError(ErrorCode.CATALOG_NOT_READY, "완성 목록의 검토를 먼저 완료해 주세요.", 503)
    if definition.review.reviewed_at > datetime.now(UTC):
        raise AppError(ErrorCode.VALIDATION_ERROR, "검토일은 미래 시각일 수 없어요.", 422)
    identifiers = [
        definition.version,
        definition.review.reviewer,
        *(item.id for item in (*definition.rooms, *definition.facilities, *definition.symptoms)),
        *(question.question_id for question in definition.questions),
    ]
    test_only = any(
        value.lower().startswith(("test-", "test_", "test-only")) for value in identifiers
    )
    if test_only and not (
        settings.app_env == "test"
        and make_url(settings.database_url.get_secret_value()).database == "repair_guide_test"
    ):
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "시험 전용 목록은 공개 DB에 게시할 수 없어요.", 422
        )


async def publish_catalog(
    session: AsyncSession,
    definition: CatalogDefinition,
    settings: Settings,
) -> Catalog:
    """Caller owns the transaction. Replaying identical publication never edits a published row."""
    publication_allowed(definition, settings)
    payload = definition.model_dump(mode="json", by_alias=True)
    await session.execute(
        insert(CatalogRow)
        .values(
            version=definition.version,
            status="DRAFT",
            payload_json=payload,
        )
        .on_conflict_do_nothing(index_elements=["version"])
    )
    row = await session.scalar(
        select(CatalogRow)
        .where(
            CatalogRow.version == definition.version,
        )
        .with_for_update()
    )
    if row.status == "PUBLISHED":
        if row.payload_json != payload:
            raise AppError(
                ErrorCode.CATALOG_UPDATED, "게시된 목록은 새 버전으로 변경해 주세요.", 409
            )
    else:
        row.payload_json = payload
        row.published_at = datetime.now(UTC)
        row.status = "PUBLISHED"
        await session.flush()
    return public_catalog(row, definition)


async def get_catalog(session: AsyncSession, version: str | None = None) -> Catalog:
    catalog = await load_catalog(session, version)
    if catalog is None:
        if version is not None:
            raise AppError(ErrorCode.NOT_FOUND, "목록을 찾을 수 없어요.", 404)
        raise AppError(ErrorCode.CATALOG_NOT_READY, "증상 목록을 준비하고 있어요.", 503)
    return catalog
