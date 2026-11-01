from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "QMS-LIS"
    app_env: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    timezone: str = "Asia/Bangkok"
    default_branch_id: int = 1
    database_url: str = "sqlite:///./qms_lis_dev.sqlite3"
    enforce_four_eyes_check: bool = False
    allow_admin_four_eyes_bypass: bool = False
    allow_partial_release: bool = True
    enable_dev_admin_fallback: bool = True
    session_secret: str = "change-this-development-secret"
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: str | None = None
    log_level: str = "INFO"
    log_pii: bool = Field(default=False, description="PII must stay out of application logs.")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="QMS_LIS_",
        extra="ignore",
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone name") from exc
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
