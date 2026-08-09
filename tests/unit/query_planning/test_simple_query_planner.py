from __future__ import annotations

import pytest
from cheiron_core.models import (
    ChartType,
    GroupBy,
    Measure,
    SortOrder,
    TrialFilters,
    TrialQueryRequest,
)
from cheiron_core.query_planning import (
    SimpleQueryPlanner,
    UnsupportedQueryError,
)


def test_planner_creates_a_yearly_trial_count_plan() -> None:
    request = TrialQueryRequest(
        query="How many melanoma trials started each year?",
        filters=TrialFilters(condition="Melanoma", start_year=2020),
    )

    plan = SimpleQueryPlanner().plan(request)

    assert plan.filters == request.filters
    assert plan.chart_type is ChartType.TIME_SERIES
    assert plan.group_by is GroupBy.START_YEAR
    assert plan.measure is Measure.TRIAL_COUNT
    assert plan.sort is SortOrder.ASCENDING


def test_planner_preserves_the_citation_preference_in_the_chart_plan() -> None:
    plan = SimpleQueryPlanner().plan(
        TrialQueryRequest(query="Show trials by phase.", include_citations=False)
    )

    assert plan.include_citations is False


def test_planner_creates_a_phase_distribution_plan() -> None:
    plan = SimpleQueryPlanner().plan(
        TrialQueryRequest(query="Show trials by phase for pembrolizumab.")
    )

    assert plan.chart_type is ChartType.BAR_CHART
    assert plan.group_by is GroupBy.TRIAL_PHASE
    assert plan.measure is Measure.TRIAL_COUNT
    assert plan.sort is SortOrder.DESCENDING


def test_planner_creates_a_constrained_multi_drug_comparison_plan() -> None:
    plan = SimpleQueryPlanner().plan(
        TrialQueryRequest(
            query="Compare these drugs by phase.",
            filters=TrialFilters(
                condition="Melanoma",
                drug_names=("Pembrolizumab", "Nivolumab"),
            ),
        )
    )

    assert plan.chart_type is ChartType.GROUPED_BAR_CHART
    assert plan.group_by is GroupBy.TRIAL_PHASE
    assert plan.series_by is GroupBy.INTERVENTION
    assert plan.comparison_values == ("Pembrolizumab", "Nivolumab")


def test_planner_supports_country_grouping() -> None:
    plan = SimpleQueryPlanner().plan(
        TrialQueryRequest(query="Show trials by country for melanoma.")
    )

    assert plan.chart_type is ChartType.BAR_CHART
    assert plan.group_by is GroupBy.COUNTRY


@pytest.mark.parametrize(
    ("query", "chart_type", "group_by", "series_by"),
    [
        (
            "Create a grouped bar chart of trials by phase and sponsor.",
            ChartType.GROUPED_BAR_CHART,
            GroupBy.TRIAL_PHASE,
            GroupBy.SPONSOR,
        ),
        (
            "Show a scatter plot of trial drugs over time.",
            ChartType.SCATTER_PLOT,
            GroupBy.START_YEAR,
            GroupBy.INTERVENTION,
        ),
        (
            "Show a histogram of trials by start year.",
            ChartType.HISTOGRAM,
            GroupBy.START_YEAR,
            None,
        ),
        (
            "Create a network graph of drugs and sponsors.",
            ChartType.NETWORK_GRAPH,
            GroupBy.INTERVENTION,
            GroupBy.SPONSOR,
        ),
    ],
)
def test_planner_creates_extended_chart_plans(
    query: str,
    chart_type: ChartType,
    group_by: GroupBy,
    series_by: GroupBy | None,
) -> None:
    plan = SimpleQueryPlanner().plan(TrialQueryRequest(query=query))

    assert plan.chart_type is chart_type
    assert plan.group_by is group_by
    assert plan.series_by is series_by


@pytest.mark.parametrize(
    "query",
    [
        "List all trials for melanoma.",
        "Show trials by phase each year.",
    ],
)
def test_planner_rejects_unsupported_or_ambiguous_questions(query: str) -> None:
    with pytest.raises(UnsupportedQueryError):
        SimpleQueryPlanner().plan(TrialQueryRequest(query=query))
