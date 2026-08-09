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
    nodes: tuple[Mapping[str, object], ...] = ()

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
        object.__setattr__(
            self,
            "nodes",
            tuple(freeze_json_record(row, "node") for row in self.nodes),
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

        result: dict[str, object] = {
            "type": self.chart_type.value,
            "title": self.title,
            "encoding": dict(self.encoding),
            "data": [dict(row) for row in self.data],
        }
        if self.nodes:
            result["nodes"] = [dict(node) for node in self.nodes]
        return result


@dataclass(frozen=True, slots=True)
class VisualizationMeta:
    """Extra rendering context and the filters that produced the chart."""

    filters: TrialFilters
    source: str = "clinicaltrials.gov"
    units: str | None = None
    time_granularity: str | None = None
    grouping: str | None = None
    sorting: str | None = None
    truncated: bool = False
    source_query: Mapping[str, str] | None = None
    source_total_count: int | None = None
    retrieved_study_count: int | None = None
    source_trial_ids: tuple[str, ...] | None = None
    query_plan: Mapping[str, object] | None = None
    citations_truncated: bool = False

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
        if type(self.truncated) is not bool:
            raise ModelValidationError("truncated must be a boolean.")
        if type(self.citations_truncated) is not bool:
            raise ModelValidationError("citations_truncated must be a boolean.")
        object.__setattr__(
            self,
            "source_query",
            self._freeze_source_query(self.source_query),
        )
        for field_name in ("source_total_count", "retrieved_study_count"):
            value = getattr(self, field_name)
            if value is not None and (type(value) is not int or value < 0):
                raise ModelValidationError(
                    f"{field_name} must be a non-negative integer or None."
                )
        if self.source_trial_ids is not None:
            if not isinstance(self.source_trial_ids, tuple):
                raise ModelValidationError(
                    "source_trial_ids must be a tuple of strings."
                )
            trial_ids = tuple(
                require_text(value, "source_trial_ids item", max_length=32)
                for value in self.source_trial_ids
            )
            if len(set(trial_ids)) != len(trial_ids):
                raise ModelValidationError(
                    "source_trial_ids must not contain duplicates."
                )
            object.__setattr__(self, "source_trial_ids", trial_ids)
        object.__setattr__(
            self,
            "query_plan",
            None
            if self.query_plan is None
            else freeze_json_record(self.query_plan, "query_plan"),
        )

    @staticmethod
    def _freeze_source_query(value: object) -> Mapping[str, str] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ModelValidationError("source_query must be an object or None.")
        normalized = {
            require_text(key, "source_query key"): require_text(
                item, "source_query value", max_length=2_000
            )
            for key, item in value.items()
        }
        return MappingProxyType(normalized)

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
        if self.truncated:
            result["truncated"] = True
        if self.citations_truncated:
            result["citations_truncated"] = True
        if self.source_query is not None:
            result["source_query"] = dict(self.source_query)
        for field_name in ("source_total_count", "retrieved_study_count"):
            value = getattr(self, field_name)
            if value is not None:
                result[field_name] = value
        if self.source_trial_ids is not None:
            result["source_trial_ids"] = list(self.source_trial_ids)
        if self.query_plan is not None:
            result["query_plan"] = dict(self.query_plan)
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


@dataclass(frozen=True, slots=True)
class VisualizationBatchResponse:
    """An ordered collection of complete chart responses for one user question."""

    results: tuple[VisualizationResponse, ...]

    def __post_init__(self) -> None:
        if not self.results:
            raise ModelValidationError(
                "results must contain at least one chart response."
            )
        if len(self.results) > 5:
            raise ModelValidationError(
                "results must contain at most 5 chart responses."
            )
        if not all(
            isinstance(result, VisualizationResponse) for result in self.results
        ):
            raise ModelValidationError(
                "results must contain VisualizationResponse instances."
            )

    def to_dict(self) -> dict[str, object]:
        """Return the stable multi-chart response shape for the HTTP API."""

        return {"results": [result.to_dict() for result in self.results]}
