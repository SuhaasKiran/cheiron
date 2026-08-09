"""Internal, validated instructions for retrieving and grouping trial data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cheiron_core.models.query import TrialFilters
from cheiron_core.models.validation import ModelValidationError


class ChartType(StrEnum):
    """Visualization types that the renderer registry may enable."""

    BAR_CHART = "bar_chart"
    GROUPED_BAR_CHART = "grouped_bar_chart"
    TIME_SERIES = "time_series"
    SCATTER_PLOT = "scatter_plot"
    HISTOGRAM = "histogram"
    NETWORK_GRAPH = "network_graph"


class GroupBy(StrEnum):
    """Normalized trial fields available to chart renderers."""

    START_YEAR = "start_year"
    TRIAL_PHASE = "trial_phase"
    INTERVENTION = "intervention"
    SPONSOR = "sponsor"
    CONDITION = "condition"
    INVESTIGATOR = "investigator"
    SITE = "site"
    COUNTRY = "country"


class Measure(StrEnum):
    """Measures calculated by the first deterministic plans."""

    TRIAL_COUNT = "trial_count"


class SortOrder(StrEnum):
    """Supported sort orders for chart data."""

    ASCENDING = "ascending"
    DESCENDING = "descending"


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """A validated instruction for data retrieval and chart aggregation."""

    filters: TrialFilters
    chart_type: ChartType
    group_by: GroupBy
    series_by: GroupBy | None = None
    comparison_values: tuple[str, ...] = ()
    include_citations: bool = True
    measure: Measure = Measure.TRIAL_COUNT
    sort: SortOrder = SortOrder.ASCENDING

    def __post_init__(self) -> None:
        if not isinstance(self.filters, TrialFilters):
            raise ModelValidationError("filters must be a TrialFilters instance.")
        if not isinstance(self.chart_type, ChartType):
            raise ModelValidationError("chart_type must be a supported ChartType.")
        if not isinstance(self.group_by, GroupBy):
            raise ModelValidationError("group_by must be a supported GroupBy value.")
        if self.series_by is not None and not isinstance(self.series_by, GroupBy):
            raise ModelValidationError(
                "series_by must be a supported GroupBy value or None."
            )
        if not isinstance(self.comparison_values, tuple):
            raise ModelValidationError("comparison_values must be a tuple of strings.")
        if self.comparison_values:
            if self.chart_type is not ChartType.GROUPED_BAR_CHART:
                raise ModelValidationError(
                    "comparison_values are supported only by grouped_bar_chart."
                )
            if self.series_by is not GroupBy.INTERVENTION:
                raise ModelValidationError(
                    "comparison_values require series_by=intervention."
                )
            if not 2 <= len(self.comparison_values) <= 5:
                raise ModelValidationError(
                    "comparison_values must contain from 2 to 5 values."
                )
            normalized = tuple(
                value.strip() if isinstance(value, str) else ""
                for value in self.comparison_values
            )
            if not all(normalized) or len(
                {value.casefold() for value in normalized}
            ) != len(normalized):
                raise ModelValidationError(
                    "comparison_values must be distinct non-empty strings."
                )
            if normalized != self.filters.drug_names:
                raise ModelValidationError(
                    "comparison_values must match filters.drug_names."
                )
            object.__setattr__(self, "comparison_values", normalized)
        if type(self.include_citations) is not bool:
            raise ModelValidationError("include_citations must be a boolean.")
        if not isinstance(self.measure, Measure):
            raise ModelValidationError("measure must be a supported Measure value.")
        if not isinstance(self.sort, SortOrder):
            raise ModelValidationError("sort must be a supported SortOrder value.")
