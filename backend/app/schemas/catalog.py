import re
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.domain.constants import SUPPORTED_HOUSING_TYPES, HousingType
from app.schemas.base import APIModel

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")]
Version = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class CatalogItem(APIModel):
    id: Identifier
    label: Label
    aliases: list[Label] = Field(default_factory=list, max_length=20)


class HousingItem(APIModel):
    id: HousingType
    label: Label
    supported: bool

    @model_validator(mode="after")
    def supported_matches_scope(self):
        if self.supported != (self.id in SUPPORTED_HOUSING_TYPES):
            raise ValueError("Housing support must match service scope")
        return self


class FacilityItem(CatalogItem):
    room_ids: list[Identifier] = Field(min_length=1)


class SymptomItem(CatalogItem):
    facility_ids: list[Identifier] = Field(min_length=1)


class Option(APIModel):
    value: Identifier
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Condition(APIModel):
    path: str
    operator: Literal["equals", "in"]
    value: str | list[str]

    @model_validator(mode="after")
    def allowed_condition(self):
        if self.path not in {"housingType", "roomId", "facilityId", "symptomId"}:
            if not re.fullmatch(r"answers\.[a-zA-Z0-9_-]+", self.path):
                raise ValueError("Unsupported condition path")
        if self.operator == "equals" and not isinstance(self.value, str):
            raise ValueError("equals requires a string")
        if self.operator == "in" and (not isinstance(self.value, list) or not self.value):
            raise ValueError("in requires a nonempty list")
        values = [self.value] if isinstance(self.value, str) else self.value
        if any(not value.strip() for value in values) or len(values) != len(set(values)):
            raise ValueError("Condition values must be nonblank and unique")
        return self


class Question(APIModel):
    question_id: Identifier
    type: Literal["singleChoice"] = "singleChoice"
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    required: bool
    options: list[Option] = Field(min_length=2)
    interrupt_values: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_options(self):
        values = [option.value for option in self.options]
        if len(values) != len(set(values)):
            raise ValueError("Duplicate option values")
        if not set(self.interrupt_values) <= set(values):
            raise ValueError("Interrupt values must be defined options")
        if len(self.interrupt_values) != len(set(self.interrupt_values)):
            raise ValueError("Duplicate interrupt values")
        return self


class CatalogQuestion(Question):
    symptom_ids: list[Identifier] = Field(min_length=1)
    conditions: list[Condition] = Field(default_factory=list)
    order: int = Field(ge=0)


class Catalog(APIModel):
    version: Version
    published_at: AwareDatetime
    housing_types: list[HousingItem]
    rooms: list[CatalogItem]
    facilities: list[FacilityItem]
    symptoms: list[SymptomItem]


class CatalogReview(APIModel):
    state: Literal["DRAFT", "COMPLETE_VERIFIED"] = "DRAFT"
    reviewer: Label | None = None
    reviewed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def completed_review(self):
        if self.state == "COMPLETE_VERIFIED" and (not self.reviewer or self.reviewed_at is None):
            raise ValueError("Completed catalog requires reviewer and timestamp")
        return self


class CatalogDefinition(APIModel):
    version: Version
    review: CatalogReview
    housing_types: list[HousingItem]
    rooms: list[CatalogItem]
    facilities: list[FacilityItem]
    symptoms: list[SymptomItem]
    questions: list[CatalogQuestion]

    @model_validator(mode="after")
    def validate_references(self):
        groups = [
            [item.id for item in self.housing_types],
            [item.id for item in self.rooms],
            [item.id for item in self.facilities],
            [item.id for item in self.symptoms],
            [item.question_id for item in self.questions],
        ]
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError("Duplicate catalog IDs")
        room_ids, facility_ids, symptom_ids, question_ids = map(set, groups[1:])
        questions = {question.question_id: question for question in self.questions}
        condition_values = {
            "housingType": set(groups[0]),
            "roomId": room_ids,
            "facilityId": facility_ids,
            "symptomId": symptom_ids,
        }
        for item in (*self.rooms, *self.facilities, *self.symptoms):
            if len(item.aliases) != len(set(item.aliases)):
                raise ValueError("Duplicate aliases within an item")
        for facility in self.facilities:
            if len(facility.room_ids) != len(set(facility.room_ids)):
                raise ValueError("Duplicate facility room references")
            if not set(facility.room_ids) <= room_ids:
                raise ValueError("Facility refers to an unknown room")
        for symptom in self.symptoms:
            if len(symptom.facility_ids) != len(set(symptom.facility_ids)):
                raise ValueError("Duplicate symptom facility references")
            if not set(symptom.facility_ids) <= facility_ids:
                raise ValueError("Symptom refers to an unknown facility")
        for question in self.questions:
            if len(question.symptom_ids) != len(set(question.symptom_ids)):
                raise ValueError("Duplicate question symptom references")
            if not set(question.symptom_ids) <= symptom_ids:
                raise ValueError("Question refers to an unknown symptom")
            for condition in question.conditions:
                if condition.path.startswith("answers."):
                    parent_id = condition.path.split(".", 1)[1]
                    if parent_id not in question_ids:
                        raise ValueError("Condition refers to an unknown question")
                    parent = questions[parent_id]
                    if (parent.order, parent.question_id) >= (question.order, question.question_id):
                        raise ValueError("Answer conditions must refer to an earlier question")
                    if not set(question.symptom_ids) <= set(parent.symptom_ids):
                        raise ValueError("Answer condition parent must cover the same symptoms")
                    allowed = {option.value for option in parent.options}
                else:
                    allowed = condition_values[condition.path]
                values = (
                    {condition.value} if isinstance(condition.value, str) else set(condition.value)
                )
                if not values <= allowed:
                    raise ValueError("Condition refers to an unknown selection or option")
        if self.review.state == "COMPLETE_VERIFIED" and any(not group for group in groups):
            raise ValueError("Completed catalog cannot have empty item groups")
        if self.review.state == "COMPLETE_VERIFIED" and set(groups[0]) != set(HousingType):
            raise ValueError("Completed catalog must include all five housing types")
        return self
