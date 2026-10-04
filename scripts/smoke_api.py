import argparse
import json
from urllib.error import HTTPError
from urllib.request import urlopen


def fetch(base: str, path: str):
    try:
        response = urlopen(base.rstrip("/") + path, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        body = response.read().decode("utf-8")
        return response.status, response.headers, body


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--database-unavailable", action="store_true")
    parser.add_argument("--rag-ready", action="store_true")
    parser.add_argument(
        "--catalog-version", help="Expect this reviewed catalog to be published"
    )
    args = parser.parse_args()
    status, _, html = fetch(args.url, "/")
    assert status == 200 and '<div id="root">' in html
    status, _, live = fetch(args.url, "/health/live")
    assert status == 200 and json.loads(live) == {"status": "ok"}
    status, headers, ready = fetch(args.url, "/health/ready")
    assert headers["Cache-Control"] == "no-store"
    if args.database_unavailable:
        assert (
            status == 503
            and json.loads(ready)["error"]["code"] == "SERVICE_UNAVAILABLE"
        )
    else:
        assert status == 200
        assert json.loads(ready) == {
            "status": "ok",
            "catalogReady": bool(args.catalog_version),
            "ragReady": args.rag_ready,
        }
    status, headers, catalog = fetch(args.url, "/api/v1/catalog")
    if args.catalog_version and not args.database_unavailable:
        data = json.loads(catalog)
        assert status == 200 and data["version"] == args.catalog_version
        assert all(
            data[key] for key in ("housingTypes", "rooms", "facilities", "symptoms")
        )
        assert headers["Cache-Control"] == "no-store"
    else:
        error = json.loads(catalog)["error"]
        assert status == 503
        assert error["code"] == (
            "SERVICE_UNAVAILABLE" if args.database_unavailable else "CATALOG_NOT_READY"
        )
        assert (
            headers["Cache-Control"] == "no-store"
            and headers["X-Trace-Id"] == error["traceId"]
        )
    status, _, missing = fetch(args.url, "/api/v1/missing")
    assert status == 404 and json.loads(missing)["error"]["code"] == "NOT_FOUND"
    if not args.database_unavailable:
        status, headers, auth = fetch(args.url, "/api/v1/auth/me")
        assert status == 200 and json.loads(auth) == {"user": None, "csrfToken": None}
        assert headers["Cache-Control"] == "no-store"
        status, _, history = fetch(args.url, "/api/v1/me/results")
        assert status == 401 and json.loads(history)["error"]["code"] == "AUTH_REQUIRED"
    print("Smoke checks passed: web, live, ready, catalog state, auth, API errors")


if __name__ == "__main__":
    main()
