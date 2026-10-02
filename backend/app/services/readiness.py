from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSet
from app.schemas.contracts import Readiness
from app.services.catalog import load_catalog


async def get_readiness(session: AsyncSession, settings: Settings) -> Readiness:
    catalog = await load_catalog(session)
    rag_ready = False
    if catalog is not None and settings.openai_enabled:
        ready_chunk = (
            select(KnowledgeChunk.id)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(KnowledgeSet, KnowledgeSet.id == KnowledgeDocument.knowledge_set_id)
            .where(
                KnowledgeSet.catalog_version == catalog.version,
                KnowledgeSet.status == "PUBLISHED",
                KnowledgeSet.published_at <= datetime.now(UTC),
                KnowledgeSet.embedding_model == settings.openai_embedding_model,
                KnowledgeSet.embedding_dimensions == settings.embedding_dimensions,
                KnowledgeSet.manifest_json["state"].astext == "COMPLETE_VERIFIED",
                KnowledgeDocument.status == "APPROVED",
                KnowledgeDocument.reviewed_at <= datetime.now(UTC),
                KnowledgeDocument.review_until > datetime.now(UTC),
                KnowledgeChunk.embedding.is_not(None),
                KnowledgeChunk.content_hash == KnowledgeChunk.embedded_content_hash,
            )
            .limit(1)
        )
        rag_ready = await session.scalar(ready_chunk) is not None
    return Readiness(status="ok", catalog_ready=catalog is not None, rag_ready=rag_ready)
