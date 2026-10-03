import base64
import binascii
import json
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import and_, or_, select

from app.api.v1.sessions import ready_database
from app.auth.access import account, own_result, require_csrf
from app.core.errors import AppError
from app.db.models import Consultation, QuestionRecord, Result
from app.domain.constants import ErrorCode
from app.schemas.contracts import ErrorResponse, GuidanceResult, ResultList, ResultListItem
from app.services.deletion import delete_questions, delete_result
from app.services.guidance import result_dto

router = APIRouter(
    prefix="/api/v1/me",
    tags=["history"],
    dependencies=[Depends(ready_database)],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)


def cursor_for(row) -> str:
    raw = json.dumps([row.created_at.isoformat(), str(row.id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def parse_cursor(value: str) -> tuple[datetime, UUID]:
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        date, identifier = json.loads(decoded)
        stamp = datetime.fromisoformat(date)
        if stamp.tzinfo is None:
            raise ValueError("Timezone is required")
        return stamp, UUID(identifier)
    except (ValueError, TypeError, binascii.Error, UnicodeError) as error:
        raise AppError(ErrorCode.VALIDATION_ERROR, "조회 위치를 확인해 주세요.", 422) from error


@router.get("/results", response_model=ResultList, operation_id="getHistory")
async def history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, min_length=1, max_length=512),
):
    async with request.app.state.database.session() as session:
        principal = await account(request, session)
        query = select(Result).where(
            Result.owner_user_id == principal.user.id, Result.retained_until > datetime.now(UTC)
        )
        if cursor:
            stamp, identifier = parse_cursor(cursor)
            query = query.where(
                or_(
                    Result.created_at < stamp,
                    and_(Result.created_at == stamp, Result.id < identifier),
                )
            )
        rows = list(
            (
                await session.scalars(
                    query.order_by(Result.created_at.desc(), Result.id.desc()).limit(limit + 1)
                )
            ).all()
        )
        items = [
            ResultListItem.model_validate(
                {
                    key: row.payload_json[key]
                    for key in ("id", "generatedAt", "status", "summary", "retainedUntil")
                }
            )
            for row in rows[:limit]
        ]
        return ResultList(
            items=items, next_cursor=cursor_for(rows[limit - 1]) if len(rows) > limit else None
        )


@router.get("/results/{result_id}", response_model=GuidanceResult, operation_id="getHistoryResult")
async def get_history_result(result_id: UUID, request: Request):
    async with request.app.state.database.session() as session:
        return await result_dto(session, await own_result(request, session, result_id))


@router.delete("/results/{result_id}", status_code=204, operation_id="deleteHistoryResult")
async def remove_result(result_id: UUID, request: Request):
    db, settings = request.app.state.database, request.app.state.settings
    async with db.session() as session:
        row = await own_result(request, session, result_id, mutation=True)
        consultation_id = row.consultation_id
    async with db.change(), AsyncExitStack() as stack:
        if consultation_id:
            await stack.enter_async_context(
                request.app.state.consultation_locks.hold(consultation_id)
            )
        async with db.transaction() as session:
            row = await own_result(request, session, result_id, mutation=True)
            await delete_result(session, row, settings)
    return Response(status_code=204)


@router.delete("/question-records", status_code=204, operation_id="deleteQuestionRecords")
async def remove_questions(request: Request):
    db, settings = request.app.state.database, request.app.state.settings
    async with db.session() as session:
        principal = await account(request, session)
        require_csrf(request, principal)
        owner_id = principal.user.id
    async with (
        db.change(),
        request.app.state.question_deletion_locks.hold(owner_id),
        AsyncExitStack() as stack,
    ):
        async with db.session() as session:
            # All owned consultations, including those without a completed question yet.
            ids = set(
                (
                    await session.scalars(
                        select(Consultation.id).where(Consultation.owner_user_id == owner_id)
                    )
                ).all()
            )
            ids.update(
                (
                    await session.scalars(
                        select(QuestionRecord.consultation_id).where(
                            QuestionRecord.owner_user_id == owner_id,
                            QuestionRecord.consultation_id.is_not(None),
                        )
                    )
                ).all()
            )
            for consultation_id in sorted(ids, key=str):
                await stack.enter_async_context(
                    request.app.state.consultation_locks.hold(consultation_id)
                )
            async with db.transaction() as session:
                principal = await account(request, session)
                require_csrf(request, principal)
                await delete_questions(session, owner_id=owner_id, settings=settings)
    return Response(status_code=204)
