from __future__ import annotations

import pytest

from cheiron_core.settings import SettingsError, load_settings


def test_load_settings_uses_safe_defaults() -> None:
    settings = load_settings({})

    assert settings.environment == "development"
    assert settings.log_level == "INFO"


def test_load_settings_reads_supported_environment_overrides() -> None:
    settings = load_settings(
        {
            "CHEIRON_ENV": "production",
            "CHEIRON_LOG_LEVEL": "warning",
        }
    )

    assert settings.environment == "production"
    assert settings.log_level == "WARNING"


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ("staging", "CHEIRON_ENV"),
        ("", "CHEIRON_ENV"),
    ],
)
def test_load_settings_rejects_invalid_environment(
    environment: str, message: str
) -> None:
    with pytest.raises(SettingsError, match=message):
        load_settings({"CHEIRON_ENV": environment})


def test_load_settings_rejects_invalid_log_level() -> None:
    with pytest.raises(SettingsError, match="CHEIRON_LOG_LEVEL"):
        load_settings({"CHEIRON_LOG_LEVEL": "verbose"})
