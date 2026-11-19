# ruff: noqa: F811
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from test_auth_api import ORIGIN, BoundDatabase
from test_chat import enabled
from test_consultation_api import (
    evaluation,
    fill,
    start,
    survey_client,  # noqa: F401
)
from test_knowledge import seed_release
from test_knowledge_runtime import FakeEmbedding
from test_m08a_catalog import CATALOG

from app.db.models import ChatUsage, Consultation, Message, QuestionRecord, Result, User
from app.schemas.contracts import Context, Session
from app.services.catalog import publish_catalog
from app.services.chat import chat_response
from app.services.chat_context import chat_policy, confirmed_context
from app.services.retrieval import LAW_EXPLANATIONS


def test_chat_confirms_own_context_without_survey_answers():
    old = Context(answers={"not-a-chat-answer": "RISK"}, description="private")
    context = confirmed_context(old, "LH 건설임대", CATALOG)
    assert context.housing_type == "LH_CONSTRUCTION_RENTAL"
    assert context.answers == {} and context.description == ""
    assert old.answers  # The source object was not mutated.
    ambiguous = confirmed_context(Context(), "건설임대인지 모르겠어요", CATALOG)
    assert ambiguous.housing_type is None
    status, questions, _ = chat_policy(Context(), "제10조 내용을 알려 주세요")
    assert status == "NEED_CONFIRMATION" and questions == []
    status, questions, _ = chat_policy(Context(), "시설물이 고장났어요")
    assert status == "NEED_MORE_INFO" and all("설문" not in q for q in questions)
    unknown = confirmed_context(Context(), "모르겠어요", CATALOG)
    status, questions, _ = chat_policy(unknown, "모르겠어요")
    assert unknown.housing_type == "UNKNOWN" and status == "NEED_CONFIRMATION" and not questions


def test_everyday_leakage_is_confirmed_without_catalog_phrasing_or_negative_guessing():
    context = confirmed_context(
        Context(), "LH 건설임대주택이에요. 주방 싱크대 아래 배관에서 물이 새요.", CATALOG
    )
    assert (context.room_id, context.facility_id, context.symptom_id) == ("kitchen", "pipe", "leak")
    assert chat_policy(context, "어떻게 하나요?")[0] == "NEED_CONFIRMATION"
    negative = confirmed_context(Context(), "주방 배관에서 물이 새지 않아요", CATALOG)
    assert negative.symptom_id is None
    partial = confirmed_context(Context(), "물이 새요", CATALOG)
    assert partial.symptom_id == "leak"
    follow_up = confirmed_context(partial, "주방 배관이에요", CATALOG)
    assert follow_up.symptom_id == "leak" and follow_up.facility_id == "pipe"


