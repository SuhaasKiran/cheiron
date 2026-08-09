from __future__ import annotations

import cheiron_core.settings as settings_module
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


def test_load_settings_enables_llm_planning_when_openai_settings_are_complete() -> None:
    settings = load_settings(
        {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "gpt-5.4-nano",
        }
    )

    assert settings.openai is not None
    assert settings.openai.model == "gpt-5.4-nano"


def test_load_settings_rejects_partial_llm_configuration() -> None:
    with pytest.raises(SettingsError, match="OPENAI_API_KEY and OPENAI_MODEL"):
        load_settings({"OPENAI_API_KEY": "test-key"})


def test_load_settings_loads_the_root_dotenv_without_overriding_process_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dotenv_calls: list[tuple[object, bool]] = []

    def fake_load_dotenv(path: object, *, override: bool) -> bool:
        dotenv_calls.append((path, override))
        return True

    monkeypatch.setattr(settings_module, "load_dotenv", fake_load_dotenv)
    monkeypatch.setenv("CHEIRON_ENV", "test")
    monkeypatch.setenv("CHEIRON_LOG_LEVEL", "debug")

    settings = settings_module.load_settings()

    assert dotenv_calls == [(settings_module._DOTENV_PATH, False)]
    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"


def test_load_settings_reads_langsmith_tracing_configuration() -> None:
    settings = load_settings(
        {
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_API_KEY": "test-key",
            "LANGSMITH_ENDPOINT": "https://smith.example.test",
            "LANGSMITH_PROJECT": "cheiron-test",
        }
    )

    assert settings.langsmith.enabled is True
    assert settings.langsmith.endpoint == "https://smith.example.test"
    assert settings.langsmith.project == "cheiron-test"


def test_load_settings_rejects_enabled_langsmith_tracing_without_an_api_key() -> None:
    with pytest.raises(SettingsError, match="LANGSMITH_API_KEY"):
        load_settings({"LANGSMITH_TRACING": "true"})


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
