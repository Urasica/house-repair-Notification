from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://repair_guide:local-development-only@localhost:5432/repair_guide"
    )
    web_origins: list[str] = ["http://localhost:8080"]
    openai_enabled: bool = False
    openai_api_key: SecretStr = SecretStr("")
    openai_chat_model: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=1536, le=1536)
    session_ttl_hours: int = Field(default=24, ge=1, le=24)
    auth_ttl_hours: int = Field(default=24, ge=1, le=24)
    question_retention_years: int = Field(default=5, ge=3, le=5)
    member_result_retention_years: int = Field(default=5, ge=3, le=5)
    raw_record_grace_days: int = Field(default=7, ge=0, le=7)
    log_retention_days: int = Field(default=14, ge=1, le=14)
    backup_retention_days: int = Field(default=14, ge=1, le=14)
    deletion_log_retention_days: int = Field(default=15, ge=15)
    survey_timeout_seconds: int = Field(default=10, ge=1, le=10)
    chat_timeout_seconds: int = Field(default=25, ge=1, le=25)

    @model_validator(mode="after")
    def validate_runtime(self):
        url = make_url(self.database_url.get_secret_value())
        if url.drivername != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must use postgresql+psycopg")
        if self.openai_enabled and (
            not self.openai_api_key.get_secret_value() or not self.openai_chat_model
        ):
            raise ValueError("OpenAI enabled requires a server key and chat model")
        if self.deletion_log_retention_days < self.backup_retention_days + 1:
            raise ValueError("Deletion markers must outlive backups")
        if self.app_env == "production":
            if not url.password or url.password == "local-development-only":
                raise ValueError("Production requires a non-development database password")
            if not self.web_origins or any(
                not origin.startswith("https://") for origin in self.web_origins
            ):
                raise ValueError("Production requires HTTPS web origins")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
