"""Bounded single-worker restart / DB outage drill against the isolated test project."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

DOCKER = ["docker"]
if sys.platform == "win32":
    DOCKER += [
        "--config",
        ".cache/docker",
        "-H",
        "npipe:////./pipe/dockerDesktopLinuxEngine",
    ]
COMPOSE_FILES = [
    "--env-file",
    ".env.example",
    "--env-file",
    ".env.test.example",
    "-f",
    "compose.yaml",
    "-f",
    "compose.test.yaml",
]


def command(compose, *args):
    result = subprocess.run(
        compose + list(args), capture_output=True, timeout=60, check=False
    )
    if result.returncode:
        raise RuntimeError("Test Compose operation failed")


def status(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (OSError, TimeoutError):
        return 0


def wait_ready(base):
    start = time.perf_counter()
    for _ in range(30):
        if status(base, "/health/ready") == 200:
            return round(time.perf_counter() - start, 3)
        time.sleep(0.5)
    raise RuntimeError("Test API did not recover")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ci-project")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.ci_project is None and args.port is None:
        project, port, overlay = "repair-guide-test", 18080, "compose.e2e.yaml"
    elif (
        args.ci_project is not None
        and re.fullmatch(r"repair-guide-ci-[0-9a-f]{16}", args.ci_project)
        and args.port is not None
        and 1024 <= args.port <= 65535
        and args.port != 8080
    ):
        project, port, overlay = args.ci_project, args.port, "compose.ci.yaml"
        os.environ["REPAIR_CI_ORIGIN_PORT"] = str(port)
    else:
        parser.error("Specify both the isolated CI project and its test port.")
    compose = [*DOCKER, "compose", "-p", project, *COMPOSE_FILES, "-f", overlay]
    base = f"http://localhost:{port}"
    assert status(base, "/health/ready") == 200
    try:
        command(compose, "stop", "db")
        assert status(base, "/health/live") == 200
        assert status(base, "/health/ready") == 503
        assert status(base, "/api/v1/catalog") == 503
    finally:
        command(compose, "up", "-d", "--no-deps", "--wait", "db")
    database_seconds = wait_ready(base)
    command(compose, "restart", "api")
    restart_seconds = wait_ready(base)
    report = {
        "executedAt": datetime.now(UTC).isoformat(),
        "isolatedProject": project,
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
