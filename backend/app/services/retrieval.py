"""Exact pgvector search in a pinned release, followed by conservative evidence gates."""

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.db.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSet
from app.schemas.contracts import Citation, Context
from app.services.embeddings import validate_vector
from app.services.knowledge_source import digest


def question_purpose(question: str) -> str:
    # A mixed or ambiguous request is operational. Never let a model loosen this classification.
    operational = (
        r"(?:비용|무상|유상|무료|교체|수리해|보수해|부담|책임|지원|신청|접수|"
        r"대상인가|대상인지|가능해|우리|저희|내\s*집|LH|엘에이치|해당하|적용되)"
    )
    explicit = r"(?:제\s*\d+\s*조|별표\s*\d+).*(?:설명|뜻|의미|내용|알려)"
    return (
        "LAW_EXPLANATION"
        if re.search(explicit, question) and not re.search(operational, question)
        else "OPERATION"
    )


def safe_text(text: str) -> bool:
    return not re.search(r"https?://|www\.|@|(?:\d[\s().-]*){7,}|tel:|mailto:", text, re.I)


@dataclass
class Evidence:
    chunk: KnowledgeChunk
    document: KnowledgeDocument
    related: list[tuple[KnowledgeChunk, KnowledgeDocument]] = field(default_factory=list)
    context: list[tuple[KnowledgeChunk, KnowledgeDocument]] = field(default_factory=list)
    use: str = "RELATED"


@dataclass
class Retrieval:
    evidence: list[Evidence] = field(default_factory=list)
    status: str = "NEED_CONFIRMATION"
    reason: str = "NO_APPLICABLE_SOURCE"
    guidance: list[str] = field(default_factory=list)
    candidate_count: int = 0

    def citations(self, *, excerpts=False):
        output = {}
        for bundle in self.evidence:
            for chunk, document in [
                (bundle.chunk, bundle.document),
                *bundle.related,
                *(bundle.context if excerpts else []),
            ]:
                output[chunk.id] = Citation(
                    chunk_id=chunk.id,
                    document_version_id=document.id,
                    kind=document.kind,
                    use=bundle.use,
                    title=document.title,
                    locator=chunk.locator,
                    url=document.url,
                    excerpt=source_excerpt(chunk) if excerpts else None,
                    effective_date=document.effective_date.isoformat()
                    if document.effective_date
                    else None,
                    reviewed_at=document.reviewed_at,
                    review_until=document.review_until,
                )
        return list(output.values())


def source_excerpt(chunk):
    if chunk.metadata_json.get("role") != "ANNEX":
        return chunk.body
    data = json.loads(chunk.body)
    lines = [f"별표 {data['number']} · {data['title']}"]
    for row in data["rows"]:
        lines.append(
            "\n".join(
                f"{label}: {value}" for label, value in zip(data["columns"], row, strict=True)
            )
        )
    return "\n\n".join([*lines, *data["footnotes"]])


def eligible(chunk, document, now):
    return (
        document.status == "APPROVED"
        and document.reviewed_at is not None
        and document.review_until is not None
        and document.reviewed_at <= now < document.review_until
        and (document.effective_date is None or document.effective_date <= now.date())
        and document.url.startswith("https://")
        and chunk.content_hash == chunk.embedded_content_hash == digest(chunk.body)
        and document.content_hash == digest(document.normalized_text)
        and chunk.embedding is not None
    )


def operation_matches(rule, context: Context):
    if not isinstance(rule, dict) or not rule.get("conditions") or not rule.get("guidance"):
        return False
    data = context.model_dump(by_alias=True)
    for key, value in rule["conditions"].items():
        actual = data.get(key) if not key.startswith("answers.") else context.answers.get(key[8:])
        if actual is None or actual == "UNKNOWN" or actual != value:
            return False
    return all(isinstance(t, str) and t.strip() and safe_text(t) for t in rule["guidance"])


