"""Explicit BUILDING import, embedding resume, reviewed publication and withdrawal."""

from datetime import UTC, date, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text

from app.db.models import Catalog, KnowledgeChunk, KnowledgeDocument, KnowledgeSet
from app.services.embeddings import validate_vector
from app.services.knowledge_source import SourceBundle, canonical, digest


def check_review(review: dict, bundle: SourceBundle, catalog_version: str):
    now = datetime.now(UTC)
    if (
        review.get("state") != "APPROVED"
        or not review.get("reviewer")
        or review.get("manifestSha256") != bundle.manifest_hash
        or review.get("catalogVersion") != catalog_version
        or review.get("kind") != "LAW_CRITERIA"
        or review.get("operationalUse") is not False
        or not review.get("housingTypes")
        or not review.get("referenceTemplate")
    ):
        raise ValueError("Missing scoped knowledge review")
    reviewed = datetime.fromisoformat(review["reviewedAt"])
    until = datetime.fromisoformat(review["reviewUntil"])
    if reviewed.tzinfo is None or until.tzinfo is None or not reviewed <= now < until:
        raise ValueError("Review expired or not yet effective")
    # Only a fixed, explicitly conservative reference template is accepted by the M08 importer.
    if review["referenceTemplate"] != (
        "선택한 증상과 관련된 법령을 참고할 수 있어요. "
        "이 자료만으로 LH의 보수 대상·비용·교체 여부를 판단할 수는 없어요."
    ):
        raise ValueError("Unreviewed reference template")


