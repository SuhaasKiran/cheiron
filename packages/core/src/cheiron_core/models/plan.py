"""Internal, validated instructions for retrieving and grouping trial data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cheiron_core.models.query import TrialFilters
from cheiron_core.models.validation import ModelValidationError


class ChartType(str, Enum):
    """Chart types supported by the first deterministic query plans."""

    BAR_CHART = "bar_chart"
    TIME_SERIES = "time_series"


class GroupBy(str, Enum):
    """Fields that the first deterministic plans can group by."""

    START_YEAR = "start_year"
    TRIAL_PHASE = "trial_phase"


class Measure(str, Enum):
    """Measures calculated by the first deterministic plans."""

    TRIAL_COUNT = "trial_count"


class SortOrder(str, Enum):
    """Supported sort orders for chart data."""

    ASCENDING = "ascending"
    DESCENDING = "descending"


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """A validated instruction for data retrieval and chart aggregation."""

    filters: TrialFilters
    chart_type: ChartType
    group_by: GroupBy
    measure: Measure = Measure.TRIAL_COUNT
    sort: SortOrder = SortOrder.ASCENDING

    def __post_init__(self) -> None:
        if not isinstance(self.filters, TrialFilters):
            raise ModelValidationError("filters must be a TrialFilters instance.")
        if not isinstance(self.chart_type, ChartType):
            raise ModelValidationError("chart_type must be a supported ChartType.")
        if not isinstance(self.group_by, GroupBy):
            raise ModelValidationError("group_by must be a supported GroupBy value.")
        if not isinstance(self.measure, Measure):
            raise ModelValidationError("measure must be a supported Measure value.")
        if not isinstance(self.sort, SortOrder):
            raise ModelValidationError("sort must be a supported SortOrder value.")
