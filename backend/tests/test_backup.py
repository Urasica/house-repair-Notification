from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.commands.maintenance import (
    decode_file,
    encode_file,
    prune_backups,
    restore,
    reviewed_files,
)
from app.core.config import Settings
from app.services.deletion_export import encrypt


def settings(tmp_path):
    return Settings(
        _env_file=None,
        backup_key=Fernet.generate_key().decode(),
        deletion_export_path=str(tmp_path / "latest.fernet"),
    )


def test_reviewed_files_require_manifest_and_exact_hash(tmp_path):
    (tmp_path / "source.txt").write_text("조문\n별표", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest"):
        reviewed_files(tmp_path)
    (tmp_path / "manifest.json").write_text("{}")
    value = reviewed_files(tmp_path)["source.txt"]
    assert decode_file(value) == (tmp_path / "source.txt").read_bytes()
    with pytest.raises(ValueError, match="hash"):
        decode_file({**value, "sha256": "bad"})
    (tmp_path / ".env").write_text("not a real secret")
    with pytest.raises(ValueError, match="secrets"):
        reviewed_files(tmp_path)


def test_retention_uses_authenticated_timestamp_not_file_mtime(tmp_path):
    config = settings(tmp_path)
    now = datetime.now(UTC)
    for name, age, scope in (
        ("expired", 14, config.backup_scope),
        ("keep", 13, config.backup_scope),
        ("other", 30, "other"),
    ):
        (tmp_path / f"backup-{name}.fernet").write_bytes(
            encrypt(
                {
                    "format": 1,
                    "purpose": "backup",
                    "scope": scope,
                    "createdAt": (now - timedelta(days=age)).isoformat(),
                },
                config.backup_key.get_secret_value(),
            )
        )
    (tmp_path / "unrelated.txt").write_text("keep")
    assert prune_backups(tmp_path, config, now) == 1
    assert {p.name for p in tmp_path.iterdir()} == {
        "backup-keep.fernet",
        "backup-other.fernet",
        "unrelated.txt",
    }


@pytest.mark.parametrize(
    "failure", ["live-db", "not-maintenance", "stale-ledger", "scope", "expired", "traversal"]
)
async def test_restore_rejects_unsafe_inputs_before_connecting(tmp_path, failure):
    from app.db.session import MIGRATION_HEAD

    config = settings(tmp_path)
    config.database_url = SecretStr("postgresql+psycopg://unused@localhost/test_restore")
    now = datetime.now(UTC)
    archive = {
        "format": 1,
        "purpose": "backup",
        "scope": config.backup_scope,
        "schema": MIGRATION_HEAD,
        "createdAt": (now - timedelta(hours=1)).isoformat(),
        "dump": encode_file(b"dump"),
        "files": {"manifest.json": encode_file(b"{}")},
    }
    ledger = {
        "format": 1,
        "purpose": "deletions",
        "scope": config.backup_scope,
        "exportedAt": now.isoformat(),
        "entries": [],
    }
    if failure == "live-db":
        config.database_url = SecretStr("postgresql+psycopg://unused@localhost/live")
    elif failure == "stale-ledger":
        ledger["exportedAt"] = (now - timedelta(days=2)).isoformat()
    elif failure == "scope":
        ledger["scope"] = "other"
    elif failure == "expired":
        archive["createdAt"] = (now - timedelta(days=15)).isoformat()
    elif failure == "traversal":
        archive["files"] = {"../outside": encode_file(b"{}")}
    for name, value in (("archive", archive), ("ledger", ledger)):
        (tmp_path / name).write_bytes(encrypt(value, config.backup_key.get_secret_value()))
    args = SimpleNamespace(
        maintenance=failure != "not-maintenance",
        archive=tmp_path / "archive",
        latest_deletions=tmp_path / "ledger",
        reviewed_output=tmp_path / "new",
    )
    with pytest.raises(ValueError):
        await restore(None, config, args)
    assert not Path(args.reviewed_output).exists()