async def import_bundle(
    session, bundle: SourceBundle, catalog_review: dict, review: dict, settings
):
    version = catalog_review["catalogVersion"]
    check_review(review, bundle, version)
    source_key = bundle.manifest["source"]["observedUrl"]
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": source_key}
    )
    if await session.scalar(
        select(KnowledgeDocument.id)
        .where(KnowledgeDocument.source_key == source_key, KnowledgeDocument.status == "WITHDRAWN")
        .limit(1)
    ):
        raise ValueError("Withdrawn source cannot be reimported")
    catalog = await session.get(Catalog, version)
    if catalog is None or catalog.status != "PUBLISHED":
        raise ValueError("Catalog must be published")
    if (
        catalog_review.get("state") != "COMPLETE_VERIFIED"
        or catalog_review["source"]["m08ManifestSha256"] != bundle.manifest_hash
    ):
        raise ValueError("Catalog source fingerprint mismatch")
    # Catalog hash is checked by the CLI against the reviewed file and then its DB payload.
    fingerprint = digest(
        canonical(
            {
                "source": bundle.manifest_hash,
                "review": review,
                "catalog": catalog_review,
                "model": settings.openai_embedding_model,
                "dimensions": settings.embedding_dimensions,
                "chunker": "m09-v2",
                "chunks": bundle.chunks,
            }
        )
    )
    release_id = uuid5(NAMESPACE_URL, "repair-guide:" + fingerprint)
    existing = await session.get(KnowledgeSet, release_id)
    if existing:
        if existing.status != "BUILDING":
            raise ValueError("Only BUILDING releases can be resumed")
        return existing
    release = KnowledgeSet(
        id=release_id,
        catalog_version=version,
        status="BUILDING",
        embedding_model=settings.openai_embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
        manifest_json={
            "state": "COMPLETE_VERIFIED",
            "sourceSha256": bundle.manifest_hash,
            "buildFingerprint": fingerprint,
            "review": review,
            "chunker": "m09-v2",
            "embeddingTokens": 0,
        },
    )
    session.add(release)
    await session.flush()
    doc_id = uuid5(release_id, "source")
    normalized = "\n\n".join(c["body"] for c in bundle.chunks)
    document = KnowledgeDocument(
        id=doc_id,
        knowledge_set_id=release_id,
        source_key=bundle.manifest["source"]["observedUrl"],
        version_label=bundle.manifest["source"]["observedVersion"],
        kind="LAW_CRITERIA",
        title=bundle.manifest["source"]["title"],
        url=bundle.manifest["source"]["observedUrl"],
        normalized_text=normalized,
        content_hash=digest(normalized),
        scope_json={
            "housingTypes": review["housingTypes"],
            "operationalUse": False,
            "referenceTemplate": review["referenceTemplate"],
        },
        effective_date=date.fromisoformat(bundle.manifest["source"]["effectiveDate"]),
        reviewed_at=datetime.fromisoformat(review["reviewedAt"]),
        review_until=datetime.fromisoformat(review["reviewUntil"]),
        reviewer_key=review["reviewer"],
        status="APPROVED",
    )
    session.add(document)
    await session.flush()
    ids = {c["locator"]: str(uuid5(doc_id, c["locator"])) for c in bundle.chunks}
    reusable_rows = (
        await session.execute(
            select(KnowledgeChunk, KnowledgeSet)
            .join_from(
                KnowledgeChunk,
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeChunk.document_id,
            )
            .join(KnowledgeSet, KnowledgeSet.id == KnowledgeDocument.knowledge_set_id)
            .where(
                KnowledgeSet.embedding_model == settings.openai_embedding_model,
                KnowledgeSet.embedding_dimensions == settings.embedding_dimensions,
                KnowledgeSet.status.in_(["BUILDING", "PUBLISHED"]),
                KnowledgeChunk.content_hash.in_([c["contentHash"] for c in bundle.chunks]),
                KnowledgeChunk.content_hash == KnowledgeChunk.embedded_content_hash,
                KnowledgeChunk.embedding.is_not(None),
            )
        )
    ).all()
    reusable = {}
    for old, _ in reusable_rows:
        if digest(old.body) == old.content_hash:
            validate_vector(list(old.embedding), settings.embedding_dimensions)
            reusable[(old.content_hash, old.body)] = list(old.embedding)
    for ordinal, chunk in enumerate(bundle.chunks):
        metadata = dict(chunk["metadata"])
        coverage = catalog_review["articleCoverage"].get(chunk["locator"], {})
        metadata.update(
            {
                "relatedChunkIds": [ids[k] for k in metadata.pop("relatedLocators")],
                "contextChunkIds": [ids[k] for k in metadata.pop("contextLocators")],
                "symptomIds": coverage.get("symptoms", []),
                "explanationAllowed": not metadata.get("unresolved")
                and not metadata.get("externalReferences"),
                "operationalUse": False,
            }
        )
        vector = reusable.get((chunk["contentHash"], chunk["body"]))
        session.add(
            KnowledgeChunk(
                id=UUID(ids[chunk["locator"]]),
                document_id=doc_id,
                ordinal=ordinal,
                locator=chunk["locator"],
                body=chunk["body"],
                content_hash=chunk["contentHash"],
                embedding=vector,
                embedded_content_hash=chunk["contentHash"] if vector else None,
                metadata_json=metadata,
            )
        )
    await session.flush()
    return release


async def embed_release(database, release_id: UUID, provider, settings):
    """No DB transaction or row lock spans a network request; commit each successful batch."""
    async with database.session() as session:
        release = await session.get(KnowledgeSet, release_id)
        if (
            release is None
            or release.status != "BUILDING"
            or release.embedding_model != settings.openai_embedding_model
            or release.embedding_dimensions != settings.embedding_dimensions
        ):
            raise ValueError("Incompatible or immutable release")
        rows = (
            await session.scalars(
                select(KnowledgeChunk)
                .join(KnowledgeDocument)
                .where(KnowledgeDocument.knowledge_set_id == release_id)
                .order_by(KnowledgeChunk.ordinal)
            )
        ).all()
        pending = [
            (r.id, r.body, r.content_hash)
            for r in rows
            if r.embedding is None or r.content_hash != r.embedded_content_hash
        ]
        if any(digest(body) != sha for _, body, sha in pending):
            raise ValueError("Source text changed after review")
    tokens = 0
    for offset in range(0, len(pending), 16):
        batch = pending[offset : offset + 16]
        embedded = await provider.embed([body for _, body, _ in batch], timeout=30)
        async with database.transaction() as session:
            release = await session.get(KnowledgeSet, release_id, with_for_update=True)
            if release.status != "BUILDING":
                raise ValueError("Release changed during embedding")
            for (chunk_id, body, sha), vector in zip(batch, embedded.vectors, strict=True):
                row = await session.get(KnowledgeChunk, chunk_id, with_for_update=True)
                if row.body != body or row.content_hash != sha:
                    raise ValueError("Source changed during embedding")
                validate_vector(vector, settings.embedding_dimensions)
                row.embedding = vector
                row.embedded_content_hash = sha
            tokens += embedded.tokens
            release.manifest_json = {
                **release.manifest_json,
                "embeddingTokens": release.manifest_json.get("embeddingTokens", 0)
                + embedded.tokens,
            }
    return {"embeddedChunks": len(pending), "tokens": tokens}


