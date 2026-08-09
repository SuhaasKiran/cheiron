from __future__ import annotations

import cheiron_core.settings as settings_module
import pytest
from cheiron_core.settings import SettingsError, load_settings


def test_load_settings_uses_safe_defaults() -> None:
    settings = load_settings({})

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.retrieval_max_studies == 1_000


def test_load_settings_reads_the_retrieval_record_limit() -> None:
    settings = load_settings({"CHEIRON_RETRIEVAL_MAX_STUDIES": "2000"})

    assert settings.retrieval_max_studies == 2_000


@pytest.mark.parametrize("value", ("0", "10001", "many"))
def test_load_settings_rejects_an_invalid_retrieval_record_limit(value: str) -> None:
    with pytest.raises(SettingsError, match="CHEIRON_RETRIEVAL_MAX_STUDIES"):
        load_settings({"CHEIRON_RETRIEVAL_MAX_STUDIES": value})


def test_load_settings_reads_supported_environment_overrides() -> None:
    settings = load_settings(
        {
            "CHEIRON_ENV": "production",
            "CHEIRON_LOG_LEVEL": "warning",
        }
    )

    assert settings.environment == "production"
    assert settings.log_level == "WARNING"


def test_load_settings_reads_public_http_security_configuration() -> None:
    settings = load_settings(
        {
            "CHEIRON_CORS_ALLOWED_ORIGINS": (
                "https://app.example.test,http://localhost:3000"
            ),
            "CHEIRON_API_KEYS": "test-api-key,other-test-api-key",
            "CHEIRON_HTTP_RATE_LIMIT_REQUESTS": "20",
            "CHEIRON_HTTP_RATE_LIMIT_WINDOW_SECONDS": "120",
        }
    )

    assert settings.http_security.cors_allowed_origins == (
        "https://app.example.test",
        "http://localhost:3000",
    )
    assert settings.http_security.api_keys == {
        "test-api-key",
        "other-test-api-key",
    }
    assert settings.http_security.rate_limit_requests == 20
    assert settings.http_security.rate_limit_window_seconds == 120


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CHEIRON_CORS_ALLOWED_ORIGINS", "https://app.example.test/path"),
        ("CHEIRON_HTTP_RATE_LIMIT_REQUESTS", "0"),
        ("CHEIRON_HTTP_RATE_LIMIT_WINDOW_SECONDS", "many"),
    ],
)
def test_load_settings_rejects_invalid_public_http_security_configuration(
    name: str,
    value: str,
) -> None:
    with pytest.raises(SettingsError, match=name):
        load_settings({name: value})


def test_load_settings_enables_llm_planning_when_openai_settings_are_complete() -> None:
    settings = load_settings(
        {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "gpt-5.4-nano",
        }
    )

    assert settings.openai is not None
    assert settings.openai.model == "gpt-5.4-nano"
    assert settings.openai.max_concurrent_requests == 4


def test_load_settings_reads_the_llm_concurrency_limit() -> None:
    settings = load_settings(
        {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "gpt-5.4-nano",
            "CHEIRON_LLM_MAX_CONCURRENT_REQUESTS": "2",
        }
    )

    assert settings.openai is not None
    assert settings.openai.max_concurrent_requests == 2


def test_load_settings_reads_the_llm_request_rate_limit() -> None:
    settings = load_settings(
        {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "gpt-5.4-nano",
            "CHEIRON_LLM_MAX_REQUESTS_PER_MINUTE": "30",
        }
    )

    assert settings.openai is not None
    assert settings.openai.max_requests_per_minute == 30


@pytest.mark.parametrize("value", ("0", "33", "two"))
def test_load_settings_rejects_an_invalid_llm_concurrency_limit(value: str) -> None:
    with pytest.raises(SettingsError, match="CHEIRON_LLM_MAX_CONCURRENT_REQUESTS"):
        load_settings(
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MODEL": "gpt-5.4-nano",
                "CHEIRON_LLM_MAX_CONCURRENT_REQUESTS": value,
            }
        )


@pytest.mark.parametrize("value", ("0", "601", "many"))
def test_load_settings_rejects_an_invalid_llm_request_rate_limit(value: str) -> None:
    with pytest.raises(SettingsError, match="CHEIRON_LLM_MAX_REQUESTS_PER_MINUTE"):
        load_settings(
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MODEL": "gpt-5.4-nano",
                "CHEIRON_LLM_MAX_REQUESTS_PER_MINUTE": value,
            }
        )


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
