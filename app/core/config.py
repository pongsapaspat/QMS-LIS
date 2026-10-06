
from functools import lru_cache

from pydantic import Field
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
    allow_partial_release: bool = True
    enable_dev_admin_fallback: bool = True
    log_level: str = "INFO"
    log_pii: bool = Field(default=False, description="PII must stay out of application logs.")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="QMS_LIS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
