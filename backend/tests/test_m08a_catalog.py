"""Review invariants and end-to-end API checks against the actual M08A catalog."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from test_auth_api import ORIGIN, BoundDatabase, signed_in

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import QuestionRecord, RequestRun, Result
from app.main import create_app
from app.schemas.catalog import CatalogDefinition
from app.schemas.contracts import Context, Session
from app.services.catalog import get_catalog, publish_catalog, require_latest_catalog
from app.services.guidance import evaluate_survey
from app.services.survey_policy import survey_policy

DIRECTORY = Path(__file__).resolve().parents[2] / "data/catalog/m08a-20261004"
DATA = json.loads((DIRECTORY / "catalog.json").read_text(encoding="utf-8"))
REVIEW = json.loads((DIRECTORY / "review.json").read_text(encoding="utf-8"))
CATALOG = CatalogDefinition.model_validate(DATA)


def context_for(symptom, facility=None, room=None, **changes):
    item = next(item for item in CATALOG.symptoms if item.id == symptom)
    facility = facility or item.facility_ids[0]
    facility_item = next(item for item in CATALOG.facilities if item.id == facility)
    return Context(
        housing_type="LH_CONSTRUCTION_RENTAL",
        room_id=room or facility_item.room_ids[0],
        facility_id=facility,
        symptom_id=symptom,
        **changes,
    )


def answer_unknowns(context):
    answers = dict(context.answers)
    for question in survey_policy(CATALOG, context).questions:
        answers.setdefault(question.question_id, "UNKNOWN")
    return context.model_copy(update={"answers": answers})


def test_review_covers_all_sources_and_every_user_facing_item():
    assert CATALOG.review.state == REVIEW["state"] == "COMPLETE_VERIFIED"
    assert (
        REVIEW["catalogSha256"]
        == hashlib.sha256((DIRECTORY / "catalog.json").read_bytes()).hexdigest()
    )
    expected = {"제6조의2", "별표 2", "별표 3", "별표 4", "부칙 제2025-58호 제2조"}
    expected.update(f"제{i}조" for i in range(7, 46))
    assert set(REVIEW["articleCoverage"]) == expected
    assert all(row["symptoms"] or row["questions"] for row in REVIEW["articleCoverage"].values())
    for group in ("rooms", "facilities", "symptoms"):
        assert {item["id"] for item in DATA[group]} == set(REVIEW[group])
        aliases = [alias for item in DATA[group] for alias in item["aliases"]]
        assert len(aliases) == len(set(aliases))
    assert {q.question_id for q in CATALOG.questions} == set(REVIEW["questions"])
    assert not REVIEW["policy"]["legalThresholdsUsedForDecisions"]
    assert not REVIEW["policy"]["operationalEvidenceAvailable"]


@pytest.mark.parametrize("symptom", [item.id for item in CATALOG.symptoms])
def test_every_real_symptom_has_reachable_questions_and_unknown_is_not_a_decision(symptom):
    item = next(item for item in CATALOG.symptoms if item.id == symptom)
    for facility in item.facility_ids:
        facility_item = next(item for item in CATALOG.facilities if item.id == facility)
        for room in facility_item.room_ids:
            context = context_for(symptom, facility, room)
            empty = survey_policy(CATALOG, context)
            assert empty.status == "NEED_MORE_INFO"
            assert len(empty.questions) >= 4
            assert all("UNKNOWN" in {o.value for o in q.options} for q in empty.questions)
            result = survey_policy(CATALOG, answer_unknowns(context))
            assert result.status == "NEED_CONFIRMATION"
            assert not result.missing_fields


@pytest.mark.parametrize("facility,room", [("waterproof", "bathroom"), ("unknown", "living")])
def test_real_leak_branch_disappears_and_clears_its_answer(facility, room):
    context = answer_unknowns(context_for("leak", facility, room))
    context.answers["detail-leak"] = "FLOWING"
    context.answers["leak-pattern"] = "RAIN"
    active = survey_policy(CATALOG, context)
    assert "leak-pattern" in {q.question_id for q in active.questions}
    changed = active.context.model_copy(deep=True)
    changed.answers["detail-leak"] = "TRACE"
    inactive = survey_policy(CATALOG, changed, previous=active.context)
    assert inactive.context.facility_id == facility and inactive.context.symptom_id == "leak"
    assert "leak-pattern" not in inactive.context.answers
    assert "leak-pattern" not in {q.question_id for q in inactive.questions}


def test_unsure_facility_does_not_accept_a_symptom_from_an_unrelated_room():
    with pytest.raises(AppError) as error:
        survey_policy(CATALOG, context_for("elevator-defect", "unknown", "living"))
    assert error.value.details == {"field": "symptomId"}


def test_actual_source_conditions_and_ambiguous_annex_never_become_approval():
    for answer in ("SINCE_20220804", "BEFORE_20220804", "UNKNOWN"):
        context = answer_unknowns(context_for("floor-layer"))
        context.answers["floor-approval"] = answer
        assert survey_policy(CATALOG, context).status == "NEED_CONFIRMATION"
    context = answer_unknowns(context_for("retaining-defect"))
    context.answers["detail-retaining-defect"] = "DAMAGE"
    assert survey_policy(CATALOG, context).status == "NEED_CONFIRMATION"
    assert not next(q for q in CATALOG.questions if q.question_id == "disaster-context").required


def test_every_real_question_option_and_branch_is_reachable_and_conservative():
    for question in CATALOG.questions:
        for symptom in question.symptom_ids:
            for option in question.options:
                context = context_for(symptom)
                for condition in question.conditions:
                    assert condition.path.startswith("answers.")
                    context.answers[condition.path[8:]] = condition.value
                context = answer_unknowns(context)
                context.answers[question.question_id] = option.value
                context = answer_unknowns(context)  # Newly revealed required follow-up.
                result = survey_policy(CATALOG, context)
                assert question.question_id in {q.question_id for q in result.questions}
                expected = (
                    "SAFETY_PRIORITY"
                    if option.value in question.interrupt_values
                    else "NEED_CONFIRMATION"
                )
                assert result.status == expected


@pytest.mark.parametrize("answer", ["BURN_SMOKE", "SPARK"])
def test_reviewed_lighting_risk_precedes_scope_and_missing_answers(answer):
    context = context_for("light-defect", answers={"detail-light-defect": answer})
    context.housing_type = "OTHER"
    result = survey_policy(CATALOG, context)
    assert result.status == "SAFETY_PRIORITY"
    assert result.interrupt_question_ids == ["detail-light-defect"]


@pytest.mark.parametrize("status", ["SAFETY_PRIORITY", "OUT_OF_SCOPE", "NEED_MORE_INFO"])
async def test_result_only_asks_for_missing_answers_when_more_information_is_the_priority(status):
    context = context_for("light-defect")
    if status == "SAFETY_PRIORITY":
        context.answers["detail-light-defect"] = "BURN_SMOKE"
    elif status == "OUT_OF_SCOPE":
        context.housing_type = "OTHER"
    else:
        context.housing_type = "UNKNOWN"
    now = datetime.now(UTC)
    session = Session(
        id=uuid4(),
        access_mode="GUEST",
        catalog_version=CATALOG.version,
        knowledge_release_id=None,
        revision=1,
        context=context,
        current_result_id=None,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    result = await evaluate_survey(session, CATALOG, Settings(_env_file=None))
    assert result.status == status
    if status == "NEED_MORE_INFO":
        assert result.follow_up_questions == [
            "주택 유형을 확인해 주세요.",
            "선택 항목과 표시된 필수 질문을 확인해 주세요.",
        ]
    else:
        assert result.follow_up_questions == []


@pytest.mark.integration
async def test_real_catalog_publication_replay_versions_and_rejection(pg_session):
    settings = Settings(_env_file=None)
    old = CATALOG.model_copy(update={"version": "test-m08a-previous"})
    first = await publish_catalog(pg_session, old, settings)
    current = await publish_catalog(pg_session, CATALOG, settings)
    replay = await publish_catalog(pg_session, CATALOG, settings)
    assert current.published_at == replay.published_at
    assert (await get_catalog(pg_session)).version == CATALOG.version
    assert (await get_catalog(pg_session, first.version)).symptoms == current.symptoms
    with pytest.raises(AppError) as caught:
        await require_latest_catalog(pg_session, first.version)
    assert caught.value.code == "CATALOG_UPDATED"


@pytest.mark.integration
@pytest.mark.parametrize("member", [False, True])
async def test_real_catalog_api_branch_save_history_delete_and_no_resurrection(pg_session, member):
    settings = Settings(_env_file=None)
    await publish_catalog(pg_session, CATALOG, settings)
    app = create_app(settings, BoundDatabase(pg_session))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        headers = {"Origin": ORIGIN, "Content-Type": "application/json"}
        if member:
            headers["X-CSRF-Token"] = (await signed_in(client)).json()["csrfToken"]
        created = await client.post(
            "/api/v1/sessions", json={"catalogVersion": CATALOG.version}, headers=headers
        )
        assert created.status_code == 201
        session = created.json()["session"]
        if not member:
            headers["Authorization"] = "Bearer " + created.json()["sessionToken"]
        sid = session["id"]
        context = answer_unknowns(context_for("leak", "waterproof", "bathroom"))
        context.answers.update({"detail-leak": "FLOWING", "leak-pattern": "RAIN"})
        saved = await client.put(
            f"/api/v1/sessions/{sid}/context",
            json={"expectedRevision": 0, "context": context.model_dump(mode="json", by_alias=True)},
            headers=headers,
        )
        assert saved.status_code == 200
        session = saved.json()
        questions = await client.get(f"/api/v1/sessions/{sid}/questions", headers=headers)
        assert "leak-pattern" in {q["questionId"] for q in questions.json()["questions"]}
        body = {"requestId": str(uuid4()), "expectedRevision": session["revision"]}
        evaluated = await client.post(
            f"/api/v1/sessions/{sid}/evaluations", json=body, headers=headers
        )
        assert evaluated.status_code == 201
        result = evaluated.json()
        assert result["status"] == "GUIDANCE_UNAVAILABLE"
        assert result["reasonCodes"] == ["SOURCE_UNAVAILABLE"]
        assert result["savedToHistory"] is member
        assert result["summary"]["symptomLabel"] == "물이 새거나 물 자국이 있어요"
        assert result["citations"] == []
        assert (await pg_session.scalar(select(QuestionRecord))).answers_json
        if member:
            history = await client.get("/api/v1/me/results", headers=headers)
            assert history.json()["items"][0]["id"] == result["id"]
            detail = await client.get(f"/api/v1/me/results/{result['id']}", headers=headers)
            assert detail.status_code == 200
            removed = await client.delete(f"/api/v1/me/results/{result['id']}", headers=headers)
            assert removed.status_code == 204
            assert (await client.get("/api/v1/me/results", headers=headers)).json()["items"] == []
            rerun = await client.post(
                f"/api/v1/sessions/{sid}/evaluations", json=body, headers=headers
            )
            assert rerun.status_code == 410 and rerun.json()["error"]["code"] == "REQUEST_DELETED"
            run = await pg_session.scalar(select(RequestRun))
            assert run.state == "DELETED" and run.response_json is None
        else:
            assert (await client.get("/api/v1/me/results", headers=headers)).status_code == 401
            removed = await client.delete(
                f"/api/v1/sessions/{sid}?eraseRecords=true", headers=headers
            )
            assert removed.status_code == 204
        assert await pg_session.scalar(select(Result)) is None
        assert await pg_session.scalar(select(QuestionRecord)) is None
