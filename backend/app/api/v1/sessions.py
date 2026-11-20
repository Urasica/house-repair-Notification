import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select

from app.auth.access import account, not_found, own_consultation, require_csrf, require_json_origin
from app.auth.security import new_token, token_hash
from app.core.errors import AppError
from app.core.metrics import GUIDANCE_RESULTS
from app.db.models import Consultation, QuestionRecord, Result
from app.db.requests import RequestRepository, request_fingerprint
from app.domain.constants import ErrorCode, RequestKind, RequestStatus, SessionPurpose
from app.schemas.contracts import (
    Context,
    ContextUpdate,
    ErrorResponse,
    EvaluationRequest,
    GuidanceResult,
    QuestionsResponse,
    RequestState,
    Session,
    SessionCreate,
    SessionCreated,
)
from app.services.catalog import require_latest_catalog
from app.services.chat import replay_chat
from app.services.consultations import (
    check_revision,
    latest_knowledge,
    pinned_catalog,
    require_purpose,
    session_dto,
)
from app.services.deletion import delete_questions, delete_result, log_deletion
from app.services.deletion_export import export_after_delete
from app.services.guidance import add_years, result_dto, unavailable_result
from app.services.retrieval import revalidate_citations
from app.services.survey_policy import survey_policy


async def ready_database(request: Request):
    await request.app.state.database.initialize()


router = APIRouter(
    prefix="/api/v1/sessions",
    tags=["sessions"],
    dependencies=[Depends(ready_database)],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        410: {"model": ErrorResponse},
    },
)
repository = RequestRepository()


def check_question_deletion(request: Request, owner_id):
    if owner_id and request.app.state.question_deletion_locks.is_held(owner_id):
        raise AppError(
            ErrorCode.SESSION_BUSY, "질문 기록을 정리하고 있어요. 잠시 후 다시 시도해 주세요.", 409
        )


@router.post(
    "",
    status_code=201,
    response_model=SessionCreated,
    operation_id="createSession",
    responses={429: {"model": ErrorResponse}},
)
async def create_session(body: SessionCreate, request: Request):
    db, settings = request.app.state.database, request.app.state.settings
    require_json_origin(request)
    request.app.state.session_creation_limiter.check(
        request.client.host if request.client else "unknown"
    )
    async with db.transaction() as session:
        principal = await account(request, session, required=body.purpose == SessionPurpose.CHAT)
        if principal:
            require_csrf(request, principal)
            check_question_deletion(request, principal.user.id)
        await require_latest_catalog(session, body.catalog_version)
        token = None if principal else new_token()
        row = Consultation(
            purpose=body.purpose,
            owner_user_id=principal.user.id if principal else None,
            guest_token_hash=token_hash(token) if token else None,
            catalog_version=body.catalog_version,
            knowledge_set_id=await latest_knowledge(session, body.catalog_version, settings),
            context_json=Context().model_dump(mode="json", by_alias=True),
            expires_at=datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours),
        )
        session.add(row)
        await session.flush()
        result = SessionCreated(session=await session_dto(session, row), session_token=token)
    return result


@router.get("/{consultation_id}", response_model=Session, operation_id="getSession")
async def get_session(consultation_id: UUID, request: Request):
    async with request.app.state.database.session() as session:
        return await session_dto(session, await own_consultation(request, session, consultation_id))


@router.put("/{consultation_id}/context", response_model=Session, operation_id="updateContext")
async def update_context(consultation_id: UUID, body: ContextUpdate, request: Request):
    db = request.app.state.database
    async with db.session() as session:
        await own_consultation(request, session, consultation_id, mutation=True)
    async with db.change(), request.app.state.consultation_locks.hold(consultation_id):
        async with db.transaction() as session:
            row = await own_consultation(request, session, consultation_id, mutation=True)
            check_revision(row, body.expected_revision)
            catalog = await pinned_catalog(session, row)
            previous = Context.model_validate(row.context_json)
            if row.purpose == SessionPurpose.CHAT and body.context.answers:
                raise AppError(
                    ErrorCode.INVALID_ANSWER, "챗봇에서는 설문 답변을 사용하지 않아요.", 422
                )
            canonical = survey_policy(catalog, body.context, previous).context.model_dump(
                mode="json", by_alias=True
            )
            if canonical != previous.model_dump(mode="json", by_alias=True):
                row.context_json = canonical
                row.revision += 1
            await session.flush()
            result = await session_dto(session, row)
    return result


