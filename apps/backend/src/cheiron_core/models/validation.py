"""Shared validation helpers owned by the model contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType


class ModelValidationError(ValueError):
    """Raised when a model value does not meet its public contract."""


def require_text(
    value: object, field_name: str, *, max_length: int | None = None
) -> str:
    """Return a trimmed non-empty string or raise a contract error."""

    if not isinstance(value, str):
        raise ModelValidationError(f"{field_name} must be a string.")

    cleaned = value.strip()
    if not cleaned:
        raise ModelValidationError(f"{field_name} must not be empty.")
    if max_length is not None and len(cleaned) > max_length:
        raise ModelValidationError(
            f"{field_name} must not exceed {max_length} characters."
        )
    return cleaned


def optional_text(value: object, field_name: str) -> str | None:
    """Return a trimmed optional string or raise a contract error."""

    if value is None:
        return None
    return require_text(value, field_name)


def freeze_json_record(value: object, field_name: str) -> Mapping[str, object]:
    """Copy a JSON-serializable object mapping for immutable model storage."""

    if not isinstance(value, Mapping):
        raise ModelValidationError(f"{field_name} must be an object.")

    record = dict(value)
    for key in record:
        if not isinstance(key, str) or not key.strip():
            raise ModelValidationError(f"{field_name} keys must be non-empty strings.")
    try:
        json.dumps(record, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ModelValidationError(
            f"{field_name} must contain JSON-serializable values."
        ) from error
    return MappingProxyType(record)
