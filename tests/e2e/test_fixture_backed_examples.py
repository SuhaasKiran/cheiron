"""Fixture-backed end-to-end checks for the published example responses."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from cheiron_core.chart_data_builder import ChartDataBuilder
from cheiron_core.clinicaltrials import ClinicalTrialsApiClient
from cheiron_core.http_api import create_http_api
from cheiron_core.models import ChartType, GroupBy, QueryPlan, TrialFilters
from cheiron_core.query_planning import SimpleQueryPlanner
from cheiron_core.query_to_chart import QueryToChartFlow
from cheiron_core.request_validation import RequestValidator
from cheiron_core.trial_retrieval import TrialRetriever
from fastapi.testclient import TestClient

EXAMPLES_PATH = Path(__file__).parents[2] / "examples"
FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "clinicaltrials" / "nct00000102.json"
)


@dataclass
class FixtureTransport:
    """Return one saved API page and record the client URL locally."""

    payload: Mapping[str, object]
    urls: list[str] = field(default_factory=list)

    def get_json(self, url: str, *, timeout_seconds: float) -> object:
        self.urls.append(url)
        return self.payload


@dataclass(frozen=True)
class FixtureMultiPlanner:
    """Provide two independent plans while the rest of the HTTP flow is real."""

    plans: tuple[QueryPlan, ...]

    def plan_many(self, request: object) -> tuple[QueryPlan, ...]:
        return self.plans


def load_json(path: Path) -> dict[str, object]:
    """Load one checked-in JSON example with a clear local assertion."""

    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def make_fixture_client(
    query_planner: SimpleQueryPlanner | FixtureMultiPlanner | None = None,
) -> tuple[TestClient, FixtureTransport]:
    """Compose the real local flow with a saved ClinicalTrials.gov response."""

    raw_study = load_json(FIXTURE_PATH)
    transport = FixtureTransport({"studies": [raw_study], "totalCount": 1})
    api_client = ClinicalTrialsApiClient(transport, max_retries=0)
    flow = QueryToChartFlow(
        request_validator=RequestValidator(),
        query_planner=query_planner or SimpleQueryPlanner(),
        trial_retriever=TrialRetriever(api_client),
        chart_data_builder=ChartDataBuilder(),
    )
    return TestClient(create_http_api(flow)), transport


@pytest.mark.parametrize(
    ("example_name", "expected_query_parameters"),
    (
        (
            "phase-distribution-filtered",
            {
                "format": ["json"],
                "pageSize": ["100"],
                "query.cond": ["Congenital Adrenal Hyperplasia"],
            },
        ),
        (
            "phase-distribution-unfiltered",
            {"format": ["json"], "pageSize": ["100"]},
        ),
        (
            "yearly-trials-empty",
            {
                "format": ["json"],
                "pageSize": ["100"],
                "query.cond": ["Congenital Adrenal Hyperplasia"],
            },
        ),
    ),
)
def test_examples_match_the_full_local_http_flow(
    example_name: str,
    expected_query_parameters: dict[str, list[str]],
) -> None:
    request = load_json(EXAMPLES_PATH / f"{example_name}.request.json")
    expected_response = load_json(EXAMPLES_PATH / f"{example_name}.response.json")
    client, transport = make_fixture_client()

    response = client.post("/api/v1/charts", json=request)

    assert response.status_code == 200
    assert response.json() == expected_response
    assert len(transport.urls) == 2
    count_query_parameters = dict(expected_query_parameters)
    count_query_parameters["countTotal"] = ["true"]
    count_query_parameters["pageSize"] = ["1"]
    assert parse_qs(urlparse(transport.urls[0]).query) == count_query_parameters
    assert parse_qs(urlparse(transport.urls[1]).query) == expected_query_parameters


@pytest.mark.parametrize(
    (
        "chart_request",
        "expected_visualization",
        "expected_grouping",
        "expected_sorting",
    ),
    (
        (
            {
                "query": "Show a grouped bar chart of phases by sponsor.",
                "filters": {"condition": "Congenital Adrenal Hyperplasia"},
            },
            {
                "type": "grouped_bar_chart",
                "title": "Trials by Phase and Sponsor",
                "encoding": {
                    "x": "trial_phase",
                    "y": "trial_count",
                    "series": "sponsor",
                },
                "data": [
                    {
                        "trial_phase": "PHASE1",
                        "sponsor": "National Center for Research Resources (NCRR)",
                        "trial_count": 1,
                    },
                    {
                        "trial_phase": "PHASE2",
                        "sponsor": "National Center for Research Resources (NCRR)",
                        "trial_count": 1,
                    },
                ],
            },
            "trial_phase,sponsor",
            "trial_phase_ascending,sponsor_ascending",
        ),
        (
            {
                "query": "Show a network of interventions and sponsors.",
                "filters": {"condition": "Congenital Adrenal Hyperplasia"},
            },
            {
                "type": "network_graph",
                "title": "Trial Network: Intervention to Sponsor",
                "encoding": {
                    "node_id": "id",
                    "source": "source",
                    "target": "target",
                    "weight": "trial_count",
                },
                "data": [
                    {
                        "source": "intervention:Nifedipine",
                        "target": (
                            "sponsor:National Center for Research Resources (NCRR)"
                        ),
                        "trial_count": 1,
                    }
                ],
                "nodes": [
                    {
                        "id": "intervention:Nifedipine",
                        "label": "Nifedipine",
                        "type": "intervention",
                    },
                    {
                        "id": "sponsor:National Center for Research Resources (NCRR)",
                        "label": "National Center for Research Resources (NCRR)",
                        "type": "sponsor",
                    },
                ],
            },
            "intervention,sponsor",
            "source_ascending,target_ascending",
        ),
    ),
)
def test_extended_charts_match_the_full_local_http_flow(
    chart_request: dict[str, object],
    expected_visualization: dict[str, object],
    expected_grouping: str,
    expected_sorting: str,
) -> None:
    """Exercise validation through HTTP serialization using only saved source data."""

    client, transport = make_fixture_client()

    response = client.post("/api/v1/charts", json=chart_request)

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "visualization": expected_visualization,
                "meta": {
                    "filters": {"condition": "Congenital Adrenal Hyperplasia"},
                    "source": "clinicaltrials.gov",
                    "units": "trials",
                    "grouping": expected_grouping,
                    "sorting": expected_sorting,
                },
            }
        ]
    }
    assert len(transport.urls) == 2
    assert parse_qs(urlparse(transport.urls[0]).query) == {
        "countTotal": ["true"],
        "format": ["json"],
        "pageSize": ["1"],
        "query.cond": ["Congenital Adrenal Hyperplasia"],
    }
    assert parse_qs(urlparse(transport.urls[1]).query) == {
        "format": ["json"],
        "pageSize": ["100"],
        "query.cond": ["Congenital Adrenal Hyperplasia"],
    }


def test_multiple_chart_results_use_real_fixture_retrieval_and_serialization() -> None:
    plans = (
        QueryPlan(
            filters=TrialFilters(condition="Melanoma"),
            chart_type=ChartType.TIME_SERIES,
            group_by=GroupBy.START_YEAR,
        ),
        QueryPlan(
            filters=TrialFilters(condition="Lung cancer"),
            chart_type=ChartType.BAR_CHART,
            group_by=GroupBy.TRIAL_PHASE,
        ),
    )
    client, transport = make_fixture_client(FixtureMultiPlanner(plans))

    response = client.post(
        "/api/v1/charts",
        json={"query": "Show two independent charts.", "filters": {}},
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert [result["visualization"]["type"] for result in results] == [
        "time_series",
        "bar_chart",
    ]
    assert len(transport.urls) == 4
    assert {
        tuple(sorted(parse_qs(urlparse(url).query)["query.cond"]))
        for url in transport.urls
    } == {("Lung cancer",), ("Melanoma",)}
