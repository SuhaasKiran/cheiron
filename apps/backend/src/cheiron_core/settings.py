"""Validated application settings loaded at the process boundary."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

_DEFAULT_ENVIRONMENT: Final = "development"
_DEFAULT_LOG_LEVEL: Final = "INFO"
_DEFAULT_LLM_MAX_CONCURRENT_REQUESTS: Final = 4
_MAX_LLM_MAX_CONCURRENT_REQUESTS: Final = 32
_DEFAULT_LLM_MAX_REQUESTS_PER_MINUTE: Final = 60
_MAX_LLM_MAX_REQUESTS_PER_MINUTE: Final = 600
_VALID_ENVIRONMENTS: Final = frozenset({"development", "test", "production"})
_VALID_LOG_LEVELS: Final = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})
_TRUE_VALUES: Final = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES: Final = frozenset({"", "0", "false", "no", "off"})
_PROJECT_ROOT: Final = Path(__file__).resolve().parents[4]
_DOTENV_PATH: Final = _PROJECT_ROOT / ".env"


class SettingsError(ValueError):
    """Raised when application settings are missing or invalid."""


@dataclass(frozen=True, slots=True)
class OpenAiLlmSettings:
    """Credentials and model selection for the optional LLM query planner."""

    api_key: str
    model: str
    max_concurrent_requests: int = _DEFAULT_LLM_MAX_CONCURRENT_REQUESTS
    max_requests_per_minute: int = _DEFAULT_LLM_MAX_REQUESTS_PER_MINUTE


@dataclass(frozen=True, slots=True)
class LangSmithTracingSettings:
    """Optional, explicitly configured tracing for LLM calls."""

    enabled: bool
    api_key: str | None = None
    endpoint: str | None = None
    project: str | None = None


@dataclass(frozen=True, slots=True)
class Settings:
    """The settings needed by the application foundation and optional LLM path."""

    environment: str
    log_level: str
    openai: OpenAiLlmSettings | None = None
    langsmith: LangSmithTracingSettings = LangSmithTracingSettings(enabled=False)


def load_settings(
    environment: Mapping[str, str] | None = None,
) -> Settings:
    """Load and validate settings from an environment-like mapping.

    Passing a mapping makes settings deterministic and easy to test. Production
    callers use the process environment by accepting the default argument.
    """

    if environment is None:
        load_dotenv(_DOTENV_PATH, override=False)
    values = os.environ if environment is None else environment
    app_environment = values.get("CHEIRON_ENV", _DEFAULT_ENVIRONMENT).strip().lower()
    if app_environment not in _VALID_ENVIRONMENTS:
        allowed = ", ".join(sorted(_VALID_ENVIRONMENTS))
        raise SettingsError(f"CHEIRON_ENV must be one of: {allowed}.")

    log_level = values.get("CHEIRON_LOG_LEVEL", _DEFAULT_LOG_LEVEL).strip().upper()
    if log_level not in _VALID_LOG_LEVELS:
        allowed = ", ".join(sorted(_VALID_LOG_LEVELS))
        raise SettingsError(f"CHEIRON_LOG_LEVEL must be one of: {allowed}.")

    openai_api_key = _optional_environment_value(values, "OPENAI_API_KEY")
    openai_model = _optional_environment_value(values, "OPENAI_MODEL")
    if (openai_api_key is None) != (openai_model is None):
        raise SettingsError(
            "OPENAI_API_KEY and OPENAI_MODEL must be set together to enable "
            "LLM query planning."
        )

    openai = (
        OpenAiLlmSettings(
            api_key=openai_api_key,
            model=openai_model,
            max_concurrent_requests=_load_llm_max_concurrent_requests(values),
            max_requests_per_minute=_load_llm_max_requests_per_minute(values),
        )
        if openai_api_key is not None and openai_model is not None
        else None
    )
    langsmith = _load_langsmith_settings(values)
    return Settings(
        environment=app_environment,
        log_level=log_level,
        openai=openai,
        langsmith=langsmith,
    )


def _optional_environment_value(
    environment: Mapping[str, str],
    name: str,
) -> str | None:
    """Return a stripped optional setting without leaking its value."""

    value = environment.get(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _load_llm_max_concurrent_requests(environment: Mapping[str, str]) -> int:
    """Load a finite per-process LLM planning limit from configuration."""

    raw_value = environment.get(
        "CHEIRON_LLM_MAX_CONCURRENT_REQUESTS",
        str(_DEFAULT_LLM_MAX_CONCURRENT_REQUESTS),
    )
    if not raw_value.isdecimal():
        raise SettingsError(
            "CHEIRON_LLM_MAX_CONCURRENT_REQUESTS must be a positive integer."
        )
    value = int(raw_value)
    if not 1 <= value <= _MAX_LLM_MAX_CONCURRENT_REQUESTS:
        raise SettingsError(
            "CHEIRON_LLM_MAX_CONCURRENT_REQUESTS must be between 1 and "
            f"{_MAX_LLM_MAX_CONCURRENT_REQUESTS}."
        )
    return value


def _load_llm_max_requests_per_minute(environment: Mapping[str, str]) -> int:
    """Load a finite per-process LLM request-rate limit from configuration."""

    raw_value = environment.get(
        "CHEIRON_LLM_MAX_REQUESTS_PER_MINUTE",
        str(_DEFAULT_LLM_MAX_REQUESTS_PER_MINUTE),
    )
    if not raw_value.isdecimal():
        raise SettingsError(
            "CHEIRON_LLM_MAX_REQUESTS_PER_MINUTE must be a positive integer."
        )
    value = int(raw_value)
    if not 1 <= value <= _MAX_LLM_MAX_REQUESTS_PER_MINUTE:
        raise SettingsError(
            "CHEIRON_LLM_MAX_REQUESTS_PER_MINUTE must be between 1 and "
            f"{_MAX_LLM_MAX_REQUESTS_PER_MINUTE}."
        )
    return value


def _load_langsmith_settings(
    environment: Mapping[str, str],
) -> LangSmithTracingSettings:
    """Validate the LangSmith settings used only at the tracing boundary."""

    enabled = _parse_boolean(environment.get("LANGSMITH_TRACING", ""))
    api_key = _optional_environment_value(environment, "LANGSMITH_API_KEY")
    if enabled and api_key is None:
        raise SettingsError(
            "LANGSMITH_API_KEY must be set when LANGSMITH_TRACING is enabled."
        )
    return LangSmithTracingSettings(
        enabled=enabled,
        api_key=api_key,
        endpoint=_optional_environment_value(environment, "LANGSMITH_ENDPOINT"),
        project=_optional_environment_value(environment, "LANGSMITH_PROJECT"),
    )


def _parse_boolean(value: object) -> bool:
    """Parse an environment boolean with clear failure behavior."""

    if not isinstance(value, str):
        raise SettingsError("LANGSMITH_TRACING must be a boolean value.")
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise SettingsError("LANGSMITH_TRACING must be a boolean value.")
