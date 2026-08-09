"""Request and filter contracts for clinical-trial questions."""

from __future__ import annotations

from dataclasses import dataclass

from cheiron_core.models.validation import (
    ModelValidationError,
    optional_text,
    require_text,
)

_MIN_YEAR = 1900
_MAX_YEAR = 2100


@dataclass(frozen=True, slots=True)
class TrialFilters:
    """Optional structured filters that narrow a clinical-trial question."""

    drug_name: str | None = None
    condition: str | None = None
    trial_phase: str | None = None
    start_year: int | None = None
    end_year: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "drug_name", optional_text(self.drug_name, "drug_name")
        )
        object.__setattr__(
            self, "condition", optional_text(self.condition, "condition")
        )
        object.__setattr__(
            self, "trial_phase", optional_text(self.trial_phase, "trial_phase")
        )
        self._validate_year("start_year", self.start_year)
        self._validate_year("end_year", self.end_year)
        if (
            self.start_year is not None
            and self.end_year is not None
            and self.end_year < self.start_year
        ):
            raise ModelValidationError(
                "end_year must be greater than or equal to start_year."
            )

    @staticmethod
    def _validate_year(field_name: str, value: int | None) -> None:
        if value is None:
            return
        if type(value) is not int or not _MIN_YEAR <= value <= _MAX_YEAR:
            raise ModelValidationError(
                f"{field_name} must be a year from {_MIN_YEAR} to {_MAX_YEAR}."
            )

    def to_dict(self) -> dict[str, str | int]:
        """Return only filters the caller actually supplied."""

        values = {
            "drug_name": self.drug_name,
            "condition": self.condition,
            "trial_phase": self.trial_phase,
            "start_year": self.start_year,
            "end_year": self.end_year,
        }
        return {key: value for key, value in values.items() if value is not None}


@dataclass(frozen=True, slots=True)
class TrialQueryRequest:
    """A natural-language question and optional structured trial filters."""

    query: str
    filters: TrialFilters = TrialFilters()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "query",
            require_text(self.query, "query", max_length=1000),
        )
        if not isinstance(self.filters, TrialFilters):
            raise ModelValidationError("filters must be a TrialFilters instance.")
