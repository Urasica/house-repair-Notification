from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update

from app.db.models import DeletionLog, QuestionRecord, RequestRun, Result
from app.domain.constants import RequestStatus


def log_deletion(session, entity_type, entity_id, settings):
    now = datetime.now(UTC)
    session.add(
        DeletionLog(
            entity_type=entity_type,
            entity_id=entity_id,
            deleted_at=now,
            expires_at=now + timedelta(days=settings.deletion_log_retention_days),
        )
    )


async def delete_result(session, row: Result, settings, *, preserve_question=False):
    if row.request_run_id:
        await session.execute(
            update(RequestRun)
            .where(RequestRun.id == row.request_run_id, RequestRun.state == RequestStatus.COMPLETED)
            .values(state=RequestStatus.DELETED, response_json=None)
        )
    if row.question_record_id and not preserve_question:
        record_id = row.question_record_id
        # Explicitly clear the link, including ORM state, before deleting its target.
        row.question_record_id = None
        await session.flush()
        await session.execute(delete(QuestionRecord).where(QuestionRecord.id == record_id))
        log_deletion(session, "QUESTION_RECORD", record_id, settings)
    result_id = row.id
    await session.delete(row)
    log_deletion(session, "RESULT", result_id, settings)


async def delete_questions(session, *, owner_id=None, consultation_id=None, settings):
    query = select(QuestionRecord.id)
    query = (
        query.where(QuestionRecord.owner_user_id == owner_id)
        if owner_id
        else query.where(QuestionRecord.consultation_id == consultation_id)
    )
    ids = list((await session.scalars(query)).all())
    if ids:
        await session.execute(
            update(Result).where(Result.question_record_id.in_(ids)).values(question_record_id=None)
        )
        await session.execute(delete(QuestionRecord).where(QuestionRecord.id.in_(ids)))
        for record_id in ids:
            log_deletion(session, "QUESTION_RECORD", record_id, settings)
