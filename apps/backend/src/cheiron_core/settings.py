"""Validated application settings loaded at the process boundary."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

_DEFAULT_ENVIRONMENT: Final = "development"
_DEFAULT_LOG_LEVEL: Final = "INFO"
_VALID_ENVIRONMENTS: Final = frozenset({"development", "test", "production"})
_VALID_LOG_LEVELS: Final = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})


class SettingsError(ValueError):
    """Raised when application settings are missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """The small set of settings needed by the application foundation."""

    environment: str
    log_level: str


def load_settings(
    environment: Mapping[str, str] | None = None,
) -> Settings:
    """Load and validate settings from an environment-like mapping.

    Passing a mapping makes settings deterministic and easy to test. Production
    callers use the process environment by accepting the default argument.
    """

    values = os.environ if environment is None else environment
    app_environment = values.get("CHEIRON_ENV", _DEFAULT_ENVIRONMENT).strip().lower()
    if app_environment not in _VALID_ENVIRONMENTS:
        allowed = ", ".join(sorted(_VALID_ENVIRONMENTS))
        raise SettingsError(f"CHEIRON_ENV must be one of: {allowed}.")

    log_level = values.get("CHEIRON_LOG_LEVEL", _DEFAULT_LOG_LEVEL).strip().upper()
    if log_level not in _VALID_LOG_LEVELS:
        allowed = ", ".join(sorted(_VALID_LOG_LEVELS))
        raise SettingsError(f"CHEIRON_LOG_LEVEL must be one of: {allowed}.")

    return Settings(environment=app_environment, log_level=log_level)
