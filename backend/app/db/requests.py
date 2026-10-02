import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import RequestRun
from app.domain.constants import ErrorCode, RequestKind, RequestStatus


def request_fingerprint(kind: RequestKind, payload: dict) -> str:
    encoded = json.dumps(
        {"kind": kind, "payload": payload},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Reservation:
    run_id: UUID
    replay: dict | None = None

    @property
    def is_replay(self) -> bool:
        return self.replay is not None


class RequestRepository:
    """Never commits: request/result/question writes share the caller's transaction."""

    async def reserve(
        self,
        session: AsyncSession,
        consultation_id: UUID,
        request_id: UUID,
        kind: RequestKind,
        request_hash: str,
    ) -> Reservation:
        if not re.fullmatch(r"[0-9a-f]{64}", request_hash):
            raise ValueError("Expected a SHA-256 request fingerprint")
        statement = (
            insert(RequestRun)
            .values(
                consultation_id=consultation_id,
                request_id=request_id,
                kind=kind,
                request_hash=request_hash,
                state=RequestStatus.PROCESSING,
            )
            .on_conflict_do_nothing(index_elements=["consultation_id", "request_id"])
            .returning(RequestRun.id)
        )
        run_id = await session.scalar(statement)
        if run_id is not None:
            return Reservation(run_id)
        existing = await session.scalar(
            select(RequestRun).where(
                RequestRun.consultation_id == consultation_id, RequestRun.request_id == request_id
            )
        )
        if existing is None:
            raise AppError(ErrorCode.NOT_FOUND, "요청을 찾을 수 없어요.", 404)
        if existing.kind != kind or existing.request_hash != request_hash:
            raise AppError(ErrorCode.IDEMPOTENCY_CONFLICT, "같은 요청 ID의 입력이 달라요.", 409)
        if existing.state == RequestStatus.COMPLETED:
            return Reservation(existing.id, existing.response_json)
        if existing.state == RequestStatus.PROCESSING:
            raise AppError(ErrorCode.REQUEST_IN_PROGRESS, "요청을 처리하고 있어요.", 409)
        raise AppError(
            ErrorCode.REQUEST_FAILED, "실패한 요청이에요. 새 요청으로 다시 시도해 주세요.", 409
        )

    async def complete(self, session: AsyncSession, run_id: UUID, response: dict) -> None:
        updated = await session.execute(
            update(RequestRun)
            .where(RequestRun.id == run_id, RequestRun.state == RequestStatus.PROCESSING)
            .values(
                state=RequestStatus.COMPLETED, response_json=response, finished_at=datetime.now(UTC)
            )
        )
        if updated.rowcount != 1:
            raise AppError(ErrorCode.REQUEST_FAILED, "이미 종료된 요청이에요.", 409)

    async def fail(self, session: AsyncSession, run_id: UUID) -> bool:
        updated = await session.execute(
            update(RequestRun)
            .where(RequestRun.id == run_id, RequestRun.state == RequestStatus.PROCESSING)
            .values(state=RequestStatus.FAILED, response_json=None, finished_at=datetime.now(UTC))
        )
        return updated.rowcount == 1

    async def fail_interrupted(self, session: AsyncSession) -> int:
        """Only at startup, after the previous process has fully stopped."""
        updated = await session.execute(
            update(RequestRun)
            .where(RequestRun.state == RequestStatus.PROCESSING)
            .values(state=RequestStatus.FAILED, response_json=None, finished_at=datetime.now(UTC))
        )
        return updated.rowcount
