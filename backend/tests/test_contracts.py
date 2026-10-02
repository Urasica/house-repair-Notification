import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.catalog import CatalogDefinition, Condition
from app.schemas.contracts import ChatRequest, ContextUpdate, Session

FIXTURE = Path(__file__).parent / "fixtures" / "catalog.test.json"


def test_context_rejects_unknown_fields_and_negative_revision():
    with pytest.raises(ValidationError):
        ContextUpdate.model_validate({"expectedRevision": -1, "context": {"address": "private"}})


def test_chat_requires_uuid_and_nonblank_bounded_text():
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"requestId": "wrong", "expectedRevision": 0, "content": " "})


def test_catalog_rejects_unknown_parent_reference():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["facilities"][0]["roomIds"] = ["missing"]
    with pytest.raises(ValidationError, match="unknown room"):
        CatalogDefinition.model_validate(data)


def test_catalog_review_gate_requires_identity_and_complete_groups():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["review"] = {"state": "COMPLETE_VERIFIED"}
    with pytest.raises(ValidationError, match="reviewer"):
        CatalogDefinition.model_validate(data)


def test_condition_cannot_execute_expression():
    with pytest.raises(ValidationError, match="Unsupported"):
        Condition(path="__import__('os')", operator="equals", value="TEST")


def test_settings_reject_mysql_and_out_of_policy_retention():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="mysql://user:pass@localhost/db")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, question_retention_years=6)


def test_production_rejects_demo_database_credentials():
    with pytest.raises(ValidationError, match="non-development"):
        Settings(_env_file=None, app_env="production")


def test_wire_contract_normalizes_timezone_and_uses_camel_case():
    session = Session.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "accessMode": "GUEST",
            "catalogVersion": "test-only-v1",
            "knowledgeReleaseId": None,
            "revision": 0,
            "context": {},
            "currentResultId": None,
            "createdAt": "2026-10-03T09:00:00+09:00",
            "expiresAt": "2026-10-04T09:00:00+09:00",
        }
    )
    payload = session.model_dump(mode="json", by_alias=True)
    assert payload["createdAt"] == "2026-10-03T00:00:00Z"
    assert "access_mode" not in payload


def test_docker_environment_dimension_is_parsed_as_integer(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "1536")
    assert Settings(_env_file=None).embedding_dimensions == 1536
