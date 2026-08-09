"""Deterministic planning for the first supported trial questions."""

from __future__ import annotations

from dataclasses import replace

from cheiron_core.chart_rendering import (
    ChartCapabilityError,
    ChartRendererRegistry,
    create_default_chart_renderer_registry,
)
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
_NETWORK_PATTERNS = ("network", "relationship graph", "connections")
_GROUPED_BAR_PATTERNS = ("grouped bar", "grouped chart")
_SCATTER_PATTERNS = ("scatter", "scatter plot")
_HISTOGRAM_PATTERNS = ("histogram",)
_ENTITY_KEYWORDS = (
    (GroupBy.TRIAL_PHASE, ("phase",)),
    (GroupBy.INTERVENTION, ("drug", "intervention")),
    (GroupBy.SPONSOR, ("sponsor",)),
    (GroupBy.CONDITION, ("condition", "disease")),
    (GroupBy.INVESTIGATOR, ("investigator", "official")),
    (GroupBy.SITE, ("site", "facility")),
)


class QueryPlanningError(ValueError):
    """Raised when a request cannot be converted into a safe query plan."""


class UnsupportedQueryError(QueryPlanningError):
    """Raised when a question is unsupported or has more than one meaning."""


class SimpleQueryPlanner:
    """Create plans for explicit fallback patterns and enabled chart renderers."""

    def __init__(self, chart_registry: ChartRendererRegistry | None = None) -> None:
        self._chart_registry = (
            chart_registry or create_default_chart_renderer_registry()
        )

    def plan(self, request: TrialQueryRequest) -> QueryPlan:
        """Return a deterministic plan or a clear unsupported-query error."""

        if not isinstance(request, TrialQueryRequest):
            raise QueryPlanningError("request must be a TrialQueryRequest instance.")

        query = request.query.casefold()
        asks_for_years = any(pattern in query for pattern in _YEAR_PATTERNS)
        asks_for_phases = any(pattern in query for pattern in _PHASE_PATTERNS)

        if any(pattern in query for pattern in _NETWORK_PATTERNS):
            network_entities = self._mentioned_entity_fields(query)
            if len(network_entities) < 2:
                raise UnsupportedQueryError(
                    "A network graph must name two entity types to connect."
                )
            return self._create_plan(
                request,
                chart_type=ChartType.NETWORK_GRAPH,
                group_by=network_entities[0],
                series_by=network_entities[1],
            )
        if any(pattern in query for pattern in _GROUPED_BAR_PATTERNS):
            group_fields = self._mentioned_entity_fields(query)
            if len(group_fields) < 2:
                raise UnsupportedQueryError(
                    "A grouped bar chart must name two grouping fields."
                )
            return self._create_plan(
                request,
                chart_type=ChartType.GROUPED_BAR_CHART,
                group_by=group_fields[0],
                series_by=group_fields[1],
            )
        if any(pattern in query for pattern in _SCATTER_PATTERNS):
            scatter_fields = self._mentioned_entity_fields(query)
            series_by = (
                scatter_fields[0]
                if scatter_fields and scatter_fields[0] is not GroupBy.START_YEAR
                else GroupBy.INTERVENTION
            )
            return self._create_plan(
                request,
                chart_type=ChartType.SCATTER_PLOT,
                group_by=GroupBy.START_YEAR,
                series_by=series_by,
            )
        if any(pattern in query for pattern in _HISTOGRAM_PATTERNS):
            return self._create_plan(
                request,
                chart_type=ChartType.HISTOGRAM,
                group_by=GroupBy.START_YEAR,
            )
        if asks_for_years and asks_for_phases:
            raise UnsupportedQueryError(
                "The question asks for more than one grouping and is ambiguous."
            )
        if asks_for_years:
            return self._create_plan(
                request,
                chart_type=ChartType.TIME_SERIES,
                group_by=GroupBy.START_YEAR,
            )
        if asks_for_phases:
            return self._create_plan(
                request,
                chart_type=ChartType.BAR_CHART,
                group_by=GroupBy.TRIAL_PHASE,
            )

        categorical_fields = self._mentioned_entity_fields(query)
        if categorical_fields:
            return self._create_plan(
                request,
                chart_type=ChartType.BAR_CHART,
                group_by=categorical_fields[0],
            )

        raise UnsupportedQueryError(
            "This question is not supported by the simple query planner."
        )

    def plan_many(self, request: TrialQueryRequest) -> tuple[QueryPlan, ...]:
        """Return the one deterministic plan supported by the fallback planner."""

        return (self.plan(request),)

    def _create_plan(
        self,
        request: TrialQueryRequest,
        *,
        chart_type: ChartType,
        group_by: GroupBy,
        series_by: GroupBy | None = None,
    ) -> QueryPlan:
        candidate = QueryPlan(
            filters=request.filters,
            chart_type=chart_type,
            group_by=group_by,
            series_by=series_by,
            measure=Measure.TRIAL_COUNT,
            sort=SortOrder.ASCENDING,
        )
        try:
            return replace(
                candidate,
                sort=self._chart_registry.default_sort(candidate),
            )
        except ChartCapabilityError as error:
            raise UnsupportedQueryError(
                "This visualization is not supported by the configured chart "
                f"capabilities: {error}"
            ) from error

    @staticmethod
    def _mentioned_entity_fields(query: str) -> tuple[GroupBy, ...]:
        fields: list[GroupBy] = []
        if any(pattern in query for pattern in _YEAR_PATTERNS):
            fields.append(GroupBy.START_YEAR)
        for group_by, keywords in _ENTITY_KEYWORDS:
            if any(keyword in query for keyword in keywords):
                fields.append(group_by)
        return tuple(fields)
