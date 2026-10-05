import pytest

from app.core.config import Settings


def test_settings_ignore_generic_debug_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("QMS_LIS_DEBUG", "true")

    settings = Settings(_env_file=None)

    assert settings.debug is True