@pytest.mark.integration
async def test_ceiling_leak_followups_use_symptom_reference_without_guessing_cause(pg_session):
    settings = enabled()
    catalog = await publish_catalog(pg_session, CATALOG, settings)
    release, _, _ = await seed_release(pg_session, catalog=catalog)
    now = datetime.now(UTC)
    release.status, release.published_at = "PUBLISHED", now
    await pg_session.flush()
    snapshot = Session(
        id=uuid4(),
        purpose="CHAT",
        access_mode="MEMBER",
        catalog_version=catalog.version,
        knowledge_release_id=release.id,
        revision=0,
        context=Context(),
        current_result_id=None,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    embeddings = FakeEmbedding()
    generator = AsyncMock()
    turns = (
        ("집 천장에서 물이 새고 있어", None),
        ("LH 건설임대야 거실 천장", "문제가 보이는 위치"),
        ("거실 천장", "문제가 보이는 위치"),
        (
            "비가 올 때만 그래요. 연락처는 private@example.com이에요.",
            "비가 올 때만 물이 보였다는 점",
        ),
        ("비가 안 올 때도 물자국이 보여요.", "비가 오지 않을 때도 물자국이 보였다는 점"),
        ("비가 올 때만 새는 건 아니에요.", "문제가 보이는 위치"),
    )
    for content, expected in turns:
        snapshot.context = confirmed_context(snapshot.context, content, CATALOG)
        response = await chat_response(
            snapshot,
            CATALOG,
            settings,
            content,
            uuid4(),
            [],
            database=BoundDatabase(pg_session),
            embeddings=embeddings,
            generator=generator,
        )
        if snapshot.context.housing_type is None:
            assert response.answer_mode == "CLARIFY" and len(response.follow_up_questions) == 1
            assert "주택 유형" in response.follow_up_questions[0]
            assert not embeddings.inputs
        else:
            assert snapshot.context.room_id == "living" and snapshot.context.symptom_id == "leak"
            assert snapshot.context.facility_id is None
            assert response.status == "NEED_CONFIRMATION" and not response.follow_up_questions
            assert expected in response.assistant_message.content
            citation = response.assistant_message.citations[0]
            assert citation.locator == "제10조" and citation.use == "RELATED"
    assert len(embeddings.inputs) == 5
    assert all(
        "천장" not in query and "private@example.com" not in query for query in embeddings.inputs
    )
    assert "비가 올 때 새어요" in embeddings.inputs[2]
    assert "비가 오지 않을 때도 물자국이 보여요" in embeddings.inputs[3]
    assert embeddings.inputs[0] == embeddings.inputs[4]
    generator.generate.assert_not_awaited()


@pytest.mark.integration
async def test_opt_in_survey_import_checks_consent_scope_revision_and_keeps_answers(survey_client):
    client, _ = survey_client
    survey, headers, _ = await start(client, member=True)
    survey = await fill(client, survey, headers, description="private free text")
    result, _ = await evaluation(client, survey, headers)
    chat = (
        await client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"catalogVersion": survey["catalogVersion"], "purpose": "CHAT"},
        )
    ).json()["session"]
    base = f"/api/v1/sessions/{chat['id']}"
    assert chat["context"]["answers"] == {}
    body = {"resultId": result.json()["id"], "expectedRevision": 0}
    assert (
        await client.post(
            base + "/chat/survey-context",
            json=body,
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        )
    ).status_code == 403
    loaded = await client.post(base + "/chat/survey-context", json=body, headers=headers)
    assert loaded.status_code == 200
    saved = loaded.json()
    assert saved["revision"] == 1 and saved["context"]["description"] == ""
    assert saved["context"]["answers"] == survey["context"]["answers"]
    assert (
        await client.post(base + "/chat/survey-context", json=body, headers=headers)
    ).status_code == 409
    reply = await client.post(
        base + "/chat/messages",
        headers=headers,
        json={"requestId": str(uuid4()), "expectedRevision": 1, "content": "어떻게 확인하나요?"},
    )
    assert reply.status_code == 200 and reply.json()["answerMode"] != "CLARIFY"
    assert (await client.get(base, headers=headers)).json()["context"]["answers"] == survey[
        "context"
    ]["answers"]
    assert (await client.get(f"/api/v1/sessions/{survey['id']}", headers=headers)).json()[
        "context"
    ] == survey["context"]


@pytest.mark.integration
@pytest.mark.parametrize("unavailable", ["other_owner", "guest", "expired", "catalog"])
async def test_survey_import_rejects_inaccessible_or_incompatible_sources(
    survey_client, pg_session, unavailable
):
    client, _ = survey_client
    survey, headers, _ = await start(client, member=True)
    survey = await fill(client, survey, headers)
    result, _ = await evaluation(client, survey, headers)
    row = await pg_session.get(Result, result.json()["id"])
    if unavailable == "other_owner":
        user = User(normalized_email="other-import@example.com", password_hash="test-only")
        pg_session.add(user)
        await pg_session.flush()
        row.owner_user_id = user.id
    elif unavailable == "guest":
        row.owner_user_id = None
    elif unavailable == "expired":
        row.retained_until = datetime.now(UTC) - timedelta(seconds=1)
    else:
        row.payload_json = {**row.payload_json, "catalogVersion": "another-version"}
    await pg_session.flush()
    chat = (
        await client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"catalogVersion": survey["catalogVersion"], "purpose": "CHAT"},
        )
    ).json()["session"]
    response = await client.post(
        f"/api/v1/sessions/{chat['id']}/chat/survey-context",
        headers=headers,
        json={"resultId": result.json()["id"], "expectedRevision": 0},
    )
    assert response.status_code == (409 if unavailable == "catalog" else 404)
    assert (await client.get(f"/api/v1/sessions/{chat['id']}", headers=headers)).json()["context"][
        "answers"
    ] == {}


