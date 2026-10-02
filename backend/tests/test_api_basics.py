from contextlib import asynccontextmanager

import httpx
import pytest

from app.core.config import Settings
from app.db.session import Database
from app.main import create_app
from app.schemas.contracts import ContextUpdate


class EmptySession:
    async def scalar(self, statement):
        return None


class EmptyDatabase:
    async def initialize(self):
        pass

    @asynccontextmanager
    async def session(self):
        yield EmptySession()

    async def dispose(self):
        pass


class UnavailableDatabase(EmptyDatabase):
    async def initialize(self):
        raise Database.unavailable()


@pytest.fixture
async def client():
    app = create_app(Settings(_env_file=None), EmptyDatabase())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


async def test_live_does_not_depend_on_catalog_or_openai(client):
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_catalog_missing_has_safe_error_envelope_and_no_examples(client):
    response = await client.get("/api/v1/catalog")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CATALOG_NOT_READY"
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"]["traceId"] == response.headers["x-trace-id"]


async def test_empty_db_readiness_is_distinct_from_unavailable(client):
    response = await client.get("/health/ready")
    assert response.json() == {"status": "ok", "catalogReady": False, "ragReady": False}


async def test_unknown_api_route_does_not_return_frontend_html(client):
    response = await client.get("/api/v1/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_missing_catalog_version_is_not_found(client):
    response = await client.get("/api/v1/catalog?version=missing")
    assert response.status_code == 404


async def test_invalid_query_has_common_validation_envelope(client):
    response = await client.get("/api/v1/catalog?version=")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_db_failure_keeps_live_and_fails_ready_and_catalog():
    app = create_app(Settings(_env_file=None), UnavailableDatabase())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/health/live")).status_code == 200
            for path in ("/health/ready", "/api/v1/catalog"):
                response = await client.get(path)
                assert response.status_code == 503
                assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


async def test_internal_errors_and_validation_never_echo_raw_input(caplog):
    app = create_app(Settings(_env_file=None), EmptyDatabase())

    @app.post("/api/test-context")
    async def validate_context(body: ContextUpdate):
        raise RuntimeError("secret-password and raw SQL must never be logged")

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            invalid = await client.post(
                "/api/test-context",
                json={"expectedRevision": -1, "context": {}, "secret": "private"},
            )
            assert invalid.status_code == 422
            assert "private" not in invalid.text
            failure = await client.post(
                "/api/test-context", json={"expectedRevision": 0, "context": {}}
            )
            assert failure.status_code == 503
            assert failure.headers["cache-control"] == "no-store"
            assert "secret-password" not in failure.text
            assert "secret-password" not in caplog.text
