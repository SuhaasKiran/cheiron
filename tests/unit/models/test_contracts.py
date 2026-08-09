from __future__ import annotations

import pytest
from cheiron_core.models import (
    ChartType,
    GroupBy,
    Measure,
    ModelValidationError,
    QueryPlan,
    SortOrder,
    TrialFilters,
    TrialQueryRequest,
    VisualizationBatchResponse,
    VisualizationMeta,
    VisualizationResponse,
    VisualizationSpec,
)


def test_request_model_normalizes_valid_query_and_filters() -> None:
    request = TrialQueryRequest(
        query="  How many melanoma trials started each year?  ",
        filters=TrialFilters(
            drug_name=" Pembrolizumab ",
            condition=" Melanoma ",
            start_year=2020,
            end_year=2024,
        ),
    )

    assert request.query == "How many melanoma trials started each year?"
    assert request.filters.drug_name == "Pembrolizumab"
    assert request.filters.condition == "Melanoma"
    assert request.filters.to_dict() == {
        "drug_name": "Pembrolizumab",
        "condition": "Melanoma",
        "start_year": 2020,
        "end_year": 2024,
    }


def test_filter_model_accepts_an_explicit_multi_drug_comparison() -> None:
    filters = TrialFilters(drug_names=(" Pembrolizumab ", "Nivolumab"))

    assert filters.drug_names == ("Pembrolizumab", "Nivolumab")
    assert filters.to_dict() == {
        "drug_names": ["Pembrolizumab", "Nivolumab"],
    }


def test_filter_model_rejects_single_and_multi_drug_filters_together() -> None:
    with pytest.raises(ModelValidationError, match="cannot be supplied together"):
        TrialFilters(
            drug_name="Pembrolizumab",
            drug_names=("Nivolumab", "Ipilimumab"),
        )


def test_plan_model_rejects_comparison_values_that_do_not_match_its_filters() -> None:
    with pytest.raises(ModelValidationError, match="must match"):
        QueryPlan(
            filters=TrialFilters(
                condition="Melanoma",
                drug_names=("Pembrolizumab", "Nivolumab"),
            ),
            chart_type=ChartType.GROUPED_BAR_CHART,
            group_by=GroupBy.TRIAL_PHASE,
            series_by=GroupBy.INTERVENTION,
            comparison_values=("Pembrolizumab", "Ipilimumab"),
        )


@pytest.mark.parametrize(
    "query",
    ["", "   "],
)
def test_request_model_rejects_missing_query(query: str) -> None:
    with pytest.raises(ModelValidationError, match="query"):
        TrialQueryRequest(query=query)


def test_filter_model_rejects_an_invalid_year_range() -> None:
    with pytest.raises(ModelValidationError, match="end_year"):
        TrialFilters(start_year=2024, end_year=2020)


def test_plan_model_describes_a_count_by_year() -> None:
    plan = QueryPlan(
        filters=TrialFilters(condition="Melanoma", start_year=2020),
        chart_type=ChartType.TIME_SERIES,
        group_by=GroupBy.START_YEAR,
        measure=Measure.TRIAL_COUNT,
        sort=SortOrder.ASCENDING,
    )

    assert plan.chart_type is ChartType.TIME_SERIES
    assert plan.group_by is GroupBy.START_YEAR
    assert plan.measure is Measure.TRIAL_COUNT


def test_plan_model_rejects_an_unknown_chart_type() -> None:
    with pytest.raises(ModelValidationError, match="chart_type"):
        QueryPlan(
            filters=TrialFilters(),
            chart_type="pie_chart",  # type: ignore[arg-type]
            group_by=GroupBy.TRIAL_PHASE,
        )


def test_visualization_response_serializes_a_frontend_ready_chart() -> None:
    response = VisualizationResponse(
        visualization=VisualizationSpec(
            chart_type=ChartType.BAR_CHART,
            title="Trials by Phase for Pembrolizumab",
            encoding={"x": "phase", "y": "trial_count"},
            data=(
                {"phase": "PHASE1", "trial_count": 32},
                {"phase": "PHASE2", "trial_count": 78},
            ),
        ),
        meta=VisualizationMeta(
            filters=TrialFilters(drug_name="Pembrolizumab"),
            grouping="trial_phase",
            sorting="trial_count_descending",
        ),
    )

    assert response.to_dict() == {
        "visualization": {
            "type": "bar_chart",
            "title": "Trials by Phase for Pembrolizumab",
            "encoding": {"x": "phase", "y": "trial_count"},
            "data": [
                {"phase": "PHASE1", "trial_count": 32},
                {"phase": "PHASE2", "trial_count": 78},
            ],
        },
        "meta": {
            "filters": {"drug_name": "Pembrolizumab"},
            "source": "clinicaltrials.gov",
            "grouping": "trial_phase",
            "sorting": "trial_count_descending",
        },
    }


def test_visualization_batch_response_serializes_ordered_chart_results() -> None:
    result = VisualizationResponse(
        visualization=VisualizationSpec(
            chart_type=ChartType.BAR_CHART,
            title="Trials by Phase",
            encoding={"x": "trial_phase", "y": "trial_count"},
            data=(),
        ),
        meta=VisualizationMeta(filters=TrialFilters()),
    )

    response = VisualizationBatchResponse(results=(result, result))

    assert response.to_dict() == {"results": [result.to_dict(), result.to_dict()]}


def test_visualization_model_rejects_an_empty_encoding() -> None:
    with pytest.raises(ModelValidationError, match="encoding"):
        VisualizationSpec(
            chart_type=ChartType.BAR_CHART,
            title="Trials by Phase",
            encoding={},
            data=(),
        )
