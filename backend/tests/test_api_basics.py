from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_live_does_not_depend_on_catalog_or_openai():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_catalog_missing_has_safe_error_envelope_and_no_examples():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/api/v1/catalog")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "CATALOG_NOT_READY"
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["error"]["traceId"] == response.headers["x-trace-id"]


def test_unknown_api_route_does_not_return_frontend_html():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/api/v1/missing")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
