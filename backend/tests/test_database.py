import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import DataError, IntegrityError

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (
    AuthSession,
    Base,
    Catalog,
    Consultation,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSet,
    Message,
    QuestionRecord,
    RequestRun,
    Result,
    User,
)
from app.db.requests import RequestRepository, request_fingerprint
from app.domain.constants import ErrorCode, RequestKind
from app.main import create_app
from app.services.catalog import get_catalog
from app.services.readiness import get_readiness

pytestmark = pytest.mark.integration


async def seed_catalog(session, *, published=False):
    payload = json.loads(
        (Path(__file__).parent / "fixtures/catalog.test.json").read_text(encoding="utf-8")
    )
    now = datetime.now(UTC)
    if published:
        payload["review"] = {
            "state": "COMPLETE_VERIFIED",
            "reviewer": "test-only",
            "reviewedAt": now.isoformat(),
        }
    row = Catalog(
        version=payload["version"],
        status="PUBLISHED" if published else "DRAFT",
        payload_json=payload,
        published_at=now - timedelta(seconds=1) if published else None,
    )
    session.add(row)
    await session.flush()
    return row


async def seed_consultation(session, *, member=False):
    catalog = await seed_catalog(session)
    user = None
    if member:
        user = User(normalized_email="test@example.invalid", password_hash="test-only")
        session.add(user)
        await session.flush()
    consultation = Consultation(
        owner_user_id=user.id if user else None,
        guest_token_hash=None if member else "a" * 64,
        catalog_version=catalog.version,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    session.add(consultation)
    await session.flush()
    return consultation, user


async def seed_knowledge(session):
    catalog = await seed_catalog(session, published=True)
    now = datetime.now(UTC)
    knowledge = KnowledgeSet(
        catalog_version=catalog.version,
        status="PUBLISHED",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        manifest_json={"state": "COMPLETE_VERIFIED"},
        published_at=now - timedelta(seconds=1),
    )
    session.add(knowledge)
    await session.flush()
    document = KnowledgeDocument(
        knowledge_set_id=knowledge.id,
        source_key="test-only-source",
        version_label="test-v1",
        kind="LH_OPERATION",
        title="시험 문서",
        url="https://example.invalid/test",
        normalized_text="시험 전용 문장",
        content_hash="b" * 64,
        scope_json={},
        reviewed_at=now - timedelta(days=2),
        review_until=now + timedelta(days=1),
        reviewer_key="test-only",
        status="APPROVED",
    )
    session.add(document)
    await session.flush()
    chunk = KnowledgeChunk(
        document_id=document.id,
        ordinal=0,
        locator="test-only",
        body="시험 청크",
        content_hash="c" * 64,
        embedded_content_hash="c" * 64,
        embedding=[1.0] + [0.0] * 1535,
        metadata_json={},
    )
    session.add(chunk)
    await session.flush()
    return knowledge, document, chunk


async def test_real_schema_has_twelve_tables_vector_and_limited_app_role(pg_database):
    async with pg_database.engine.connect() as connection:
        tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        assert set(tables) == set(Base.metadata.tables) | {"alembic_version"}
        assert await connection.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname='vector'")
        )
        assert not await connection.scalar(
            text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
        )
        assert not await connection.scalar(
            text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
        )
        columns = await connection.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid='knowledge_chunks'::regclass AND attname='embedding'"
            )
        )
        assert columns.scalar_one() == "vector(1536)"


@pytest.mark.parametrize("has_owner,has_guest", [(False, False), (True, True)])
async def test_consultation_has_exactly_one_owner(pg_session, has_owner, has_guest):
    consultation, user = await seed_consultation(pg_session, member=True)
    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            pg_session.add(
                Consultation(
                    catalog_version=consultation.catalog_version,
                    owner_user_id=user.id if has_owner else None,
                    guest_token_hash="b" * 64 if has_guest else None,
                    expires_at=datetime.now(UTC) + timedelta(hours=24),
                )
            )
            await pg_session.flush()


async def test_unknown_catalog_and_negative_revision_are_rejected(pg_session):
    await seed_catalog(pg_session)
    for version, revision in (("missing", 0), ("test-only-v1", -1)):
        with pytest.raises(IntegrityError):
            async with pg_session.begin_nested():
                pg_session.add(
                    Consultation(
                        catalog_version=version,
                        guest_token_hash="b" * 64,
                        revision=revision,
                        expires_at=datetime.now(UTC) + timedelta(hours=24),
                    )
                )
                await pg_session.flush()


