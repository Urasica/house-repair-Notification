"""One-shot knowledge preparation. Does not run API startup/recovery or fetch source URLs."""

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Catalog, KnowledgeDocument, KnowledgeSet
from app.db.session import Database
from app.schemas.catalog import CatalogDefinition
from app.schemas.contracts import Context
from app.services.catalog import load_definition
from app.services.consultations import latest_knowledge
from app.services.embeddings import Embeddings, EmbeddingUnavailable
from app.services.knowledge import (
    embed_release,
    import_bundle,
    publish_release,
    release_fingerprint,
    release_rows,
    withdraw_source,
)
from app.services.knowledge_source import canonical, digest, prepare_source, read_bounded
from app.services.retrieval import question_purpose, retrieve


async def check_review_deadline(session, settings, warn_days: int, now: datetime) -> dict:
    loaded = await load_definition(session)
    if loaded is None:
        return {"status": "NOT_READY"}
    catalog, _ = loaded
    report = {"status": "NOT_READY", "catalogVersion": catalog.version}
    release_id = await latest_knowledge(session, catalog.version, settings)
    if release_id is None:
        return report
    report["releaseId"] = str(release_id)
    deadline = await session.scalar(
        select(func.min(KnowledgeDocument.review_until)).where(
            KnowledgeDocument.knowledge_set_id == release_id,
            KnowledgeDocument.status == "APPROVED",
        )
    )
    if deadline is None:
        return report
    status = "OK"
    if deadline <= now:
        status = "EXPIRED"
    elif deadline <= now + timedelta(days=warn_days):
        status = "REVIEW_DUE"
    return {**report, "status": status, "reviewUntil": deadline.astimezone(UTC).isoformat()}


async def evaluate_release(database, release_id, cases, provider, settings):
    if not cases or len(cases) > 200:
        raise ValueError("Evaluation requires 1..200 reviewed cases")
    async with database.session() as session:
        release = await session.get(KnowledgeSet, release_id)
        if release is None or release.status != "BUILDING":
            raise ValueError("Only BUILDING may be evaluated")
        fingerprint = release_fingerprint(await release_rows(session, release_id))
    results = []
    tokens = 0
    vectors = {}  # Evaluation queries only; not persisted as source knowledge.
    for case in cases:
        question = case["question"]
        if question not in vectors:
            batch = await provider.embed([question])
            tokens += batch.tokens
            vectors[question] = batch.vectors[0]
        purpose = question_purpose(question)
        async with database.session() as session:
            found = await retrieve(
                session,
                release_id,
                vectors[question],
                settings,
                Context.model_validate(case["context"]),
                purpose=purpose,
                question=question,
                building=True,
            )
        locators = {e.chunk.locator for e in found.evidence}
        for evidence in found.evidence:
            locators.update(c.locator for c, _ in evidence.related)
        expected = set(case["expectedLocators"])
        results.append(
            {
                "id": case["id"],
                "purpose": purpose,
                "status": found.status,
                "expectedStatus": case["expectedStatus"],
                "locators": sorted(locators),
                "expectedLocators": sorted(expected),
                "recall": len(expected & locators) / len(expected) if expected else None,
                "correctStatus": found.status == case["expectedStatus"],
                "unsafe": purpose == "OPERATION"
                and any(
                    e.use == "APPLICABLE" and e.document.kind == "LAW_CRITERIA"
                    for e in found.evidence
                ),
            }
        )
    recalls = [r["recall"] for r in results if r["recall"] is not None]
    report = {
        "releaseId": str(release_id),
        "fingerprint": fingerprint,
        "embeddingModel": settings.openai_embedding_model,
        "embeddingDimensions": settings.embedding_dimensions,
        "provider": "OPENAI",
        "reviewer": "Codex M09 automated evaluation",
        "evaluationSha256": digest(canonical(cases)),
        "queryTokens": tokens,
        "recallAt5": sum(recalls) / len(recalls) if recalls else 0,
        "statusAccuracy": sum(r["correctStatus"] for r in results) / len(results),
        "unsafeDecisions": sum(r["unsafe"] for r in results),
        "cases": results,
    }
    async with database.transaction() as session:
        release = await session.get(KnowledgeSet, release_id, with_for_update=True)
        if (
            release.status != "BUILDING"
            or release_fingerprint(await release_rows(session, release_id)) != fingerprint
        ):
            raise ValueError("Knowledge changed during evaluation")
        release.manifest_json = {**release.manifest_json, "evaluation": report}
    return report