async def retrieve(
    session,
    release_id: UUID,
    vector: list[float],
    settings,
    context: Context,
    *,
    purpose="OPERATION",
    question="",
    building=False,
    catalog_version=None,
) -> Retrieval:
    validate_vector(vector, settings.embedding_dimensions)
    now = datetime.now(UTC)
    release = await session.get(KnowledgeSet, release_id)
    if (
        release is None
        or (catalog_version is not None and release.catalog_version != catalog_version)
        or release.status != ("BUILDING" if building else "PUBLISHED")
        or release.embedding_model != settings.openai_embedding_model
        or release.embedding_dimensions != settings.embedding_dimensions
        or release.manifest_json.get("state") != "COMPLETE_VERIFIED"
        or (not building and (release.published_at is None or release.published_at > now))
    ):
        return Retrieval(reason="SOURCE_UNAVAILABLE")
    release_filters = [
        KnowledgeDocument.knowledge_set_id == release_id,
        KnowledgeDocument.status == "APPROVED",
        KnowledgeDocument.reviewed_at <= now,
        KnowledgeDocument.review_until > now,
        KnowledgeChunk.embedding.is_not(None),
        KnowledgeChunk.content_hash == KnowledgeChunk.embedded_content_hash,
    ]
    filters = list(release_filters)
    if context.housing_type and context.housing_type != "UNKNOWN":
        filters.append(
            KnowledgeDocument.scope_json["housingTypes"].contains([context.housing_type])
        )
    elif purpose == "LAW_EXPLANATION":
        # A general article explanation does not require a survey housing selection.
        filters.append(KnowledgeDocument.kind == "LAW_CRITERIA")
    else:
        return Retrieval()
    explicit = re.findall(r"제\s*(\d+)\s*조(?:의\s*(\d+))?|별표\s*(\d+)", question)
    locators = [
        f"별표 {annex}" if annex else f"제{n}조" + (f"의{sub}" if sub else "")
        for n, sub, annex in explicit
    ]
    query = select(KnowledgeChunk, KnowledgeDocument).join(KnowledgeDocument).where(*filters)
    if locators:
        query = query.where(KnowledgeChunk.locator.in_(locators))
    else:
        # Selected catalog tags restrict relevance; vector proximity alone never supplies scope.
        if not context.symptom_id or context.symptom_id == "unknown":
            return Retrieval()
        query = query.where(
            KnowledgeChunk.metadata_json["role"].astext == "ARTICLE",
            KnowledgeChunk.metadata_json["symptomIds"].contains([context.symptom_id]),
        )
    candidates = (
        await session.execute(
            query.order_by(
                KnowledgeChunk.embedding.cosine_distance(vector), KnowledgeChunk.id
            ).limit(20)
        )
    ).all()
    if not candidates and not await session.scalar(
        select(KnowledgeChunk.id).join(KnowledgeDocument).where(*release_filters).limit(1)
    ):
        return Retrieval(reason="SOURCE_UNAVAILABLE")
    result = Retrieval(candidate_count=len(candidates))
    groups = {}
    seen = set()
    for chunk, document in candidates:
        if not eligible(chunk, document, now):
            continue
        metadata = chunk.metadata_json
        related_ids = metadata.get("relatedChunkIds", [])
        context_ids = metadata.get("contextChunkIds", [])
        dependency_ids = set(related_ids + context_ids)
        if len(dependency_ids) > 30:
            continue
        try:
            dependency_uuids = [UUID(k) for k in dependency_ids]
        except (ValueError, TypeError):
            continue
        dependencies = (
            (
                await session.execute(
                    select(KnowledgeChunk, KnowledgeDocument)
                    .join(KnowledgeDocument)
                    .where(*filters, KnowledgeChunk.id.in_(dependency_uuids))
                )
            ).all()
            if dependency_ids
            else []
        )
        valid = {str(c.id): (c, d) for c, d in dependencies if eligible(c, d, now)}
        if set(valid) != dependency_ids:
            continue
        evidence = Evidence(
            chunk, document, [valid[k] for k in related_ids], [valid[k] for k in context_ids]
        )
        if purpose == "LAW_EXPLANATION" and document.kind == "LAW_CRITERIA":
            if all(
                c.metadata_json.get("explanationAllowed")
                for c, _ in [(chunk, document), *evidence.related]
            ):
                evidence.use = "APPLICABLE"
        rule = metadata.get("operationRule")
        if (
            purpose == "OPERATION"
            and document.kind == "LH_OPERATION"
            and document.scope_json.get("operationalUse") is True
            and operation_matches(rule, context)
        ):
            evidence.use = "APPLICABLE"
            key = rule.get("conflictKey")
            if not key:
                continue
            groups.setdefault(key, set()).add(tuple(rule["guidance"]))
        if chunk.id not in seen:
            seen.add(chunk.id)
            result.evidence.append(evidence)
    if candidates and not result.evidence:
        return Retrieval(reason="SOURCE_UNAVAILABLE", candidate_count=len(candidates))
    # Check conflicts across all 20 candidates before reducing to 5 evidence bundles.
    if any(len(values) > 1 for values in groups.values()):
        return Retrieval(reason="SOURCE_CONFLICT", candidate_count=len(candidates))
    result.evidence.sort(key=lambda e: e.use != "APPLICABLE")
    result.evidence = result.evidence[:5]
    applicable = [e for e in result.evidence if e.use == "APPLICABLE"]
    if purpose == "LAW_EXPLANATION" and locators:
        covered = {c.locator for e in applicable for c, _ in [(e.chunk, e.document), *e.related]}
        if not set(locators).issubset(covered):
            for evidence in result.evidence:
                evidence.use = "RELATED"
            applicable = []
    if applicable:
        result.status = "GUIDANCE_AVAILABLE"
        result.reason = "MATCHED_OPERATION_RULE" if purpose == "OPERATION" else "LAW_EXPLANATION"
        if purpose == "OPERATION":
            result.guidance = list(
                dict.fromkeys(
                    t
                    for e in applicable
                    for t in e.chunk.metadata_json["operationRule"]["guidance"]
                )
            )
    elif result.evidence:
        templates = [e.document.scope_json.get("referenceTemplate", "") for e in result.evidence]
        result.guidance = list(dict.fromkeys(t for t in templates if t and safe_text(t)))
    return result


async def revalidate_citations(session, result, settings=None, *, lock=True):
    """Short final lock closes the withdrawal/review race before result commit."""
    if not result.citations:
        return True
    release = await session.get(KnowledgeSet, result.knowledge_release_id, with_for_update=lock)
    if (
        release is None
        or release.status != "PUBLISHED"
        or release.catalog_version != result.catalog_version
        or (settings is not None and release.embedding_model != settings.openai_embedding_model)
        or (settings is not None and release.embedding_dimensions != settings.embedding_dimensions)
    ):
        return False
    query = (
        select(KnowledgeChunk, KnowledgeDocument)
        .join(KnowledgeDocument)
        .where(KnowledgeDocument.knowledge_set_id == release.id)
    )
    rows = (await session.execute(query.with_for_update() if lock else query)).all()
    valid = {str(c.id): (c, d) for c, d in rows if eligible(c, d, datetime.now(UTC))}
    for citation in result.citations:
        pair = valid.get(str(citation.chunk_id))
        if pair is None or citation.document_version_id != pair[1].id:
            return False
        meta = pair[0].metadata_json
        if any(
            k not in valid
            for k in meta.get("relatedChunkIds", []) + meta.get("contextChunkIds", [])
        ):
            return False
    return True
