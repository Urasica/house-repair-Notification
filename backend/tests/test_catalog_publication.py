from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from test_auth_api import BoundDatabase
from test_catalog_policy import catalog_data
from test_database import seed_consultation

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Catalog, RequestRun
from app.schemas.catalog import CatalogDefinition
from app.services.catalog import get_catalog, publish_catalog, require_latest_catalog

pytestmark = pytest.mark.integration


async def test_publication_is_idempotent_and_old_versions_remain_readable(pg_session):
    settings = Settings(_env_file=None)
    definition = CatalogDefinition.model_validate(catalog_data())
    first = await publish_catalog(pg_session, definition, settings)
    repeated = await publish_catalog(pg_session, definition, settings)
    assert first.published_at == repeated.published_at
    data = catalog_data()
    data["version"] = "test-only-v2"
    second = await publish_catalog(pg_session, CatalogDefinition.model_validate(data), settings)
    assert (await get_catalog(pg_session)).version == second.version
    assert (await get_catalog(pg_session, first.version)).version == first.version
    assert (await require_latest_catalog(pg_session, second.version)).version == second.version
    with pytest.raises(AppError) as error:
        await require_latest_catalog(pg_session, first.version)
    assert error.value.status == 409 and error.value.code == "CATALOG_UPDATED"
    assert error.value.details == {"catalogVersion": second.version}


async def test_published_payload_requires_new_version_to_change(pg_session):
    settings = Settings(_env_file=None)
    data = catalog_data()
    await publish_catalog(pg_session, CatalogDefinition.model_validate(data), settings)
    data["rooms"][0]["label"] = "시험용 변경 라벨"
    with pytest.raises(AppError) as error:
        await publish_catalog(pg_session, CatalogDefinition.model_validate(data), settings)
    assert error.value.code == "CATALOG_UPDATED"
    assert (await get_catalog(pg_session)).rooms[0].label != "시험용 변경 라벨"


@pytest.mark.parametrize("operation", ["payload", "status", "version", "timestamp", "delete"])
async def test_database_rejects_all_published_mutations(pg_session, operation):
    result = await publish_catalog(
        pg_session, CatalogDefinition.model_validate(catalog_data()), Settings(_env_file=None)
    )
    changes = {
        "payload": {"payload_json": {}},
        "status": {"status": "DRAFT"},
        "version": {"version": "test-only-new"},
        "timestamp": {"published_at": datetime.now(UTC)},
    }
    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            statement = (
                delete(Catalog)
                if operation == "delete"
                else update(Catalog).values(**changes[operation])
            )
            await pg_session.execute(statement.where(Catalog.version == result.version))
    assert (await get_catalog(pg_session)).version == result.version


async def test_draft_can_be_replaced_and_published_only_after_review(pg_session):
    data = catalog_data(complete=False)
    definition = CatalogDefinition.model_validate(data)
    pg_session.add(Catalog(version=definition.version, status="DRAFT", payload_json=data))
    await pg_session.flush()
    with pytest.raises(AppError) as error:
        await publish_catalog(pg_session, definition, Settings(_env_file=None))
    assert error.value.code == "CATALOG_NOT_READY"
    data["review"] = catalog_data()["review"]
    result = await publish_catalog(
        pg_session, CatalogDefinition.model_validate(data), Settings(_env_file=None)
    )
    assert result.version == definition.version
    assert (await pg_session.scalar(select(Catalog))).status == "PUBLISHED"


async def test_missing_or_unverified_catalog_cannot_start_consultation(pg_session):
    with pytest.raises(AppError) as error:
        await require_latest_catalog(pg_session, "test-only-v1")
    assert error.value.code == "CATALOG_NOT_READY"
    data = catalog_data(complete=False)
    pg_session.add(
        Catalog(
            version=data["version"],
            status="PUBLISHED",
            payload_json=data,
            published_at=datetime.now(UTC),
        )
    )
    await pg_session.flush()
    with pytest.raises(AppError) as error:
        await get_catalog(pg_session)
    assert error.value.code == "CATALOG_NOT_READY"


async def test_publication_command_never_runs_api_startup_recovery(pg_session, monkeypatch):
    from app.commands import catalog as command

    consultation, _ = await seed_consultation(pg_session)
    run = RequestRun(
        consultation_id=consultation.id,
        request_id=uuid4(),
        kind="SURVEY",
        request_hash="c" * 64,
    )
    pg_session.add(run)
    await pg_session.flush()

    class CommandDatabase(BoundDatabase):
        async def initialize(self):
            raise AssertionError("A live API owns recovery; a publication command must not run it")

    monkeypatch.setattr(command, "Database", lambda settings: CommandDatabase(pg_session))
    result = await command.publish(CatalogDefinition.model_validate(catalog_data()))
    assert result.version == "test-only-v1"
    assert (await pg_session.get(RequestRun, run.id)).state == "PROCESSING"
