"""Twenty concurrent users against isolated E2E stack; no provider calls."""

import asyncio
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx

BASE = "http://localhost:18080"


async def main():
    headers = {"Origin": BASE, "Content-Type": "application/json"}
    samples = {
        key: []
        for key in ("catalog", "session", "questions", "history", "survey", "chat")
    }
    async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=30) as client:
        email = f"load-{uuid4().hex}@example.com"
        credentials = {"email": email, "password": "load-only-long-password"}
        (
            await client.post("/api/v1/auth/register", json=credentials)
        ).raise_for_status()
        login = await client.post("/api/v1/auth/login", json=credentials)
        login.raise_for_status()
        client.headers["X-CSRF-Token"] = login.json()["csrfToken"]
        catalog = (await client.get("/api/v1/catalog")).json()

        async def user():
            created = await client.post(
                "/api/v1/sessions", json={"catalogVersion": catalog["version"]}
            )
            created.raise_for_status()
            session = created.json()["session"]
            base = f"/api/v1/sessions/{session['id']}"
            try:
                for _ in range(5):
                    for kind, path in (
                        ("catalog", "/api/v1/catalog"),
                        ("session", base),
                        ("questions", base + "/questions"),
                        ("history", "/api/v1/me/results"),
                    ):
                        started = perf_counter()
                        response = await client.get(path)
                        response.raise_for_status()
                        samples[kind].append((perf_counter() - started) * 1000)
                for kind, path, body in (
                    ("survey", "/evaluations", {}),
                    (
                        "chat",
                        "/chat/messages",
                        {"content": "조문 설명에 필요한 정보를 알려주세요"},
                    ),
                ):
                    started = perf_counter()
                    response = await client.post(
                        base + path,
                        json={"requestId": str(uuid4()), "expectedRevision": 0, **body},
                    )
                    response.raise_for_status()
                    samples[kind].append((perf_counter() - started) * 1000)
            finally:
                (await client.delete(base)).raise_for_status()

        await asyncio.gather(*(user() for _ in range(20)))
        history = (await client.get("/api/v1/me/results?limit=50")).json()
        for item in history["items"]:
            (await client.delete(f"/api/v1/me/results/{item['id']}")).raise_for_status()
        (await client.delete("/api/v1/me/question-records")).raise_for_status()
        (await client.post("/api/v1/auth/logout")).raise_for_status()
    report = {
        "executedAt": datetime.now(UTC).isoformat(),
        "concurrency": 20,
        "openai": "disabled; provider deadline covered by mock tests",
        "measurements": {
            kind: {
                "count": len(values),
                "p95Ms": round(sorted(values)[math.ceil(len(values) * 0.95) - 1], 2),
                "maxMs": round(max(values), 2),
            }
            for kind, values in samples.items()
        },
    }
    report["basicApiTargetPassed"] = all(
        report["measurements"][kind]["p95Ms"] <= 1500
        for kind in ("catalog", "session", "questions", "history")
    )
    destination = Path("artifacts/m11/load-report.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    assert report["basicApiTargetPassed"]


if __name__ == "__main__":
    asyncio.run(main())
