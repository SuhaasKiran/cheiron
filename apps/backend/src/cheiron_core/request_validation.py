"""Validation for untrusted request payloads at the application boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping

from cheiron_core.models import ModelValidationError, TrialFilters, TrialQueryRequest

_REQUEST_FIELDS = frozenset({"query", "filters", "include_citations"})
_FILTER_FIELDS = frozenset(
    {"drug_name", "drug_names", "condition", "trial_phase", "start_year", "end_year"}
)


class RequestValidationError(ValueError):
    """Raised when an external request payload is unsafe or invalid."""


class RequestValidator:
    """Turn a bounded JSON-object payload into a validated request model."""

    def __init__(self, *, max_payload_bytes: int = 8_192) -> None:
        if type(max_payload_bytes) is not int or max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be a positive integer.")
        self._max_payload_bytes = max_payload_bytes

    def validate(self, payload: object) -> TrialQueryRequest:
        """Validate a public request payload and return its domain contract."""

        request = self._require_object(payload, "request")
        self._reject_unknown_fields(request, _REQUEST_FIELDS, "request")
        self._validate_size(request)

        raw_filters = request.get("filters", {})
        filters = self._require_object(raw_filters, "filters")
        self._reject_unknown_fields(filters, _FILTER_FIELDS, "filters")

        try:
            return TrialQueryRequest(
                query=self._require_text(request.get("query"), "query"),
                include_citations=self._optional_boolean(
                    request.get("include_citations"), "include_citations", default=True
                ),
                filters=TrialFilters(
                    drug_name=self._optional_text(
                        filters.get("drug_name"), "drug_name"
                    ),
                    drug_names=self._optional_text_list(
                        filters.get("drug_names"), "drug_names"
                    ),
                    condition=self._optional_text(
                        filters.get("condition"), "condition"
                    ),
                    trial_phase=self._optional_text(
                        filters.get("trial_phase"), "trial_phase"
                    ),
                    start_year=self._optional_year(
                        filters.get("start_year"), "start_year"
                    ),
                    end_year=self._optional_year(filters.get("end_year"), "end_year"),
                ),
            )
        except ModelValidationError as error:
            raise RequestValidationError(str(error)) from error

    def _validate_size(self, payload: Mapping[str, object]) -> None:
        try:
            encoded = json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise RequestValidationError(
                "request must contain only JSON-serializable values."
            ) from error

        if len(encoded) > self._max_payload_bytes:
            raise RequestValidationError(
                f"request must not exceed {self._max_payload_bytes} bytes."
            )

    @staticmethod
    def _require_object(value: object, field_name: str) -> dict[str, object]:
        if not isinstance(value, Mapping):
            raise RequestValidationError(f"{field_name} must be an object.")
        return dict(value)

    @staticmethod
    def _require_text(value: object, field_name: str) -> str:
        if not isinstance(value, str):
            raise RequestValidationError(f"{field_name} must be a string.")
        return value

    @classmethod
    def _optional_text(cls, value: object, field_name: str) -> str | None:
        if value is None:
            return None
        return cls._require_text(value, field_name)

    @staticmethod
    def _optional_year(value: object, field_name: str) -> int | None:
        if value is None:
            return None
        if type(value) is not int:
            raise RequestValidationError(f"{field_name} must be an integer year.")
        return value

    @staticmethod
    def _optional_boolean(value: object, field_name: str, *, default: bool) -> bool:
        if value is None:
            return default
        if type(value) is not bool:
            raise RequestValidationError(f"{field_name} must be a boolean.")
        return value

    @classmethod
    def _optional_text_list(cls, value: object, field_name: str) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise RequestValidationError(f"{field_name} must be an array of strings.")
        if not value:
            raise RequestValidationError(
                f"{field_name} must contain at least two values."
            )
        return tuple(cls._require_text(item, f"{field_name} item") for item in value)

    @staticmethod
    def _reject_unknown_fields(
        values: Mapping[str, object], allowed_fields: frozenset[str], field_name: str
    ) -> None:
        unexpected_fields = set(values).difference(allowed_fields)
        if unexpected_fields:
            field_names = ", ".join(sorted(str(field) for field in unexpected_fields))
            raise RequestValidationError(
                f"{field_name} contains unsupported field(s): {field_names}."
            )
