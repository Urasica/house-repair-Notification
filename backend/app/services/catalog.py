from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import Catalog as CatalogRow
from app.domain.constants import ErrorCode
from app.schemas.catalog import Catalog, CatalogDefinition


async def load_catalog(session: AsyncSession, version: str | None = None) -> Catalog | None:
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
        return Catalog(
            version=row.version,
            published_at=row.published_at,
            housing_types=definition.housing_types,
            rooms=definition.rooms,
            facilities=definition.facilities,
            symptoms=definition.symptoms,
        )
    except ValidationError:
        return None


async def get_catalog(session: AsyncSession, version: str | None = None) -> Catalog:
    catalog = await load_catalog(session, version)
    if catalog is None:
        if version is not None:
            raise AppError(ErrorCode.NOT_FOUND, "목록을 찾을 수 없어요.", 404)
        raise AppError(ErrorCode.CATALOG_NOT_READY, "증상 목록을 준비하고 있어요.", 503)
    return catalog