@pytest.mark.integration
async def test_imported_safety_answer_remains_a_priority_for_chat(survey_client):
    client, _ = survey_client
    survey, headers, _ = await start(client, member=True)
    survey = await fill(client, survey, headers, answers={"test-question": "RISK"})
    result, _ = await evaluation(client, survey, headers)
    chat = (
        await client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"catalogVersion": survey["catalogVersion"], "purpose": "CHAT"},
        )
    ).json()["session"]
    base = f"/api/v1/sessions/{chat['id']}"
    assert (
        await client.post(
            base + "/chat/survey-context",
            headers=headers,
            json={"resultId": result.json()["id"], "expectedRevision": 0},
        )
    ).status_code == 200
    reply = await client.post(
        base + "/chat/messages",
        headers=headers,
        json={
            "requestId": str(uuid4()),
            "expectedRevision": 1,
            "content": "제10조 내용 알려 주세요",
        },
    )
    assert reply.status_code == 200 and reply.json()["status"] == "SAFETY_PRIORITY"


@pytest.mark.integration
async def test_independent_chat_reset_preserves_survey_history_records_and_budget(
    survey_client, pg_session
):
    client, app = survey_client
    survey, headers, _ = await start(client, member=True)
    survey = await fill(client, survey, headers)
    result, _ = await evaluation(client, survey, headers)
    assert result.status_code == 201
    created = await client.post(
        "/api/v1/sessions",
        headers=headers,
        json={
            "catalogVersion": survey["catalogVersion"],
            "purpose": "CHAT",
        },
    )
    assert created.status_code == 201
    chat = created.json()["session"]
    assert chat["id"] != survey["id"] and chat["purpose"] == "CHAT"
    assert chat["context"] == Context().model_dump(mode="json", by_alias=True)
    base = f"/api/v1/sessions/{chat['id']}"
    body = {"requestId": str(uuid4()), "expectedRevision": 0, "content": "제10조 내용 알려 주세요"}
    assert (
        await client.post(
            f"/api/v1/sessions/{survey['id']}/chat/messages", headers=headers, json=body
        )
    ).json()["error"]["code"] == "SESSION_PURPOSE_MISMATCH"
    assert (await client.get(base + "/questions", headers=headers)).status_code == 409
    assert (
        await client.post(
            base + "/evaluations",
            headers=headers,
            json={"requestId": str(uuid4()), "expectedRevision": 0},
        )
    ).status_code == 409
    assert (
        await client.put(
            base + "/context",
            headers=headers,
            json={"expectedRevision": 0, "context": {"answers": {"test-question": "RISK"}}},
        )
    ).status_code == 422
    response = await client.post(base + "/chat/messages", headers=headers, json=body)
    assert response.status_code == 200
    assert "설문" not in response.json()["assistantMessage"]["content"]
    assert (
        await client.delete(base, headers={"Origin": ORIGIN, "Content-Type": "application/json"})
    ).status_code == 403
    assert (await client.delete(base, headers=headers)).status_code == 204
    assert (await client.get(base + "/chat/messages", headers=headers)).status_code == 404
    assert await pg_session.scalar(select(func.count()).select_from(Message)) == 0
    assert await pg_session.scalar(select(func.count()).select_from(ChatUsage)) == 1
    chat_record = await pg_session.scalar(
        select(QuestionRecord).where(QuestionRecord.kind == "CHAT")
    )
    assert chat_record.consultation_id is None
    assert (await client.get(f"/api/v1/me/results/{result.json()['id']}")).status_code == 200
    assert (await client.get(f"/api/v1/sessions/{survey['id']}", headers=headers)).json()[
        "context"
    ] == survey["context"]
    fresh = (
        await client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"catalogVersion": survey["catalogVersion"], "purpose": "CHAT"},
        )
    ).json()["session"]
    assert (
        fresh["id"] != chat["id"] and fresh["revision"] == 0 and fresh["context"]["answers"] == {}
    )
    app.state.settings.chat_user_window_limit = 1
    assert (
        await client.post(
            f"/api/v1/sessions/{fresh['id']}/chat/messages", headers=headers, json=body
        )
    ).status_code == 429


