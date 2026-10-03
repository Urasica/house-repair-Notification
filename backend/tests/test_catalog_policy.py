import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.commands.catalog import MAX_FILE_BYTES, main, read_definition
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.constants import GuidanceStatus, HousingType
from app.schemas.catalog import CatalogDefinition
from app.schemas.contracts import Context
from app.services.catalog import publication_allowed
from app.services.survey_policy import survey_policy

FIXTURE = Path(__file__).parent / "fixtures/catalog.test.json"


def catalog_data(*, complete=True):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if complete:
        data["review"] = {
            "state": "COMPLETE_VERIFIED",
            "reviewer": "test-only",
            "reviewedAt": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        }
    data["rooms"].append({"id": "test-room2", "label": "시험용 다른 공간"})
    data["facilities"].append(
        {"id": "test-facility2", "label": "시험용 다른 시설", "roomIds": ["test-room2"]}
    )
    data["symptoms"].append(
        {"id": "test-symptom2", "label": "시험용 다른 항목", "facilityIds": ["test-facility2"]}
    )
    data["questions"][0]["options"].append({"value": "RISK", "label": "시험용 위험 선택"})
    data["questions"][0]["interruptValues"] = ["RISK"]
    data["questions"].append(
        {
            "questionId": "test-follow-up",
            "label": "시험용 분기 질문",
            "required": True,
            "options": [
                {"value": "YES", "label": "시험 값"},
                {"value": "UNKNOWN", "label": "모름"},
            ],
            "symptomIds": ["test-symptom"],
            "order": 1,
            "conditions": [
                {"path": "answers.test-question", "operator": "in", "value": ["TEST", "RISK"]},
                {"path": "housingType", "operator": "equals", "value": "LH_CONSTRUCTION_RENTAL"},
            ],
        }
    )
    data["questions"].append(
        {
            "questionId": "test-optional",
            "label": "시험용 선택 질문",
            "required": False,
            "options": [
                {"value": "YES", "label": "시험 값"},
                {"value": "UNKNOWN", "label": "모름"},
            ],
            "symptomIds": ["test-symptom"],
            "order": 2,
            "conditions": [
                {"path": "answers.test-follow-up", "operator": "equals", "value": "YES"},
                {"path": "roomId", "operator": "in", "value": ["test-room"]},
            ],
        }
    )
    return data


def context(**changes):
    return Context.model_validate(
        {
            "housingType": "LH_CONSTRUCTION_RENTAL",
            "roomId": "test-room",
            "facilityId": "test-facility",
            "symptomId": "test-symptom",
            **changes,
        }
    )


def test_complete_catalog_requires_five_housing_types_and_nonblank_labels():
    data = catalog_data()
    data["housingTypes"].pop()
    with pytest.raises(ValidationError, match="five housing"):
        CatalogDefinition.model_validate(data)
    data = catalog_data()
    data["rooms"][0]["label"] = "  "
    with pytest.raises(ValidationError):
        CatalogDefinition.model_validate(data)


@pytest.mark.parametrize(
    "mutation", ["option", "selection", "cycle", "future", "symptom", "duplicates", "identifier"]
)
def test_branch_validation_rejects_unusable_conditions(mutation):
    data = catalog_data()
    question = data["questions"][1]
    if mutation == "option":
        question["conditions"][0]["value"] = ["MISSING"]
    elif mutation == "selection":
        question["conditions"][1]["value"] = "MISSING"
    elif mutation == "cycle":
        question["conditions"][0]["path"] = "answers.test-follow-up"
    elif mutation == "future":
        question["conditions"][0]["path"] = "answers.test-optional"
    elif mutation == "symptom":
        question["symptomIds"] = ["test-symptom2"]
    elif mutation == "duplicates":
        question["conditions"][0]["value"] = ["TEST", "TEST"]
    else:
        question["questionId"] = "../private"
    with pytest.raises(ValidationError):
        CatalogDefinition.model_validate(data)


def test_branch_order_is_stable_and_conditions_are_and():
    data = catalog_data()
    data["questions"].reverse()
    catalog = CatalogDefinition.model_validate(data)
    result = survey_policy(
        catalog, context(answers={"test-question": "TEST", "test-follow-up": "YES"})
    )
    assert [question.question_id for question in result.questions] == [
        "test-question",
        "test-follow-up",
        "test-optional",
    ]
    assert result.missing_fields == [] and result.status == GuidanceStatus.NEED_CONFIRMATION
    response = result.questions_response(catalog.version, 3).model_dump(by_alias=True)
    assert response["revision"] == 3
    assert "conditions" not in response["questions"][0]
    assert "symptomIds" not in response["questions"][0]


def test_hidden_and_downstream_answers_are_removed_without_mutating_input():
    catalog = CatalogDefinition.model_validate(catalog_data())
    incoming = context(
        answers={"test-question": "UNKNOWN", "test-follow-up": "YES", "test-optional": "YES"}
    )
    result = survey_policy(catalog, incoming)
    assert result.context.answers == {"test-question": "UNKNOWN"}
    assert len(incoming.answers) == 3
    assert (
        result.status == GuidanceStatus.NEED_CONFIRMATION
    )  # Unknown is a valid answer, not omitted.


