# ruff: noqa: F811
from datetime import UTC, datetime, timedelta
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

from app.db.models import ChatUsage, Consultation, Message, QuestionRecord
from app.schemas.contracts import Context, Session
from app.services.chat import chat_response
from app.services.chat_context import chat_policy, confirmed_context


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
async def test_empty_chat_can_explain_law_and_returns_complete_inline_evidence(pg_session):
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

    class Generator:
        async def generate(self, *args, **kwargs):
            return [chunk.body]

    response = await chat_response(
        snapshot,
        CATALOG,
        enabled(),
        "제10조 내용을 설명해 주세요",
        uuid4(),
        [],
        database=BoundDatabase(pg_session),
        embeddings=FakeEmbedding(),
        generator=Generator(),
    )
    assert response.status == "GUIDANCE_AVAILABLE" and response.answer_mode == "GROUNDED"
    assert chunk.body in response.assistant_message.content
    citation = response.assistant_message.citations[0]
    assert citation.excerpt == chunk.body and citation.locator == chunk.locator
    assert citation.title == doc.title and citation.use == "APPLICABLE"


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
    assert all("채팅" in question for question in first["followUpQuestions"])
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
