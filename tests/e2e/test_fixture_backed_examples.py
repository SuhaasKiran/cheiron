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


def load_json(path: Path) -> dict[str, object]:
    """Load one checked-in JSON example with a clear local assertion."""

    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def make_fixture_client() -> tuple[TestClient, FixtureTransport]:
    """Compose the real local flow with a saved ClinicalTrials.gov response."""

    raw_study = load_json(FIXTURE_PATH)
    transport = FixtureTransport({"studies": [raw_study], "totalCount": 1})
    api_client = ClinicalTrialsApiClient(transport, max_retries=0)
    flow = QueryToChartFlow(
        request_validator=RequestValidator(),
        query_planner=SimpleQueryPlanner(),
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
    assert len(transport.urls) == 1
    request_parameters = parse_qs(urlparse(transport.urls[0]).query)
    assert request_parameters == expected_query_parameters
