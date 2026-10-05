"""One-shot retention, aggregate, encrypted backup and isolated restore commands."""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from uuid import uuid4

from sqlalchemy import delete, text, update
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.models import AuthSession, KnowledgeSet
from app.db.session import MIGRATION_HEAD, Database
from app.services.deletion_export import (
    apply_deletions,
    atomic_write,
    decrypt,
    encrypt,
    export_deletions,
)
from app.services.retention import cleanup, question_statistics

MAX_ARCHIVE_BYTES = (
    128 * 1024 * 1024
)  # Fernet authenticates the complete small-MVP archive in memory.


def timestamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("Timezone required")
    return stamp


def pg_environment(settings):
    url = make_url(settings.database_url.get_secret_value())
    environment = dict(os.environ)
    environment.update(
        PGHOST=url.host or "localhost",
        PGPORT=str(url.port or 5432),
        PGUSER=url.username or "",
        PGPASSWORD=url.password or "",
        PGDATABASE=url.database or "",
        PGCONNECT_TIMEOUT="5",
    )
    # Preserve TLS connection options without putting passwords in argv or errors.
    for name in ("sslmode", "sslrootcert", "sslcert", "sslkey"):
        if name in url.query:
            environment["PG" + name.upper()] = url.query[name]
    return environment


def pg_command(command, settings, *, data=None):
    result = subprocess.run(
        command,
        input=data,
        capture_output=True,
        env=pg_environment(settings),
        timeout=600,
        check=False,
    )
    if result.returncode:
        raise ValueError("PostgreSQL command failed; no secret-bearing stderr emitted")
    if len(result.stdout) > MAX_ARCHIVE_BYTES:
        raise ValueError("MVP backup size limit exceeded; use streaming backup before scaling")
    return result.stdout


def encode_file(data):
    return {"sha256": hashlib.sha256(data).hexdigest(), "data": base64.b64encode(data).decode()}


def decode_file(value):
    data = base64.b64decode(value["data"], validate=True)
    if hashlib.sha256(data).hexdigest() != value["sha256"]:
        raise ValueError("Archive content hash mismatch")
    return data


def reviewed_files(root):
    root = root.resolve(strict=True)
    files = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Reviewed files cannot contain symlinks")
        if not path.is_file():
            continue
        if path.name.startswith(".env"):
            raise ValueError("Do not include environment secrets in reviewed files")
        total += path.stat().st_size
        if total > MAX_ARCHIVE_BYTES:
            raise ValueError("Reviewed files exceed MVP limit")
        files[path.relative_to(root).as_posix()] = encode_file(path.read_bytes())
    if not files or not any("manifest" in name.lower() for name in files):
        raise ValueError("Reviewed files must include a manifest")
    return files


def prune_backups(directory, settings, now):
    removed = 0
    for path in directory.glob("backup-*.fernet"):
        # Never delete unrelated, corrupt, other-scope or symlinked files.
        if path.is_symlink():
            continue
        try:
            payload = decrypt(path.read_bytes(), settings.backup_key.get_secret_value(), "backup")
            if payload["scope"] == settings.backup_scope and timestamp(
                payload["createdAt"]
            ) <= now - timedelta(days=settings.backup_retention_days):
                path.unlink()
                removed += 1
        except Exception:
            raise ValueError("Backup retention verification failed") from None
    return removed


async def backup(database, settings, args):
    local, remote = args.local.resolve(), args.remote.resolve(strict=True)
    if local == remote or local in remote.parents or remote in local.parents:
        raise ValueError("Separate local and remote backup destinations are required")
    if not remote.is_dir():
        raise ValueError("Remote storage must be mounted first")
    started = datetime.now(UTC)
    files = await asyncio.to_thread(reviewed_files, args.reviewed)
    dump = await asyncio.to_thread(
        pg_command, ["pg_dump", "--format=custom", "--no-owner", "--no-acl"], settings
    )
    ledger = await export_deletions(database, settings)
    payload = {
        "format": 1,
        "purpose": "backup",
        "scope": settings.backup_scope,
        "schema": MIGRATION_HEAD,
        "createdAt": started.isoformat(),
        "completedAt": datetime.now(UTC).isoformat(),
        "deletionExport": ledger,
        "dump": encode_file(dump),
        "files": files,
    }
    encrypted = await asyncio.to_thread(encrypt, payload, settings.backup_key.get_secret_value())
    if len(encrypted) > MAX_ARCHIVE_BYTES * 2:
        raise ValueError("Combined archive exceeds MVP size limit")
    name = f"backup-{started:%Y%m%dT%H%M%SZ}-{uuid4().hex}.fernet"
    await asyncio.to_thread(atomic_write, local / name, encrypted)
    await asyncio.to_thread(atomic_write, remote / name, encrypted)
    if hashlib.sha256((remote / name).read_bytes()).digest() != hashlib.sha256(encrypted).digest():
        raise ValueError("Remote backup verification failed")
    removed = sum(prune_backups(directory, settings, started) for directory in (local, remote))
    return {
        "backup": name,
        "bytes": len(encrypted),
        "reviewedFiles": len(files),
        "remoteVerified": True,
        "expiredBackupsRemoved": removed,
        "seconds": (datetime.now(UTC) - started).total_seconds(),
    }


