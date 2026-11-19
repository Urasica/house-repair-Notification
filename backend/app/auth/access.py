import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import csrf_token, token_hash, valid_token
from app.core.errors import AppError
from app.db.models import AuthSession, Consultation, Result, User
from app.domain.constants import ErrorCode


@dataclass(frozen=True)
class Principal:
    user: User
    auth: AuthSession
    csrf: str


def require_json_origin(request: Request):
    if not request.app.state.settings.allows_write_origin(
        request.headers.get("origin"), request.headers.get("sec-fetch-site")
    ):
        raise AppError(ErrorCode.UNAUTHORIZED, "이 요청은 허용되지 않아요.", 403)
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise AppError(ErrorCode.VALIDATION_ERROR, "JSON 형식으로 요청해 주세요.", 415)


async def account(request: Request, session: AsyncSession, *, required=True) -> Principal | None:
    token = request.cookies.get(request.app.state.settings.auth_cookie_name)
    if token is None:
        if required:
            raise AppError(ErrorCode.AUTH_REQUIRED, "로그인 후 이용해 주세요.", 401)
        return None
    if not valid_token(token):
        raise AppError(ErrorCode.AUTH_EXPIRED, "로그인이 만료됐어요. 다시 로그인해 주세요.", 401)
    row = (
        await session.execute(
            select(AuthSession, User)
            .join(User, User.id == AuthSession.user_id)
            .where(AuthSession.token_hash == token_hash(token))
        )
    ).first()
    if row is None or row[0].expires_at <= datetime.now(UTC) or row[1].status != "ACTIVE":
        raise AppError(ErrorCode.AUTH_EXPIRED, "로그인이 만료됐어요. 다시 로그인해 주세요.", 401)
    csrf = csrf_token(token)
    if not hmac.compare_digest(row[0].csrf_hash, token_hash(csrf)):
        raise AppError(ErrorCode.AUTH_EXPIRED, "다시 로그인해 주세요.", 401)
    return Principal(row[1], row[0], csrf)


def require_csrf(request: Request, principal: Principal):
    require_json_origin(request)
    supplied = request.headers.get("x-csrf-token", "")
    if not re.fullmatch(r"[0-9a-f]{64}", supplied) or not hmac.compare_digest(
        supplied, principal.csrf
    ):
        raise AppError(ErrorCode.UNAUTHORIZED, "요청을 확인한 뒤 다시 시도해 주세요.", 403)


async def guest(request: Request, session: AsyncSession) -> Consultation:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not valid_token(token):
        raise AppError(ErrorCode.UNAUTHORIZED, "상담 인증을 확인해 주세요.", 401)
    row = await session.scalar(
        select(Consultation).where(Consultation.guest_token_hash == token_hash(token)).limit(1)
    )
    if row is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "상담 인증을 확인해 주세요.", 401)
    if row.expires_at <= datetime.now(UTC):
        raise AppError(
            ErrorCode.SESSION_EXPIRED, "상담이 만료됐어요. 새 상담을 시작해 주세요.", 401
        )
    return row


def not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "기록을 찾을 수 없어요.", 404)


async def own_consultation(
    request: Request,
    session: AsyncSession,
    consultation_id: UUID,
    *,
    member_only=False,
    mutation=False,
) -> Consultation:
    if not member_only and request.headers.get("authorization"):
        row = await guest(request, session)
        if row.id != consultation_id:
            raise not_found()
        return row
    principal = await account(request, session)
    row = await session.get(Consultation, consultation_id)
    if row is None or row.owner_user_id != principal.user.id:
        raise not_found()
    if row.expires_at <= datetime.now(UTC):
        raise AppError(
            ErrorCode.SESSION_EXPIRED, "상담이 만료됐어요. 새 상담을 시작해 주세요.", 401
        )
    if mutation:
        require_csrf(request, principal)
    return row


async def own_result(
    request: Request, session: AsyncSession, result_id: UUID, *, mutation=False
) -> Result:
    principal = await account(request, session)
    row = await session.get(Result, result_id)
    if (
        row is None
        or row.owner_user_id != principal.user.id
        or row.retained_until <= datetime.now(UTC)
    ):
        raise not_found()
    if mutation:
        require_csrf(request, principal)
    return row


async def guard_member_path(request: Request):
    path = request.url.path
    chat = re.fullmatch(r"/api/v1/sessions/([^/]+)/chat/(?:messages|survey-context)", path)
    history = re.fullmatch(r"/api/v1/me/(?:results(?:/[^/]+)?|question-records)", path)
    if not chat and not history:
        return
    db = request.app.state.database
    await db.initialize()
    async with db.session() as session:
        principal = await account(request, session)
        mutation = request.method in {"POST", "PUT", "DELETE", "PATCH"}
        if mutation:
            require_csrf(request, principal)
        if chat:
            try:
                consultation_id = UUID(chat.group(1))
            except ValueError as error:
                raise not_found() from error
            await own_consultation(request, session, consultation_id, member_only=True)
        elif path.startswith("/api/v1/me/results/"):
            try:
                result_id = UUID(path.rsplit("/", 1)[1])
            except ValueError as error:
                raise not_found() from error
            await own_result(request, session, result_id)
