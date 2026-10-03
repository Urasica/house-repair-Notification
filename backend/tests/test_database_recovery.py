import asyncio
from contextlib import asynccontextmanager

import anyio
import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import MIGRATION_HEAD, Database


class RecoveredSession:
    def __init__(self):
        self.recovered = False

    @asynccontextmanager
    async def begin(self):
        yield

    async def scalar(self, query):
        return MIGRATION_HEAD if "alembic_version" in str(query) else "0.8.7"

    async def execute(self, query):
        self.recovered = True
        return type("Rows", (), {"rowcount": 1})()


async def test_database_failure_cancels_active_mutation_and_blocks_early_recovery():
    database = Database(Settings(_env_file=None))
    database._initialized = True
    restored = RecoveredSession()

    @asynccontextmanager
    async def factory():
        yield restored

    database.sessions = factory
    started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def work():
        async with database.change():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                with anyio.CancelScope(shield=True):
                    cancelled.set()
                    await release.wait()

    pending = asyncio.create_task(work())
    await started.wait()
    try:
        with pytest.raises(AppError):
            async with database.session():
                raise SQLAlchemyError("private SQL must not escape")
        await cancelled.wait()
        with pytest.raises(AppError):
            await database.initialize()
        assert restored.recovered is False
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await database.initialize()
        assert restored.recovered is True
        async with database.change():
            pass
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
        await database.dispose()
