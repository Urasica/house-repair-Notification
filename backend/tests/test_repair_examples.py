from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from test_m08a_catalog import CATALOG, answer_unknowns, context_for

from app.core.config import Settings
from app.schemas.contracts import Context, GuidanceResult, Session
from app.services.chat import chat_response
from app.services.chat_context import confirmed_context
from app.services.guidance import evaluate_survey
from app.services.repair_examples import repair_examples


def snapshot(context):
    now = datetime.now(UTC)
    return Session(
        id=uuid4(),
        access_mode="MEMBER",
        catalog_version=CATALOG.version,
        knowledge_release_id=None,
        revision=1,
        context=context,
        current_result_id=None,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )


async def test_all_unknown_survey_answers_keep_inquiry_and_add_two_pipe_examples():
    context = answer_unknowns(context_for("leak", "pipe", "kitchen"))
    result = await evaluate_survey(snapshot(context), CATALOG, Settings(_env_file=None))
    assert result.status == "NEED_CONFIRMATION"
    assert "관리사무소" in " ".join(result.guidance)
    assert len(result.reference_examples) == 2
    assert all("배관" in example for example in result.reference_examples)
    assert any("보수나 교체를 검토" in example for example in result.reference_examples)
    assert not result.citations
    old_payload = result.model_dump(exclude={"reference_examples"})
    assert GuidanceResult.model_validate(old_payload).reference_examples == []


@pytest.mark.parametrize("enabled", [False, True])
async def test_completed_door_survey_explains_why_search_is_unavailable(enabled):
    context = answer_unknowns(context_for("opening-function", "door", "entrance"))
    context.answers.update({"detail-opening-function": "CLOSE", "immediate-danger": "NO"})
    settings = Settings(
        _env_file=None,
        openai_enabled=enabled,
        openai_api_key="test-only",
        openai_chat_model="test-only",
    )
    result = await evaluate_survey(snapshot(context), CATALOG, settings)
    assert result.status == "GUIDANCE_UNAVAILABLE"
    assert result.reason_codes == ["SOURCE_UNAVAILABLE"]
    assert ("기준 자료가 없어" if enabled else "안내 서비스 연결이 꺼져") in result.guidance[0]
    assert not result.citations and not result.reference_examples


@pytest.mark.parametrize("status", ["SAFETY_PRIORITY", "OUT_OF_SCOPE", "GUIDANCE_AVAILABLE"])
def test_examples_never_compete_with_safety_scope_or_applicable_guidance(status):
    assert repair_examples(CATALOG, context_for("leak", "pipe"), status) == []


@pytest.mark.parametrize("housing", ["OTHER", "SOLD_OR_PRIVATE"])
def test_unsupported_housing_never_gets_repair_examples_even_with_missing_inputs(housing):
    context = context_for("leak", "pipe").model_copy(update={"housing_type": housing})
    assert repair_examples(CATALOG, context, "NEED_MORE_INFO") == []


def test_unknown_context_gets_explicit_general_examples_and_no_unrelated_facility_match():
    assert all(
        example.startswith("일반 예시")
        for example in repair_examples(CATALOG, Context(), "NEED_MORE_INFO")
    )
    context = context_for("leak", "pipe")
    context.facility_id = "door"
    assert repair_examples(CATALOG, context, "NEED_MORE_INFO") == []
    context.symptom_id = "unknown"
    assert repair_examples(CATALOG, context, "NEED_MORE_INFO") == []


def test_other_symptoms_use_reviewed_options_and_never_present_interrupt_or_unknown_options():
    examples = repair_examples(CATALOG, context_for("wallpaper-defect"), "NEED_CONFIRMATION")
    assert len(examples) == 2
    question = next(q for q in CATALOG.questions if q.question_id == "detail-wallpaper-defect")
    assert all(
        option.label in example
        for option, example in zip(question.options[:2], examples, strict=True)
    )
    for symptom in CATALOG.symptoms:
        context = context_for(symptom.id)
        for facility in symptom.facility_ids:
            context.facility_id = facility
            values = repair_examples(CATALOG, context, "NEED_CONFIRMATION")
            assert len(values) <= 2
            assert all("모르겠어요" not in value for value in values)
            if facility in {"gas", "electric", "fire", "elevator", "railing", "retaining"}:
                assert values == []


@pytest.mark.parametrize(
    ("context", "content", "status", "count"),
    [
        (Context(), "잘 모르겠어요", "NEED_MORE_INFO", 2),
        (Context(housing_type="UNKNOWN"), "모르겠어요", "NEED_CONFIRMATION", 2),
        (context_for("leak", "pipe"), "어떻게 하나요?", "GUIDANCE_UNAVAILABLE", 0),
        (context_for("leak", "pipe"), "가스 냄새가 나요", "SAFETY_PRIORITY", 0),
        (Context(housing_type="OTHER"), "잘 모르겠어요", "OUT_OF_SCOPE", 0),
        (context_for("leak", "pipe"), "제10조 내용 설명", "GUIDANCE_UNAVAILABLE", 0),
    ],
)
async def test_chat_clarification_fallback_and_safety_examples(context, content, status, count):
    result = await chat_response(
        snapshot(context), CATALOG, Settings(_env_file=None), content, uuid4(), [], database=None
    )
    assert result.status == status
    assert len(result.reference_examples) == count
    assert not result.assistant_message.citations
    if status == "GUIDANCE_UNAVAILABLE":
        assert "안내 서비스 연결이 꺼져" in result.assistant_message.content


def test_examples_do_not_repeat_contact_details_from_catalog_options():
    catalog = CATALOG.model_copy(deep=True)
    question = next(q for q in catalog.questions if q.question_id == "detail-wallpaper-defect")
    for option in question.options:
        option.label = "010-1234-5678 또는 private@example.com"
    assert repair_examples(catalog, context_for("wallpaper-defect"), "NEED_CONFIRMATION") == []


async def test_reviewed_survey_hazard_clears_examples_before_chat_returns():
    context = context_for("leak", "pipe", answers={"immediate-danger": "YES"})
    result = await evaluate_survey(snapshot(context), CATALOG, Settings(_env_file=None))
    assert result.status == "SAFETY_PRIORITY" and not result.reference_examples
    chat = await chat_response(
        snapshot(context),
        CATALOG,
        Settings(_env_file=None),
        "도와주세요",
        uuid4(),
        [],
        database=None,
    )
    assert chat.status == "SAFETY_PRIORITY" and not chat.reference_examples


@pytest.mark.parametrize(
    ("content", "status"),
    [
        ("LH 건설임대 거실 천장에서 물이 떨어지고 있어요.", "GUIDANCE_UNAVAILABLE"),
        ("LH 건설임대 현관문이 경첩에서 빠져서 곧 떨어질 것 같아요.", "SAFETY_PRIORITY"),
        ("욕실 타일이 떨어지려고 해요.", "SAFETY_PRIORITY"),
        ("창틀은 멀쩡한데 물방울이 떨어져요.", "NEED_MORE_INFO"),
        ("분양주택 콘센트에서 연기가 나요.", "SAFETY_PRIORITY"),
    ],
)
async def test_chat_distinguishes_falling_fixtures_from_dripping_water(content, status):
    context = confirmed_context(Context(), content, CATALOG)
    response = await chat_response(
        snapshot(context), CATALOG, Settings(_env_file=None), content, uuid4(), [], database=None
    )
    assert response.status == status
    if status == "SAFETY_PRIORITY":
        assert not response.follow_up_questions and not response.reference_examples
    if status == "GUIDANCE_UNAVAILABLE":
        assert context.symptom_id == "leak"
