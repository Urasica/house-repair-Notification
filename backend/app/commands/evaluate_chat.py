"""Explicit bounded real-provider evaluation; never persists questions/vectors or source text."""

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Catalog, KnowledgeSet
from app.db.session import Database
from app.schemas.catalog import CatalogDefinition
from app.schemas.contracts import Context, Session
from app.services.chat import chat_response
from app.services.embeddings import Embeddings
from app.services.generation import PROMPT_VERSION, Responses
from app.services.knowledge_source import canonical, digest, read_bounded
from app.services.retrieval import safe_text
from app.services.survey_policy import survey_policy


class CountedResponses(Responses):
    def __init__(self, settings):
        super().__init__(settings)
        self.calls = 0

    async def generate(self, *args, **kwargs):
        self.calls += 1
        self.last_usage = {}
        return await super().generate(*args, **kwargs)


async def evaluate(args):
    settings = get_settings()
    cases = json.loads(read_bounded(args.cases))
    if not settings.openai_enabled or not isinstance(cases, list) or not 1 <= len(cases) <= 20:
        raise ValueError(
            "Explicit enabled configuration and at most 20 reviewed synthetic cases required"
        )
    database = Database(settings)
    try:
        async with database.session() as session:
            release = await session.get(KnowledgeSet, args.release_id)
            if release is None or release.status != "PUBLISHED":
                raise ValueError("Published knowledge required")
            catalog = CatalogDefinition.model_validate(
                (await session.get(Catalog, release.catalog_version)).payload_json
            )
            fingerprint = release.manifest_json["evaluation"]["fingerprint"]
        rows, tokens = [], {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        generator = CountedResponses(settings)
        for case in cases:
            context = Context.model_validate(case["context"])
            if case.get("fillUnknown", True):
                for _ in range(5):
                    policy = survey_policy(catalog, context)
                    for question in policy.questions:
                        if question.question_id not in context.answers:
                            context.answers[question.question_id] = "UNKNOWN"
            now = datetime.now(UTC)
            snapshot = Session(
                id=uuid4(),
                access_mode="MEMBER",
                catalog_version=catalog.version,
                knowledge_release_id=release.id,
                revision=1,
                context=context,
                current_result_id=None,
                created_at=now,
                expires_at=now + timedelta(hours=24),
            )
            before = generator.calls
            started = time.monotonic()
            response = await chat_response(
                snapshot,
                catalog,
                settings,
                case["question"],
                uuid4(),
                [],
                database=database,
                embeddings=Embeddings(settings),
                generator=generator,
            )
            calls = generator.calls - before
            for key in tokens:
                tokens[key] += generator.last_usage.get(key, 0) if calls else 0
            locators = sorted({c.locator for c in response.assistant_message.citations})
            passed = (
                response.status == case["expectedStatus"]
                and response.answer_mode == case["expectedMode"]
                and calls == case["expectedGenerationCalls"]
                and safe_text(response.assistant_message.content)
                and set(case.get("expectedLocators", [])).issubset(locators)
            )
            rows.append(
                {
                    "id": case["id"],
                    "status": response.status,
                    "answerMode": response.answer_mode,
                    "generationCalls": calls,
                    "locators": locators,
                    "passed": passed,
                    "seconds": round(time.monotonic() - started, 3),
                    "answerSha256": digest(response.assistant_message.content),
                }
            )
        report = {
            "evaluatedAt": datetime.now(UTC).isoformat(),
            "promptVersion": PROMPT_VERSION,
            "model": settings.openai_chat_model,
            "embeddingModel": settings.openai_embedding_model,
            "releaseId": str(release.id),
            "knowledgeFingerprint": fingerprint,
            "casesSha256": digest(canonical(cases)),
            "provider": "OPENAI",
            "generationCalls": generator.calls,
            "generationTokens": tokens,
            "passed": all(row["passed"] for row in rows),
            "cases": rows,
        }
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return {key: value for key, value in report.items() if key != "cases"}
    finally:
        await database.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate at most 20 synthetic chat cases with real OpenAI"
    )
    parser.add_argument("--release-id", type=UUID, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    try:
        report = asyncio.run(evaluate(parser.parse_args()))
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["passed"] else 1
    except (AppError, ValueError, KeyError, TypeError, OSError):
        print('{"error":"CHAT_EVALUATION_FAILED"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
