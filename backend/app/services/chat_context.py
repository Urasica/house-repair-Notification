"""Chat confirmations and explicitly imported, catalog-validated survey context."""

import re

from app.domain.constants import SUPPORTED_HOUSING_TYPES, GuidanceStatus, HousingType
from app.services.retrieval import question_purpose
from app.services.survey_policy import survey_policy


def leak_observation(content):
    """Recognize observations as fixed labels without forwarding the user's wording."""
    if re.search(r"모르|같아|같은|일까요|인가요|경우|아니|새(?:지|지는)\s*않", content):
        return None
    observations = [
        (
            r"비(?:가)?\s*(?:안\s*올|오지\s*않을)\s*때도[^.!?\n]*"
            r"물\s*(?:자국|얼룩)(?:이|은|도)?\s*(?:보여|보였|있어|남아|남았|생겨|생겼)",
            "비가 오지 않을 때도 물자국이 보여요",
            "비가 오지 않을 때도 물자국이 보였다는 점을 관리사무소에 알려 주세요. "
            "물이 지금도 떨어지는지, 마른 자국만 보이는지도 함께 전달하면 도움이 돼요.",
        ),
        (
            r"비(?:가)?\s*올\s*때만\s*(?:그래|새|물[이가]?\s*(?:새|떨어))",
            "비가 올 때 새어요",
            "비가 올 때만 물이 보였다는 점을 관리사무소에 알려 주세요. "
            "비가 그친 뒤에도 물이 떨어졌는지 알고 계시면 함께 전달해 주세요.",
        ),
        (
            r"물(?:을)?\s*(?:쓸|사용할)\s*때만\s*(?:그래|새|물[이가]?\s*(?:새|떨어))",
            "물을 사용할 때 새어요",
            "물을 쓸 때만 물이 보였다는 점을 관리사무소에 알려 주세요. "
            "그때 어느 곳에서 물을 쓰고 있었는지도 기억나면 함께 전달해 주세요.",
        ),
    ]
    matches = [
        (label, action) for pattern, label, action in observations if re.search(pattern, content)
    ]
    return matches[0] if len(matches) == 1 else None


def confirmed_context(previous, content, catalog):
    context = previous.model_copy(deep=True)
    context.description = ""
    allowed = {q.question_id: {option.value for option in q.options} for q in catalog.questions}
    context.answers = {
        key: value for key, value in context.answers.items() if value in allowed.get(key, set())
    }
    if context.housing_type is None and content.strip().rstrip(".!? ") in {
        "모름",
        "몰라요",
        "모르겠어요",
        "주택 유형을 모르겠어요",
    }:
        context.housing_type = HousingType.UNKNOWN
    # Ambiguous/negative descriptions do not establish a new housing type.
    if not re.search(r"아니|아닌|모르|인지|않", content):
        housing = [
            (HousingType.SOLD_OR_PRIVATE, r"분양전환\s*(?:이후|후)|분양주택|민간주택"),
            (HousingType.LH_RENTAL_BEFORE_SALE, r"분양전환형\s*임대|분양전환\s*전"),
            (HousingType.LH_CONSTRUCTION_RENTAL, r"건설임대"),
        ]
        matches = {code for code, pattern in housing if re.search(pattern, content)}
        if len(matches) == 1:
            context.housing_type = matches.pop()

    def match(items):
        matches = []
        for item in items:
            terms = [item.label, *item.aliases]
            if catalog.version == "m08a-20261004-v2":
                if item.id == "pipe":
                    terms.append("배관")
                if item.id == "leak" and not re.search(r"새지|안\s*새|새는.*아니", content):
                    terms.extend(["물이 새", "물이 샙", "물샘"])
            lengths = [len(term) for term in terms if len(term) > 1 and term in content]
            if lengths and item.id != "unknown":
                matches.append((max(lengths), item.id))
        if not matches:
            return None
        longest = max(length for length, _ in matches)
        ids = {identifier for length, identifier in matches if length == longest}
        return next(iter(ids)) if len(ids) == 1 else None

    room = match(catalog.rooms)
    if room and room != context.room_id:
        if context.room_id is not None:
            context.facility_id, context.symptom_id = None, None
        context.room_id = room
    facilities = [
        item
        for item in catalog.facilities
        if not context.room_id or context.room_id in item.room_ids
    ]
    facility = match(facilities)
    if facility and facility != context.facility_id:
        if context.facility_id is not None or not any(
            item.id == context.symptom_id and facility in item.facility_ids
            for item in catalog.symptoms
        ):
            context.symptom_id = None
        context.facility_id = facility
    symptoms = [
        item
        for item in catalog.symptoms
        if not context.facility_id or context.facility_id in item.facility_ids
    ]
    symptom = match(symptoms)
    if symptom:
        context.symptom_id = symptom
    if any(
        getattr(context, field) != getattr(previous, field)
        for field in ("housing_type", "room_id", "facility_id", "symptom_id")
    ):
        context.answers = {}
    if context.room_id and context.facility_id and context.symptom_id:
        return survey_policy(catalog, context, previous).context
    context.answers = {}
    return context


def chat_policy(context, content):
    if context.housing_type in {HousingType.SOLD_OR_PRIVATE, HousingType.OTHER}:
        return (
            GuidanceStatus.OUT_OF_SCOPE,
            [],
            "이 서비스의 지원 주택 범위에 해당하지 않아요. "
            "관리사무소 또는 담당 기관에 직접 문의해 주세요.",
        )
    if question_purpose(content) == "LAW_EXPLANATION":
        return GuidanceStatus.NEED_CONFIRMATION, [], ""
    if context.housing_type == HousingType.UNKNOWN:
        return (
            GuidanceStatus.NEED_CONFIRMATION,
            [],
            "주택 유형을 확인하기 어려워 실제 보수 기준의 적용 여부를 안내하기 어려워요. "
            "관리사무소 또는 담당 기관에 주택 유형과 보수 절차를 직접 확인해 주세요.",
        )
    questions = []
    if context.housing_type not in SUPPORTED_HOUSING_TYPES:
        questions.append(
            "주택 유형을 채팅으로 알려 주세요. LH 건설임대 또는 분양전환 전 임대주택인가요? "
            "모르면 모른다고 답해 주세요."
        )
    if context.symptom_id in {None, "unknown"} and not re.search(
        r"제\s*\d+\s*조|별표\s*\d+", content
    ):
        questions.append(
            "어느 곳에서 어떤 문제가 보이나요? 예: 거실 천장에서 물이 떨어져요."
            if context.facility_id in {None, "unknown"}
            else "어떤 증상인지 알려 주세요. 예: 물이 새요, 문이 잠기지 않아요."
        )
    if questions:
        return (
            GuidanceStatus.NEED_MORE_INFO,
            questions,
            "답변에 필요한 내용을 이 대화에서 확인할게요.",
        )
    return GuidanceStatus.NEED_CONFIRMATION, [], ""
