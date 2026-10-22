"""Verify the isolated localhost HTTPS deployment without printing secrets."""

import json
import ssl
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def docker(*args, include_stderr=False):
    result = subprocess.run(
        ["docker", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Docker verification command failed")
    return result.stdout + (result.stderr if include_stderr else "")


def main():
    state = json.loads((ROOT / "data/private/preview/state.json").read_text())
    target = urlsplit(state["url"])
    assert (
        state["localOnly"]
        and target.scheme == "https"
        and target.hostname == "localhost"
    )
    assert target.port == state["port"] and not target.username and not target.password
    assert not target.path and not target.query and not target.fragment
    ids = docker(
        "ps", "-q", "--filter", "label=com.docker.compose.project=repair-guide-preview"
    ).split()
    assert len(ids) == 3
    containers = json.loads(docker("inspect", *ids))
    services = {
        item["Config"]["Labels"]["com.docker.compose.service"]: item
        for item in containers
    }
    for name in ("api", "db"):
        assert not services[name]["HostConfig"]["PortBindings"]
    bindings = services["web"]["HostConfig"]["PortBindings"]
    assert bindings == {
        "443/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(state["port"])}]
    }
    assert services["api"]["HostConfig"]["ReadonlyRootfs"]
    assert services["api"]["Config"]["User"] == "appuser"
    assert "--no-access-log" in services["api"]["Config"]["Cmd"]
    assert all(
        mount["Type"] == "volume"
        for name in ("db", "web")
        for mount in services[name]["Mounts"]
    )
    assert all(
        mount["Destination"] in {"/deletions", "/tmp"}
        for mount in services["api"]["Mounts"]
    )
    env = dict(value.split("=", 1) for value in services["api"]["Config"]["Env"])
    assert env["APP_ENV"] == "production"
    assert json.loads(env["WEB_ORIGINS"]) == [state["url"]]
    assert env["OPENAI_CHAT_MODEL"] == "gpt-5.4-mini"
    assert env["OPENAI_EMBEDDING_MODEL"] == "text-embedding-3-large"
    assert env["EMBEDDING_DIMENSIONS"] == "1536"
    schema = docker(
        "exec",
        services["db"]["Id"],
        "psql",
        "-U",
        "postgres",
        "-d",
        "repair_guide_preview",
        "-Atc",
        "SELECT version_num FROM alembic_version",
    ).strip()
    assert schema == "0006_m13"
    role = docker(
        "exec",
        services["db"]["Id"],
        "psql",
        "-U",
        "postgres",
        "-d",
        "repair_guide_preview",
        "-Atc",
        "SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles "
        "WHERE rolname='repair_guide'",
    ).strip()
    assert role == "f"
    cert = ROOT / "data/private/preview/local-ca.crt"
    docker(
        "cp",
        services["web"]["Id"] + ":/data/caddy/pki/authorities/local/root.crt",
        str(cert),
    )
    context = ssl.create_default_context(cafile=str(cert))

    def get(path):
        try:
            response = urlopen(state["url"] + path, context=context, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read().decode()

    status, _, html = get("/")
    assert status == 200 and '<div id="root">' in html
    status, headers, body = get("/health/ready")
    ready = json.loads(body)
    assert status == 200 and ready["catalogReady"]
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    status, _, body = get("/api/v1/catalog")
    catalog = json.loads(body)
    assert status == 200 and catalog["version"] == "m08a-20261004-v2"
    status, _, _ = get("/api/v1/m12-private-probe?token=m12-private-probe")
    assert status == 404
    logs = docker("logs", "--since", "2m", services["api"]["Id"], include_stderr=True)
    assert "m12-private-probe" not in logs
    events = [
        json.loads(line)
        for line in logs.splitlines()
        if line.startswith('{"event": "http"')
    ]
    assert any(
        event["route"] == "unmatched" and event["status"] == 404 for event in events
    )
    report = {
        "checkedAt": datetime.now(UTC).isoformat(),
        "publicTunnel": False,
        "httpsCertificateValidated": True,
        "readiness": ready,
        "schema": schema,
        "catalog": catalog["version"],
        "internalPortsOnly": True,
        "sourceBindMounts": False,
        "limitedDatabaseRole": True,
        "safeHttpLogs": True,
        "images": {name: item["Image"] for name, item in services.items()},
        "generationModel": env["OPENAI_CHAT_MODEL"],
        "embeddingModel": env["OPENAI_EMBEDDING_MODEL"],
        "embeddingDimensions": 1536,
        "openaiEnabled": env["OPENAI_ENABLED"],
    }
    output = ROOT / "data/operations/m12-20261006/preview-verification.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