async def release_rows(session, release_id, *, lock=False):
    statement = (
        select(KnowledgeChunk, KnowledgeDocument)
        .join(KnowledgeDocument)
        .where(KnowledgeDocument.knowledge_set_id == release_id)
        .order_by(KnowledgeChunk.ordinal)
    )
    if lock:
        statement = statement.with_for_update()
    return (await session.execute(statement)).all()


def release_fingerprint(rows) -> str:
    return digest(
        canonical(
            [
                {
                    "id": str(c.id),
                    "hash": c.content_hash,
                    "embeddingHash": c.embedded_content_hash,
                    "vectorHash": digest(canonical([float(v) for v in c.embedding]))
                    if c.embedding is not None
                    else None,
                    "metadata": c.metadata_json,
                    "documentHash": d.content_hash,
                    "scope": d.scope_json,
                    "reviewUntil": d.review_until.isoformat(),
                }
                for c, d in rows
            ]
        )
    )


async def publish_release(session, release_id, report: dict):
    release = await session.get(KnowledgeSet, release_id, with_for_update=True)
    if release is None or release.status != "BUILDING":
        raise ValueError("Only BUILDING may be published")
    rows = await release_rows(session, release_id, lock=True)
    now = datetime.now(UTC)
    if (
        not rows
        or report != release.manifest_json.get("evaluation")
        or report.get("releaseId") != str(release_id)
        or report.get("fingerprint") != release_fingerprint(rows)
        or report.get("embeddingModel") != release.embedding_model
        or report.get("embeddingDimensions") != release.embedding_dimensions
        or report.get("provider") != "OPENAI"
        or report.get("recallAt5", 0) < 0.9
        or report.get("statusAccuracy", 0) < 0.95
        or report.get("unsafeDecisions") != 0
        or not report.get("cases")
        or not report.get("reviewer")
    ):
        raise ValueError("Evaluation gate failed")
    ids = {str(c.id) for c, _ in rows}
    for chunk, document in rows:
        if (
            document.status != "APPROVED"
            or not document.reviewed_at <= now < document.review_until
            or chunk.content_hash != digest(chunk.body)
            or chunk.content_hash != chunk.embedded_content_hash
            or document.content_hash != digest(document.normalized_text)
        ):
            raise ValueError("Source/embedding review gate failed")
        validate_vector(
            list(chunk.embedding) if chunk.embedding is not None else None,
            release.embedding_dimensions,
        )
        if any(
            k not in ids
            for k in chunk.metadata_json.get("relatedChunkIds", [])
            + chunk.metadata_json.get("contextChunkIds", [])
        ):
            raise ValueError("Missing related source")
    release.manifest_json = {**release.manifest_json, "evaluation": report}
    release.status = "PUBLISHED"
    release.published_at = now
    await session.flush()
    return release


async def withdraw_source(session, source_key: str, reason: str):
    if not reason.strip():
        raise ValueError("Withdrawal reason required")
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": source_key}
    )
    # Same parent-before-child lock order as final evaluation and publication.
    release_ids = select(KnowledgeDocument.knowledge_set_id).where(
        KnowledgeDocument.source_key == source_key
    )
    await session.execute(
        select(KnowledgeSet)
        .where(KnowledgeSet.id.in_(release_ids))
        .order_by(KnowledgeSet.id)
        .with_for_update()
    )
    rows = (
        await session.scalars(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.source_key == source_key)
            .with_for_update()
        )
    ).all()
    for row in rows:
        row.status = "WITHDRAWN"
        row.withdrawn_at = datetime.now(UTC)
        row.withdrawal_reason = reason
    await session.flush()
    return len(rows)