async def test_consultation_delete_keeps_member_history_and_long_term_question(pg_session):
    consultation, user = await seed_consultation(pg_session, member=True)
    run = RequestRun(
        consultation_id=consultation.id,
        request_id=uuid4(),
        kind="CHAT",
        request_hash="b" * 64,
    )
    question = QuestionRecord(
        consultation_id=consultation.id,
        owner_user_id=user.id,
        origin_key="test-only-request",
        kind="CHAT",
        catalog_version=consultation.catalog_version,
        answers_json={},
        masked_question="식별정보 없는 시험 질문",
        retrieval_meta_json={},
        retained_until=datetime.now(UTC) + timedelta(days=365 * 5),
    )
    pg_session.add_all([run, question])
    await pg_session.flush()
    result = Result(
        consultation_id=consultation.id,
        owner_user_id=user.id,
        request_run_id=run.id,
        question_record_id=question.id,
        input_snapshot_json={},
        payload_json={"saved": True},
        retained_until=question.retained_until,
    )
    pg_session.add_all(
        [
            result,
            Message(
                consultation_id=consultation.id,
                request_run_id=run.id,
                role="USER",
                content="시험",
                citations_json=[],
            ),
        ]
    )
    await pg_session.flush()
    await pg_session.execute(delete(Consultation).where(Consultation.id == consultation.id))
    await pg_session.refresh(result)
    await pg_session.refresh(question)
    kept_result = result
    kept_question = question
    assert kept_result.consultation_id is None and kept_result.request_run_id is None
    assert kept_result.owner_user_id == user.id and kept_result.payload_json == {"saved": True}
    assert kept_question.consultation_id is None and kept_question.owner_user_id == user.id
    assert await pg_session.scalar(select(func.count()).select_from(RequestRun)) == 0
    assert await pg_session.scalar(select(func.count()).select_from(Message)) == 0
    await pg_session.execute(delete(QuestionRecord).where(QuestionRecord.id == kept_question.id))
    await pg_session.refresh(kept_result)
    assert kept_result.question_record_id is None


async def test_account_auth_is_cascade_but_history_requires_explicit_cleanup(pg_session):
    consultation, user = await seed_consultation(pg_session, member=True)
    auth = AuthSession(
        user_id=user.id, token_hash="c" * 64, csrf_hash="d" * 64, expires_at=consultation.expires_at
    )
    pg_session.add(auth)
    await pg_session.flush()
    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            await pg_session.execute(delete(User).where(User.id == user.id))
    user_id = user.id
    await pg_session.execute(delete(Consultation).where(Consultation.id == consultation.id))
    await pg_session.execute(delete(User).where(User.id == user_id))
    assert await pg_session.scalar(select(func.count()).select_from(AuthSession)) == 0


async def test_request_replay_conflicts_and_failed_request_cannot_restart(pg_session):
    consultation, _ = await seed_consultation(pg_session)
    repository = RequestRepository()
    request_id = uuid4()
    fingerprint = request_fingerprint(RequestKind.SURVEY, {"expectedRevision": 0})
    reservation = await repository.reserve(
        pg_session, consultation.id, request_id, RequestKind.SURVEY, fingerprint
    )
    for kind, digest, expected in (
        (RequestKind.SURVEY, fingerprint, ErrorCode.REQUEST_IN_PROGRESS),
        (RequestKind.CHAT, fingerprint, ErrorCode.IDEMPOTENCY_CONFLICT),
        (RequestKind.SURVEY, "d" * 64, ErrorCode.IDEMPOTENCY_CONFLICT),
    ):
        with pytest.raises(AppError) as error:
            await repository.reserve(pg_session, consultation.id, request_id, kind, digest)
        assert error.value.code == expected
    await repository.complete(pg_session, reservation.run_id, {"id": "saved-once"})
    replay = await repository.reserve(
        pg_session, consultation.id, request_id, RequestKind.SURVEY, fingerprint
    )
    assert replay.is_replay and replay.replay == {"id": "saved-once"}
    assert not await repository.fail(pg_session, reservation.run_id)
    failed = await repository.reserve(
        pg_session, consultation.id, uuid4(), RequestKind.SURVEY, fingerprint
    )
    assert await repository.fail(pg_session, failed.run_id)
    with pytest.raises(AppError):
        await repository.complete(pg_session, failed.run_id, {"late": True})
    row = await pg_session.get(RequestRun, failed.run_id)
    assert row.state == "FAILED" and row.response_json is None
    with pytest.raises(AppError) as error:
        await repository.reserve(
            pg_session, consultation.id, row.request_id, RequestKind.SURVEY, fingerprint
        )
    assert error.value.code == ErrorCode.REQUEST_FAILED
    assert await pg_session.scalar(select(func.count()).select_from(RequestRun)) == 2


async def test_completion_and_question_result_are_one_transaction(pg_session):
    consultation, _ = await seed_consultation(pg_session)
    repository = RequestRepository()
    reservation = await repository.reserve(
        pg_session, consultation.id, uuid4(), RequestKind.SURVEY, "b" * 64
    )
    with pytest.raises(RuntimeError):
        async with pg_session.begin_nested():
            question = QuestionRecord(
                consultation_id=consultation.id,
                origin_key="atomic-test",
                kind="SURVEY",
                catalog_version=consultation.catalog_version,
                answers_json={},
                retrieval_meta_json={},
                retained_until=datetime.now(UTC) + timedelta(days=365 * 5),
            )
            pg_session.add(question)
            await pg_session.flush()
            pg_session.add(
                Result(
                    consultation_id=consultation.id,
                    request_run_id=reservation.run_id,
                    question_record_id=question.id,
                    input_snapshot_json={},
                    payload_json={},
                    retained_until=question.retained_until,
                )
            )
            await pg_session.flush()
            await repository.complete(pg_session, reservation.run_id, {"stored": True})
            raise RuntimeError("Simulated interruption before commit")
    assert (
        await pg_session.scalar(select(RequestRun.state).where(RequestRun.id == reservation.run_id))
        == "PROCESSING"
    )
    assert await pg_session.scalar(select(func.count()).select_from(Result)) == 0
    assert await pg_session.scalar(select(func.count()).select_from(QuestionRecord)) == 0
    assert await repository.fail_interrupted(pg_session) == 1


