# ruff: noqa: F811
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select, update
from test_auth_api import BoundDatabase
from test_consultation_api import evaluation, fill, start, survey_client  # noqa: F401

from app.core.config import Settings
from app.db.models import AuthSession, Consultation, DeletionLog, QuestionRecord, RequestRun, Result
from app.services.deletion_export import (
    apply_deletions,
    decrypt,
    encrypt,
    export_after_delete,
    export_deletions,
)
from app.services.guidance import add_years
from app.services.retention import cleanup, question_statistics


def test_leap_and_retention_bounds():
    leap = datetime(2024, 2, 29, 12, tzinfo=UTC)
    assert add_years(leap, 3) == datetime(2027, 2, 28, 12, tzinfo=UTC)
    assert add_years(leap, 5) == datetime(2029, 2, 28, 12, tzinfo=UTC)
    assert add_years(leap, 4) == datetime(2028, 2, 29, 12, tzinfo=UTC)
    for years in (2, 6):
        with pytest.raises(ValueError):
            Settings(_env_file=None, question_retention_years=years)


def test_encryption_authenticates_content_and_purpose():
    key = Fernet.generate_key().decode()
    token = encrypt({"format": 1, "purpose": "deletions", "secret": "private"}, key)
    assert b"private" not in token
    assert decrypt(token, key, "deletions")["secret"] == "private"
    with pytest.raises(ValueError):
        decrypt(token, key, "backup")
    with pytest.raises(InvalidToken):
        decrypt(token, Fernet.generate_key().decode(), "deletions")
    with pytest.raises(InvalidToken):
        decrypt(token[:-5] + b"abcde", key, "deletions")


@pytest.mark.integration
@pytest.mark.parametrize("member", [False, True])
async def test_expiry_keeps_only_member_results_and_clean_questions(
    survey_client, pg_session, member
):
    client, _ = survey_client
    snapshot, headers, _ = await start(client, member=member)
    snapshot = await fill(client, snapshot, headers)
    result, _ = await evaluation(client, snapshot, headers)
    assert result.status_code == 201
    consultation = await pg_session.get(Consultation, UUID(snapshot["id"]))
    moment = consultation.expires_at
    before = await cleanup(pg_session, Settings(_env_file=None), now=moment - timedelta(seconds=1))
    assert before["consultations"] == 0
    counts = await cleanup(pg_session, Settings(_env_file=None), now=moment)
    assert counts["consultations"] == 1
    await pg_session.flush()
    pg_session.expire_all()
    assert await pg_session.get(Consultation, UUID(snapshot["id"])) is None
    assert await pg_session.scalar(select(func.count()).select_from(RequestRun)) == 0
    assert await pg_session.scalar(select(func.count()).select_from(AuthSession)) == 0
    record = await pg_session.scalar(select(QuestionRecord))
    assert record is not None and record.consultation_id is None
    saved = await pg_session.get(Result, UUID(result.json()["id"]))
    assert (saved is not None) == member
    if member:
        assert saved.consultation_id is None and saved.request_run_id is None
        await cleanup(pg_session, Settings(_env_file=None), now=saved.retained_until)
        await pg_session.flush()
        pg_session.expire_all()
        assert await pg_session.get(Result, UUID(result.json()["id"])) is None


@pytest.mark.integration
async def test_statistics_replay_delete_and_question_deadline(survey_client, pg_session):
    client, _ = survey_client
    snapshot, headers, _ = await start(client, member=True)
    snapshot = await fill(client, snapshot, headers)
    result, request_id = await evaluation(client, snapshot, headers)
    replay, _ = await evaluation(client, snapshot, headers, request_id=request_id)
    assert replay.status_code == 200
    assert (await question_statistics(pg_session))[0]["count"] == 1
    record = await pg_session.scalar(select(QuestionRecord))
    assert await question_statistics(pg_session, now=record.retained_until) == []
    response = await client.delete(f"/api/v1/me/results/{result.json()['id']}", headers=headers)
    assert response.status_code == 204
    assert await question_statistics(pg_session) == []


@pytest.mark.integration
async def test_restore_preserves_question_only_marker_for_next_export(pg_session, tmp_path):
    now = datetime.now(UTC)
    identifier = uuid4()
    payload = {
        "entries": [
            {
                "type": "QUESTION_RECORD",
                "id": str(identifier),
                "deletedAt": now.isoformat(),
                "expiresAt": (now + timedelta(days=15)).isoformat(),
            }
        ]
    }
    config = Settings(
        _env_file=None,
        backup_key=Fernet.generate_key().decode(),
        deletion_export_path=str(tmp_path / "latest.fernet"),
    )
    await apply_deletions(pg_session, payload, config)
    await export_deletions(BoundDatabase(pg_session), config)
    exported = decrypt(
        (tmp_path / "latest.fernet").read_bytes(), config.backup_key.get_secret_value(), "deletions"
    )
    assert exported["entries"] == payload["entries"]


