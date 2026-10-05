"""One-shot maintenance; never run API startup recovery from these commands."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import case, delete, func, select, update

from app.db.models import AuthSession, ChatUsage, Consultation, QuestionRecord, Result
from app.services.deletion import delete_result, log_deletion


async def cleanup(session, settings, *, now=None):
    now = now or datetime.now(UTC)
    counts = {}
    counts["authSessions"] = (
        await session.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    ).rowcount
    # Delete expired consultations immediately: a daily schedule remains within the
    # seven-day upper bound. FK SET NULL preserves member history and clean questions.
    expired = select(Consultation.id).where(Consultation.expires_at <= now)
    results = list(
        (
            await session.scalars(
                select(Result)
                .where(
                    (Result.retained_until <= now)
                    | (Result.owner_user_id.is_(None) & Result.consultation_id.in_(expired))
                )
                .with_for_update()
            )
        ).all()
    )
    for row in results:
        await delete_result(session, row, settings, preserve_question=True)
    counts["results"] = len(results)
    questions = list(
        (
            await session.scalars(
                select(QuestionRecord.id).where(QuestionRecord.retained_until <= now)
            )
        ).all()
    )
    if questions:
        await session.execute(
            update(Result)
            .where(Result.question_record_id.in_(questions))
            .values(question_record_id=None)
        )
        await session.execute(delete(QuestionRecord).where(QuestionRecord.id.in_(questions)))
        for identifier in questions:
            log_deletion(session, "QUESTION_RECORD", identifier, settings)
    counts["questions"] = len(questions)
    await session.flush()
    identifiers = list((await session.scalars(expired.with_for_update())).all())
    await session.execute(delete(Consultation).where(Consultation.id.in_(identifiers)))
    for identifier in identifiers:
        log_deletion(session, "CONSULTATION", identifier, settings)
    counts["consultations"] = len(identifiers)
    counts["usage"] = (
        await session.execute(
            delete(ChatUsage).where(ChatUsage.created_at <= now - timedelta(days=2))
        )
    ).rowcount
    return counts


async def question_statistics(session, *, since=None, now=None):
    """Aggregate only sanitized classifications; never return raw text or user IDs."""
    now = now or datetime.now(UTC)
    fields = [
        QuestionRecord.kind,
        QuestionRecord.catalog_version,
        case(
            (
                QuestionRecord.kind == "SURVEY",
                QuestionRecord.answers_json["selections"]["facilityId"].astext,
            ),
            else_=QuestionRecord.answers_json["facilityId"].astext,
        ),
        case(
            (
                QuestionRecord.kind == "SURVEY",
                QuestionRecord.answers_json["selections"]["symptomId"].astext,
            ),
            else_=QuestionRecord.answers_json["symptomId"].astext,
        ),
    ]
    query = select(*fields, func.count()).where(QuestionRecord.retained_until > now)
    if since:
        query = query.where(QuestionRecord.created_at >= since)
    rows = await session.execute(query.group_by(*fields).order_by(func.count().desc(), *fields))
    return [
        dict(zip(("kind", "catalogVersion", "facilityId", "symptomId", "count"), row, strict=True))
        for row in rows
    ]
