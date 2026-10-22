"""Explicit local M10 smoke with a synthetic member and one real generation."""

import argparse
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-live-generation", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    origin = "http://localhost:8080"
    session_id = None
    report = {"verifiedAt": datetime.now(UTC).isoformat()}
    with httpx.Client(
        base_url=origin,
        headers={"Origin": origin, "Content-Type": "application/json"},
        timeout=30,
        trust_env=False,
    ) as client:
        credentials = {
            "email": f"m10-{uuid4().hex}@example.com",
            "password": secrets.token_urlsafe(24),
        }
        assert client.post("/api/v1/auth/register", json=credentials).status_code == 201
        login = client.post("/api/v1/auth/login", json=credentials)
        assert login.status_code == 200
        client.headers["X-CSRF-Token"] = login.json()["csrfToken"]
        try:
            catalog = client.get("/api/v1/catalog").json()
            created = client.post(
                "/api/v1/sessions", json={"catalogVersion": catalog["version"], "purpose": "CHAT"}
            )
            assert created.status_code == 201
            snapshot = created.json()["session"]
            session_id = snapshot["id"]
            path = f"/api/v1/sessions/{session_id}"
            context = {
                "housingType": "LH_CONSTRUCTION_RENTAL",
                "roomId": "bathroom",
                "facilityId": "waterproof",
                "symptomId": "leak",
                "answers": {},
            }
            for _ in range(5):
                changed = client.put(
                    path + "/context",
                    json={"expectedRevision": snapshot["revision"], "context": context},
                )
                assert changed.status_code == 200
                snapshot = changed.json()
                break  # Chat confirms its own context and never loads survey questions.
            body = {
                "requestId": str(uuid4()),
                "expectedRevision": snapshot["revision"],
                "content": "제10조 내용을 설명해 주세요",
            }
            result = client.post(path + "/chat/messages", json=body)
            assert result.status_code == 200
            answer = result.json()
            assert answer["answerMode"] == "GROUNDED" and answer["status"] == "GUIDANCE_AVAILABLE"
            assert "비고:" in answer["assistantMessage"]["content"]
            assert "유지관리 부실" in answer["assistantMessage"]["content"]
            assert client.post(path + "/chat/messages", json=body).json() == answer
            assert client.get(path + "/chat/messages").json()["items"] == [answer]
            assert client.get(path + "/requests/" + body["requestId"]).json()["response"] == answer
            context["description"] = "합성 확인 입력"
            changed = client.put(
                path + "/context",
                json={"expectedRevision": snapshot["revision"], "context": context},
            )
            assert changed.status_code == 200
            stale = client.get(path + "/chat/messages").json()["items"][0]
            assert not stale["isCurrent"] and not stale["assistantMessage"]["isCurrent"]
            report.update(
                {
                    "readiness": client.get("/health/ready").json(),
                    "answerMode": answer["answerMode"],
                    "status": answer["status"],
                    "locators": [c["locator"] for c in answer["assistantMessage"]["citations"]],
                    "annexFootnotePresent": True,
                    "sameRequestReplay": True,
                    "historyRestored": True,
                    "requestStateRestored": True,
                    "staleAfterContextChange": True,
                }
            )
        finally:
            if session_id:
                assert client.delete("/api/v1/me/question-records").status_code == 204
                assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204
            assert client.post("/api/v1/auth/logout").status_code == 204
        report["syntheticConversationRemoved"] = True
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print("M10 live smoke passed: generation, annex, history, replay, stale display, cleanup")


if __name__ == "__main__":
    main()
