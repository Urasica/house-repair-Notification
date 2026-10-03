"""Catalog-only survey rules; applicable evidence and result storage belong to M06/M09."""

from dataclasses import dataclass

from app.core.errors import AppError
from app.domain.constants import (
    SUPPORTED_HOUSING_TYPES,
    ErrorCode,
    GuidanceStatus,
    HousingType,
)
from app.schemas.catalog import CatalogDefinition, Condition, Question
from app.schemas.contracts import Context, QuestionsResponse


@dataclass(frozen=True)
class SurveyPolicy:
    context: Context
    questions: list[Question]
    missing_fields: list[str]
    interrupt_question_ids: list[str]
    status: GuidanceStatus

    def questions_response(self, version: str, revision: int) -> QuestionsResponse:
        return QuestionsResponse(
            catalog_version=version, revision=revision, questions=self.questions
        )


def selection_error(field: str):
    raise AppError(
        ErrorCode.INVALID_SELECTION, "선택한 항목을 다시 확인해 주세요.", 422, {"field": field}
    )


def matches(condition: Condition, context: Context, answers: dict[str, str]) -> bool:
    fields = {
        "housingType": context.housing_type,
        "roomId": context.room_id,
        "facilityId": context.facility_id,
        "symptomId": context.symptom_id,
    }
    actual = (
        answers.get(condition.path[8:])
        if condition.path.startswith("answers.")
        else fields[condition.path]
    )
    return (
        actual == condition.value if condition.operator == "equals" else actual in condition.value
    )


def survey_policy(
    catalog: CatalogDefinition,
    context: Context,
    previous: Context | None = None,
) -> SurveyPolicy:
    """Validate known codes, clear invalid descendants, then evaluate branches in order."""
    canonical = context.model_copy(deep=True)
    rooms = {item.id for item in catalog.rooms}
    facilities = {item.id: item for item in catalog.facilities}
    symptoms = {item.id: item for item in catalog.symptoms}
    questions = {item.question_id: item for item in catalog.questions}
    housing = {item.id for item in catalog.housing_types}
    for field, value, allowed in (
        ("housingType", canonical.housing_type, housing),
        ("roomId", canonical.room_id, rooms),
        ("facilityId", canonical.facility_id, facilities),
        ("symptomId", canonical.symptom_id, symptoms),
    ):
        if value is not None and value not in allowed:
            selection_error(field)
    for question_id, answer in canonical.answers.items():
        question = questions.get(question_id)
        if question is None or answer not in {option.value for option in question.options}:
            raise AppError(
                ErrorCode.INVALID_ANSWER,
                "설문 답을 다시 확인해 주세요.",
                422,
                {"field": f"answers.{question_id}"},
            )

    room_changed = previous is not None and previous.room_id != canonical.room_id
    if (
        canonical.facility_id
        and canonical.room_id not in facilities[canonical.facility_id].room_ids
    ):
        if not room_changed:
            selection_error("facilityId")
        canonical.facility_id = None
    facility_changed = previous is not None and previous.facility_id != canonical.facility_id
    if (
        canonical.symptom_id
        and canonical.facility_id not in symptoms[canonical.symptom_id].facility_ids
    ):
        if not (room_changed or facility_changed):
            selection_error("symptomId")
        canonical.symptom_id = None

    visible: list[Question] = []
    answers: dict[str, str] = {}
    if canonical.room_id and canonical.facility_id and canonical.symptom_id:
        for question in sorted(catalog.questions, key=lambda item: (item.order, item.question_id)):
            if canonical.symptom_id not in question.symptom_ids:
                continue
            if not all(matches(condition, canonical, answers) for condition in question.conditions):
                continue
            visible.append(
                Question.model_validate(question.model_dump(include=set(Question.model_fields)))
            )
            if question.question_id in canonical.answers:
                answers[question.question_id] = canonical.answers[question.question_id]
    canonical.answers = answers
    missing = []
    for field, value in (
        ("housingType", canonical.housing_type),
        ("roomId", canonical.room_id),
        ("facilityId", canonical.facility_id),
        ("symptomId", canonical.symptom_id),
    ):
        if value is None or (field == "housingType" and value == HousingType.UNKNOWN):
            missing.append(field)
    missing.extend(
        f"answers.{question.question_id}"
        for question in visible
        if question.required and question.question_id not in answers
    )
    interrupts = [
        question.question_id
        for question in visible
        if answers.get(question.question_id) in question.interrupt_values
    ]
    if interrupts:
        status = GuidanceStatus.SAFETY_PRIORITY
    elif canonical.housing_type is not None and canonical.housing_type not in (
        *SUPPORTED_HOUSING_TYPES,
        HousingType.UNKNOWN,
    ):
        status = GuidanceStatus.OUT_OF_SCOPE
    elif missing:
        status = GuidanceStatus.NEED_MORE_INFO
    else:
        status = GuidanceStatus.NEED_CONFIRMATION
    return SurveyPolicy(canonical, visible, missing, interrupts, status)
