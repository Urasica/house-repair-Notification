from pydantic import EmailStr, Field, SecretStr, field_validator

from app.schemas.base import APIModel


class Credentials(APIModel):
    email: EmailStr = Field(max_length=254)
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().casefold() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value):
        if not value.get_secret_value().strip():
            raise ValueError("Password cannot be blank")
        return value
