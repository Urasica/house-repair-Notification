from datetime import UTC, datetime

from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import KnowledgeSet, Result
from app.domain.constants import AccessMode, ErrorCode
from app.schemas.contracts import Context, Session
from app.services.catalog import load_definition


async def session_dto(session, row) -> Session:
    current_result = await session.scalar(
        select(Result.id)
        .where(
            Result.consultation_id == row.id,
            Result.retained_until > datetime.now(UTC),
            Result.payload_json["contextRevision"].as_integer() == row.revision,
        )
        .order_by(Result.created_at.desc(), Result.id.desc())
        .limit(1)
    )
    return Session(
        id=row.id,
        access_mode=AccessMode.MEMBER if row.owner_user_id else AccessMode.GUEST,
        catalog_version=row.catalog_version,
        knowledge_release_id=row.knowledge_set_id,
        revision=row.revision,
        context=Context.model_validate(row.context_json),
        current_result_id=current_result,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


async def pinned_catalog(session, row):
    loaded = await load_definition(session, row.catalog_version)
    if loaded is None:
        raise AppError(ErrorCode.CATALOG_NOT_READY, "목록을 확인할 수 없어요.", 503)
    return loaded[1]


async def latest_knowledge(session, version: str, settings):
    return await session.scalar(
        select(KnowledgeSet.id)
        .where(
            KnowledgeSet.catalog_version == version,
            KnowledgeSet.status == "PUBLISHED",
            KnowledgeSet.published_at <= datetime.now(UTC),
            KnowledgeSet.manifest_json["state"].astext == "COMPLETE_VERIFIED",
            KnowledgeSet.embedding_model == settings.openai_embedding_model,
            KnowledgeSet.embedding_dimensions == settings.embedding_dimensions,
        )
        .order_by(KnowledgeSet.published_at.desc(), KnowledgeSet.id.desc())
        .limit(1)
    )


def check_revision(row, expected: int):
    if row.revision != expected:
        raise AppError(
            ErrorCode.CONTEXT_CONFLICT,
            "입력이 바뀌었어요. 최신 내용을 확인해 주세요.",
            409,
            {"revision": row.revision},
        )
