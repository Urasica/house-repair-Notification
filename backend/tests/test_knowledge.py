import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.exc import DBAPIError
from test_database import seed_catalog

from app.core.config import Settings
from app.db.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSet
from app.schemas.contracts import Context
from app.services.embeddings import Embeddings, EmbeddingUnavailable
from app.services.knowledge import (
    publish_release,
    release_fingerprint,
    release_rows,
    withdraw_source,
)
from app.services.knowledge_source import ARTICLES, CONTEXT, RELATIONS, digest, prepare_source
from app.services.retrieval import question_purpose, retrieve


def source_fixture(path):
    def write(name, value):
        (path / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    paragraphs = [f"{key}(시험 조문) 본문. 단서와 예외를 보존한다." for key in ARTICLES]
    write("law-paragraphs.json", paragraphs)
    (path / "organized.md").write_text(
        "\n".join(
            f"## {key}(시험)\n```text\n{body}\n```"
            for key, body in zip(ARTICLES, paragraphs, strict=True)
        ),
        encoding="utf-8",
    )
    (path / "context.md").write_text(
        "\n".join(f"## {key}\n```text\n적용 조건 {key}\n```" for key in CONTEXT), encoding="utf-8"
    )
    coverage = [
        {
            "id": key,
            "acquired": True,
            "organized": True,
            "complete": True,
            "missing": [],
            "sourceParagraphRange": [i + 1, i + 1],
            "sha256": digest(paragraphs[i]),
            "relatedAnnexes": {"제10조": [2], "제42조": [3], "제43조": [4]}.get(key, []),
        }
        for i, key in enumerate(ARTICLES)
    ]
    coverage += [
        {
            "id": f"별표 {n}",
            "acquired": True,
            "organized": True,
            "complete": True,
            "missing": [],
            "dataRows": 1,
            "footnotes": 1,
            "sourceFile": f"appendix-{n}.pdf",
        }
        for n in [2, 3, 4]
    ]
    write("coverage.json", coverage)
    write(
        "verification.json",
        {
            "status": "PASS",
            "missing": [],
            "checks": [{"id": c["id"], "passed": True} for c in coverage],
        },
    )
    write("external-references.json", [{"article": "제45조", "references": ["외부 기준"]}])
    write(
        "annexes-organized.json",
        [{"number": n, "rows": [["단위 mm", "예외"]], "footnotes": ["비고"]} for n in [2, 3, 4]],
    )
    manifest = {
        "schemaVersion": 1,
        "status": "COMPLETE_VERIFIED",
        "missing": [],
        "articles": ARTICLES,
        "relations": RELATIONS,
        "reviewer": "test-only",
        "reviewedAt": "2026-01-01T00:00:00Z",
        "documentKind": "LAW_CRITERIA",
        "annexes": [{"number": n} for n in [2, 3, 4]],
        "files": [
            {"path": f.name, "bytes": len(f.read_bytes()), "sha256": digest(f.read_bytes())}
            for f in path.iterdir()
        ],
    }
    write("manifest.json", manifest)
    return digest((path / "manifest.json").read_bytes())


def test_complete_source_preserves_full_articles_annexes_and_context(tmp_path):
    sha = source_fixture(tmp_path)
    bundle = prepare_source(tmp_path, sha)
    assert len(bundle.chunks) == 49
    leak = next(c for c in bundle.chunks if c["locator"] == "제10조")
    assert leak["metadata"]["relatedLocators"] == ["별표 2"]
    assert leak["metadata"]["contextLocators"] == CONTEXT
    assert "단서와 예외" in leak["body"]
    annex = next(c for c in bundle.chunks if c["locator"] == "별표 2")
    assert json.loads(annex["body"])["footnotes"] == ["비고"]


@pytest.mark.parametrize("change", ["file", "status", "missing", "scope", "escape", "duplicate"])
def test_source_gate_rejects_incomplete_tampered_or_unsafe_input(tmp_path, change):
    sha = source_fixture(tmp_path)
    p = tmp_path / "manifest.json"
    manifest = json.loads(p.read_bytes())
    if change == "file":
        (tmp_path / "organized.md").write_text("changed", encoding="utf-8")
    elif change == "status":
        manifest["status"] = "DRAFT"
    elif change == "missing":
        manifest["missing"] = ["제7조"]
    elif change == "scope":
        manifest["articles"] = ARTICLES[:-1]
    elif change == "duplicate":
        manifest["files"].append(manifest["files"][0])
    else:
        manifest["files"][0]["path"] = "../outside.txt"
    if change != "file":
        p.write_text(json.dumps(manifest), encoding="utf-8")
        sha = digest(p.read_bytes())
    with pytest.raises((ValueError, OSError)):
        prepare_source(tmp_path, sha)


@pytest.mark.parametrize(
    "question,purpose",
    [
        ("제10조와 별표 2 내용을 설명해 주세요", "LAW_EXPLANATION"),
        ("제10조 내용을 설명하고 비용도 알려 주세요", "OPERATION"),
        ("이거 어떻게 하나요?", "OPERATION"),
        ("제7조상 LH가 무료로 해 주나요?", "OPERATION"),
    ],
)
def test_purpose_is_conservative(question, purpose):
    assert question_purpose(question) == purpose


@pytest.mark.parametrize("failure", ["status", "model", "dimension", "nan", "index"])
async def test_embedding_rejects_provider_errors_and_invalid_responses_without_retry(failure):
    calls = []

    def handle(request):
        calls.append(request)
        if failure == "status":
            return httpx.Response(429, text="private provider details")
        data = {
            "model": "text-embedding-3-large",
            "data": [{"index": 0, "embedding": [1.0] + [0.0] * 1535}],
            "usage": {"total_tokens": 1},
        }
        if failure == "model":
            data["model"] = "other"
        if failure == "dimension":
            data["data"][0]["embedding"] = [1.0]
        if failure == "nan":
            data["data"][0]["embedding"][0] = "NaN"
        if failure == "index":
            data["data"][0]["index"] = 1
        return httpx.Response(200, json=data)

    settings = Settings(
        _env_file=None,
        openai_enabled=True,
        openai_api_key="test-only",
        openai_chat_model="test-only",
    )
    with pytest.raises(EmbeddingUnavailable) as caught:
        await Embeddings(settings, transport=httpx.MockTransport(handle)).embed(["한국어"])
    assert len(calls) == 1
    assert "private" not in str(caught.value)


async def test_embedding_off_and_oversize_never_call_network():
    def forbidden(request):
        raise AssertionError("network called")

    settings = Settings(_env_file=None)
    with pytest.raises(EmbeddingUnavailable, match="OPENAI_DISABLED"):
        await Embeddings(settings, transport=httpx.MockTransport(forbidden)).embed(["test"])
    settings = Settings(
        _env_file=None, openai_enabled=True, openai_api_key="test", openai_chat_model="test"
    )
    with pytest.raises(EmbeddingUnavailable, match="INPUT_LIMIT"):
        await Embeddings(settings, transport=httpx.MockTransport(forbidden)).embed(["한" * 3000])


async def seed_release(session, kind="LAW_CRITERIA", operation=False, catalog=None):
    catalog = catalog or await seed_catalog(session, published=True)
    now = datetime.now(UTC)
    release = KnowledgeSet(
        catalog_version=catalog.version,
        status="BUILDING",
        embedding_model="text-embedding-3-large",
        embedding_dimensions=1536,
        manifest_json={"state": "COMPLETE_VERIFIED"},
    )
    session.add(release)
    await session.flush()
    body = "Full reviewed text"
    doc = KnowledgeDocument(
        knowledge_set_id=release.id,
        source_key="test-m09",
        version_label="v1",
        kind=kind,
        title="test",
        url="https://example.invalid/law",
        normalized_text=body,
        content_hash=digest(body),
        scope_json={"housingTypes": ["LH_CONSTRUCTION_RENTAL"], "operationalUse": operation},
        reviewed_at=now - timedelta(days=2),
        review_until=now + timedelta(days=1),
        reviewer_key="test-only",
        status="APPROVED",
    )
    session.add(doc)
    await session.flush()
    chunk = KnowledgeChunk(
        document_id=doc.id,
        ordinal=0,
        locator="제10조",
        body=body,
        content_hash=digest(body),
        embedded_content_hash=digest(body),
        embedding=[1.0] + [0.0] * 1535,
        metadata_json={
            "role": "ARTICLE",
            "symptomIds": ["leak"],
            "explanationAllowed": True,
            "relatedChunkIds": [],
            "contextChunkIds": [],
        },
    )
    session.add(chunk)
    await session.flush()
    return release, doc, chunk


CONTEXT_INPUT = Context(housing_type="LH_CONSTRUCTION_RENTAL", symptom_id="leak")
VECTOR = [1.0] + [0.0] * 1535


@pytest.mark.integration
async def test_real_exact_search_law_purpose_annex_and_filters(pg_session):
    release, doc, chunk = await seed_release(pg_session)
    settings = Settings(_env_file=None)
    found = await retrieve(pg_session, release.id, VECTOR, settings, CONTEXT_INPUT, building=True)
    assert found.status == "NEED_CONFIRMATION" and found.citations()[0].use == "RELATED"
    law = await retrieve(
        pg_session,
        release.id,
        VECTOR,
        settings,
        CONTEXT_INPUT,
        purpose="LAW_EXPLANATION",
        question="제10조 설명",
        building=True,
    )
    assert law.status == "GUIDANCE_AVAILABLE" and law.citations()[0].use == "APPLICABLE"
    incomplete = await retrieve(
        pg_session,
        release.id,
        VECTOR,
        settings,
        CONTEXT_INPUT,
        purpose="LAW_EXPLANATION",
        question="제10조와 제99조 설명",
        building=True,
    )
    assert incomplete.status == "NEED_CONFIRMATION"
    assert all(c.use == "RELATED" for c in incomplete.citations())
    chunk.metadata_json = {**chunk.metadata_json, "relatedChunkIds": [str(uuid4())]}
    await pg_session.flush()
    assert not (
        await retrieve(pg_session, release.id, VECTOR, settings, CONTEXT_INPUT, building=True)
    ).evidence
    chunk.metadata_json = {**chunk.metadata_json, "relatedChunkIds": []}
    await pg_session.flush()
    doc.review_until = datetime.now(UTC) - timedelta(days=1)
    await pg_session.flush()
    assert not (
        await retrieve(pg_session, release.id, VECTOR, settings, CONTEXT_INPUT, building=True)
    ).evidence


@pytest.mark.integration
async def test_operational_conditions_and_conflict_override_vector_rank(pg_session):
    release, doc, chunk = await seed_release(pg_session, "LH_OPERATION", True)
    rule = {
        "conditions": {"answers.cause": "AGING"},
        "guidance": ["검토된 안내 문구"],
        "conflictKey": "same-rule",
    }
    chunk.metadata_json = {**chunk.metadata_json, "operationRule": rule}
    await pg_session.flush()
    settings = Settings(_env_file=None)
    assert (
        await retrieve(pg_session, release.id, VECTOR, settings, CONTEXT_INPUT, building=True)
    ).status == "NEED_CONFIRMATION"
    context = CONTEXT_INPUT.model_copy(update={"answers": {"cause": "AGING"}})
    assert (
        await retrieve(pg_session, release.id, VECTOR, settings, context, building=True)
    ).status == "GUIDANCE_AVAILABLE"
    other = KnowledgeChunk(
        document_id=doc.id,
        ordinal=1,
        locator="제11조",
        body=chunk.body,
        content_hash=chunk.content_hash,
        embedded_content_hash=chunk.content_hash,
        embedding=VECTOR,
        metadata_json={
            **chunk.metadata_json,
            "operationRule": {**rule, "guidance": ["상충하는 안내 문구"]},
        },
    )
    pg_session.add(other)
    await pg_session.flush()
    assert (
        await retrieve(pg_session, release.id, VECTOR, settings, context, building=True)
    ).reason == "SOURCE_CONFLICT"


@pytest.mark.integration
async def test_publish_gate_immutability_and_source_wide_withdrawal(pg_session):
    release, doc, chunk = await seed_release(pg_session)
    with pytest.raises(ValueError):
        await publish_release(pg_session, release.id, {})
    report = {
        "releaseId": str(release.id),
        "fingerprint": release_fingerprint(await release_rows(pg_session, release.id)),
        "embeddingModel": release.embedding_model,
        "embeddingDimensions": 1536,
        "provider": "OPENAI",
        "recallAt5": 1,
        "statusAccuracy": 1,
        "unsafeDecisions": 0,
        "cases": [{"id": "test-only"}],
        "reviewer": "test-only",
    }
    release.manifest_json = {**release.manifest_json, "evaluation": report}
    await pg_session.flush()
    await publish_release(pg_session, release.id, report)
    release_id = release.id
    for model, identifier, field, value in [
        (KnowledgeChunk, chunk.id, "body", "changed"),
        (KnowledgeDocument, doc.id, "normalized_text", "changed"),
        (KnowledgeSet, release.id, "embedding_model", "changed"),
    ]:
        with pytest.raises(DBAPIError):
            async with pg_session.begin_nested():
                row = await pg_session.get(model, identifier)
                setattr(row, field, value)
                await pg_session.flush()
    assert await withdraw_source(pg_session, "test-m09", "test withdrawal") == 1
    assert not (
        await retrieve(pg_session, release_id, VECTOR, Settings(_env_file=None), CONTEXT_INPUT)
    ).evidence
