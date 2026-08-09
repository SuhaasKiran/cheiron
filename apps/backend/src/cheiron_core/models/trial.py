"""Normalized internal record used by later trial aggregations."""

from __future__ import annotations

import calendar
import re
from collections.abc import Mapping
from dataclasses import dataclass

from cheiron_core.models.validation import (
    ModelValidationError,
    freeze_json_record,
    optional_text,
    require_text,
)

_NCT_ID_PATTERN = re.compile(r"NCT\d{8}")
_PARTIAL_DATE_PATTERN = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")


@dataclass(frozen=True, slots=True)
class TrialRecord:
    """A clean, chart-focused representation of one source trial record."""

    nct_id: str
    start_date: str | None
    phases: tuple[str, ...]
    interventions: tuple[str, ...]
    sponsor: str | None
    recruitment_status: str | None
    countries: tuple[str, ...]
    source_fields: Mapping[str, object]
    conditions: tuple[str, ...] = ()
    investigators: tuple[str, ...] = ()
    sites: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        nct_id = require_text(self.nct_id, "nct_id")
        if _NCT_ID_PATTERN.fullmatch(nct_id) is None:
            raise ModelValidationError("nct_id must use the NCT######## format.")

        object.__setattr__(self, "nct_id", nct_id)
        object.__setattr__(
            self, "start_date", self._validate_start_date(self.start_date)
        )
        object.__setattr__(
            self, "phases", self._normalize_text_tuple(self.phases, "phases")
        )
        object.__setattr__(
            self,
            "interventions",
            self._normalize_text_tuple(self.interventions, "interventions"),
        )
        object.__setattr__(self, "sponsor", optional_text(self.sponsor, "sponsor"))
        object.__setattr__(
            self,
            "recruitment_status",
            optional_text(self.recruitment_status, "recruitment_status"),
        )
        object.__setattr__(
            self,
            "countries",
            self._normalize_text_tuple(self.countries, "countries"),
        )
        object.__setattr__(
            self,
            "conditions",
            self._normalize_text_tuple(self.conditions, "conditions"),
        )
        object.__setattr__(
            self,
            "investigators",
            self._normalize_text_tuple(self.investigators, "investigators"),
        )
        object.__setattr__(
            self,
            "sites",
            self._normalize_text_tuple(self.sites, "sites"),
        )
        object.__setattr__(
            self,
            "source_fields",
            freeze_json_record(self.source_fields, "source_fields"),
        )

    @property
    def start_year(self) -> int | None:
        """Return the known start year without inventing missing date precision."""

        if self.start_date is None:
            return None
        return int(self.start_date[:4])

    @staticmethod
    def _validate_start_date(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ModelValidationError("start_date must be a string or None.")

        match = _PARTIAL_DATE_PATTERN.fullmatch(value)
        if match is None:
            raise ModelValidationError(
                "start_date must use YYYY, YYYY-MM, or YYYY-MM-DD precision."
            )

        year, month, day = match.groups()
        if not 1 <= int(year) <= 9_999:
            raise ModelValidationError("start_date contains an invalid year.")
        if month is not None and not 1 <= int(month) <= 12:
            raise ModelValidationError("start_date contains an invalid month.")
        if day is not None and month is not None:
            if not 1 <= int(day) <= calendar.monthrange(int(year), int(month))[1]:
                raise ModelValidationError("start_date contains an invalid day.")
        return value

    @staticmethod
    def _normalize_text_tuple(value: object, field_name: str) -> tuple[str, ...]:
        if not isinstance(value, tuple):
            raise ModelValidationError(f"{field_name} must be a tuple of strings.")
        normalized: list[str] = []
        for item in value:
            normalized_item = require_text(item, field_name)
            if normalized_item not in normalized:
                normalized.append(normalized_item)
        return tuple(normalized)
