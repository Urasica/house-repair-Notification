# ruff: noqa: F811
import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from test_auth_api import BoundDatabase
from test_consultation_api import fill, start
from test_consultation_api import survey_client as chat_client  # noqa: F401
from test_knowledge import seed_release
from test_knowledge_runtime import FakeEmbedding
from test_m08a_catalog import CATALOG, answer_unknowns, context_for

from app.core.config import Settings
from app.db.models import Catalog, ChatUsage, Consultation, Message, QuestionRecord, RequestRun
from app.schemas.contracts import Session
from app.services.chat import chat_response, project_question
from app.services.generation import (
    GeneratedDraft,
    GenerationUnavailable,
    Responses,
    annex_texts,
    validate_draft,
)
from app.services.knowledge import withdraw_source
from app.services.retrieval import Evidence, Retrieval


def enabled():
    return Settings(
        _env_file=None,
        openai_enabled=True,
        openai_api_key="test-only",
        openai_chat_model="gpt-5.4-mini",
    )


def evidence():
    chunk = SimpleNamespace(
        id=uuid4(),
        body="① 기준은 3 mm이다. 다만 별도의 조건을 함께 확인한다.",
        metadata_json={"role": "ARTICLE"},
    )
    return Retrieval(evidence=[Evidence(chunk, SimpleNamespace(), use="APPLICABLE")]), chunk


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "claim",
        "condition",
        "citation",
        "contact",
        "followup",
        "refusal",
        "incomplete",
        "tool",
        "429",
        "schema",
    ],
)
async def test_responses_contract_and_fail_closed_output(failure):
    found, chunk = evidence()
    calls = []

    def handle(request):
        calls.append(request)
        body = json.loads(request.content)
        assert request.url == "https://api.openai.com/v1/responses"
        assert body["model"] == "gpt-5.4-mini" and body["tools"] == [] and body["store"] is False
        assert body["text"]["format"]["strict"] and body["max_output_tokens"] == 4096
        assert len(json.loads(body["input"])["recent"]) == 6
        draft = {
            "statements": [{"text": chunk.body, "evidenceChunkIds": [str(chunk.id)]}],
            "followUpQuestions": [],
        }
        if failure == "claim":
            draft["statements"][0]["text"] = "무료 교체가 가능합니다."
        if failure == "condition":
            draft["statements"][0]["text"] = "① 기준은 3 mm이다."
        if failure == "citation":
            draft["statements"][0]["evidenceChunkIds"] = [str(uuid4())]
        if failure == "contact":
            draft["statements"][0]["text"] = "010-1234-5678"
        if failure == "followup":
            draft["followUpQuestions"] = ["10년이 지났나요?"]
        if failure == "schema":
            draft["status"] = "GUIDANCE_AVAILABLE"
        data = {
            "model": "gpt-5.4-mini-2026-03-17",
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": json.dumps(draft)}]}
            ],
        }
        if failure == "refusal":
            data["output"][0]["content"] = [{"type": "refusal", "refusal": "no"}]
        if failure == "incomplete":
            data["status"] = "incomplete"
        if failure == "tool":
            data["output"].append({"type": "web_search_call"})
        return (
            httpx.Response(429, text="private error")
            if failure == "429"
            else httpx.Response(200, json=data)
        )

    provider = Responses(enabled(), transport=httpx.MockTransport(handle))
    if failure:
        with pytest.raises(GenerationUnavailable) as error:
            await provider.generate(
                "제10조 설명", ["safe"] * 10, found, "LAW_EXPLANATION", timeout=1
            )
        assert "private" not in str(error.value)
    else:
        assert await provider.generate(
            "제10조 설명", ["safe"] * 10, found, "LAW_EXPLANATION", timeout=1
        ) == [chunk.body]
    assert len(calls) == 1


