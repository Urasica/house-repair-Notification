from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.config import Settings
from app.db.models import Catalog, Consultation, RequestRun
from app.db.requests import RequestRepository
from app.db.session import Database
from app.domain.constants import RequestKind

pytestmark = pytest.mark.integration


async def test_startup_fails_interrupted_only_once_and_preserves_completed(pg_database):
    version = f"recovery-test-{uuid4()}"
    consultation_id = uuid4()
    repository = RequestRepository()
    restarted = Database(Settings(_env_file=None))
    try:
        async with pg_database.transaction() as session:
            session.add(Catalog(version=version, payload_json={}))
            await session.flush()
            session.add(
                Consultation(
                    id=consultation_id,
                    catalog_version=version,
                    guest_token_hash="b" * 64,
                    expires_at=datetime.now(UTC) + timedelta(hours=24),
                )
            )
            await session.flush()
            interrupted = await repository.reserve(
                session, consultation_id, uuid4(), RequestKind.SURVEY, "c" * 64
            )
            completed = await repository.reserve(
                session, consultation_id, uuid4(), RequestKind.SURVEY, "d" * 64
            )
            await repository.complete(session, completed.run_id, {"saved": True})

        # The test project has no running API process; recovery is safe here.
        await restarted.initialize()
        async with restarted.transaction() as session:
            row = await session.get(RequestRun, interrupted.run_id)
            assert row.state == "FAILED" and row.finished_at is not None
            saved = await session.get(RequestRun, completed.run_id)
            assert saved.state == "COMPLETED" and saved.response_json == {"saved": True}
            active = await repository.reserve(
                session, consultation_id, uuid4(), RequestKind.SURVEY, "e" * 64
            )
        await restarted.initialize()
        async with restarted.session() as session:
            assert (
                await session.scalar(select(RequestRun.state).where(RequestRun.id == active.run_id))
                == "PROCESSING"
            )
    finally:
        async with pg_database.transaction() as session:
            await session.execute(delete(Consultation).where(Consultation.id == consultation_id))
            await session.execute(delete(Catalog).where(Catalog.version == version))
        await restarted.dispose()
