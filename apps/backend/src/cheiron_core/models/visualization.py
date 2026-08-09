"""Frontend-ready visualization response contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from cheiron_core.models.plan import ChartType
from cheiron_core.models.query import TrialFilters
from cheiron_core.models.validation import (
    ModelValidationError,
    freeze_json_record,
    optional_text,
    require_text,
)


@dataclass(frozen=True, slots=True)
class VisualizationSpec:
    """The chart type, data, and field-to-channel mapping a frontend renders."""

    chart_type: ChartType
    title: str
    encoding: Mapping[str, str]
    data: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.chart_type, ChartType):
            raise ModelValidationError("chart_type must be a supported ChartType.")
        object.__setattr__(
            self,
            "title",
            require_text(self.title, "title", max_length=300),
        )
        object.__setattr__(self, "encoding", self._freeze_encoding(self.encoding))
        object.__setattr__(
            self,
            "data",
            tuple(freeze_json_record(row, "data row") for row in self.data),
        )

    @staticmethod
    def _freeze_encoding(encoding: object) -> Mapping[str, str]:
        if not isinstance(encoding, Mapping) or not encoding:
            raise ModelValidationError("encoding must be a non-empty object.")

        normalized: dict[str, str] = {}
        for channel, field in encoding.items():
            clean_channel = require_text(channel, "encoding channel")
            normalized[clean_channel] = require_text(field, "encoding field")
        return MappingProxyType(normalized)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready chart specification."""

        return {
            "type": self.chart_type.value,
            "title": self.title,
            "encoding": dict(self.encoding),
            "data": [dict(row) for row in self.data],
        }


@dataclass(frozen=True, slots=True)
class VisualizationMeta:
    """Extra rendering context and the filters that produced the chart."""

    filters: TrialFilters
    source: str = "clinicaltrials.gov"
    units: str | None = None
    time_granularity: str | None = None
    grouping: str | None = None
    sorting: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.filters, TrialFilters):
            raise ModelValidationError("filters must be a TrialFilters instance.")
        object.__setattr__(self, "source", require_text(self.source, "source"))
        object.__setattr__(self, "units", optional_text(self.units, "units"))
        object.__setattr__(
            self,
            "time_granularity",
            optional_text(self.time_granularity, "time_granularity"),
        )
        object.__setattr__(self, "grouping", optional_text(self.grouping, "grouping"))
        object.__setattr__(self, "sorting", optional_text(self.sorting, "sorting"))

    def to_dict(self) -> dict[str, object]:
        """Return JSON-ready metadata without empty optional fields."""

        result: dict[str, object] = {
            "filters": self.filters.to_dict(),
            "source": self.source,
        }
        for field_name in ("units", "time_granularity", "grouping", "sorting"):
            value = getattr(self, field_name)
            if value is not None:
                result[field_name] = value
        return result


@dataclass(frozen=True, slots=True)
class VisualizationResponse:
    """The complete structured response returned to a future frontend adapter."""

    visualization: VisualizationSpec
    meta: VisualizationMeta

    def __post_init__(self) -> None:
        if not isinstance(self.visualization, VisualizationSpec):
            raise ModelValidationError(
                "visualization must be a VisualizationSpec instance."
            )
        if not isinstance(self.meta, VisualizationMeta):
            raise ModelValidationError("meta must be a VisualizationMeta instance.")

    def to_dict(self) -> dict[str, object]:
        """Return the stable, frontend-ready response shape."""

        return {
            "visualization": self.visualization.to_dict(),
            "meta": self.meta.to_dict(),
        }
