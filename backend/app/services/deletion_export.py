"""Authenticated deletion ledger kept separately from daily backups."""

import asyncio
import json
import logging
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from cryptography.fernet import Fernet
from sqlalchemy import delete, select, text, update

from app.core.metrics import DELETION_EXPORT
from app.db.models import Consultation, DeletionLog, QuestionRecord, RequestRun, Result
from app.services.deletion import delete_result

logger = logging.getLogger(__name__)
EXPORT_LOCK = 11002026


def encrypt(data: dict, key: str) -> bytes:
    return Fernet(key.encode()).encrypt(json.dumps(data, ensure_ascii=False).encode())


def decrypt(data: bytes, key: str, purpose: str) -> dict:
    value = json.loads(Fernet(key.encode()).decrypt(data))
    if value.get("format") != 1 or value.get("purpose") != purpose:
        raise ValueError("Invalid encrypted file purpose/version")
    return value


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def export_deletions(database, settings):
    if not settings.deletion_export_path:
        raise ValueError("Deletion export is not configured")
    async with database.transaction() as session:
        # All exporters serialize BEFORE reading, so an older snapshot cannot
        # overwrite a newer file. API deletion transactions have already committed.
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": EXPORT_LOCK})
        now = datetime.now(UTC)
        rows = (
            await session.scalars(
                select(DeletionLog)
                .where(DeletionLog.expires_at > now)
                .order_by(DeletionLog.deleted_at, DeletionLog.id)
            )
        ).all()
        payload = {
            "format": 1,
            "purpose": "deletions",
            "scope": settings.backup_scope,
            "exportedAt": now.isoformat(),
            "entries": [
                {
                    "type": row.entity_type,
                    "id": str(row.entity_id),
                    "deletedAt": row.deleted_at.isoformat(),
                    "expiresAt": row.expires_at.isoformat(),
                }
                for row in rows
            ],
        }
        # Keep the lock until the durable rename is finished, even on cancellation.
        task = asyncio.create_task(
            asyncio.to_thread(
                atomic_write,
                Path(settings.deletion_export_path),
                encrypt(payload, settings.backup_key.get_secret_value()),
            )
        )
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
        # Prune only after a successful export. Failed exports retain the retry source.
        await session.execute(delete(DeletionLog).where(DeletionLog.expires_at <= now))
        return {"exportedAt": payload["exportedAt"], "entries": len(rows)}


async def export_after_delete(database, settings):
    if not settings.deletion_export_path:
        return
    try:
        await export_deletions(database, settings)
    except Exception:
        DELETION_EXPORT.labels("failure").inc()
        # DB deletion is already committed. Do not falsely report rollback or log
        # keys/paths/input. Host monitoring must alert and retry export-deletions.
        logger.error("DELETION_EXPORT_FAILED: retry export-deletions before any restore")
    else:
        DELETION_EXPORT.labels("success").inc()


async def apply_deletions(session, payload, settings):
    # Validate the complete ledger before making changes.
    entries = [(item["type"], UUID(item["id"])) for item in payload["entries"]]
    if any(kind not in {"RESULT", "QUESTION_RECORD", "CONSULTATION"} for kind, _ in entries):
        raise ValueError("Unsupported deletion marker")
    for kind, identifier in entries:
        if kind == "RESULT":
            row = await session.get(Result, identifier)
            if row:
                # Resolve the request FK BEFORE removing the restored result.
                await delete_result(session, row, settings, preserve_question=True)
        elif kind == "QUESTION_RECORD":
            await session.execute(
                update(Result)
                .where(Result.question_record_id == identifier)
                .values(question_record_id=None)
            )
            await session.execute(delete(QuestionRecord).where(QuestionRecord.id == identifier))
        else:
            await session.execute(
                delete(Result).where(
                    Result.consultation_id == identifier, Result.owner_user_id.is_(None)
                )
            )
            await session.execute(delete(Consultation).where(Consultation.id == identifier))
    # Keep the independent ledger in the restored DB as well. Otherwise the first
    # post-cutover export could forget question-only / consultation deletions and
    # permit them to reappear when an older backup is restored a second time.
    for item in payload["entries"]:
        existing = await session.scalar(
            select(DeletionLog.id)
            .where(
                DeletionLog.entity_type == item["type"], DeletionLog.entity_id == UUID(item["id"])
            )
            .limit(1)
        )
        if existing is None:
            now = datetime.now(UTC)
            session.add(
                DeletionLog(
                    entity_type=item["type"],
                    entity_id=UUID(item["id"]),
                    deleted_at=datetime.fromisoformat(item["deletedAt"])
                    if "deletedAt" in item
                    else now,
                    expires_at=datetime.fromisoformat(item["expiresAt"])
                    if "expiresAt" in item
                    else now + timedelta(days=settings.deletion_log_retention_days),
                )
            )
    # All interrupted work is terminal after a restore; never regenerate it.
    await session.execute(
        update(RequestRun)
        .where(RequestRun.state == "PROCESSING")
        .values(state="FAILED", response_json=None, finished_at=datetime.now(UTC))
    )
    return len(entries)
