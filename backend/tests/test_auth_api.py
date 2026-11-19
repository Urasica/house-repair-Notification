from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from starlette.requests import Request

from app.auth.access import own_consultation, own_result
from app.auth.rate_limit import AuthRateLimiter
from app.auth.security import new_token, token_hash
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import AuthSession, Catalog, Consultation, Result, User
from app.domain.constants import ErrorCode
from app.main import create_app

pytestmark = pytest.mark.integration
ORIGIN = "http://localhost:8080"
BODY = {"email": "member@example.com", "password": "not-a-real-password"}


class BoundDatabase:
    def __init__(self, session):
        self.bound = session

    async def initialize(self):
        pass

    @asynccontextmanager
    async def session(self):
        async with self.bound.begin_nested():
            yield self.bound

    transaction = session

    async def dispose(self):
        pass

    @asynccontextmanager
    async def change(self):
        yield


@pytest.fixture
async def auth_client(pg_session):
    app = create_app(Settings(_env_file=None), BoundDatabase(pg_session))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, app


async def signed_in(client):
    registered = await client.post("/api/v1/auth/register", json=BODY, headers={"Origin": ORIGIN})
    assert registered.status_code == 201
    response = await client.post("/api/v1/auth/login", json=BODY, headers={"Origin": ORIGIN})
    assert response.status_code == 200
    return response


async def test_register_login_me_logout_and_db_hashes(auth_client, pg_session):
    client, _ = auth_client
    assert (await client.get("/api/v1/auth/me")).json() == {"user": None, "csrfToken": None}
    response = await signed_in(client)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=86400" in cookie
    assert "Domain=" not in cookie and "Secure" not in cookie
    token = client.cookies.get("repair_auth")
    state = response.json()
    assert (
        "password" not in response.text
        and "passwordHash" not in response.text
        and token not in response.text
    )
    user = await pg_session.scalar(select(User))
    saved = await pg_session.scalar(select(AuthSession))
    assert user.password_hash.startswith("$argon2id$")
    assert saved.token_hash == token_hash(token) and saved.csrf_hash == token_hash(
        state["csrfToken"]
    )
    assert saved.expires_at > datetime.now(UTC) + timedelta(hours=23)
    assert (await client.get("/api/v1/auth/me")).json() == state
    csrf = state["csrfToken"]
    out = await client.post(
        "/api/v1/auth/logout",
        headers={
            "Origin": ORIGIN,
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
        },
    )
    assert out.status_code == 204 and out.headers["cache-control"] == "no-store"
    assert await pg_session.scalar(select(func.count()).select_from(AuthSession)) == 0
    assert (await client.get("/api/v1/auth/me")).json()["user"] is None
    client.cookies.set("repair_auth", token)
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_origin_json_csrf_and_duplicate_registration(auth_client, pg_session):
    client, _ = auth_client
    for origin in (None, "null", "https://evil.example"):
        headers = {"Origin": origin} if origin else {}
        response = await client.post("/api/v1/auth/register", json=BODY, headers=headers)
        assert response.status_code == 403
    response = await client.post(
        "/api/v1/auth/register",
        content="{}",
        headers={"Origin": ORIGIN, "Content-Type": "text/plain"},
    )
    assert response.status_code == 415
    signed = await signed_in(client)
    duplicate = await client.post(
        "/api/v1/auth/register",
        json={**BODY, "email": " MEMBER@Example.COM "},
        headers={"Origin": ORIGIN},
    )
    assert duplicate.status_code == 409
    assert await pg_session.scalar(select(func.count()).select_from(User)) == 1
    for csrf in ("", "d" * 64, "한국어"):
        if not csrf.isascii():
            continue  # Browser HTTP headers cannot contain raw non-ASCII; covered by unit guard.
        out = await client.post(
            "/api/v1/auth/logout",
            headers={"Origin": ORIGIN, "Content-Type": "application/json", "X-CSRF-Token": csrf},
        )
        assert out.status_code == 403
    assert (await client.get("/api/v1/auth/me")).json()["csrfToken"] == signed.json()["csrfToken"]


async def test_invalid_credentials_and_disabled_account_have_same_failure(auth_client, pg_session):
    client, _ = auth_client
    await signed_in(client)
    unknown = await client.post(
        "/api/v1/auth/login",
        json={**BODY, "email": "missing@example.com"},
        headers={"Origin": ORIGIN},
    )
    wrong = await client.post(
        "/api/v1/auth/login",
        json={**BODY, "password": "different-password"},
        headers={"Origin": ORIGIN},
    )
    user = await pg_session.scalar(select(User))
    user.status = "DISABLED"
    await pg_session.flush()
    disabled = await client.post("/api/v1/auth/login", json=BODY, headers={"Origin": ORIGIN})
    for response in (unknown, wrong, disabled):
        assert response.status_code == 401 and response.json()["error"]["code"] == "UNAUTHORIZED"
        assert response.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_expired_auth_clears_cookie_and_rotation_revokes_previous(auth_client, pg_session):
    client, _ = auth_client
    first = await signed_in(client)
    old = client.cookies.get("repair_auth")
    second = await client.post("/api/v1/auth/login", json=BODY, headers={"Origin": ORIGIN})
    assert first.json()["csrfToken"] != second.json()["csrfToken"]
    assert await pg_session.scalar(select(func.count()).select_from(AuthSession)) == 1
    assert (
        await pg_session.scalar(
            select(AuthSession).where(AuthSession.token_hash == token_hash(old))
        )
        is None
    )
    saved = await pg_session.scalar(select(AuthSession))
    saved.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await pg_session.flush()
    expired = await client.get("/api/v1/auth/me")
    assert expired.status_code == 401 and expired.json()["error"]["code"] == "AUTH_EXPIRED"
    assert "Max-Age=0" in expired.headers["set-cookie"]