@router.get(
    "/{consultation_id}/questions", response_model=QuestionsResponse, operation_id="getQuestions"
)
async def get_questions(consultation_id: UUID, request: Request):
    async with request.app.state.database.session() as session:
        row = await own_consultation(request, session, consultation_id)
        require_purpose(row, SessionPurpose.SURVEY)
        catalog = await pinned_catalog(session, row)
        return survey_policy(catalog, Context.model_validate(row.context_json)).questions_response(
            row.catalog_version, row.revision
        )


async def replay_result(session, payload):
    saved = GuidanceResult.model_validate(payload)
    row = await session.get(Result, saved.id)
    if row is None or row.retained_until <= datetime.now(UTC):
        raise not_found()
    return await result_dto(session, row)


@router.post(
    "/{consultation_id}/evaluations",
    status_code=201,
    response_model=GuidanceResult,
    operation_id="evaluateSurvey",
    responses={200: {"model": GuidanceResult}, 429: {"model": ErrorResponse}},
)
async def evaluate(
    consultation_id: UUID, body: EvaluationRequest, request: Request, response: Response
):
    db, settings = request.app.state.database, request.app.state.settings
    fingerprint = request_fingerprint(
        RequestKind.SURVEY, body.model_dump(mode="json", by_alias=True)
    )
    async with db.session() as session:
        row = await own_consultation(request, session, consultation_id, mutation=True)
        require_purpose(row, SessionPurpose.SURVEY)
        existing = await repository.lookup(session, consultation_id, body.request_id)
        if existing:
            reservation = repository.existing(existing, RequestKind.SURVEY, fingerprint)
            response.status_code = 200
            return await replay_result(session, reservation.replay)
    async with db.change(), request.app.state.consultation_locks.hold(consultation_id):
        run_id = None
        try:
            async with asyncio.timeout(settings.survey_timeout_seconds):
                async with db.transaction() as session:
                    row = await own_consultation(request, session, consultation_id, mutation=True)
                    check_question_deletion(request, row.owner_user_id)
                    check_revision(row, body.expected_revision)
                    reservation = await repository.reserve(
                        session, consultation_id, body.request_id, RequestKind.SURVEY, fingerprint
                    )
                    if reservation.is_replay:
                        response.status_code = 200
                        return await replay_result(session, reservation.replay)
                    run_id = reservation.run_id
                    snapshot = await session_dto(session, row)
                    catalog = await pinned_catalog(session, row)
                result = await request.app.state.evaluate_survey(snapshot, catalog, settings)
                async with db.transaction() as session:
                    row = await own_consultation(request, session, consultation_id, mutation=True)
                    check_revision(row, snapshot.revision)
                    if not await revalidate_citations(session, result, settings):
                        result = unavailable_result(result)
                    record = QuestionRecord(
                        owner_user_id=row.owner_user_id,
                        consultation_id=row.id,
                        origin_key=f"SURVEY:{run_id}",
                        kind="SURVEY",
                        catalog_version=row.catalog_version,
                        answers_json={
                            "selections": snapshot.context.model_dump(
                                mode="json", by_alias=True, exclude={"description", "answers"}
                            ),
                            "answers": snapshot.context.answers,
                            "answerLabels": result.summary.answer_labels,
                        },
                        masked_question=None,
                        retrieval_meta_json={
                            "status": result.status,
                            "chunkIds": [str(c.chunk_id) for c in result.citations],
                        },
                        retained_until=add_years(
                            result.generated_at, settings.question_retention_years
                        ),
                    )
                    session.add(record)
                    await session.flush()
                    session.add(
                        Result(
                            id=result.id,
                            consultation_id=row.id,
                            owner_user_id=row.owner_user_id,
                            request_run_id=run_id,
                            question_record_id=record.id,
                            input_snapshot_json=snapshot.context.model_dump(
                                mode="json", by_alias=True
                            ),
                            payload_json=result.model_dump(mode="json", by_alias=True),
                            retained_until=result.retained_until,
                        )
                    )
                    await repository.complete(
                        session, run_id, result.model_dump(mode="json", by_alias=True)
                    )
                GUIDANCE_RESULTS.labels("survey", result.status).inc()
                return result
        except BaseException as error:
            if run_id:
                try:
                    with anyio.CancelScope(shield=True):
                        async with db.transaction() as session:
                            await repository.fail(session, run_id)
                except AppError:
                    pass  # DB recovery will fail remaining PROCESSING after active changes finish.
            if isinstance(error, TimeoutError):
                raise AppError(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "처리를 완료하지 못했어요. 요청 상태를 확인해 주세요.",
                    503,
                ) from error
            raise


