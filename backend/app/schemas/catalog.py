import re
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from app.domain.constants import SUPPORTED_HOUSING_TYPES, HousingType
from app.schemas.base import APIModel

Identifier = str


class CatalogItem(APIModel):
    id: Identifier = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")
    label: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list)


class HousingItem(APIModel):
    id: HousingType
    label: str = Field(min_length=1, max_length=120)
    supported: bool

    @model_validator(mode="after")
    def supported_matches_scope(self):
        if self.supported != (self.id in SUPPORTED_HOUSING_TYPES):
            raise ValueError("Housing support must match service scope")
        return self


class FacilityItem(CatalogItem):
    room_ids: list[str] = Field(min_length=1)


class SymptomItem(CatalogItem):
    facility_ids: list[str] = Field(min_length=1)


class Option(APIModel):
    value: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=200)


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
        return self


class Question(APIModel):
    question_id: str
    type: Literal["singleChoice"] = "singleChoice"
    label: str = Field(min_length=1, max_length=500)
    required: bool
    options: list[Option] = Field(min_length=2)
    interrupt_values: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_options(self):
        values = [option.value for option in self.options]
        if len(values) != len(set(values)):
            raise ValueError("Duplicate option values")
        if not set(self.interrupt_values) <= set(values):
            raise ValueError("Interrupt values must be defined options")
        return self


class CatalogQuestion(Question):
    symptom_ids: list[str] = Field(min_length=1)
    conditions: list[Condition] = Field(default_factory=list)
    order: int = Field(ge=0)


class Catalog(APIModel):
    version: str = Field(min_length=1, max_length=80)
    published_at: AwareDatetime
    housing_types: list[HousingItem]
    rooms: list[CatalogItem]
    facilities: list[FacilityItem]
    symptoms: list[SymptomItem]


class CatalogReview(APIModel):
    state: Literal["DRAFT", "COMPLETE_VERIFIED"] = "DRAFT"
    reviewer: str | None = None
    reviewed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def completed_review(self):
        if self.state == "COMPLETE_VERIFIED" and (not self.reviewer or self.reviewed_at is None):
            raise ValueError("Completed catalog requires reviewer and timestamp")
        return self


class CatalogDefinition(APIModel):
    version: str = Field(min_length=1, max_length=80)
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
        for facility in self.facilities:
            if not set(facility.room_ids) <= room_ids:
                raise ValueError("Facility refers to an unknown room")
        for symptom in self.symptoms:
            if not set(symptom.facility_ids) <= facility_ids:
                raise ValueError("Symptom refers to an unknown facility")
        for question in self.questions:
            if not set(question.symptom_ids) <= symptom_ids:
                raise ValueError("Question refers to an unknown symptom")
            for condition in question.conditions:
                if condition.path.startswith("answers."):
                    if condition.path.split(".", 1)[1] not in question_ids:
                        raise ValueError("Condition refers to an unknown question")
        if self.review.state == "COMPLETE_VERIFIED" and any(not group for group in groups):
            raise ValueError("Completed catalog cannot have empty item groups")
        return self
