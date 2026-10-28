"""Editorial, hypothetical repair reviews; never evidence of eligibility or cost."""

from app.domain.constants import SUPPORTED_HOUSING_TYPES, GuidanceStatus
from app.services.retrieval import safe_text


def repair_examples(catalog, context, status):
    if status not in {GuidanceStatus.NEED_MORE_INFO, GuidanceStatus.NEED_CONFIRMATION}:
        return []
    if context.housing_type not in {*SUPPORTED_HOUSING_TYPES, None, "UNKNOWN"}:
        return []
    if context.facility_id in {"gas", "electric", "fire", "elevator", "railing", "retaining"}:
        return []
    symptom = next((s for s in catalog.symptoms if s.id == context.symptom_id), None)
    if symptom is None or symptom.id == "unknown":
        if context.facility_id not in {None, "unknown"}:
            return []
        return [
            "일반 예시 · 배관 연결 부근에서 물이 반복해서 떨어진다면, "
            "새는 곳과 원인을 확인한 뒤 연결 부위의 보수를 검토할 수 있어요.",
            "일반 예시 · 문이 틀에 걸려 잘 닫히지 않는다면, "
            "문과 틀의 상태를 확인한 뒤 위치 조정이나 부품 보수를 검토할 수 있어요.",
        ]
    if context.facility_id not in symptom.facility_ids:
        return []
    if symptom.id == "leak":
        if context.facility_id == "pipe":
            return [
                "배관 연결 부근에서 물방울이 반복해서 떨어지는 경우: "
                "담당자가 연결 부위와 부품 상태를 확인한 뒤 해당 부위의 보수를 검토할 수 있어요.",
                "배관에 손상이 있고 그 주변으로 물이 새는 경우: "
                "담당자가 손상 범위와 원인을 확인한 뒤 해당 부분의 보수나 교체를 검토할 수 있어요.",
            ]
        return [
            "비가 온 뒤 같은 곳에 물 자국이 반복해서 생기는 경우: "
            "담당자가 물이 들어오는 경로를 확인한 뒤 해당 부위의 보수를 검토할 수 있어요.",
            "물을 사용할 때 벽이나 바닥이 젖는 경우: "
            "담당자가 배관과 방수 부위 등 원인을 확인한 뒤 보수가 필요한 곳을 살펴볼 수 있어요.",
        ]
    if symptom.id == "opening-function":
        return [
            "문이나 창문이 틀에 걸려 잘 열리거나 닫히지 않는 경우: "
            "담당자가 틀과 움직이는 부품을 확인한 뒤 위치 조정이나 부품 보수를 검토할 수 있어요.",
            "손잡이나 잠금장치가 작동하지 않는 경우: "
            "담당자가 부품의 상태와 원인을 확인한 뒤 보수나 교체를 검토할 수 있어요.",
        ]
    question = next(
        (
            q
            for q in catalog.questions
            if q.question_id == f"detail-{symptom.id}" and not q.conditions
        ),
        None,
    )
    if question is None:
        return []
    return [
        f"‘{option.label}’와 같은 상태가 확인되는 경우: "
        "담당자가 원인과 사용에 미치는 영향을 살펴본 뒤 "
        "해당 부위의 보수 필요 여부를 검토할 수 있어요."
        for option in question.options
        if option.value != "UNKNOWN"
        and option.value not in question.interrupt_values
        and safe_text(option.label)
    ][:2]
