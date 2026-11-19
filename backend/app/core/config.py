import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

QUICK_TUNNEL_ORIGIN = re.compile(
    r"https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.trycloudflare\.com"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "tunnel_test", "production"] = "development"
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://repair_guide:local-development-only@localhost:5432/repair_guide"
    )
    web_origins: list[str] = ["http://localhost:8080"]
    openai_enabled: bool = False
    openai_api_key: SecretStr = SecretStr("")
    openai_chat_model: str = ""
    openai_embedding_model: str = "text-embedding-3-large"
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
    chat_user_window_limit: int = Field(default=20, ge=1, le=100)
    chat_daily_limit: int = Field(default=100, ge=1, le=10000)
    chat_max_output_tokens: int = Field(default=4096, ge=512, le=8192)
    backup_key: SecretStr = SecretStr("")
    deletion_export_path: str = ""
    backup_scope: str = "repair-guide"

    @property
    def auth_cookie_name(self) -> str:
        return "__Host-repair_auth" if self.auth_cookie_secure else "repair_auth"

    @property
    def auth_cookie_secure(self) -> bool:
        return self.app_env in {"production", "tunnel_test"}

    def allows_write_origin(self, origin: str | None, fetch_site: str | None) -> bool:
        if origin in self.web_origins:
            return True
        # The tunnel rewrites Host to loopback, while the browser preserves Origin.
        # Keep credentialed CORS limited to web_origins, independent of this check.
        return (
            self.app_env == "tunnel_test"
            and fetch_site in {None, "same-origin"}
            and origin is not None
            and QUICK_TUNNEL_ORIGIN.fullmatch(origin) is not None
        )

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
        if bool(self.deletion_export_path) != bool(self.backup_key.get_secret_value()):
            raise ValueError("Deletion export requires both path and encryption key")
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
