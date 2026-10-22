import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, delete, func, or_, select

from app.api.v1.history import cursor_for, parse_cursor
from app.api.v1.sessions import check_question_deletion, ready_database, repository
from app.auth.access import own_consultation, own_result
from app.core.errors import AppError
from app.db.models import ChatUsage, Message, QuestionRecord, RequestRun
from app.db.requests import request_fingerprint
from app.domain.constants import ErrorCode, RequestKind, SessionPurpose
from app.schemas.contracts import (
    ChatHistory,
    ChatRequest,
    ChatResponse,
    ChatSurveyImport,
    Context,
    Session,
)
from app.services.chat import (
    citation_check,
    fallback,
    project_question,
    replay_chat,
    stored_response,
)
from app.services.chat_context import confirmed_context
from app.services.consultations import check_revision, pinned_catalog, require_purpose, session_dto
from app.services.guidance import add_years
from app.services.retrieval import revalidate_citations
from app.services.survey_policy import survey_policy

router = APIRouter(prefix="/api/v1/sessions", tags=["chat"], dependencies=[Depends(ready_database)])


@router.post(
    "/{consultation_id}/chat/survey-context",
    response_model=Session,
    operation_id="importChatSurvey",
)
async def import_survey(consultation_id: UUID, body: ChatSurveyImport, request: Request):
    db = request.app.state.database
    async with db.session() as session:
        await own_consultation(request, session, consultation_id, member_only=True, mutation=True)
    async with db.change(), request.app.state.consultation_locks.hold(consultation_id):
        async with db.transaction() as session:
            row = await own_consultation(
                request, session, consultation_id, member_only=True, mutation=True
            )
            require_purpose(row, SessionPurpose.CHAT)
            check_revision(row, body.expected_revision)
            source = await own_result(request, session, body.result_id)
            if source.payload_json["catalogVersion"] != row.catalog_version:
                raise AppError(
                    ErrorCode.CATALOG_UPDATED,
                    "이 설문은 다른 목록으로 작성됐어요. 새 대화에서 직접 상황을 알려 주세요.",
                    409,
                )
            catalog = await pinned_catalog(session, row)
            context = Context.model_validate(source.input_snapshot_json)
            context.description = ""
            canonical = survey_policy(catalog, context).context.model_dump(
                mode="json", by_alias=True
            )
            if canonical != row.context_json:
                row.context_json = canonical
                row.revision += 1
            await session.flush()
            return await session_dto(session, row)


async def check_budget(session, owner, settings):
    now = datetime.now(UTC)
    await session.execute(delete(ChatUsage).where(ChatUsage.created_at < now - timedelta(days=2)))
    query = select(func.count()).select_from(ChatUsage)
    personal = await session.scalar(
        query.where(
            ChatUsage.owner_user_id == owner, ChatUsage.created_at > now - timedelta(minutes=10)
        )
    )
    daily = await session.scalar(
        query.where(ChatUsage.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0))
    )
    if personal >= settings.chat_user_window_limit or daily >= settings.chat_daily_limit:
        raise AppError(
            ErrorCode.RATE_LIMITED,
            "오늘 또는 최근 대화 사용량이 많아요. 잠시 후 다시 시도해 주세요.",
            429,
            {
                "retryAfterSeconds": 600
                if personal >= settings.chat_user_window_limit
                else max(
                    1,
                    int(
                        (
                            (now + timedelta(days=1)).replace(
                                hour=0, minute=0, second=0, microsecond=0
                            )
                            - now
                        ).total_seconds()
                    ),
                )
            },
        )


@router.get(
    "/{consultation_id}/chat/messages", response_model=ChatHistory, operation_id="getChatHistory"
)
async def history(
    consultation_id: UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, min_length=1, max_length=512),
):
    async with request.app.state.database.session() as session:
        await own_consultation(request, session, consultation_id, member_only=True)
        query = select(RequestRun).where(
            RequestRun.consultation_id == consultation_id,
            RequestRun.kind == "CHAT",
            RequestRun.state == "COMPLETED",
        )
        if cursor:
            stamp, identifier = parse_cursor(cursor)
            query = query.where(
                or_(
                    RequestRun.created_at > stamp,
                    and_(RequestRun.created_at == stamp, RequestRun.id > identifier),
                )
            )
        rows = list(
            (
                await session.scalars(
                    query.order_by(RequestRun.created_at, RequestRun.id).limit(limit + 1)
                )
            ).all()
        )
        return ChatHistory(
            items=[
                await replay_chat(session, row, request.app.state.settings) for row in rows[:limit]
            ],
            next_cursor=cursor_for(rows[limit - 1]) if len(rows) > limit else None,
        )