async def test_unique_origin_and_message_role_prevent_duplicate_statistics(pg_session):
    consultation, _ = await seed_consultation(pg_session)
    run = RequestRun(
        consultation_id=consultation.id, request_id=uuid4(), kind="CHAT", request_hash="b" * 64
    )
    pg_session.add(run)
    await pg_session.flush()
    for _ in range(2):
        try:
            async with pg_session.begin_nested():
                pg_session.add(
                    Message(
                        consultation_id=consultation.id,
                        request_run_id=run.id,
                        role="USER",
                        content="시험",
                        citations_json=[],
                    )
                )
                await pg_session.flush()
        except IntegrityError:
            break
    assert await pg_session.scalar(select(func.count()).select_from(Message)) == 1
    question_values = dict(
        origin_key="unique-origin",
        kind="SURVEY",
        catalog_version=consultation.catalog_version,
        answers_json={},
        retrieval_meta_json={},
        retained_until=datetime.now(UTC) + timedelta(days=365 * 5),
    )
    pg_session.add(QuestionRecord(**question_values))
    await pg_session.flush()
    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            pg_session.add(QuestionRecord(**question_values))
            await pg_session.flush()


async def test_catalog_only_exposes_verified_published_payload_and_utc(pg_session):
    catalog = await seed_catalog(pg_session)
    with pytest.raises(AppError):
        await get_catalog(pg_session)
    catalog.status = "PUBLISHED"
    catalog.published_at = datetime.now(UTC) - timedelta(seconds=1)
    await pg_session.flush()
    with pytest.raises(AppError):
        await get_catalog(pg_session)
    payload = dict(catalog.payload_json)
    payload["review"] = {
        "state": "COMPLETE_VERIFIED",
        "reviewer": "test-only",
        "reviewedAt": datetime.now(UTC).isoformat(),
    }
    catalog.payload_json = payload
    await pg_session.flush()
    response = await get_catalog(pg_session)
    data = response.model_dump(mode="json", by_alias=True)
    assert data["publishedAt"].endswith("Z")
    assert "questions" not in data and "review" not in data
    assert (await get_readiness(pg_session, Settings(_env_file=None))).catalog_ready


@pytest.mark.parametrize(
    "invalidity", ["expired", "withdrawn", "stale-hash", "building", "wrong-model", "unverified"]
)
async def test_rag_readiness_filters_ineligible_sources(pg_session, invalidity):
    knowledge, document, chunk = await seed_knowledge(pg_session)
    settings = Settings(
        _env_file=None,
        openai_enabled=True,
        openai_api_key="test-only",
        openai_chat_model="test-only",
    )
    assert (await get_readiness(pg_session, settings)).rag_ready
    if invalidity == "expired":
        document.review_until = datetime.now(UTC) - timedelta(days=1)
    elif invalidity == "withdrawn":
        document.status = "WITHDRAWN"
        document.withdrawn_at = datetime.now(UTC)
        document.withdrawal_reason = "test-only"
    elif invalidity == "stale-hash":
        chunk.embedded_content_hash = "d" * 64
    elif invalidity == "building":
        knowledge.status = "BUILDING"
    elif invalidity == "wrong-model":
        knowledge.embedding_model = "different-test-model"
    else:
        knowledge.manifest_json = {"state": "DRAFT"}
    await pg_session.flush()
    assert not (await get_readiness(pg_session, settings)).rag_ready


async def test_actual_pgvector_cosine_and_dimension(pg_session):
    _, _, chunk = await seed_knowledge(pg_session)
    distance = await pg_session.scalar(
        select(KnowledgeChunk.embedding.cosine_distance([1.0] + [0.0] * 1535))
    )
    assert distance == pytest.approx(0.0)
    assert len(chunk.embedding) == 1536
    with pytest.raises(DataError):
        async with pg_session.begin_nested():
            await pg_session.execute(
                text("UPDATE knowledge_chunks SET embedding='[1,0]'::vector WHERE id=:id"),
                {"id": chunk.id},
            )


async def test_public_api_uses_real_database_and_reports_empty_catalog(pg_database):
    app = create_app(Settings(_env_file=None), pg_database)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ready = await client.get("/health/ready")
            assert ready.status_code == 200
            assert ready.json() == {"status": "ok", "catalogReady": False, "ragReady": False}
            catalog = await client.get("/api/v1/catalog")
            assert (
                catalog.status_code == 503
                and catalog.json()["error"]["code"] == "CATALOG_NOT_READY"
            )