@pytest.mark.integration
async def test_statistics_classifies_chat_context_without_survey_wrapper(survey_client, pg_session):
    client, _ = survey_client
    snapshot, headers, _ = await start(client, member=True)
    snapshot = await fill(client, snapshot, headers)
    response = await client.post(
        f"/api/v1/sessions/{snapshot['id']}/chat/messages",
        headers=headers,
        json={
            "requestId": str(uuid4()),
            "expectedRevision": snapshot["revision"],
            "content": "조문 설명을 알려주세요",
        },
    )
    assert response.status_code == 200
    rows = await question_statistics(pg_session)
    assert len(rows) == 1 and rows[0]["kind"] == "CHAT"
    assert rows[0]["facilityId"] == "test-facility" and rows[0]["symptomId"] == "test-symptom"


@pytest.mark.integration
async def test_restored_result_marker_erases_replay_before_fk_is_lost(survey_client, pg_session):
    client, app = survey_client
    snapshot, headers, _ = await start(client, member=True)
    snapshot = await fill(client, snapshot, headers)
    result, request_id = await evaluation(client, snapshot, headers)
    record = await pg_session.scalar(select(QuestionRecord))
    payload = {
        "entries": [
            {"type": "RESULT", "id": result.json()["id"]},
            {"type": "QUESTION_RECORD", "id": str(record.id)},
        ]
    }
    for _ in range(2):
        await apply_deletions(pg_session, payload, app.state.settings)
        await pg_session.flush()
    pg_session.expire_all()
    run = await pg_session.scalar(select(RequestRun))
    assert run.state == "DELETED" and run.response_json is None
    assert await pg_session.get(Result, UUID(result.json()["id"])) is None
    replay, _ = await evaluation(client, snapshot, headers, request_id=request_id)
    assert replay.status_code == 410 and replay.json()["error"]["code"] == "REQUEST_DELETED"
    assert await question_statistics(pg_session) == []


@pytest.mark.integration
async def test_export_failure_retains_markers_and_retry_succeeds(pg_session, tmp_path, caplog):
    now = datetime.now(UTC)
    pg_session.add(
        DeletionLog(
            entity_type="RESULT",
            entity_id=uuid4(),
            deleted_at=now,
            expires_at=now + timedelta(days=15),
        )
    )
    pg_session.add(
        DeletionLog(
            entity_type="RESULT",
            entity_id=uuid4(),
            deleted_at=now - timedelta(days=16),
            expires_at=now - timedelta(days=1),
        )
    )
    await pg_session.flush()
    blocking_file = tmp_path / "blocked"
    blocking_file.write_text("file, not directory")
    settings = Settings(
        _env_file=None,
        backup_key=Fernet.generate_key().decode(),
        deletion_export_path=str(blocking_file / "latest.fernet"),
    )
    db = BoundDatabase(pg_session)
    await export_after_delete(db, settings)
    assert "DELETION_EXPORT_FAILED" in caplog.text
    assert await pg_session.scalar(select(func.count()).select_from(DeletionLog)) == 2
    settings.deletion_export_path = str(tmp_path / "latest.fernet")
    assert (await export_deletions(db, settings))["entries"] == 1
    payload = decrypt(
        (tmp_path / "latest.fernet").read_bytes(),
        settings.backup_key.get_secret_value(),
        "deletions",
    )
    assert len(payload["entries"]) == 1
    assert await pg_session.scalar(select(func.count()).select_from(DeletionLog)) == 1


@pytest.mark.integration
async def test_question_expiry_unlinks_live_result(survey_client, pg_session):
    client, app = survey_client
    snapshot, headers, _ = await start(client, member=True)
    snapshot = await fill(client, snapshot, headers)
    result, _ = await evaluation(client, snapshot, headers)
    await pg_session.execute(update(QuestionRecord).values(retained_until=datetime.now(UTC)))
    counts = await cleanup(pg_session, app.state.settings)
    assert counts["questions"] == 1 and counts["results"] == 0
    pg_session.expire_all()
    assert (await pg_session.get(Result, UUID(result.json()["id"]))).question_record_id is None
