import asyncio
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.errors import AppError
from app.db.requests import RequestRepository
from app.domain.constants import ErrorCode

MIGRATION_HEAD = "0005_m10"


class Database:
    def __init__(self, settings: Settings):
        self.engine = create_async_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
            pool_timeout=3,
            hide_parameters=True,
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self._initialized = False
        self._initialization_lock = asyncio.Lock()
        self._active_changes: set[asyncio.Task] = set()

    async def initialize(self):
        if self._initialized:
            return
        async with self._initialization_lock:
            if self._initialized:
                return
            if self._active_changes:
                raise self.unavailable()
            async with self.transaction() as session:
                revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
                vector = await session.scalar(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                )
                if revision != MIGRATION_HEAD or vector is None:
                    raise self.unavailable()
                await RequestRepository().fail_interrupted(session)
            self._initialized = True

    @staticmethod
    def unavailable() -> AppError:
        return AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "서비스에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.",
            503,
        )

    @asynccontextmanager
    async def session(self):
        try:
            async with self.sessions() as session:
                yield session
        except SQLAlchemyError as error:
            self._initialized = False
            current = asyncio.current_task()
            for task in self._active_changes:
                if task is not current and not task.cancelling():
                    task.cancel()
            raise self.unavailable() from error

    @asynccontextmanager
    async def change(self):
        await self.initialize()
        task = asyncio.current_task()
        self._active_changes.add(task)
        try:
            yield
        finally:
            self._active_changes.discard(task)

    @asynccontextmanager
    async def transaction(self):
        async with self.session() as session, session.begin():
            yield session

    async def dispose(self):
        await self.engine.dispose()