async def test_attempt_limit_and_retry_after(auth_client):
    client, app = auth_client
    app.state.auth_rate_limiter = AuthRateLimiter(email_limit=1)
    first = await client.post("/api/v1/auth/login", json=BODY, headers={"Origin": ORIGIN})
    limited = await client.post("/api/v1/auth/login", json=BODY, headers={"Origin": ORIGIN})
    assert first.status_code == 401 and limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert int(limited.headers["retry-after"]) > 0


@pytest.mark.parametrize(
    "profile,origin",
    [
        ("production", "https://example.com"),
        ("tunnel_test", "https://blue-house.trycloudflare.com"),
    ],
)
async def test_secure_cookie_on_https_profiles(pg_session, profile, origin):
    settings = Settings(
        _env_file=None,
        app_env=profile,
        web_origins=["https://example.com"] if profile == "production" else [ORIGIN],
        database_url="postgresql+psycopg://test:nondevelopment@localhost/db",
    )
    headers = {"Origin": origin, "Sec-Fetch-Site": "same-origin"}
    if profile == "tunnel_test":
        headers["Host"] = "127.0.0.1:18081"
    app = create_app(settings, BoundDatabase(pg_session))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=origin
        ) as client:
            registered = await client.post("/api/v1/auth/register", json=BODY, headers=headers)
            assert registered.status_code == 201
            response = await client.post("/api/v1/auth/login", json=BODY, headers=headers)
            assert response.status_code == 200
            assert response.headers["set-cookie"].startswith("__Host-repair_auth=")
            assert (
                "Secure" in response.headers["set-cookie"]
                and "HttpOnly" in response.headers["set-cookie"]
            )
            assert (await client.get("/api/v1/auth/me")).status_code == 200
            if profile == "tunnel_test":
                assert "access-control-allow-origin" not in response.headers
                preflight = await client.options(
                    "/api/v1/auth/logout",
                    headers={
                        "Origin": "https://other.trycloudflare.com",
                        "Access-Control-Request-Method": "POST",
                    },
                )
                assert preflight.status_code == 400
                assert "access-control-allow-origin" not in preflight.headers
            logout_headers = {**headers, "Content-Type": "application/json"}
            denied = await client.post("/api/v1/auth/logout", headers=logout_headers)
            assert denied.status_code == 403
            logout_headers["X-CSRF-Token"] = response.json()["csrfToken"]
            logout = await client.post("/api/v1/auth/logout", headers=logout_headers)
            assert logout.status_code == 204


def request_for(app, *, token=None, bearer=None):
    headers = []
    if token:
        headers.append((b"cookie", f"repair_auth={token}".encode()))
    if bearer:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "app": app})


async def test_member_and_guest_ownership_expiry_and_long_term_result(auth_client, pg_session):
    client, app = auth_client
    signed = await signed_in(client)
    token = client.cookies.get("repair_auth")
    user = await pg_session.scalar(select(User))
    pg_session.add(Catalog(version="ownership-test", payload_json={}))
    await pg_session.flush()
    guest_token = new_token()
    rows = [
        Consultation(
            owner_user_id=user.id,
            catalog_version="ownership-test",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        ),
        Consultation(
            guest_token_hash=token_hash(guest_token),
            catalog_version="ownership-test",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        ),
    ]
    pg_session.add_all(rows)
    await pg_session.flush()
    member, guest = rows
    account_request = request_for(app, token=token)
    guest_request = request_for(app, bearer=guest_token)
    assert (await own_consultation(account_request, pg_session, member.id)).id == member.id
    assert (await own_consultation(guest_request, pg_session, guest.id)).id == guest.id
    for request, target, kwargs, code in (
        (guest_request, guest.id, {"member_only": True}, ErrorCode.AUTH_REQUIRED),
        (guest_request, member.id, {}, ErrorCode.NOT_FOUND),
        (account_request, guest.id, {}, ErrorCode.NOT_FOUND),
        (account_request, uuid4(), {}, ErrorCode.NOT_FOUND),
    ):
        with pytest.raises(AppError) as error:
            await own_consultation(request, pg_session, target, **kwargs)
        assert error.value.code == code
    result = Result(
        consultation_id=member.id,
        owner_user_id=user.id,
        input_snapshot_json={},
        payload_json={},
        retained_until=datetime.now(UTC) + timedelta(days=365),
    )
    pg_session.add(result)
    await pg_session.flush()
    member.expires_at = member.created_at + timedelta(microseconds=1)
    await pg_session.flush()
    assert (await own_result(account_request, pg_session, result.id)).id == result.id
    with pytest.raises(AppError) as error:
        await own_consultation(account_request, pg_session, member.id)
    assert error.value.code == ErrorCode.SESSION_EXPIRED
    guest.expires_at = guest.created_at + timedelta(microseconds=1)
    await pg_session.flush()
    with pytest.raises(AppError) as error:
        await own_consultation(guest_request, pg_session, guest.id)
    assert error.value.code == ErrorCode.SESSION_EXPIRED
    assert signed.json()["user"]["id"] == str(user.id)


async def test_server_member_paths_reject_guests_and_hide_other_resources(auth_client, pg_session):
    client, app = auth_client
    guest_token = new_token()
    for path in ("/api/v1/me/results", f"/api/v1/sessions/{uuid4()}/chat/messages"):
        response = await client.get(path, headers={"Authorization": f"Bearer {guest_token}"})
        assert response.status_code == 401 and response.json()["error"]["code"] == "AUTH_REQUIRED"
    await signed_in(client)
    foreign = await client.get(f"/api/v1/me/results/{uuid4()}")
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "NOT_FOUND"
