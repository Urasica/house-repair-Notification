from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.auth.access import account, require_csrf, require_json_origin
from app.auth.security import csrf_token, new_token, token_hash, valid_token
from app.core.errors import AppError
from app.db.models import AuthSession
from app.db.models import User as UserRow
from app.domain.constants import ErrorCode
from app.schemas.auth import Credentials
from app.schemas.contracts import AuthState, ErrorResponse, User

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["auth"],
    responses={403: {"model": ErrorResponse}, 415: {"model": ErrorResponse}},
)


def user_dto(row: UserRow) -> User:
    return User(id=row.id, email=row.normalized_email, created_at=row.created_at)


def check_attempt(request: Request, body: Credentials):
    request.app.state.auth_rate_limiter.check(
        request.client.host if request.client else "unknown", str(body.email)
    )


@router.post(
    "/register",
    status_code=201,
    response_model=User,
    operation_id="register",
    dependencies=[Depends(require_json_origin)],
    responses={409: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
async def register(body: Credentials, request: Request) -> User:
    check_attempt(request, body)
    db = request.app.state.database
    await db.initialize()
    encoded = await request.app.state.passwords.hash(body.password.get_secret_value())
    async with db.transaction() as session:
        row = await session.scalar(
            insert(UserRow)
            .values(normalized_email=str(body.email), password_hash=encoded)
            .on_conflict_do_nothing(index_elements=["normalized_email"])
            .returning(UserRow)
        )
        if row is None:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "가입을 완료할 수 없어요. 입력을 확인해 주세요.", 409
            )
        result = user_dto(row)
    return result


@router.post(
    "/login",
    response_model=AuthState,
    operation_id="login",
    dependencies=[Depends(require_json_origin)],
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
async def login(body: Credentials, request: Request, response: Response) -> AuthState:
    check_attempt(request, body)
    db = request.app.state.database
    await db.initialize()
    async with db.session() as session:
        user = await session.scalar(
            select(UserRow).where(UserRow.normalized_email == str(body.email))
        )
        user_id = user.id if user else None
        encoded = user.password_hash if user else None
    passwords = request.app.state.passwords
    verified = await passwords.verify(encoded, body.password.get_secret_value())
    if not verified:
        raise AppError(ErrorCode.UNAUTHORIZED, "이메일 또는 비밀번호를 확인해 주세요.", 401)
    replacement = (
        await passwords.hash(body.password.get_secret_value())
        if passwords.hasher.check_needs_rehash(encoded)
        else None
    )
    settings = request.app.state.settings
    token = new_token()
    csrf = csrf_token(token)
    async with db.transaction() as session:
        # Recheck state/hash after password verification without holding a DB connection.
        user = await session.get(UserRow, user_id, with_for_update=True)
        if user is None or user.status != "ACTIVE" or user.password_hash != encoded:
            raise AppError(ErrorCode.UNAUTHORIZED, "이메일 또는 비밀번호를 확인해 주세요.", 401)
        if replacement:
            user.password_hash = replacement
        previous = request.cookies.get(settings.auth_cookie_name)
        if valid_token(previous):
            await session.execute(
                delete(AuthSession).where(AuthSession.token_hash == token_hash(previous))
            )
        session.add(
            AuthSession(
                user_id=user.id,
                token_hash=token_hash(token),
                csrf_hash=token_hash(csrf),
                expires_at=datetime.now(UTC) + timedelta(hours=settings.auth_ttl_hours),
            )
        )
        result = AuthState(user=user_dto(user), csrf_token=csrf)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.auth_ttl_hours * 3600,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    return result


@router.get(
    "/me",
    response_model=AuthState,
    operation_id="getAuth",
    responses={401: {"model": ErrorResponse}},
)
async def me(request: Request) -> AuthState:
    async with request.app.state.database.session() as session:
        principal = await account(request, session, required=False)
        return AuthState(
            user=user_dto(principal.user) if principal else None,
            csrf_token=principal.csrf if principal else None,
        )


@router.post(
    "/logout", status_code=204, operation_id="logout", responses={401: {"model": ErrorResponse}}
)
async def logout(request: Request) -> Response:
    db = request.app.state.database
    async with db.transaction() as session:
        principal = await account(request, session)
        require_csrf(request, principal)
        await session.execute(delete(AuthSession).where(AuthSession.id == principal.auth.id))
    response = Response(status_code=204)
    settings = request.app.state.settings
    response.delete_cookie(
        settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    return response
