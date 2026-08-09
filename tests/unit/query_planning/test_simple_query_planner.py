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


def test_planner_creates_a_phase_distribution_plan() -> None:
    plan = SimpleQueryPlanner().plan(
        TrialQueryRequest(query="Show trials by phase for pembrolizumab.")
    )

    assert plan.chart_type is ChartType.BAR_CHART
    assert plan.group_by is GroupBy.TRIAL_PHASE
    assert plan.measure is Measure.TRIAL_COUNT
    assert plan.sort is SortOrder.DESCENDING


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
