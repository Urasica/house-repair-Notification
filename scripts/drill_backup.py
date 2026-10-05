"""Isolated PostgreSQL restore drill. Run in the ops image on the TEST network only."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from app.commands.maintenance import backup, pg_command, restore
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (
    Catalog,
    Consultation,
    KnowledgeSet,
    QuestionRecord,
    RequestRun,
    Result,
    User,
)
from app.db.requests import RequestRepository
from app.db.session import Database
from app.services.deletion import delete_result
from app.services.deletion_export import export_deletions
from cryptography.fernet import Fernet
from psycopg import sql
from sqlalchemy import func, select
from sqlalchemy.engine import make_url


async def main():
    settings = Settings(_env_file=None)
    url = make_url(settings.database_url.get_secret_value())
    if (
        settings.app_env != "test"
        or url.database != "repair_guide_test"
        or url.username != "postgres"
    ):
        raise ValueError("Only dedicated test admin connection is allowed")
    run = uuid4().hex[:12]
    source_name, target_name = f"m11_{run}_fixture", f"m11_{run}_restore"
    root = Path("/drill") / run
    for directory in (root / "local", root / "remote", root / "reviewed"):
        directory.mkdir(parents=True)
    (root / "reviewed" / "manifest.json").write_text(
        '{"testOnly":true}', encoding="utf-8"
    )
    (root / "reviewed" / "source.txt").write_text(
        "검토 원문 및 별표 보존 시험", encoding="utf-8"
    )
    key = Fernet.generate_key().decode()
    source = settings.model_copy(
        update={
            "database_url": settings.database_url.__class__(
                url.set(database=source_name).render_as_string(hide_password=False)
            ),
            "backup_key": settings.backup_key.__class__(key),
            "deletion_export_path": str(root / "independent" / "latest.fernet"),
            "backup_scope": run,
        }
    )
    target = source.model_copy(
        update={
            "database_url": settings.database_url.__class__(
                url.set(database=target_name).render_as_string(hide_password=False)
            )
        }
    )
    source_db, target_db = Database(source), Database(target)
    connection = await psycopg.AsyncConnection.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False),
        autocommit=True,
    )
    try:
        for name in (source_name, target_name):
            await connection.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
            )
        schema = await asyncio.to_thread(
            pg_command, ["pg_dump", "--schema-only", "--format=custom"], settings
        )
        await asyncio.to_thread(
            pg_command,
            [
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                "--dbname",
                source_name,
            ],
            source,
            data=schema,
        )
        now = datetime.now(UTC)
        async with source_db.transaction() as session:
            # Copy only migration version; fixture data lives exclusively in the new DB.
            from app.db.session import MIGRATION_HEAD
            from sqlalchemy import text

            await session.execute(
                text("INSERT INTO alembic_version VALUES (:head)"),
                {"head": MIGRATION_HEAD},
            )
            catalog = Catalog(version="drill-only", payload_json={})
            user = User(
                normalized_email="drill@example.invalid", password_hash="unused"
            )
            session.add_all([catalog, user])
            await session.flush()
            knowledge = KnowledgeSet(
                catalog_version=catalog.version,
                status="PUBLISHED",
                embedding_model="text-embedding-3-large",
                embedding_dimensions=1536,
                manifest_json={},
                published_at=now,
            )
            session.add(knowledge)
            consultation = Consultation(
                owner_user_id=user.id,
                catalog_version=catalog.version,
                expires_at=now + timedelta(hours=24),
            )
            session.add(consultation)
            await session.flush()
            run_row = RequestRun(
                consultation_id=consultation.id,
                request_id=uuid4(),
                kind="SURVEY",
                request_hash="a" * 64,
                state="COMPLETED",
                finished_at=now,
                response_json={"private": "must not revive"},
            )
            question = QuestionRecord(
                consultation_id=consultation.id,
                owner_user_id=user.id,
                origin_key="drill",
                kind="SURVEY",
                catalog_version=catalog.version,
                answers_json={},
                retrieval_meta_json={},
                retained_until=now + timedelta(days=365),
            )
            session.add_all([run_row, question])
            await session.flush()
            result = Result(
                consultation_id=consultation.id,
                owner_user_id=user.id,
                request_run_id=run_row.id,
                question_record_id=question.id,
                input_snapshot_json={},
                payload_json={},
                retained_until=now + timedelta(days=365),
            )
            session.add(result)
            await session.flush()
            result_id, request_run_id = result.id, run_row.id
        saved = await backup(
            source_db,
            source,
            SimpleNamespace(
                reviewed=root / "reviewed", local=root / "local", remote=root / "remote"
            ),
        )
        async with source_db.transaction() as session:
            await delete_result(session, await session.get(Result, result_id), source)
        await export_deletions(source_db, source)
        restored = await restore(
            target_db,
            target,
            SimpleNamespace(
                maintenance=True,
                archive=root / "remote" / saved["backup"],
                latest_deletions=Path(source.deletion_export_path),
                reviewed_output=root / "restored",
            ),
        )
        async with target_db.session() as session:
            assert await session.get(Result, result_id) is None
            assert (
                await session.scalar(select(func.count()).select_from(QuestionRecord))
                == 0
            )
            request = await session.get(RequestRun, request_run_id)
            assert request.state == "DELETED" and request.response_json is None
            assert await session.scalar(select(KnowledgeSet.status)) == "WITHDRAWN"
            try:
                RequestRepository.existing(request, "SURVEY", "a" * 64)
                raise AssertionError("Deleted replay revived")
            except AppError as error:
                assert error.status == 410
        assert (root / "restored" / "source.txt").read_bytes() == (
            root / "reviewed" / "source.txt"
        ).read_bytes()
        report = {
            "executedAt": datetime.now(UTC).isoformat(),
            "backup": saved,
            "restore": restored,
            "postgresRestorePassed": True,
            "deletedReplay410": True,
            "reviewedFilesByteIdentical": True,
            "remoteStorage": "local mounted stand-in",
            "rpoTargetSeconds": 86400,
            "rtoTargetSeconds": 14400,
            "limitations": "Tiny synthetic dataset on local Docker; no production RPO/RTO guarantee",
        }
        Path("/drill/report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False))
    finally:
        await source_db.dispose()
        await target_db.dispose()
        for name in (source_name, target_name):
            await connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(name)
                )
            )
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