async def execute(args):
    settings = get_settings()
    if args.action == "validate":
        bundle = prepare_source(args.source, args.manifest_sha256)
        return {
            "state": "COMPLETE_VERIFIED",
            "chunks": len(bundle.chunks),
            "sourceSha256": bundle.manifest_hash,
        }
    database = Database(settings)
    try:
        if args.action == "check-review":
            if not 0 <= args.warn_days <= 365:
                raise ValueError("Review warning interval must be 0..365 days")
            async with database.session() as session:
                return await check_review_deadline(
                    session, settings, args.warn_days, datetime.now(UTC)
                )
        if args.action == "import":
            bundle = prepare_source(args.source, args.manifest_sha256)
            catalog_raw = read_bounded(args.catalog)
            catalog = CatalogDefinition.model_validate_json(catalog_raw)
            catalog_review = json.loads(read_bounded(args.catalog_review))
            review = json.loads(read_bounded(args.review))
            if digest(catalog_raw) != catalog_review["catalogSha256"]:
                raise ValueError("Catalog fingerprint mismatch")
            async with database.transaction() as session:
                saved = await session.get(Catalog, catalog.version)
                if saved is None or CatalogDefinition.model_validate(saved.payload_json) != catalog:
                    raise ValueError("Catalog DB payload mismatch")
                release = await import_bundle(session, bundle, catalog_review, review, settings)
                return {
                    "releaseId": str(release.id),
                    "status": release.status,
                    "chunks": len(bundle.chunks),
                }
        if args.action == "embed":
            return await embed_release(database, args.release_id, Embeddings(settings), settings)
        if args.action == "evaluate":
            cases = json.loads(read_bounded(args.cases))
            report = await evaluate_release(
                database, args.release_id, cases, Embeddings(settings), settings
            )
            if args.output:
                args.output.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            return {key: value for key, value in report.items() if key != "cases"}
        async with database.transaction() as session:
            if args.action == "publish":
                release = await session.get(KnowledgeSet, args.release_id)
                report = release.manifest_json.get("evaluation", {}) if release else {}
                result = await publish_release(session, args.release_id, report)
                return {
                    "releaseId": str(result.id),
                    "status": result.status,
                    "publishedAt": result.published_at.isoformat(),
                }
            count = await withdraw_source(session, args.source_key, args.reason)
            return {"withdrawnDocuments": count}
    finally:
        await database.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify, import, embed, evaluate, publish and check knowledge"
    )
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("validate", "import"):
        command = sub.add_parser(action)
        command.add_argument("--source", required=True, type=Path)
        command.add_argument("--manifest-sha256", required=True)
        if action == "import":
            command.add_argument("--catalog", required=True, type=Path)
            command.add_argument("--catalog-review", required=True, type=Path)
            command.add_argument("--review", required=True, type=Path)
    for action in ("embed", "evaluate", "publish"):
        command = sub.add_parser(action)
        command.add_argument("--release-id", required=True, type=UUID)
        if action == "evaluate":
            command.add_argument("--cases", required=True, type=Path)
            command.add_argument("--output", type=Path)
    command = sub.add_parser("withdraw")
    command.add_argument("--source-key", required=True)
    command.add_argument("--reason", required=True)
    command = sub.add_parser("check-review", help="Check the published review deadline")
    command.add_argument("--warn-days", type=int, default=30, help="Warning window (0..365 days)")
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(execute(args))
        print(json.dumps(report, ensure_ascii=False))
        return int(args.action == "check-review" and report["status"] != "OK")
    except (ValueError, KeyError, TypeError, OSError, AppError, EmbeddingUnavailable):
        # Credentials, source paragraphs, user text and provider bodies never enter command logs.
        print(json.dumps({"error": "KNOWLEDGE_OPERATION_FAILED"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