def test_question_projection_and_output_are_allowlisted():
    value = project_question(
        "홍길동 서울로 123 101동 102호 a@b.com 010-1234-5678 제10조 내용을 설명해 주세요 https://evil.invalid"
    )
    assert value == "LAW_EXPLANATION 제10조"
    draft = GeneratedDraft(
        statements=[{"text": "검토 문구", "evidenceChunkIds": ["allowed", "fake"]}],
        followUpQuestions=[],
    )
    with pytest.raises(GenerationUnavailable):
        validate_draft(draft, {"allowed": ["검토 문구"]})
    draft = GeneratedDraft(
        statements=[{"text": "검토 문구", "evidenceChunkIds": ["allowed"]}], followUpQuestions=[]
    )
    with pytest.raises(GenerationUnavailable, match="INCOMPLETE_EVIDENCE"):
        validate_draft(draft, {"allowed": ["검토 문구"], "required": ["단서"]})


def test_annex_display_preserves_all_columns_rows_and_exceptions():
    table = {
        "number": 2,
        "title": "검토 표",
        "columns": ["조건", "결론"],
        "rows": [["상시", "첫 행"], ["일시", "둘째 행"]],
        "footnotes": ["단, 제외 조건 확인"],
    }
    chunk = SimpleNamespace(id=uuid4(), body=json.dumps(table), metadata_json={"role": "ANNEX"})
    found = Retrieval(evidence=[Evidence(chunk, SimpleNamespace(), use="APPLICABLE")])
    output = annex_texts(found)[0]
    assert all(
        value in output
        for value in [
            "조건: 상시",
            "결론: 첫 행",
            "조건: 일시",
            "결론: 둘째 행",
            "단, 제외 조건 확인",
        ]
    )


