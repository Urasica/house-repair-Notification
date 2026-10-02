import os

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import Database


@pytest.fixture
async def pg_database():
    if os.getenv("RUN_DB_TESTS") != "1":
        pytest.skip("Run integration tests in the dedicated repair-guide-test Compose project")
    if os.getenv("APP_ENV") != "test":
        pytest.fail("Real database tests require APP_ENV=test")
    settings = Settings(_env_file=None)
    if make_url(settings.database_url.get_secret_value()).database != "repair_guide_test":
        pytest.fail("Refusing integration tests outside repair_guide_test")
    database = Database(settings)
    try:
        await database.initialize()
        yield database
    finally:
        await database.dispose()


@pytest.fixture
async def pg_session(pg_database):
    async with pg_database.engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
        await transaction.rollback()
