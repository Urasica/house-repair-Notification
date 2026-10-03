"""Conservative survey results until M09 connects approved operational evidence."""

from calendar import monthrange
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.core.config import Settings
from app.db.models import Consultation, KnowledgeChunk, KnowledgeDocument, KnowledgeSet, Result
from app.domain.constants import DISCLAIMER, INSUFFICIENT_INFORMATION_MESSAGE, GuidanceStatus
from app.schemas.catalog import CatalogDefinition
from app.schemas.contracts import GuidanceResult, ResultSummary, Session
from app.services.survey_policy import survey_policy

ENGINE_VERSION = "survey-v1"


def add_years(value: datetime, years: int) -> datetime:
    year = value.year + years
    return value.replace(year=year, day=min(value.day, monthrange(year, value.month)[1]))


async def evaluate_survey(
    snapshot: Session, catalog: CatalogDefinition, settings: Settings
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
    return GuidanceResult(
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
        checks=[],
        follow_up_questions=[
            "주택 유형을 확인해 주세요."
            if field == "housingType"
            else "선택 항목과 표시된 필수 질문을 확인해 주세요."
            for field in dict.fromkeys(policy.missing_fields)
        ],
        contact_draft="보수 대상과 증상을 확인하고 필요한 절차를 안내해 주세요.",
        citations=[],
        disclaimer=DISCLAIMER,
        engine_version=ENGINE_VERSION,
        generated_at=now,
        retained_until=retained_until,
        is_current=True,
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
        now = datetime.now(UTC)
        ids = {citation.chunk_id for citation in result.citations}
        eligible = set(
            (
                await session.scalars(
                    select(KnowledgeChunk.id)
                    .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                    .join(KnowledgeSet, KnowledgeSet.id == KnowledgeDocument.knowledge_set_id)
                    .where(
                        KnowledgeChunk.id.in_(ids),
                        KnowledgeSet.id == result.knowledge_release_id,
                        KnowledgeSet.status == "PUBLISHED",
                        KnowledgeDocument.status == "APPROVED",
                        KnowledgeDocument.reviewed_at <= now,
                        KnowledgeDocument.review_until > now,
                        KnowledgeChunk.content_hash == KnowledgeChunk.embedded_content_hash,
                    )
                )
            ).all()
        )
        current = ids == eligible
    return result.model_copy(update={"session_id": row.consultation_id, "is_current": current})
