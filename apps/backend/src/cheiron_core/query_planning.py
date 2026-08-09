"""Deterministic planning for the first supported trial questions."""

from __future__ import annotations

from cheiron_core.models import (
    ChartType,
    GroupBy,
    Measure,
    QueryPlan,
    SortOrder,
    TrialQueryRequest,
)

_YEAR_PATTERNS = ("per year", "each year", "by year", "over time", "yearly")
_PHASE_PATTERNS = (
    "by phase",
    "across phases",
    "phase distribution",
    "distributed across phases",
)


class QueryPlanningError(ValueError):
    """Raised when a request cannot be converted into a safe query plan."""


class UnsupportedQueryError(QueryPlanningError):
    """Raised when a question is unsupported or has more than one meaning."""


class SimpleQueryPlanner:
    """Create plans for the small, explicit set of initial question patterns."""

    def plan(self, request: TrialQueryRequest) -> QueryPlan:
        """Return a deterministic plan or a clear unsupported-query error."""

        if not isinstance(request, TrialQueryRequest):
            raise QueryPlanningError("request must be a TrialQueryRequest instance.")

        query = request.query.casefold()
        asks_for_years = any(pattern in query for pattern in _YEAR_PATTERNS)
        asks_for_phases = any(pattern in query for pattern in _PHASE_PATTERNS)

        if asks_for_years and asks_for_phases:
            raise UnsupportedQueryError(
                "The question asks for more than one grouping and is ambiguous."
            )
        if asks_for_years:
            return QueryPlan(
                filters=request.filters,
                chart_type=ChartType.TIME_SERIES,
                group_by=GroupBy.START_YEAR,
                measure=Measure.TRIAL_COUNT,
                sort=SortOrder.ASCENDING,
            )
        if asks_for_phases:
            return QueryPlan(
                filters=request.filters,
                chart_type=ChartType.BAR_CHART,
                group_by=GroupBy.TRIAL_PHASE,
                measure=Measure.TRIAL_COUNT,
                sort=SortOrder.DESCENDING,
            )

        raise UnsupportedQueryError(
            "This question is not supported by the simple query planner."
        )