async def restore(database, settings, args):
    target = make_url(settings.database_url.get_secret_value()).database or ""
    if not args.maintenance or not re.fullmatch(r"[a-z0-9_]+_restore", target):
        raise ValueError("Restore requires maintenance mode and an isolated *_restore database")
    if args.reviewed_output.exists():
        raise ValueError("Reviewed output must be a new directory")
    key = settings.backup_key.get_secret_value()
    payload = decrypt(args.archive.read_bytes(), key, "backup")
    ledger = decrypt(args.latest_deletions.read_bytes(), key, "deletions")
    now = datetime.now(UTC)
    if payload["scope"] != settings.backup_scope or ledger["scope"] != settings.backup_scope:
        raise ValueError("Backup/deletion scope mismatch")
    if payload["schema"] != MIGRATION_HEAD:
        raise ValueError("Use the matching application/schema to restore")
    created, exported = timestamp(payload["createdAt"]), timestamp(ledger["exportedAt"])
    if not now - timedelta(days=settings.backup_retention_days) < created <= now:
        raise ValueError("Backup is expired or future-dated")
    if not max(created, now - timedelta(hours=24)) <= exported <= now:
        raise ValueError("Latest independent deletion ledger is missing or stale")
    dump = decode_file(payload["dump"])
    files = {}
    for name, value in payload["files"].items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
            raise ValueError("Unsafe archive path")
        files[path] = decode_file(value)
    async with database.transaction() as session:
        exists = await session.scalar(
            text(
                "SELECT count(*) FROM pg_tables "
                "WHERE schemaname NOT IN ('pg_catalog','information_schema')"
            )
        )
        if exists:
            raise ValueError("Restore target is not empty")
    started = datetime.now(UTC)
    await asyncio.to_thread(
        pg_command,
        [
            "pg_restore",
            "--exit-on-error",
            "--single-transaction",
            "--no-owner",
            "--no-acl",
            "--dbname",
            target,
        ],
        settings,
        data=dump,
    )
    async with database.transaction() as session:
        applied = await apply_deletions(session, ledger, settings)
        counts = await cleanup(session, settings)
        await session.execute(delete(AuthSession))
        # A daily backup cannot prove the latest withdrawal/review state. Quarantine
        # restored releases; only a freshly reviewed NEW release can become published.
        await session.execute(
            update(KnowledgeSet)
            .where(KnowledgeSet.status == "PUBLISHED")
            .values(status="WITHDRAWN")
        )
    args.reviewed_output.mkdir(parents=True)
    for path, data in files.items():
        atomic_write(args.reviewed_output / str(path), data)
    return {
        "deletionsApplied": applied,
        "cleanup": counts,
        "authRevoked": True,
        "knowledgeQuarantined": True,
        "seconds": (datetime.now(UTC) - started).total_seconds(),
        "snapshotAgeSeconds": (now - created).total_seconds(),
        "cutoverPerformed": False,
    }


async def execute(args):
    settings = get_settings()
    database = Database(settings)
    try:
        if args.action == "restore":
            return await restore(database, settings, args)
        async with database.transaction() as session:
            if (
                await session.scalar(text("SELECT version_num FROM alembic_version"))
                != MIGRATION_HEAD
            ):
                raise ValueError("Schema is not ready")
            if args.action == "statistics":
                return await question_statistics(session, since=args.since)
            if args.action == "cleanup":
                result = await cleanup(session, settings)
        if args.action == "cleanup":
            result["deletionExport"] = await export_deletions(database, settings)
            return result
        if args.action == "export-deletions":
            return await export_deletions(database, settings)
        return await backup(database, settings, args)
    finally:
        await database.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("cleanup")
    commands.add_parser("export-deletions")
    statistics = commands.add_parser("statistics")
    statistics.add_argument("--since", type=timestamp)
    save = commands.add_parser("backup")
    save.add_argument("--reviewed", type=Path, required=True)
    save.add_argument("--local", type=Path, required=True)
    save.add_argument("--remote", type=Path, required=True)
    load = commands.add_parser("restore")
    load.add_argument("--archive", type=Path, required=True)
    load.add_argument("--latest-deletions", type=Path, required=True)
    load.add_argument("--reviewed-output", type=Path, required=True)
    load.add_argument("--maintenance", action="store_true")
    try:
        print(json.dumps(asyncio.run(execute(parser.parse_args())), ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({"error": "MAINTENANCE_FAILED", "type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
