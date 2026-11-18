from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from test_auth_api import BoundDatabase
from test_database import seed_catalog
from test_knowledge import VECTOR, seed_release, source_fixture
from test_m08a_catalog import CATALOG, answer_unknowns, context_for

from app.core.config import Settings
from app.db.models import KnowledgeChunk
from app.schemas.contracts import Session
from app.services.embeddings import EmbeddedBatch, EmbeddingUnavailable
from app.services.guidance import evaluate_survey
from app.services.knowledge import embed_release, import_bundle, withdraw_source
from app.services.knowledge_source import prepare_source
from app.services.retrieval import revalidate_citations

pytestmark = pytest.mark.integration


class FakeEmbedding:
    def __init__(self):
        self.inputs = []
        self.fail = False

    async def embed(self, texts, **kwargs):
        if self.fail:
            raise EmbeddingUnavailable("test-only")
        self.inputs.extend(texts)
        return EmbeddedBatch([VECTOR for _ in texts], len(texts))


async def test_import_resume_and_metadata_release_reuses_identical_vectors(pg_session, tmp_path):
    sha = source_fixture(tmp_path)
    bundle = prepare_source(tmp_path, sha)
    bundle.manifest["source"] = {
        "observedUrl": "https://example.invalid/source",
        "observedVersion": "test-only",
        "title": "test source",
        "effectiveDate": "2020-01-01",
    }
    catalog = await seed_catalog(pg_session, published=True)
    now = datetime.now(UTC)
    review = {
        "state": "APPROVED",
        "reviewer": "test-only",
        "manifestSha256": sha,
        "catalogVersion": catalog.version,
        "kind": "LAW_CRITERIA",
        "operationalUse": False,
        "housingTypes": ["LH_CONSTRUCTION_RENTAL"],
        "reviewedAt": now.isoformat(),
        "reviewUntil": (now + timedelta(days=1)).isoformat(),
        "referenceTemplate": (
            "선택한 증상과 관련된 법령을 참고할 수 있어요. "
            "이 자료만으로 LH의 보수 대상·비용·교체 여부를 판단할 수는 없어요."
        ),
    }
    catalog_review = {
        "catalogVersion": catalog.version,
        "state": "COMPLETE_VERIFIED",
        "source": {"m08ManifestSha256": sha},
        "articleCoverage": {},
    }
    settings = Settings(_env_file=None)
    first = await import_bundle(pg_session, bundle, catalog_review, review, settings)
    assert (
        await import_bundle(pg_session, bundle, catalog_review, review, settings)
    ).id == first.id
    provider = FakeEmbedding()
    database = BoundDatabase(pg_session)
    assert (await embed_release(database, first.id, provider, settings))["embeddedChunks"] == 49
    assert (await embed_release(database, first.id, provider, settings))["embeddedChunks"] == 0
    review["reviewer"] = "test-review-refreshed"
    second = await import_bundle(pg_session, bundle, catalog_review, review, settings)
    assert second.id != first.id
    assert (await embed_release(database, second.id, provider, settings))["embeddedChunks"] == 0
    assert len(provider.inputs) == 49
    assert (
        await withdraw_source(pg_session, bundle.manifest["source"]["observedUrl"], "test-only")
        == 2
    )
    review["reviewer"] = "attempted-reimport"
    with pytest.raises(ValueError, match="Withdrawn"):
        await import_bundle(pg_session, bundle, catalog_review, review, settings)


async def test_survey_embeds_only_labels_and_withdrawal_blocks_final_save(pg_session):
    release, document, chunk = await seed_release(pg_session)
    release.status = "PUBLISHED"
    release.published_at = datetime.now(UTC)
    await pg_session.flush()
    now = datetime.now(UTC)
    context = answer_unknowns(context_for("leak", "waterproof", "bathroom"))
    context.description = "private@example.com and private address"
    snapshot = Session(
        id=uuid4(),
        access_mode="GUEST",
        catalog_version=release.catalog_version,
        knowledge_release_id=release.id,
        revision=1,
        context=context,
        current_result_id=None,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    settings = Settings(
        _env_file=None,
        openai_enabled=True,
        openai_api_key="test-only",
        openai_chat_model="test-only",
    )
    provider = FakeEmbedding()
    result = await evaluate_survey(
        snapshot, CATALOG, settings, database=BoundDatabase(pg_session), provider=provider
    )
    assert result.status == "NEED_CONFIRMATION"
    assert len(result.reference_examples) == 2
    assert result.citations and all(c.use == "RELATED" for c in result.citations)
    assert all("private" not in t for t in provider.inputs)
    assert await revalidate_citations(pg_session, result, settings)
    assert await withdraw_source(pg_session, document.source_key, "test-only") == 1
    assert not await revalidate_citations(pg_session, result, settings)
    provider.fail = True
    failure = await evaluate_survey(
        snapshot, CATALOG, settings, database=BoundDatabase(pg_session), provider=provider
    )
    assert failure.reason_codes == ["SOURCE_UNAVAILABLE"] and not failure.citations
    assert failure.status == "GUIDANCE_UNAVAILABLE" and not failure.reference_examples
    assert "OpenAI에서 필요한 응답을 받지 못했어요" in failure.guidance[0]
    snapshot.context.answers["immediate-danger"] = "YES"
    safety = await evaluate_survey(
        snapshot, CATALOG, settings, database=BoundDatabase(pg_session), provider=provider
    )
    assert safety.status == "SAFETY_PRIORITY" and not safety.citations


async def test_required_context_hash_and_review_changes_fail_closed(pg_session):
    from test_knowledge import CONTEXT_INPUT

    from app.services.retrieval import retrieve

    release, document, chunk = await seed_release(pg_session)
    parent = KnowledgeChunk(
        document_id=document.id,
        ordinal=1,
        locator="부칙 전체",
        body=chunk.body,
        content_hash=chunk.content_hash,
        embedded_content_hash="f" * 64,
        embedding=VECTOR,
        metadata_json={},
    )
    pg_session.add(parent)
    await pg_session.flush()
    chunk.metadata_json = {**chunk.metadata_json, "contextChunkIds": [str(parent.id)]}
    await pg_session.flush()
    assert not (
        await retrieve(
            pg_session, release.id, VECTOR, Settings(_env_file=None), CONTEXT_INPUT, building=True
        )
    ).evidence
    parent.embedded_content_hash = parent.content_hash
    await pg_session.flush()
    assert (
        await retrieve(
            pg_session, release.id, VECTOR, Settings(_env_file=None), CONTEXT_INPUT, building=True
        )
    ).evidence
    release.embedding_model = "incompatible-model"
    await pg_session.flush()
    assert not (
        await retrieve(
            pg_session, release.id, VECTOR, Settings(_env_file=None), CONTEXT_INPUT, building=True
        )
    ).evidence
