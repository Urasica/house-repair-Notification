"""Survey templates with pinned internal evidence; no generative model calls."""

from calendar import monthrange
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.config import Settings
from app.db.models import Consultation, KnowledgeSet, Result
from app.domain.constants import DISCLAIMER, INSUFFICIENT_INFORMATION_MESSAGE, GuidanceStatus
from app.schemas.catalog import CatalogDefinition
from app.schemas.contracts import GuidanceResult, ResultSummary, Session
from app.services.embeddings import Embeddings, EmbeddingUnavailable
from app.services.repair_examples import repair_examples
from app.services.retrieval import retrieve, revalidate_citations
from app.services.survey_policy import survey_policy

ENGINE_VERSION = "survey-v4-reference-examples"


def add_years(value: datetime, years: int) -> datetime:
    year = value.year + years
    return value.replace(year=year, day=min(value.day, monthrange(year, value.month)[1]))


async def evaluate_survey(
    snapshot: Session,
    catalog: CatalogDefinition,
    settings: Settings,
    *,
    database=None,
    provider=None,
) -> GuidanceResult:
    policy = survey_policy(catalog, snapshot.context)
    context = policy.context

    def label(items, identifier):
        return next((item.label for item in items if item.id == identifier), "선택하지 않음")

    answers = []
    for question in policy.questions:
        value = context.answers.get(question.question_id)
        if value is not None:
            answer_label = next(
                option.label for option in question.options if option.value == value
            )
            answers.append(f"{question.label}: {answer_label}")
    messages = {
        GuidanceStatus.SAFETY_PRIORITY: (
            [
                "일반 보수 안내보다 안전 확인이 우선이에요.",
                "관리사무소 또는 담당 기관에 직접 문의해 주세요.",
            ],
            "HAZARD_SIGNAL",
        ),
        GuidanceStatus.OUT_OF_SCOPE: (
            [
                "이 서비스의 지원 주택 범위에 해당하지 않아요.",
                "관리사무소 또는 담당 기관에 직접 문의해 주세요.",
            ],
            "HOUSING_OUT_OF_SCOPE",
        ),
        GuidanceStatus.NEED_MORE_INFO: (
            ["선택한 주택 유형과 필요한 설문 답을 더 확인해 주세요."],
            "MISSING_INPUT",
        ),
        GuidanceStatus.NEED_CONFIRMATION: (
            [INSUFFICIENT_INFORMATION_MESSAGE],
            "NO_APPLICABLE_SOURCE",
        ),
    }
    guidance, reason = messages[policy.status]
    now = datetime.now(UTC)
    retained_until = (
        add_years(now, settings.member_result_retention_years)
        if snapshot.access_mode == "MEMBER"
        else snapshot.expires_at + timedelta(days=settings.raw_record_grace_days)
    )
    result = GuidanceResult(
        id=uuid4(),
        session_id=snapshot.id,
        saved_to_history=snapshot.access_mode == "MEMBER",
        catalog_version=snapshot.catalog_version,
        knowledge_release_id=snapshot.knowledge_release_id,
        context_revision=snapshot.revision,
        status=policy.status,
        reason_codes=[reason],
        summary=ResultSummary(
            housing_label=label(catalog.housing_types, context.housing_type),
            room_label=label(catalog.rooms, context.room_id),
            facility_label=label(catalog.facilities, context.facility_id),
            symptom_label=label(catalog.symptoms, context.symptom_id),
            description=context.description,
            answer_labels=answers,
        ),
        guidance=guidance,
        reference_examples=repair_examples(catalog, context, policy.status),
        checks=[],
        follow_up_questions=(
            list(
                dict.fromkeys(
                    "주택 유형을 확인해 주세요."
                    if field == "housingType"
                    else "선택 항목과 표시된 필수 질문을 확인해 주세요."
                    for field in policy.missing_fields
                )
            )
            if policy.status == GuidanceStatus.NEED_MORE_INFO
            else []
        ),
        contact_draft="보수 대상과 증상을 확인하고 필요한 절차를 안내해 주세요.",
        citations=[],
        disclaimer=DISCLAIMER,
        engine_version=ENGINE_VERSION,
        generated_at=now,
        retained_until=retained_until,
        is_current=True,
    )
    if (
        database is not None
        and settings.openai_enabled
        and snapshot.knowledge_release_id
        and policy.status == GuidanceStatus.NEED_CONFIRMATION
    ):
        # Only catalog-reviewed labels leave the server; no free-text personal data.
        query = " · ".join(
            [
                result.summary.housing_label,
                result.summary.room_label,
                result.summary.facility_label,
                result.summary.symptom_label,
                *answers,
            ]
        )
        try:
            vector = (await (provider or Embeddings(settings)).embed([query])).vectors[0]
            async with database.session() as session:
                found = await retrieve(
                    session,
                    snapshot.knowledge_release_id,
                    vector,
                    settings,
                    context,
                    catalog_version=snapshot.catalog_version,
                )
            result = result.model_copy(
                update={
                    "status": found.status,
                    "reason_codes": [found.reason],
                    "citations": found.citations(),
                    "reference_examples": repair_examples(catalog, context, found.status),
                    "guidance": found.guidance
                    + (
                        [INSUFFICIENT_INFORMATION_MESSAGE]
                        if found.status == "NEED_CONFIRMATION"
                        else []
                    ),
                }
            )
        except EmbeddingUnavailable:
            result = unavailable_result(result)
    return result


def unavailable_result(result):
    return result.model_copy(
        update={
            "status": GuidanceStatus.NEED_CONFIRMATION,
            "reason_codes": ["SOURCE_UNAVAILABLE"],
            "citations": [],
            "guidance": [INSUFFICIENT_INFORMATION_MESSAGE],
            "checks": [],
            "follow_up_questions": [],
        }
    )


async def result_dto(session, row: Result) -> GuidanceResult:
    result = GuidanceResult.model_validate(row.payload_json)
    consultation = (
        await session.get(Consultation, row.consultation_id) if row.consultation_id else None
    )
    current = bool(
        consultation
        and consultation.expires_at > datetime.now(UTC)
        and consultation.revision == result.context_revision
        and consultation.knowledge_set_id == result.knowledge_release_id
        and consultation.catalog_version == result.catalog_version
        and result.engine_version == ENGINE_VERSION
    )
    if current and result.knowledge_release_id:
        release = await session.get(KnowledgeSet, result.knowledge_release_id)
        current = bool(
            release
            and release.status == "PUBLISHED"
            and release.manifest_json.get("state") == "COMPLETE_VERIFIED"
        )
    if current and result.citations:
        current = await revalidate_citations(session, result, lock=False)
    return result.model_copy(update={"session_id": row.consultation_id, "is_current": current})