def test_missing_required_questions_only_include_visible_questions():
    catalog = CatalogDefinition.model_validate(catalog_data())
    result = survey_policy(catalog, context())
    assert result.missing_fields == ["answers.test-question"]
    result = survey_policy(catalog, context(answers={"test-question": "TEST"}))
    assert result.missing_fields == ["answers.test-follow-up"]


def test_parent_change_clears_incompatible_descendants_and_answers():
    catalog = CatalogDefinition.model_validate(catalog_data())
    previous = context(answers={"test-question": "TEST", "test-follow-up": "YES"})
    changed = previous.model_copy(update={"room_id": "test-room2"})
    result = survey_policy(catalog, changed, previous)
    assert result.context.facility_id is None and result.context.symptom_id is None
    assert result.context.answers == {} and result.questions == []
    changed = previous.model_copy(update={"facility_id": "test-facility2", "room_id": "test-room2"})
    assert survey_policy(catalog, changed, previous).context.symptom_id is None
    cleared = previous.model_copy(update={"room_id": None})
    assert survey_policy(catalog, cleared, previous).context.answers == {}


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"facilityId": "missing"}, "INVALID_SELECTION"),
        ({"facilityId": "test-facility2"}, "INVALID_SELECTION"),
        ({"answers": {"unknown-question": "UNKNOWN"}}, "INVALID_ANSWER"),
        ({"answers": {"test-follow-up": "FAKE"}}, "INVALID_ANSWER"),
    ],
)
def test_invalid_codes_and_inconsistent_selections_return_422(changes, code):
    catalog = CatalogDefinition.model_validate(catalog_data())
    with pytest.raises(AppError) as error:
        survey_policy(catalog, context(**changes))
    assert error.value.status == 422 and error.value.code == code


@pytest.mark.parametrize("housing", list(HousingType))
def test_housing_scope_unknown_and_safety_priority(housing):
    catalog = CatalogDefinition.model_validate(catalog_data())
    result = survey_policy(
        catalog, context(housingType=housing, answers={"test-question": "UNKNOWN"})
    )
    expected = GuidanceStatus.NEED_CONFIRMATION
    if housing in {HousingType.OTHER, HousingType.SOLD_OR_PRIVATE}:
        expected = GuidanceStatus.OUT_OF_SCOPE
    elif housing == HousingType.UNKNOWN:
        expected = GuidanceStatus.NEED_MORE_INFO
    assert result.status == expected
    risk = survey_policy(catalog, context(housingType=housing, answers={"test-question": "RISK"}))
    assert risk.status == GuidanceStatus.SAFETY_PRIORITY
    assert risk.interrupt_question_ids == ["test-question"]


def test_free_text_never_invents_a_hazard_or_repair_rule():
    catalog = CatalogDefinition.model_validate(catalog_data())
    result = survey_policy(
        catalog,
        context(
            description="가스, 화재, 누수: 시험용 자유 입력", answers={"test-question": "UNKNOWN"}
        ),
    )
    assert result.status == GuidanceStatus.NEED_CONFIRMATION and result.interrupt_question_ids == []


def test_publication_requires_review_and_rejects_test_namespace_in_public_database():
    settings = Settings(_env_file=None, app_env="development")
    with pytest.raises(AppError) as error:
        publication_allowed(
            CatalogDefinition.model_validate(catalog_data(complete=False)), settings
        )
    assert error.value.code == "CATALOG_NOT_READY"
    with pytest.raises(AppError) as error:
        publication_allowed(CatalogDefinition.model_validate(catalog_data()), settings)
    assert error.value.code == "VALIDATION_ERROR"
    unsafe_test = Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+psycopg://app:secret@localhost/development",
    )
    with pytest.raises(AppError):
        publication_allowed(CatalogDefinition.model_validate(catalog_data()), unsafe_test)


def test_future_review_cannot_be_published():
    data = catalog_data()
    data["review"]["reviewedAt"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    with pytest.raises(AppError) as error:
        publication_allowed(CatalogDefinition.model_validate(data), Settings(_env_file=None))
    assert error.value.status == 422


def test_command_validates_draft_without_database_and_hides_invalid_input(tmp_path, capsys):
    assert main(["validate", str(FIXTURE)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["reviewState"] == "DRAFT" and output["reviewComplete"] is False
    path = tmp_path / "invalid.json"
    path.write_text('{"password":"private-value"}', encoding="utf-8")
    assert main(["validate", str(path)]) == 1
    assert "private-value" not in capsys.readouterr().out
    path.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError):
        read_definition(path)
    path.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8-sig")
    assert read_definition(path).version == "test-only-v1"


def test_command_refuses_draft_publication_before_connecting_to_database(capsys, monkeypatch):
    from app.commands import catalog as command

    def forbidden_database(settings):
        raise AssertionError("Draft publication must not connect to the DB")

    monkeypatch.setattr(command, "Database", forbidden_database)
    assert main(["publish", str(FIXTURE)]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "CATALOG_NOT_READY"
