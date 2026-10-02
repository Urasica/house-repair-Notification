import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

from app.core.errors import AppError
from app.domain.constants import ErrorCode


class ConsultationLocks:
    """Single event loop/process only; callers authenticate before acquiring."""

    def __init__(self):
        self._locks: dict[UUID, asyncio.Lock] = {}

    @asynccontextmanager
    async def hold(self, consultation_id: UUID):
        lock = self._locks.setdefault(consultation_id, asyncio.Lock())
        if lock.locked():
            raise AppError(
                ErrorCode.SESSION_BUSY, "상담을 처리하고 있어요. 잠시 후 다시 시도해 주세요.", 409
            )
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            self._locks.pop(consultation_id, None)

    @property
    def active_count(self) -> int:
        return len(self._locks)