@pytest.mark.integration
async def test_runtime_purpose_privacy_failure_and_deadline(pg_session):
    release, doc, chunk = await seed_release(pg_session)
    release.status, release.published_at = "PUBLISHED", datetime.now(UTC)
    await pg_session.flush()
    now = datetime.now(UTC)
    snapshot = Session(
        id=uuid4(),
        access_mode="MEMBER",
        catalog_version=release.catalog_version,
        knowledge_release_id=release.id,
        revision=1,
        context=answer_unknowns(context_for("leak", "waterproof", "bathroom")),
        current_result_id=None,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    snapshot.context.description = "private address"
    embed = FakeEmbedding()

    class Generator:
        calls = 0
        failure = False

        async def generate(self, *args, **kwargs):
            self.calls += 1
            assert "private" not in args[0] and "@" not in args[0]
            if self.failure:
                raise GenerationUnavailable("test")
            return [chunk.body]

    generator = Generator()

    async def answer(content, **kwargs):
        return await chat_response(
            snapshot,
            CATALOG,
            enabled(),
            content,
            uuid4(),
            [],
            database=BoundDatabase(pg_session),
            embeddings=embed,
            generator=generator,
            **kwargs,
        )

    result = await answer("private@example.com 제10조 내용을 알려 주세요")
    assert result.answer_mode == "GROUNDED" and result.status == "GUIDANCE_AVAILABLE"
    for content in [
        "제10조로 우리 집 무료 교체가 되나요?",
        "제10조 내용과 LH 비용도 알려 주세요",
        "이거 어떻게 하나요?",
    ]:
        result = await answer(content)
        assert result.answer_mode == "TEMPLATE" and result.status == "NEED_CONFIRMATION"
    assert generator.calls == 1
    assert all("private" not in query for query in embed.inputs)
    result = await answer("가스 냄새가 나요 제10조 설명")
    assert result.status == "SAFETY_PRIORITY" and generator.calls == 1
    generator.failure = True
    result = await answer("제10조 설명")
    assert result.answer_mode == "TEMPLATE" and not result.assistant_message.citations
    result = await answer("제10조 설명", deadline=asyncio.get_running_loop().time() - 1)
    assert result.answer_mode == "TEMPLATE"


@pytest.mark.integration
async def test_chat_atomic_history_replay_revision_and_question_deletion(chat_client, pg_session):
    client, app = chat_client
    snapshot, headers, _ = await start(client, member=True)
    snapshot = await fill(client, snapshot, headers)
    url = f"/api/v1/sessions/{snapshot['id']}/chat/messages"
    body = {
        "requestId": str(uuid4()),
        "expectedRevision": snapshot["revision"],
        "content": "private@example.com 문의",
    }
    first = await client.post(url, json=body, headers=headers)
    assert first.status_code == 200, first.text
    answer = first.json()
    assert answer["answerMode"] == "TEMPLATE" and answer["isCurrent"]
    assert "_meta" not in first.text
    assert (await client.post(url, json=body, headers=headers)).json() == answer
    assert (await client.get(url, headers=headers)).json()["items"] == [answer]
    assert (
        await client.get(
            f"/api/v1/sessions/{snapshot['id']}/requests/{body['requestId']}", headers=headers
        )
    ).json()["response"] == answer
    assert await pg_session.scalar(select(func.count()).select_from(Message)) == 2
    assert await pg_session.scalar(select(func.count()).select_from(QuestionRecord)) == 1
    assert (await pg_session.scalar(select(QuestionRecord))).masked_question == "OPERATION "
    conflict = await client.post(url, json={**body, "content": "different"}, headers=headers)
    assert conflict.status_code == 409
    snapshot = await fill(client, snapshot, headers, description="changed")
    replay = (await client.post(url, json=body, headers=headers)).json()
    assert not replay["isCurrent"] and not replay["assistantMessage"]["isCurrent"]
    assert (await client.delete("/api/v1/me/question-records", headers=headers)).status_code == 204
    await client.post(url, json=body, headers=headers)
    assert await pg_session.scalar(select(func.count()).select_from(QuestionRecord)) == 0
    # Reservations survive conversation deletion, so fresh sessions cannot evade limits.
    app.state.settings.chat_user_window_limit = 1
    assert (
        await client.post(
            url,
            json={**body, "requestId": str(uuid4()), "expectedRevision": snapshot["revision"]},
            headers=headers,
        )
    ).status_code == 429
    assert (
        await client.delete(f"/api/v1/sessions/{snapshot['id']}", headers=headers)
    ).status_code == 204
    assert await pg_session.scalar(select(func.count()).select_from(Message)) == 0
    assert await pg_session.scalar(select(func.count()).select_from(ChatUsage)) == 1


@pytest.mark.integration
async def test_chat_permissions_pagination_and_failed_run(chat_client, pg_session):
    client, app = chat_client
    guest, guest_headers, _ = await start(client)
    guest_url = f"/api/v1/sessions/{guest['id']}/chat/messages"
    assert (await client.get(guest_url, headers=guest_headers)).status_code == 401
    snapshot, headers, _ = await start(client, member=True)
    assert (await client.get(guest_url, headers=headers)).status_code == 404
    url = f"/api/v1/sessions/{snapshot['id']}/chat/messages"
    for _ in range(3):
        assert (
            await client.post(
                url,
                json={"requestId": str(uuid4()), "expectedRevision": 0, "content": "문의"},
                headers=headers,
            )
        ).status_code == 200
    page = (await client.get(url + "?limit=2", headers=headers)).json()
    assert len(page["items"]) == 2 and page["nextCursor"]
    last = (await client.get(url + "?limit=2&cursor=" + page["nextCursor"], headers=headers)).json()
    assert len(last["items"]) == 1 and last["nextCursor"] is None
    assert len({r["requestId"] for r in page["items"] + last["items"]}) == 3
    body = {"requestId": str(uuid4()), "expectedRevision": 0, "content": "문의"}

    async def fail(*args, **kwargs):
        raise TimeoutError()

    app.state.chat_response = fail
    assert (await client.post(url, json=body, headers=headers)).status_code == 503
    run = await pg_session.scalar(
        select(RequestRun).where(RequestRun.request_id == body["requestId"])
    )
    assert run.state == "FAILED"
    assert (await client.post(url, json=body, headers=headers)).status_code == 409
    assert await pg_session.scalar(select(func.count()).select_from(Message)) == 6
    assert (await client.get(url + "?cursor=bad", headers=headers)).status_code == 422


@pytest.mark.integration
async def test_final_withdrawal_cannot_commit_grounded_answer(chat_client, pg_session):
    client, app = chat_client
    snapshot, headers, _ = await start(client, member=True)
    snapshot = await fill(client, snapshot, headers)
    release, doc, chunk = await seed_release(
        pg_session, catalog=await pg_session.get(Catalog, snapshot["catalogVersion"])
    )
    release.catalog_version = snapshot["catalogVersion"]
    release.status, release.published_at = "PUBLISHED", datetime.now(UTC)
    row = await pg_session.get(Consultation, snapshot["id"])
    row.knowledge_set_id = release.id
    await pg_session.flush()
    original = app.state.chat_response

    async def revoked(*args, **kwargs):
        from app.schemas.contracts import Citation

        response = await original(*args, **kwargs)
        response.answer_mode, response.status = "GROUNDED", "GUIDANCE_AVAILABLE"
        response.assistant_message.citations = [
            Citation(
                chunk_id=chunk.id,
                document_version_id=doc.id,
                kind="LAW_CRITERIA",
                use="APPLICABLE",
                title=doc.title,
                locator=chunk.locator,
                url=doc.url,
                effective_date=None,
                reviewed_at=doc.reviewed_at,
                review_until=doc.review_until,
            )
        ]
        await withdraw_source(pg_session, doc.source_key, "test withdrawal")
        return response

    app.state.chat_response = revoked
    url = f"/api/v1/sessions/{snapshot['id']}/chat/messages"
    response = await client.post(
        url,
        headers=headers,
        json={
            "requestId": str(uuid4()),
            "expectedRevision": snapshot["revision"],
            "content": "제10조 설명",
        },
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["answerMode"] == "TEMPLATE"
        and not response.json()["assistantMessage"]["citations"]
    )


@pytest.mark.integration
async def test_inflight_chat_lock_and_cancel_do_not_store_late_messages(chat_client, pg_session):
    client, app = chat_client
    snapshot, headers, _ = await start(client, member=True)
    snapshot = await fill(client, snapshot, headers)
    url = f"/api/v1/sessions/{snapshot['id']}/chat/messages"
    body = {"requestId": str(uuid4()), "expectedRevision": snapshot["revision"], "content": "문의"}
    started, release = asyncio.Event(), asyncio.Event()
    original = app.state.chat_response

    async def delayed(*args, **kwargs):
        started.set()
        await release.wait()
        return await original(*args, **kwargs)

    app.state.chat_response = delayed
    task = asyncio.create_task(client.post(url, headers=headers, json=body))
    await started.wait()
    try:
        duplicate = await client.post(url, headers=headers, json=body)
        assert duplicate.json()["error"]["code"] == "REQUEST_IN_PROGRESS"
        different = await client.post(
            url, headers=headers, json={**body, "requestId": str(uuid4())}
        )
        assert different.json()["error"]["code"] == "SESSION_BUSY"
        assert (
            await client.delete(f"/api/v1/sessions/{snapshot['id']}", headers=headers)
        ).status_code == 409
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        if not task.done():
            await task
    run = await pg_session.scalar(
        select(RequestRun).where(RequestRun.request_id == body["requestId"])
    )
    assert run.state == "FAILED"
    assert await pg_session.scalar(select(func.count()).select_from(Message)) == 0
    assert await pg_session.scalar(select(func.count()).select_from(QuestionRecord)) == 0
