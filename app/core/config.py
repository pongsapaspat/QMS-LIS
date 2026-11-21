from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "QMS-LIS"
    report_lab_name: str = "QMS-LIS"
    report_lab_address: str = ""
    report_lab_phone: str = ""
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
    session_idle_timeout_seconds: int = 1800
    max_active_sessions: int = Field(default=12, ge=1)
    session_max_age_seconds: int = 28800
    session_https_only: bool = False
    login_failure_limit: int = 5
    login_failure_window_seconds: int = 900
    account_lockout_seconds: int = 900
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

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.app_env == "production":
            if self.enable_dev_admin_fallback:
                raise ValueError("enable_dev_admin_fallback must be false in production")
            if self.session_secret == "change-this-development-secret":
                raise ValueError("session_secret must be changed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
