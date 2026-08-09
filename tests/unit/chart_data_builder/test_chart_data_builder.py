"""Tests for deterministic chart data aggregation."""

from __future__ import annotations

import pytest
from cheiron_core.chart_data_builder import ChartDataBuilder, ChartDataBuilderError
from cheiron_core.models.plan import ChartType, GroupBy, QueryPlan, SortOrder
from cheiron_core.models.query import TrialFilters
from cheiron_core.models.trial import TrialRecord


def make_record(
    nct_id: str,
    *,
    start_date: str | None = None,
    phases: tuple[str, ...] = (),
) -> TrialRecord:
    """Build the smallest valid cleaned record needed by these tests."""

    return TrialRecord(
        nct_id=nct_id,
        start_date=start_date,
        phases=phases,
        interventions=(),
        sponsor=None,
        recruitment_status=None,
        countries=(),
        source_fields={"nct_id": nct_id},
    )


def make_plan(
    chart_type: ChartType,
    group_by: GroupBy,
    *,
    sort: SortOrder = SortOrder.ASCENDING,
) -> QueryPlan:
    """Build the smallest valid plan needed by these tests."""

    return QueryPlan(
        filters=TrialFilters(condition="asthma"),
        chart_type=chart_type,
        group_by=group_by,
        sort=sort,
    )


def test_builds_time_series_from_unique_known_start_years() -> None:
    plan = make_plan(ChartType.TIME_SERIES, GroupBy.START_YEAR)
    records = (
        make_record("NCT00000001", start_date="2021-05"),
        make_record("NCT00000002", start_date="2020"),
        make_record("NCT00000001", start_date="2019"),
        make_record("NCT00000003"),
        make_record("NCT00000004", start_date="2021-01-01"),
    )

    response = ChartDataBuilder().build(plan, records)

    assert response.to_dict() == {
        "visualization": {
            "type": "time_series",
            "title": "Trials by Start Year",
            "encoding": {"x": "start_year", "y": "trial_count"},
            "data": [
                {"start_year": 2020, "trial_count": 1},
                {"start_year": 2021, "trial_count": 2},
            ],
        },
        "meta": {
            "filters": {"condition": "asthma"},
            "source": "clinicaltrials.gov",
            "units": "trials",
            "time_granularity": "year",
            "grouping": "start_year",
            "sorting": "start_year_ascending",
        },
    }


def test_builds_phase_chart_with_unknown_values_and_stable_tie_breaking() -> None:
    plan = make_plan(
        ChartType.BAR_CHART,
        GroupBy.TRIAL_PHASE,
        sort=SortOrder.DESCENDING,
    )
    records = (
        make_record("NCT00000001", phases=("PHASE2", "PHASE3")),
        make_record("NCT00000002", phases=("UNKNOWN", "PHASE2")),
        make_record("NCT00000003", phases=("PHASE1",)),
        make_record("NCT00000002", phases=("PHASE4",)),
        make_record("NCT00000004"),
    )

    response = ChartDataBuilder().build(plan, records)

    assert response.visualization.data == (
        {"trial_phase": "PHASE2", "trial_count": 2},
        {"trial_phase": "PHASE1", "trial_count": 1},
        {"trial_phase": "PHASE3", "trial_count": 1},
        {"trial_phase": "UNKNOWN", "trial_count": 1},
    )
    assert response.meta.sorting == "trial_count_descending"


def test_build_returns_empty_data_when_no_records_have_the_grouping_value() -> None:
    plan = make_plan(ChartType.TIME_SERIES, GroupBy.START_YEAR)

    response = ChartDataBuilder().build(
        plan,
        (make_record("NCT00000001"),),
    )

    assert response.visualization.data == ()


def test_build_rejects_a_plan_with_an_unsupported_chart_and_grouping_pair() -> None:
    plan = make_plan(ChartType.TIME_SERIES, GroupBy.TRIAL_PHASE)

    with pytest.raises(
        ChartDataBuilderError,
        match="time_series requires group_by=start_year and series_by=null",
    ):
        ChartDataBuilder().build(plan, ())