@router.post(
    "/{consultation_id}/chat/messages", response_model=ChatResponse, operation_id="sendChatMessage"
)
async def send(consultation_id: UUID, body: ChatRequest, request: Request):
    db, settings = request.app.state.database, request.app.state.settings
    fingerprint = request_fingerprint(RequestKind.CHAT, body.model_dump(mode="json", by_alias=True))
    async with db.session() as session:
        row = await own_consultation(
            request, session, consultation_id, member_only=True, mutation=True
        )
        require_purpose(row, SessionPurpose.CHAT)
        existing = await repository.lookup(session, consultation_id, body.request_id)
        if existing:
            repository.existing(existing, RequestKind.CHAT, fingerprint)
            return await replay_chat(session, existing, settings)
    async with db.change(), request.app.state.consultation_locks.hold(consultation_id):
        run_id = None
        try:
            async with asyncio.timeout(settings.chat_timeout_seconds):
                deadline = asyncio.get_running_loop().time() + settings.chat_timeout_seconds - 2
                # Serialize only reservations across sessions; release before external calls.
                async with request.app.state.chat_budget_lock:
                    async with db.transaction() as session:
                        row = await own_consultation(
                            request, session, consultation_id, member_only=True, mutation=True
                        )
                        check_question_deletion(request, row.owner_user_id)
                        require_purpose(row, SessionPurpose.CHAT)
                        check_revision(row, body.expected_revision)
                        await check_budget(session, row.owner_user_id, settings)
                        reservation = await repository.reserve(
                            session, consultation_id, body.request_id, RequestKind.CHAT, fingerprint
                        )
                        run_id = reservation.run_id
                        session.add(ChatUsage(owner_user_id=row.owner_user_id))
                        catalog = await pinned_catalog(session, row)
                        context = confirmed_context(
                            Context.model_validate(row.context_json), body.content, catalog
                        )
                        canonical = context.model_dump(mode="json", by_alias=True)
                        if canonical != Context.model_validate(row.context_json).model_dump(
                            mode="json", by_alias=True
                        ):
                            row.context_json = canonical
                            row.revision += 1
                        await session.flush()
                        snapshot = await session_dto(session, row)
                        messages = list(
                            (
                                await session.scalars(
                                    select(Message)
                                    .where(Message.consultation_id == row.id)
                                    .order_by(Message.created_at.desc(), Message.id.desc())
                                    .limit(6)
                                )
                            ).all()
                        )
                        recent = [
                            {"role": m.role, "content": project_question(m.content)}
                            for m in reversed(messages)
                        ]
                result = await request.app.state.chat_response(
                    snapshot,
                    catalog,
                    settings,
                    body.content,
                    body.request_id,
                    recent,
                    deadline=deadline,
                )
                async with db.transaction() as session:
                    row = await own_consultation(
                        request, session, consultation_id, member_only=True, mutation=True
                    )
                    check_revision(row, snapshot.revision)
                    if not await revalidate_citations(
                        session, citation_check(result, snapshot), settings
                    ):
                        result = fallback(result)
                    for message in (result.user_message, result.assistant_message):
                        session.add(
                            Message(
                                id=message.id,
                                consultation_id=row.id,
                                request_run_id=run_id,
                                role=message.role,
                                content=message.content,
                                created_at=message.created_at,
                                citations_json=[
                                    c.model_dump(mode="json", by_alias=True)
                                    for c in message.citations
                                ],
                            )
                        )
                    session.add(
                        QuestionRecord(
                            owner_user_id=row.owner_user_id,
                            consultation_id=row.id,
                            origin_key=f"CHAT:{run_id}",
                            kind="CHAT",
                            catalog_version=row.catalog_version,
                            answers_json=snapshot.context.model_dump(
                                mode="json", by_alias=True, exclude={"description"}
                            ),
                            masked_question=project_question(body.content),
                            retrieval_meta_json={
                                "status": result.status,
                                "answerMode": result.answer_mode,
                                "chunkIds": [
                                    str(c.chunk_id) for c in result.assistant_message.citations
                                ],
                            },
                            retained_until=add_years(
                                result.user_message.created_at, settings.question_retention_years
                            ),
                        )
                    )
                    await repository.complete(
                        session, run_id, stored_response(result, snapshot, settings)
                    )
                return result
        except BaseException as error:
            if run_id:
                try:
                    with anyio.CancelScope(shield=True):
                        async with db.transaction() as session:
                            await repository.fail(session, run_id)
                except AppError:
                    pass
            if isinstance(error, TimeoutError):
                raise AppError(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "처리를 완료하지 못했어요. 요청 상태를 확인해 주세요.",
                    503,
                ) from error
            raise
