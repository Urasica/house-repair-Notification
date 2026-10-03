from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.auth.access import require_csrf
from app.auth.rate_limit import AuthRateLimiter
from app.auth.security import Passwords, csrf_token, new_token, token_hash
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.constants import ErrorCode
from app.schemas.auth import Credentials


async def test_passwords_use_argon2id_random_salt_and_reject_unknown_account():
    passwords = Passwords()
    password = "not-a-real-password"
    encoded = await passwords.hash(password)
    assert encoded.startswith("$argon2id$")
    assert await passwords.verify(encoded, password)
    assert not await passwords.verify(encoded, "different-password")
    assert not await passwords.verify(None, password)
    assert not await passwords.verify("invalid-hash", password)
    assert encoded != await passwords.hash(password)


def test_credentials_normalize_email_reject_extra_and_hide_password():
    data = Credentials(email=" Member@Example.COM ", password="private-password")
    assert data.email == "member@example.com"
    assert "private-password" not in repr(data)
    for payload in (
        {"email": "invalid", "password": "private-password"},
        {"email": "member@example.com", "password": "short"},
        {"email": "member@example.com", "password": " " * 12},
        {"email": "member@example.com", "password": "private-password", "role": "admin"},
    ):
        with pytest.raises(ValidationError):
            Credentials.model_validate(payload)


def test_tokens_are_distinct_csrf_is_recoverable_and_production_cookie_is_secure():
    token = new_token()
    assert len(token) == 43 and len(token_hash(token)) == 64
    assert token != new_token()
    assert csrf_token(token) != token and csrf_token(token) == csrf_token(token)
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+psycopg://test:nondevelopment@localhost/db",
        web_origins=["https://example.com"],
    )
    assert settings.auth_cookie_name == "__Host-repair_auth" and settings.auth_cookie_secure
    assert not Settings(_env_file=None).auth_cookie_secure


def test_rate_limit_expiry_bounded_storage_and_no_raw_identifiers():
    now = [0.0]
    limiter = AuthRateLimiter(
        email_limit=2, address_limit=3, window_seconds=10, clock=lambda: now[0]
    )
    limiter.check("192.0.2.1", "member@example.com")
    limiter.check("192.0.2.1", "member@example.com")
    with pytest.raises(AppError) as error:
        limiter.check("192.0.2.2", "member@example.com")
    assert error.value.code == ErrorCode.RATE_LIMITED
    assert error.value.details["retryAfterSeconds"] == 10
    assert "member@example.com" not in str(limiter._buckets)
    assert "192.0.2.1" not in str(limiter._buckets)
    now[0] = 10.0
    limiter.check("192.0.2.1", "member@example.com")


def test_csrf_rejects_wrong_origin_media_type_and_unicode_without_internal_error():
    csrf = "c" * 64
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=Settings(_env_file=None))),
        headers={
            "origin": "http://localhost:8080",
            "content-type": "application/json",
            "x-csrf-token": csrf,
        },
    )
    principal = SimpleNamespace(csrf=csrf)
    require_csrf(request, principal)
    for header, value, status in (
        ("origin", "https://untrusted.example", 403),
        ("content-type", "text/plain", 415),
        ("x-csrf-token", "한국어", 403),
    ):
        original = request.headers[header]
        request.headers[header] = value
        with pytest.raises(AppError) as error:
            require_csrf(request, principal)
        assert error.value.status == status
        request.headers[header] = original
