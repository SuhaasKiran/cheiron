"""Tests for the minimal query-to-chart application flow."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

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
)
from cheiron_core.request_validation import RequestValidationError, RequestValidator
from cheiron_core.trial_retrieval import (
    TrialRetrievalDependencyError,
    TrialRetrievalResult,
)


@dataclass
class FakePlanner:
    result: QueryPlan
    requests: list[TrialQueryRequest] = field(default_factory=list)

    def plan(self, request: TrialQueryRequest) -> QueryPlan:
        self.requests.append(request)
        return self.result


@dataclass
class FakeRetriever:
    result: TrialRetrievalResult | Exception
    plans: list[QueryPlan] = field(default_factory=list)

    def retrieve(self, plan: QueryPlan) -> TrialRetrievalResult:
        self.plans.append(plan)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def make_year_plan() -> QueryPlan:
    """Build the plan used by the focused flow tests."""

    return QueryPlan(
        filters=TrialFilters(condition="Melanoma"),
        chart_type=ChartType.TIME_SERIES,
        group_by=GroupBy.START_YEAR,
    )


def make_retrieval_result(
    studies: tuple[Mapping[str, object], ...] = (),
    *,
    truncated: bool = False,
) -> TrialRetrievalResult:
    """Build a bounded retrieval result without calling the live API."""

    return TrialRetrievalResult(
        studies=studies,
        total_count=len(studies),
        pages_fetched=1,
        truncated=truncated,
        query_parameters={"query.cond": "Melanoma"},
    )


def raw_study(nct_id: str, start_date: str = "2021") -> Mapping[str, object]:
    """Build the smallest raw study needed to exercise real mapping."""

    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct_id},
            "statusModule": {"startDateStruct": {"date": start_date}},
        }
    }


def make_flow(
    planner: FakePlanner | SimpleQueryPlanner,
    retriever: FakeRetriever,
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
    assert response.visualization.data == (
        {"start_year": 2020, "trial_count": 1},
        {"start_year": 2021, "trial_count": 1},
    )


def test_flow_returns_a_valid_empty_chart_for_a_successful_empty_retrieval() -> None:
    plan = make_year_plan()
    planner = FakePlanner(plan)
    retriever = FakeRetriever(make_retrieval_result())

    response = make_flow(planner, retriever).execute(
        {"query": "How many melanoma trials started each year?", "filters": {}}
    )

    assert response.visualization.data == ()
    assert retriever.plans == [plan]


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
        make_retrieval_result((raw_study("NCT00000001"),), truncated=True)
    )

    with pytest.raises(IncompleteTrialRetrievalError, match="truncated"):
        make_flow(planner, retriever).execute(
            {"query": "How many melanoma trials started each year?", "filters": {}}
        )


def test_flow_preserves_a_malformed_record_error() -> None:
    planner = FakePlanner(make_year_plan())
    retriever = FakeRetriever(make_retrieval_result(({},)))

    with pytest.raises(ClinicalTrialsRecordMappingError, match="protocolSection"):
        make_flow(planner, retriever).execute(
            {"query": "How many melanoma trials started each year?", "filters": {}}
        )
