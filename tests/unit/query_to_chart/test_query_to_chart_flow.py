"""Tests for the minimal query-to-chart application flow."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Barrier

import pytest
from cheiron_core.chart_data_builder import ChartDataBuilder
from cheiron_core.clinicaltrials import ClinicalTrialsRecordMappingError
from cheiron_core.models import (
    ChartType,
    GroupBy,
    QueryPlan,
    TrialFilters,
    TrialQueryRequest,
)
from cheiron_core.query_planning import SimpleQueryPlanner, UnsupportedQueryError
from cheiron_core.query_to_chart import (
    IncompleteTrialRetrievalError,
    QueryToChartFlow,
    TrialResultLimitExceededError,
)
from cheiron_core.request_validation import RequestValidationError, RequestValidator
from cheiron_core.trial_retrieval import (
    TrialRetrievalDependencyError,
    TrialRetrievalResult,
)


def without_citations(row: dict[str, object]) -> dict[str, object]:
    """Keep flow assertions focused on chart values rather than provenance."""

    return {
        key: value
        for key, value in row.items()
        if key not in {"citations", "citations_truncated"}
    }


@dataclass
class FakePlanner:
    result: QueryPlan | tuple[QueryPlan, ...]
    requests: list[TrialQueryRequest] = field(default_factory=list)

    def plan_many(self, request: TrialQueryRequest) -> tuple[QueryPlan, ...]:
        self.requests.append(request)
        return self.result if isinstance(self.result, tuple) else (self.result,)


@dataclass
class FakeRetriever:
    result: TrialRetrievalResult | Exception
    plans: list[QueryPlan] = field(default_factory=list)

    def retrieve(self, plan: QueryPlan) -> TrialRetrievalResult:
        self.plans.append(plan)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@dataclass
class ParallelRetriever:
    """Require two retrieval calls to overlap before returning local fixtures."""

    results: dict[ChartType, TrialRetrievalResult]
    barrier: Barrier = field(default_factory=lambda: Barrier(2, timeout=1))
    plans: list[QueryPlan] = field(default_factory=list)

    def retrieve(self, plan: QueryPlan) -> TrialRetrievalResult:
        self.plans.append(plan)
        self.barrier.wait()
        return self.results[plan.chart_type]


def make_year_plan() -> QueryPlan:
    """Build the plan used by the focused flow tests."""

    return QueryPlan(
        filters=TrialFilters(condition="Melanoma"),
        chart_type=ChartType.TIME_SERIES,
        group_by=GroupBy.START_YEAR,
    )


def make_phase_plan() -> QueryPlan:
    return QueryPlan(
        filters=TrialFilters(condition="Melanoma"),
        chart_type=ChartType.BAR_CHART,
        group_by=GroupBy.TRIAL_PHASE,
    )


def make_retrieval_result(
    studies: tuple[Mapping[str, object], ...] = (),
    *,
    truncated: bool = False,
    max_studies: int | None = None,
    has_more_results: bool | None = None,
    total_count: int | None = None,
) -> TrialRetrievalResult:
    """Build a bounded retrieval result without calling the live API."""

    return TrialRetrievalResult(
        studies=studies,
        total_count=len(studies) if total_count is None else total_count,
        pages_fetched=1,
        truncated=truncated,
        query_parameters={"query.cond": "Melanoma"},
        max_studies=max_studies,
        has_more_results=has_more_results,
    )


def raw_study(
    nct_id: str,
    start_date: str = "2021",
    phases: tuple[str, ...] = (),
) -> Mapping[str, object]:
    """Build the smallest raw study needed to exercise real mapping."""

    protocol: dict[str, object] = {
        "identificationModule": {"nctId": nct_id},
        "statusModule": {"startDateStruct": {"date": start_date}},
    }
    if phases:
        protocol["designModule"] = {"phases": list(phases)}
    return {
        "protocolSection": {
            **protocol,
        }
    }


def make_flow(
    planner: FakePlanner | SimpleQueryPlanner,
    retriever: FakeRetriever | ParallelRetriever,
) -> QueryToChartFlow:
    """Create the flow using real validation, mapping, and chart building."""

    return QueryToChartFlow(
        request_validator=RequestValidator(),
        query_planner=planner,
        trial_retriever=retriever,
        chart_data_builder=ChartDataBuilder(),
    )


def test_flow_validates_plans_retrieves_maps_and_builds_a_chart() -> None:
    plan = make_year_plan()
    planner = FakePlanner(plan)
    retriever = FakeRetriever(
        make_retrieval_result(
            (raw_study("NCT00000001", "2020"), raw_study("NCT00000002")),
        )
    )

    response = make_flow(planner, retriever).execute(
        {
            "query": "How many melanoma trials started each year?",
            "filters": {"condition": "Melanoma"},
        }
    )

    assert planner.requests == [
        TrialQueryRequest(
            query="How many melanoma trials started each year?",
            filters=TrialFilters(condition="Melanoma"),
        )
    ]
    assert retriever.plans == [plan]
    assert tuple(
        without_citations(dict(row)) for row in response.results[0].visualization.data
    ) == (
        {"start_year": 2020, "trial_count": 1},
        {"start_year": 2021, "trial_count": 1},
    )
    assert response.results[0].meta.to_dict() == {
        "filters": {"condition": "Melanoma"},
        "source": "clinicaltrials.gov",
        "units": "trials",
        "time_granularity": "year",
        "grouping": "start_year",
        "sorting": "start_year_ascending",
        "source_query": {"query.cond": "Melanoma"},
        "source_total_count": 2,
        "retrieved_study_count": 2,
        "source_trial_ids": ["NCT00000001", "NCT00000002"],
        "query_plan": {
            "chart_type": "time_series",
            "group_by": "start_year",
            "series_by": None,
            "measure": "trial_count",
            "sort": "ascending",
        },
    }


def test_flow_returns_a_valid_empty_chart_for_a_successful_empty_retrieval() -> None:
    plan = make_year_plan()
    planner = FakePlanner(plan)
    retriever = FakeRetriever(make_retrieval_result())

    response = make_flow(planner, retriever).execute(
        {"query": "How many melanoma trials started each year?", "filters": {}}
    )

    assert response.results[0].visualization.data == ()
    assert retriever.plans == [plan]


def test_flow_fetches_independent_plans_in_parallel_and_preserves_result_order() -> (
    None
):
    year_plan = make_year_plan()
    phase_plan = make_phase_plan()
    retriever = ParallelRetriever(
        {
            ChartType.TIME_SERIES: make_retrieval_result(
                (raw_study("NCT00000001", "2020"),)
            ),
            ChartType.BAR_CHART: make_retrieval_result(
                (raw_study("NCT00000002", phases=("PHASE2",)),)
            ),
        }
    )
    flow = make_flow(FakePlanner((year_plan, phase_plan)), retriever)

    response = flow.execute(
        {"query": "Show trials by year and trials by phase.", "filters": {}}
    )

    assert [result.visualization.chart_type for result in response.results] == [
        ChartType.TIME_SERIES,
        ChartType.BAR_CHART,
    ]
    assert tuple(
        without_citations(dict(row)) for row in response.results[0].visualization.data
    ) == ({"start_year": 2020, "trial_count": 1},)
    assert tuple(
        without_citations(dict(row)) for row in response.results[1].visualization.data
    ) == ({"trial_phase": "PHASE2", "trial_count": 1},)
    assert {plan.chart_type for plan in retriever.plans} == {
        ChartType.TIME_SERIES,
        ChartType.BAR_CHART,
    }


def test_flow_stops_at_validation_for_an_invalid_request() -> None:
    planner = FakePlanner(make_year_plan())
    retriever = FakeRetriever(make_retrieval_result())

    with pytest.raises(RequestValidationError, match="query"):
        make_flow(planner, retriever).execute({"filters": {}})

    assert planner.requests == []
    assert retriever.plans == []


def test_flow_stops_before_retrieval_for_an_unsupported_question() -> None:
    retriever = FakeRetriever(make_retrieval_result())
    flow = make_flow(SimpleQueryPlanner(), retriever)

    with pytest.raises(UnsupportedQueryError):
        flow.execute({"query": "List melanoma trials", "filters": {}})

    assert retriever.plans == []


def test_flow_preserves_a_retrieval_dependency_failure() -> None:
    planner = FakePlanner(make_year_plan())
    retriever = FakeRetriever(
        TrialRetrievalDependencyError("ClinicalTrials.gov could not be reached.")
    )

    with pytest.raises(TrialRetrievalDependencyError, match="could not be reached"):
        make_flow(planner, retriever).execute(
            {"query": "How many melanoma trials started each year?", "filters": {}}
        )


def test_flow_rejects_truncated_retrieval_before_mapping_or_chart_building() -> None:
    planner = FakePlanner(make_year_plan())
    retriever = FakeRetriever(
        make_retrieval_result(
            (raw_study("NCT00000001"),),
            truncated=True,
            max_studies=1,
            has_more_results=True,
        )
    )

    with pytest.raises(IncompleteTrialRetrievalError, match="truncated"):
        make_flow(planner, retriever).execute(
            {"query": "How many melanoma trials started each year?", "filters": {}}
        )


def test_flow_explains_when_the_source_result_exceeds_the_record_limit() -> None:
    planner = FakePlanner(make_year_plan())
    retriever = FakeRetriever(
        make_retrieval_result(
            truncated=True,
            max_studies=1_000,
            has_more_results=True,
            total_count=12_000,
        )
    )

    with pytest.raises(TrialResultLimitExceededError) as raised_error:
        make_flow(planner, retriever).execute(
            {"query": "How many melanoma trials started each year?", "filters": {}}
        )

    assert raised_error.value.total_count == 12_000
    assert raised_error.value.max_studies == 1_000


def test_flow_logs_safe_diagnostics_for_a_truncated_retrieval(
    caplog: pytest.LogCaptureFixture,
) -> None:
    planner = FakePlanner(make_year_plan())
    retriever = FakeRetriever(
        make_retrieval_result(
            (raw_study("NCT00000001"),),
            truncated=True,
            max_studies=1,
            has_more_results=True,
        )
    )
    caplog.set_level(
        logging.DEBUG,
        logger="uvicorn.error.cheiron_core.query_to_chart",
    )

    with pytest.raises(IncompleteTrialRetrievalError):
        make_flow(planner, retriever).execute(
            {
                "query": "How many melanoma trials started each year?",
                "filters": {"condition": "Melanoma"},
            }
        )

    assert "chart_flow_validated filter_names=condition" in caplog.messages
    assert (
        "chart_flow_retrieval_incomplete "
        "reason=configured_max_studies_reached retrieved_studies=1 "
        "configured_max_studies=1 pages_fetched=1 source_total_count=1 "
        "source_has_more_results=true" in caplog.messages
    )
    assert "Melanoma" not in caplog.text
    assert "How many melanoma trials started each year?" not in caplog.text


def test_flow_preserves_a_malformed_record_error() -> None:
    planner = FakePlanner(make_year_plan())
    retriever = FakeRetriever(make_retrieval_result(({},)))

    with pytest.raises(ClinicalTrialsRecordMappingError, match="protocolSection"):
        make_flow(planner, retriever).execute(
            {"query": "How many melanoma trials started each year?", "filters": {}}
        )
