"""Reserve a survey embedding allowance before entering the provider request."""

from datetime import UTC, datetime, timedelta
from math import ceil
from uuid import UUID

from sqlalchemy import delete, func, select, text

from app.auth.security import token_hash
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import SurveyUsage
from app.domain.constants import ErrorCode


async def reserve_survey_embedding(database, consultation_id: UUID, settings: Settings):
    session_key = token_hash(str(consultation_id))
    window = timedelta(minutes=10)
    async with database.transaction() as session:
        # Across overlapping requests and API restarts, count and insert as one operation.
        await session.execute(text("SELECT pg_advisory_xact_lock(12002026)"))
        now = datetime.now(UTC)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily = await session.scalar(
            select(func.count()).select_from(SurveyUsage).where(SurveyUsage.created_at >= today)
        )
        if daily >= settings.survey_daily_limit:
            raise AppError(
                ErrorCode.RATE_LIMITED,
                "오늘의 설문 검색 한도에 도달했어요. 나중에 다시 시도해 주세요.",
                429,
                {
                    "retryAfterSeconds": max(
                        1, ceil((today + timedelta(days=1) - now).total_seconds())
                    )
                },
            )
        recent, oldest = (
            await session.execute(
                select(func.count(), func.min(SurveyUsage.created_at)).where(
                    SurveyUsage.session_key == session_key, SurveyUsage.created_at > now - window
                )
            )
        ).one()
        if recent >= settings.survey_session_window_limit:
            raise AppError(
                ErrorCode.RATE_LIMITED,
                "최근에 설문 결과를 여러 번 확인했어요. 잠시 후 다시 시도해 주세요.",
                429,
                {"retryAfterSeconds": max(1, ceil((oldest + window - now).total_seconds()))},
            )
        await session.execute(
            delete(SurveyUsage).where(SurveyUsage.created_at <= now - timedelta(days=2))
        )
        session.add(SurveyUsage(session_key=session_key, created_at=now))
