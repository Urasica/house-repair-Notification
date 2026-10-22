import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from test_auth_api import ORIGIN, BoundDatabase, signed_in
from test_catalog_policy import catalog_data

from app.core.config import Settings
from app.db.models import Consultation, DeletionLog, QuestionRecord, RequestRun, Result
from app.main import create_app
from app.schemas.catalog import CatalogDefinition
from app.services.catalog import publish_catalog

pytestmark = pytest.mark.integration


@pytest.fixture
async def survey_client(pg_session):
    await publish_catalog(
        pg_session, CatalogDefinition.model_validate(catalog_data()), Settings(_env_file=None)
    )
    app = create_app(Settings(_env_file=None), BoundDatabase(pg_session))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client, app


async def start(client, *, member=False, purpose="SURVEY"):
    headers = {"Origin": ORIGIN, "Content-Type": "application/json"}
    if member:
        state = (await signed_in(client)).json()
        headers["X-CSRF-Token"] = state["csrfToken"]
    response = await client.post(
        "/api/v1/sessions",
        json={"catalogVersion": "test-only-v1", "purpose": purpose},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    data = response.json()
    if data["sessionToken"]:
        headers["Authorization"] = "Bearer " + data["sessionToken"]
    return data["session"], headers, data["sessionToken"]


async def fill(client, session, headers, **changes):
    context = {
        "housingType": "LH_CONSTRUCTION_RENTAL",
        "roomId": "test-room",
        "facilityId": "test-facility",
        "symptomId": "test-symptom",
        "answers": {} if session.get("purpose") == "CHAT" else {"test-question": "UNKNOWN"},
        **changes,
    }
    response = await client.put(
        f"/api/v1/sessions/{session['id']}/context",
        json={"expectedRevision": session["revision"], "context": context},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def evaluation(client, session, headers, request_id=None, revision=None):
    request_id = request_id or str(uuid4())
    response = await client.post(
        f"/api/v1/sessions/{session['id']}/evaluations",
        headers=headers,
        json={
            "requestId": request_id,
            "expectedRevision": session["revision"] if revision is None else revision,
        },
    )
    return response, request_id


async def test_guest_creation_context_branching_evaluation_and_hashes(survey_client, pg_session):
    client, _ = survey_client
    session, headers, token = await start(client)
    row = await pg_session.get(Consultation, session["id"])
    assert token not in row.guest_token_hash and len(row.guest_token_hash) == 64
    assert session["revision"] == 0 and session["accessMode"] == "GUEST"
    session = await fill(
        client,
        session,
        headers,
        answers={"test-question": "TEST"},
        description="test-private-free-text",
    )
    questions = (
        await client.get(f"/api/v1/sessions/{session['id']}/questions", headers=headers)
    ).json()
    assert [q["questionId"] for q in questions["questions"]] == ["test-question", "test-follow-up"]
    response, request_id = await evaluation(client, session, headers)
    assert response.status_code == 201
    result = response.json()
    assert result["status"] == "NEED_MORE_INFO" and result["savedToHistory"] is False
    record = await pg_session.scalar(select(QuestionRecord))
    assert record.masked_question is None and "test-private-free-text" not in str(
        record.answers_json
    )
    assert record.retained_until.year == datetime.now(UTC).year + 5
    state = await client.get(
        f"/api/v1/sessions/{session['id']}/requests/{request_id}", headers=headers
    )
    assert state.json()["state"] == "COMPLETED" and state.json()["response"]["id"] == result["id"]
    current = (await client.get(f"/api/v1/sessions/{session['id']}", headers=headers)).json()
    assert current["currentResultId"] == result["id"]


async def test_cancelled_evaluation_records_failure_and_releases_lock(survey_client, pg_session):
    client, app = survey_client
    session, headers, _ = await start(client)
    session = await fill(client, session, headers)
    started = asyncio.Event()

    async def never_finishes(*args):
        started.set()
        await asyncio.Event().wait()

    app.state.evaluate_survey = never_finishes
    pending = asyncio.create_task(evaluation(client, session, headers))
    await started.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert (await pg_session.scalar(select(RequestRun))).state == "FAILED"
    assert app.state.consultation_locks.active_count == 0
    assert await pg_session.scalar(select(func.count()).select_from(Result)) == 0


async def test_timeout_and_final_save_failure_never_report_success(
    survey_client, pg_session, monkeypatch
):
    from app.api.v1.sessions import repository

    client, app = survey_client
    session, headers, _ = await start(client)
    session = await fill(client, session, headers)
    original = app.state.evaluate_survey
    app.state.settings.survey_timeout_seconds = 1

    async def timeout(*args):
        await asyncio.Event().wait()

    app.state.evaluate_survey = timeout
    response, _ = await evaluation(client, session, headers)
    assert response.status_code == 503
    app.state.evaluate_survey = original

    async def save_failure(*args):
        raise RuntimeError("private database failure")

    monkeypatch.setattr(repository, "complete", save_failure)
    response, _ = await evaluation(client, session, headers)
    assert response.status_code == 503
    assert await pg_session.scalar(select(func.count()).select_from(Result)) == 0
    assert await pg_session.scalar(select(func.count()).select_from(QuestionRecord)) == 0
    assert set((await pg_session.scalars(select(RequestRun.state))).all()) == {"FAILED"}


@pytest.mark.parametrize("terminal", ["FAILED", "DELETED"])
async def test_late_completion_cannot_replace_a_terminal_request(
    survey_client, pg_session, terminal
):
    client, app = survey_client
    session, headers, _ = await start(client)
    session = await fill(client, session, headers)
    started, release = asyncio.Event(), asyncio.Event()
    original = app.state.evaluate_survey

    async def delayed(*args):
        started.set()
        await release.wait()
        return await original(*args)

    app.state.evaluate_survey = delayed
    pending = asyncio.create_task(evaluation(client, session, headers))
    await started.wait()
    run = await pg_session.scalar(select(RequestRun))
    run.state, run.finished_at = terminal, datetime.now(UTC)
    await pg_session.flush()
    release.set()
    response, _ = await pending
    assert response.status_code == 409
    assert (await pg_session.scalar(select(RequestRun))).state == terminal
    assert await pg_session.scalar(select(func.count()).select_from(Result)) == 0
    assert await pg_session.scalar(select(func.count()).select_from(QuestionRecord)) == 0


async def test_account_disabled_during_evaluation_prevents_final_save(survey_client, pg_session):
    from app.db.models import User

    client, app = survey_client
    session, headers, _ = await start(client, member=True)
    session = await fill(client, session, headers)
    original = app.state.evaluate_survey

    async def disable_before_save(*args):
        user = await pg_session.scalar(select(User))
        user.status = "DISABLED"
        await pg_session.flush()
        return await original(*args)

    app.state.evaluate_survey = disable_before_save
    response, _ = await evaluation(client, session, headers)
    assert response.status_code == 401
    assert await pg_session.scalar(select(func.count()).select_from(Result)) == 0
    assert (await pg_session.scalar(select(RequestRun))).state == "FAILED"


async def test_question_deletion_checks_active_member_evaluation(survey_client):
    client, app = survey_client
    session, headers, _ = await start(client, member=True)
    session = await fill(client, session, headers)
    started, release = asyncio.Event(), asyncio.Event()
    original = app.state.evaluate_survey

    async def delayed(*args):
        started.set()
        await release.wait()
        return await original(*args)

    app.state.evaluate_survey = delayed
    pending = asyncio.create_task(evaluation(client, session, headers))
    await started.wait()
    try:
        response = await client.delete("/api/v1/me/question-records", headers=headers)
        assert response.status_code == 409
    finally:
        release.set()
        await pending
    assert app.state.question_deletion_locks.active_count == 0


@pytest.mark.parametrize(
    "housing,answers,status",
    [
        ("LH_CONSTRUCTION_RENTAL", {"test-question": "UNKNOWN"}, "NEED_CONFIRMATION"),
        ("UNKNOWN", {"test-question": "UNKNOWN"}, "NEED_MORE_INFO"),
        ("OTHER", {}, "OUT_OF_SCOPE"),
        ("OTHER", {"test-question": "RISK"}, "SAFETY_PRIORITY"),
    ],
)
async def test_results_follow_policy_and_never_call_external_search(
    survey_client, housing, answers, status
):
    client, _ = survey_client
    session, headers, _ = await start(client)
    session = await fill(client, session, headers, housingType=housing, answers=answers)
    response, _ = await evaluation(client, session, headers)
    assert response.status_code == 201 and response.json()["status"] == status
    assert response.json()["citations"] == []
    assert "@" not in " ".join(response.json()["guidance"])


async def test_revision_changes_clear_invalid_descendants_and_old_result_is_not_current(
    survey_client,
):
    client, _ = survey_client
    session, headers, _ = await start(client)
    session = await fill(client, session, headers)
    response, _ = await evaluation(client, session, headers)
    result_id = response.json()["id"]
    again = await fill(client, session, headers)
    assert again["revision"] == session["revision"]
    updated = await fill(client, session, headers, roomId="test-room2")
    assert updated["context"]["facilityId"] is None and updated["context"]["answers"] == {}
    old = await client.get(f"/api/v1/sessions/{session['id']}/results/{result_id}", headers=headers)
    assert old.json()["isCurrent"] is False
    conflict, _ = await evaluation(client, updated, headers, revision=0)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "CONTEXT_CONFLICT"


async def test_completed_replay_never_duplicates_result_or_question(survey_client, pg_session):
    client, _ = survey_client
    session, headers, _ = await start(client)
    session = await fill(client, session, headers)
    first, request_id = await evaluation(client, session, headers)
    second, _ = await evaluation(client, session, headers, request_id)
    assert second.status_code == 200 and second.json()["id"] == first.json()["id"]
    assert await pg_session.scalar(select(func.count()).select_from(Result)) == 1
    assert await pg_session.scalar(select(func.count()).select_from(QuestionRecord)) == 1
    mismatch, _ = await evaluation(client, session, headers, request_id, revision=2)
    assert (
        mismatch.status_code == 409 and mismatch.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    )


async def test_member_result_delete_keeps_tombstone_before_hash_check(survey_client, pg_session):
    client, _ = survey_client
    session, headers, token = await start(client, member=True)
    assert token is None
    session = await fill(client, session, headers)
    result, request_id = await evaluation(client, session, headers)
    result_id = result.json()["id"]
    deleted = await client.delete(f"/api/v1/me/results/{result_id}", headers=headers)
    assert deleted.status_code == 204, deleted.text
    run = await pg_session.scalar(select(RequestRun))
    assert run.state == "DELETED" and run.response_json is None and run.finished_at
    assert await pg_session.scalar(select(func.count()).select_from(QuestionRecord)) == 0
    assert await pg_session.scalar(select(func.count()).select_from(DeletionLog)) == 2
    replay, _ = await evaluation(client, session, headers, request_id, revision=999)
    assert replay.status_code == 410 and replay.json()["error"]["code"] == "REQUEST_DELETED"
    assert (await client.get(f"/api/v1/me/results/{result_id}")).status_code == 404
    state = (await client.get(f"/api/v1/sessions/{session['id']}/requests/{request_id}")).json()
    assert state["state"] == "DELETED" and state["response"] is None


async def test_question_only_delete_does_not_restore_on_replay(survey_client, pg_session):
    client, _ = survey_client
    session, headers, _ = await start(client, member=True)
    session = await fill(client, session, headers)
    result, request_id = await evaluation(client, session, headers)
    assert (await client.delete("/api/v1/me/question-records", headers=headers)).status_code == 204
    replay, _ = await evaluation(client, session, headers, request_id)
    assert replay.status_code == 200 and replay.json()["id"] == result.json()["id"]
    assert await pg_session.scalar(select(func.count()).select_from(QuestionRecord)) == 0
    assert (await pg_session.scalar(select(RequestRun))).state == "COMPLETED"


@pytest.mark.parametrize(
    "member,erase,questions,results",
    [(False, False, 1, 0), (False, True, 0, 0), (True, False, 1, 1)],
)
async def test_end_session_preserves_only_allowed_long_term_records(
    survey_client, pg_session, member, erase, questions, results
):
    client, _ = survey_client
    session, headers, _ = await start(client, member=member)
    session = await fill(client, session, headers)
    result, _ = await evaluation(client, session, headers)
    ended = await client.delete(
        f"/api/v1/sessions/{session['id']}?eraseRecords={str(erase).lower()}", headers=headers
    )
    assert ended.status_code == 204, ended.text
    assert await pg_session.scalar(select(func.count()).select_from(QuestionRecord)) == questions
    assert await pg_session.scalar(select(func.count()).select_from(Result)) == results
    assert await pg_session.scalar(select(func.count()).select_from(RequestRun)) == 0
    if member:
        historical = await client.get(f"/api/v1/me/results/{result.json()['id']}")
        assert historical.status_code == 200 and historical.json()["isCurrent"] is False
        assert historical.json()["sessionId"] is None


async def test_member_history_survives_expiry_and_pagination_does_not_overlap(
    survey_client, pg_session
):
    client, _ = survey_client
    session, headers, _ = await start(client, member=True)
    session = await fill(client, session, headers)
    first, _ = await evaluation(client, session, headers)
    second, _ = await evaluation(client, session, headers)
    page = (await client.get("/api/v1/me/results?limit=1")).json()
    next_page = (
        await client.get("/api/v1/me/results", params={"limit": 1, "cursor": page["nextCursor"]})
    ).json()
    assert {page["items"][0]["id"], next_page["items"][0]["id"]} == {
        first.json()["id"],
        second.json()["id"],
    }
    row = await pg_session.get(Consultation, session["id"])
    row.expires_at = row.created_at + timedelta(seconds=1)
    row.created_at = datetime.now(UTC) - timedelta(days=1)
    row.expires_at = row.created_at + timedelta(hours=1)
    await pg_session.flush()
    assert (await client.get(f"/api/v1/sessions/{session['id']}")).status_code == 401
    assert (await client.get(f"/api/v1/me/results/{first.json()['id']}")).json()[
        "isCurrent"
    ] is False
    assert (await client.get("/api/v1/me/results?cursor=garbage")).status_code == 422


async def test_session_tokens_do_not_grant_chat_history_or_other_session_access(survey_client):
    client, _ = survey_client
    first, headers, _ = await start(client)
    second, _, _ = await start(client)
    assert (
        await client.get(f"/api/v1/sessions/{second['id']}", headers=headers)
    ).status_code == 404
    assert (await client.get("/api/v1/me/results", headers=headers)).status_code == 401
    assert (
        await client.get(f"/api/v1/sessions/{first['id']}/chat/messages", headers=headers)
    ).status_code == 401


async def test_missing_and_stale_catalog_cannot_start_session(survey_client, pg_session):
    client, _ = survey_client
    response = await client.post(
        "/api/v1/sessions", headers={"Origin": ORIGIN}, json={"catalogVersion": "old"}
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "CATALOG_UPDATED"


async def test_failed_evaluation_refuses_same_id_and_accepts_explicit_new_id(
    survey_client, pg_session
):
    client, app = survey_client
    session, headers, _ = await start(client)
    session = await fill(client, session, headers)
    original = app.state.evaluate_survey

    async def broken(*args):
        raise RuntimeError("private failure")

    app.state.evaluate_survey = broken
    failed, request_id = await evaluation(client, session, headers)
    assert failed.status_code == 503 and "private failure" not in failed.text
    assert (await pg_session.scalar(select(RequestRun))).state == "FAILED"
    app.state.evaluate_survey = original
    refused, _ = await evaluation(client, session, headers, request_id)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "REQUEST_FAILED"
    success, _ = await evaluation(client, session, headers)
    assert success.status_code == 201


async def test_in_progress_duplicate_and_mutation_are_rejected(survey_client):
    client, app = survey_client
    session, headers, _ = await start(client)
    session = await fill(client, session, headers)
    started, release = asyncio.Event(), asyncio.Event()
    original = app.state.evaluate_survey

    async def delayed(*args):
        started.set()
        await release.wait()
        return await original(*args)

    app.state.evaluate_survey = delayed
    request_id = str(uuid4())
    pending = asyncio.create_task(evaluation(client, session, headers, request_id))
    await started.wait()
    try:
        duplicate, _ = await evaluation(client, session, headers, request_id)
        assert (
            duplicate.status_code == 409
            and duplicate.json()["error"]["code"] == "REQUEST_IN_PROGRESS"
        )
        different, _ = await evaluation(client, session, headers)
        assert different.status_code == 409 and different.json()["error"]["code"] == "SESSION_BUSY"
        stopped = await client.delete(f"/api/v1/sessions/{session['id']}", headers=headers)
        assert stopped.status_code == 409
    finally:
        release.set()
        response, _ = await pending
    assert response.status_code == 201
