import asyncio
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.db.requests import request_fingerprint
from app.domain.constants import ErrorCode, RequestKind
from app.services.locks import ConsultationLocks


async def test_same_consultation_rejects_concurrent_change_other_session_can_run():
    locks = ConsultationLocks()
    consultation = uuid4()
    async with locks.hold(consultation):
        with pytest.raises(AppError) as error:
            async with locks.hold(consultation):
                pytest.fail("Concurrent change entered the lock")
        assert error.value.code == ErrorCode.SESSION_BUSY
        async with locks.hold(uuid4()):
            assert locks.active_count == 2
    assert locks.active_count == 0
    async with locks.hold(consultation):
        pass


async def test_cancelled_request_releases_lock():
    locks = ConsultationLocks()
    consultation = uuid4()
    started = asyncio.Event()

    async def work():
        async with locks.hold(consultation):
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(work())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert locks.active_count == 0
    async with locks.hold(consultation):
        pass


def test_fingerprint_is_stable_but_captures_kind_revision_and_input():
    original = request_fingerprint(RequestKind.SURVEY, {"expectedRevision": 1, "context": {}})
    assert original == request_fingerprint(
        RequestKind.SURVEY, {"context": {}, "expectedRevision": 1}
    )
    assert original != request_fingerprint(
        RequestKind.SURVEY, {"expectedRevision": 2, "context": {}}
    )
    assert original != request_fingerprint(RequestKind.CHAT, {"expectedRevision": 1, "context": {}})
