"""Bounded single-worker restart / DB outage drill against the isolated test project."""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

BASE = "http://localhost:18080"
DOCKER = ["docker"]
if sys.platform == "win32":
    DOCKER += [
        "--config",
        ".cache/docker",
        "-H",
        "npipe:////./pipe/dockerDesktopLinuxEngine",
    ]
COMPOSE = DOCKER + [
    "compose",
    "-p",
    "repair-guide-test",
    "--env-file",
    ".env.example",
    "--env-file",
    ".env.test.example",
    "-f",
    "compose.yaml",
    "-f",
    "compose.test.yaml",
    "-f",
    "compose.e2e.yaml",
]


def command(*args):
    result = subprocess.run(
        COMPOSE + list(args), capture_output=True, timeout=60, check=False
    )
    if result.returncode:
        raise RuntimeError("Test Compose operation failed")


def status(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (OSError, TimeoutError):
        return 0


def wait_ready():
    start = time.perf_counter()
    for _ in range(30):
        if status("/health/ready") == 200:
            return round(time.perf_counter() - start, 3)
        time.sleep(0.5)
    raise RuntimeError("Test API did not recover")


def main():
    assert status("/health/ready") == 200
    try:
        command("stop", "db")
        assert status("/health/live") == 200
        assert status("/health/ready") == 503
        assert status("/api/v1/catalog") == 503
    finally:
        command("up", "-d", "--no-deps", "--wait", "db")
    database_seconds = wait_ready()
    command("restart", "api")
    restart_seconds = wait_ready()
    report = {
        "executedAt": datetime.now(UTC).isoformat(),
        "isolatedProject": "repair-guide-test",
        "databaseOutage": {
            "liveStatus": 200,
            "readyStatus": 503,
            "catalogStatus": 503,
            "recoverySecondsAfterDbHealthy": database_seconds,
        },
        "singleWorkerRestart": {"recoverySecondsAfterComposeRestart": restart_seconds},
        "note": "Interrupted request persistence separately verified by PostgreSQL tests",
    }
    destination = Path("artifacts/m11/outage-report.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