@router.get(
    "/{consultation_id}/results/{result_id}",
    response_model=GuidanceResult,
    operation_id="getSessionResult",
)
async def get_result(consultation_id: UUID, result_id: UUID, request: Request):
    async with request.app.state.database.session() as session:
        await own_consultation(request, session, consultation_id)
        row = await session.get(Result, result_id)
        if (
            row is None
            or row.consultation_id != consultation_id
            or row.retained_until <= datetime.now(UTC)
        ):
            raise not_found()
        return await result_dto(session, row)


@router.get(
    "/{consultation_id}/requests/{request_id}",
    response_model=RequestState,
    operation_id="getRequest",
)
async def get_request(consultation_id: UUID, request_id: UUID, request: Request):
    async with request.app.state.database.session() as session:
        await own_consultation(request, session, consultation_id)
        row = await repository.lookup(session, consultation_id, request_id)
        if row is None:
            raise not_found()
        if row.kind == RequestKind.CHAT:
            await own_consultation(request, session, consultation_id, member_only=True)
        payload = None
        if row.state == RequestStatus.COMPLETED:
            payload = (
                await replay_result(session, row.response_json)
                if row.kind == RequestKind.SURVEY
                else await replay_chat(session, row, request.app.state.settings)
            )
        return RequestState(
            request_id=request_id,
            kind=row.kind,
            state=row.state,
            retry_after_ms=1000 if row.state == RequestStatus.PROCESSING else None,
            response=payload,
        )


@router.delete("/{consultation_id}", status_code=204, operation_id="endSession")
async def end_session(
    consultation_id: UUID,
    request: Request,
    erase_records: bool = Query(default=False, alias="eraseRecords"),
):
    db, settings = request.app.state.database, request.app.state.settings
    async with db.session() as session:
        row = await own_consultation(request, session, consultation_id, mutation=True)
        if erase_records and row.owner_user_id:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "회원 기록은 이전 결과 메뉴에서 삭제해 주세요.", 422
            )
    async with db.change(), request.app.state.consultation_locks.hold(consultation_id):
        async with db.transaction() as session:
            row = await own_consultation(request, session, consultation_id, mutation=True)
            if erase_records:
                await delete_questions(session, consultation_id=consultation_id, settings=settings)
            if row.owner_user_id is None:
                results = list(
                    (
                        await session.scalars(
                            select(Result).where(Result.consultation_id == consultation_id)
                        )
                    ).all()
                )
                for result in results:
                    await delete_result(
                        session, result, settings, preserve_question=not erase_records
                    )
            # Flush FK cleanup before deleting the short-lived consultation.
            await session.flush()
            await session.delete(row)
            log_deletion(session, "CONSULTATION", consultation_id, settings)
    await export_after_delete(db, settings)
    return Response(status_code=204)
