import json
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.db.session import MIGRATION_HEAD
from scripts.export_openapi import contract_json


def test_openapi_snapshot_matches_app_and_has_contracts_without_fake_routes():
    snapshot = Path(__file__).resolve().parents[2] / "schemas" / "openapi.json"
    schema = json.loads(snapshot.read_text(encoding="utf-8"))
    assert schema == json.loads(contract_json())
    assert set(schema["paths"]) == {"/api/v1/catalog", "/health/live", "/health/ready"}
    assert "Session" in schema["components"]["schemas"]
    assert "expectedRevision" in schema["components"]["schemas"]["ContextUpdate"]["properties"]
    assert schema["paths"]["/api/v1/catalog"]["get"]["responses"]["422"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/ErrorResponse")


def test_readiness_expects_the_only_migration_head():
    directory = ScriptDirectory.from_config(Config("alembic.ini"))
    assert directory.get_heads() == [MIGRATION_HEAD]
