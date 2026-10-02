from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel


class APIModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def normalize_datetimes(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("Datetime must include a timezone")
            return value.astimezone(UTC)
        return value
