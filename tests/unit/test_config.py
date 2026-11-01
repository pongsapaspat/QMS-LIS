import pytest

from app.core.config import Settings


def test_settings_ignore_generic_debug_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("QMS_LIS_DEBUG", "true")

    settings = Settings(_env_file=None)

    assert settings.debug is True


def test_settings_reject_unknown_timezone() -> None:
    with pytest.raises(ValueError, match="valid IANA timezone"):
        Settings(_env_file=None, timezone="Not/A_Timezone")


def test_settings_reject_insecure_production_defaults() -> None:
    with pytest.raises(ValueError, match="enable_dev_admin_fallback"):
        Settings(_env_file=None, app_env="production", session_secret="production-secret")

    with pytest.raises(ValueError, match="session_secret"):
        Settings(_env_file=None, app_env="production", enable_dev_admin_fallback=False)