@pytest.mark.integration
async def test_chat_creation_requires_account_and_legacy_history_is_read_only(
    survey_client, pg_session
):
    client, _ = survey_client
    assert (
        await client.post(
            "/api/v1/sessions",
            headers={"Origin": ORIGIN},
            json={"catalogVersion": "test-only-v1", "purpose": "CHAT"},
        )
    ).status_code == 401
    chat, headers, _ = await start(client, member=True, purpose="CHAT")
    base = f"/api/v1/sessions/{chat['id']}"
    body = {"requestId": str(uuid4()), "expectedRevision": 0, "content": "제10조 내용 알려 주세요"}
    assert (
        await client.post(base + "/chat/messages", headers=headers, json=body)
    ).status_code == 200
    row = await pg_session.get(Consultation, chat["id"])
    row.purpose = "SURVEY"  # Represents a pre-migration shared consultation.
    await pg_session.flush()
    legacy = (await client.get(base + "/chat/messages", headers=headers)).json()["items"]
    assert len(legacy) == 1 and not legacy[0]["isCurrent"]
    assert (
        await client.post(base + "/chat/messages", headers=headers, json=body)
    ).status_code == 409
    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            row.purpose = "INVALID"
            await pg_session.flush()


@pytest.mark.integration
@pytest.mark.parametrize("with_explanation", [False, True])
async def test_empty_chat_can_explain_law_and_returns_complete_inline_evidence(
    pg_session, monkeypatch, with_explanation
):
    release, doc, chunk = await seed_release(pg_session)
    release.status, release.published_at = "PUBLISHED", datetime.now(UTC)
    await pg_session.flush()
    now = datetime.now(UTC)
    snapshot = Session(
        id=uuid4(),
        purpose="CHAT",
        access_mode="MEMBER",
        catalog_version=release.catalog_version,
        knowledge_release_id=release.id,
        revision=0,
        context=Context(),
        current_result_id=None,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )

    explanation = "천장이나 벽에서 물이 보이면 먼저 어디를 통해 들어왔는지 살펴봐요."
    if with_explanation:
        monkeypatch.setitem(
            LAW_EXPLANATIONS,
            chunk.locator,
            {"contentHash": chunk.content_hash, "explanation": explanation},
        )
    generator = AsyncMock()
    generator.generate.return_value = [chunk.body]

    response = await chat_response(
        snapshot,
        CATALOG,
        enabled(),
        "제10조 내용을 설명해 주세요",
        uuid4(),
        [],
        database=BoundDatabase(pg_session),
        embeddings=FakeEmbedding(),
        generator=generator,
    )
    assert response.status == "GUIDANCE_AVAILABLE" and response.answer_mode == "GROUNDED"
    citation = response.assistant_message.citations[0]
    assert citation.excerpt == chunk.body and citation.locator == chunk.locator
    assert citation.title == doc.title and citation.use == "APPLICABLE"
    if with_explanation:
        assert citation.explanation == explanation
        assert chunk.body not in response.assistant_message.content
        generator.generate.assert_not_awaited()
    else:
        assert citation.explanation is None
        assert chunk.body in response.assistant_message.content
        generator.generate.assert_awaited_once()


@pytest.mark.integration
async def test_chat_confirms_conditions_in_conversation_and_enforces_its_own_revision(
    survey_client,
):
    client, _ = survey_client
    chat, headers, _ = await start(client, member=True, purpose="CHAT")
    base = f"/api/v1/sessions/{chat['id']}"
    request = {"requestId": str(uuid4()), "expectedRevision": 0, "content": "시설물이 고장났어요"}
    first = (await client.post(base + "/chat/messages", headers=headers, json=request)).json()
    assert first["answerMode"] == "CLARIFY"
    assert any("어떤 문제가 보이나요" in question for question in first["followUpQuestions"])
    second = await client.post(
        base + "/chat/messages",
        headers=headers,
        json={
            "requestId": str(uuid4()),
            "expectedRevision": 0,
            "content": "LH 건설임대예요",
        },
    )
    assert second.status_code == 200 and second.json()["contextRevision"] == 1
    saved = (await client.get(base, headers=headers)).json()
    assert saved["context"]["housingType"] == "LH_CONSTRUCTION_RENTAL"
    assert saved["context"]["answers"] == {} and saved["revision"] == 1
    conflict = await client.post(
        base + "/chat/messages",
        headers=headers,
        json={
            "requestId": str(uuid4()),
            "expectedRevision": 0,
            "content": "제10조 내용을 알려 주세요",
        },
    )
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "CONTEXT_CONFLICT"
