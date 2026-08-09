"""Tests for the FastAPI adapter around the query-to-chart flow."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import cast

import pytest
from cheiron_core.chart_data_builder import (
    ChartDataBuilderError,
    ChartDataBuilderLimitError,
)
from cheiron_core.clinicaltrials import ClinicalTrialsRecordMappingError
from cheiron_core.llm_query_planning import (
    LlmPlanningCapacityError,
    LlmPlanningRateLimitError,
    LlmQueryPlannerError,
)
from cheiron_core.models import (
    ChartType,
    TrialFilters,
    VisualizationBatchResponse,
    VisualizationMeta,
    VisualizationResponse,
    VisualizationSpec,
)
from cheiron_core.query_planning import UnsupportedQueryError
from cheiron_core.query_to_chart import (
    IncompleteTrialRetrievalError,
    TrialResultLimitExceededError,
)
from cheiron_core.request_validation import RequestValidationError
from cheiron_core.settings import OpenAiLlmSettings, Settings
from cheiron_core.trial_retrieval import (
    TrialRetrievalDependencyError,
    TrialRetrievalQueryError,
    TrialRetrievalSourceDataError,
)
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send


@dataclass
class FakeQueryToChartFlow:
    """A local flow double that captures the HTTP payload."""

    result: VisualizationBatchResponse | Exception
    payloads: list[object] = field(default_factory=list)

    def execute(self, payload: object) -> VisualizationBatchResponse:
        self.payloads.append(payload)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def make_response() -> VisualizationBatchResponse:
    """Build a valid response the HTTP adapter should serialize unchanged."""

    return VisualizationBatchResponse(
        results=(
            VisualizationResponse(
                visualization=VisualizationSpec(
                    chart_type=ChartType.TIME_SERIES,
                    title="Trials by Start Year",
                    encoding={"x": "start_year", "y": "trial_count"},
                    data=({"start_year": 2024, "trial_count": 2},),
                ),
                meta=VisualizationMeta(
                    filters=TrialFilters(condition="Melanoma"),
                    units="trials",
                    time_granularity="year",
                    grouping="start_year",
                    sorting="start_year_ascending",
                ),
            ),
        ),
    )


def make_citation_response(
    citation_count: int,
    *,
    evidence_size: int = 160,
) -> VisualizationBatchResponse:
    """Build a response whose citations can be safely trimmed at the HTTP boundary."""

    citations = [
        {
            "nct_id": f"NCT{index:08d}",
            "evidence": [
                {
                    "field": "protocolSection.designModule.phases",
                    "value": "P" * evidence_size,
                }
            ],
        }
        for index in range(1, citation_count + 1)
    ]
    return VisualizationBatchResponse(
        results=(
            VisualizationResponse(
                visualization=VisualizationSpec(
                    chart_type=ChartType.BAR_CHART,
                    title="Trials by Phase",
                    encoding={"x": "trial_phase", "y": "trial_count"},
                    data=(
                        {
                            "trial_phase": "PHASE3",
                            "trial_count": 41,
                            "citations": citations,
                        },
                    ),
                ),
                meta=VisualizationMeta(filters=TrialFilters(condition="Melanoma")),
            ),
        ),
    )


def invoke(
    client: TestClient,
    *,
    method: str = "POST",
    path: str = "/api/v1/charts",
    body: bytes = b'{"query":"trials by year","filters":{}}',
    content_type: str | None = "application/json",
    content_length: str | None = None,
) -> tuple[int, dict[str, str], dict[str, object]]:
    """Run one ASGI request locally and return its decoded JSON response."""

    headers: dict[str, str] = {}
    if content_type is not None:
        headers["content-type"] = content_type
    if content_length is not None:
        headers["content-length"] = content_length

    response = client.request(method, path, content=body, headers=headers)
    return response.status_code, dict(response.headers), response.json()


def error_code(response: dict[str, object]) -> str:
    """Read the stable error code from an API error response."""

    error = response["error"]
    assert isinstance(error, dict)
    code = error["code"]
    assert isinstance(code, str)
    return code


def test_post_chart_endpoint_returns_the_flow_response_schema() -> None:
    from cheiron_core.http_api import create_http_api

    flow = FakeQueryToChartFlow(make_response())

    status, headers, response = invoke(TestClient(create_http_api(flow)))

    assert status == 200
    assert headers["content-type"] == "application/json"
    assert response == make_response().to_dict()
    assert flow.payloads == [{"query": "trials by year", "filters": {}}]


def test_post_chart_endpoint_serializes_multiple_chart_results() -> None:
    from cheiron_core.http_api import create_http_api

    first_result = make_response().results[0]
    flow = FakeQueryToChartFlow(
        VisualizationBatchResponse(results=(first_result, first_result))
    )

    status, _, response = invoke(TestClient(create_http_api(flow)))

    assert status == 200
    results = response["results"]
    assert isinstance(results, list)
    assert len(results) == 2
    assert results[0] == first_result.to_dict()
    assert results[1] == first_result.to_dict()


def test_endpoint_rejects_unsupported_method_and_path() -> None:
    from cheiron_core.http_api import create_http_api

    flow = FakeQueryToChartFlow(make_response())
    client = TestClient(create_http_api(flow))
    method_status, method_headers, method_response = invoke(client, method="GET")
    path_status, _, path_response = invoke(client, path="/other")

    assert method_status == 405
    assert method_headers["allow"] == "POST"
    assert method_response == {
        "error": {"code": "method_not_allowed", "message": "Only POST is allowed."}
    }
    assert path_status == 404
    assert path_response == {
        "error": {"code": "not_found", "message": "Endpoint not found."}
    }
    assert flow.payloads == []


def test_endpoint_rejects_non_json_and_malformed_json_without_calling_flow() -> None:
    from cheiron_core.http_api import create_http_api

    flow = FakeQueryToChartFlow(make_response())
    client = TestClient(create_http_api(flow))
    media_status, _, media_response = invoke(client, content_type="text/plain")
    json_status, _, json_response = invoke(
        client, body=b"{", content_type="application/json"
    )

    assert media_status == 415
    assert error_code(media_response) == "unsupported_media_type"
    assert json_status == 400
    assert error_code(json_response) == "invalid_json"
    assert flow.payloads == []


def test_endpoint_enforces_request_body_size_before_calling_flow() -> None:
    from cheiron_core.http_api import create_http_api

    flow = FakeQueryToChartFlow(make_response())

    status, _, response = invoke(
        TestClient(create_http_api(flow, max_request_bytes=10)),
        body=b'{"query":"trials by year"}',
    )

    assert status == 413
    assert error_code(response) == "request_too_large"
    assert flow.payloads == []


def test_endpoint_enforces_streamed_body_size_without_content_length() -> None:
    from cheiron_core.http_api import create_http_api

    flow = FakeQueryToChartFlow(make_response())
    app = create_http_api(flow, max_request_bytes=10)
    events = iter(
        (
            {"type": "http.request", "body": b"{", "more_body": True},
            {"type": "http.request", "body": b"x" * 10, "more_body": False},
        )
    )
    sent_messages: list[Message] = []

    async def receive() -> Message:
        return next(events, {"type": "http.disconnect"})

    async def send(message: Message) -> None:
        sent_messages.append(message)

    scope = cast(
        Scope,
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/charts",
            "raw_path": b"/api/v1/charts",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "client": ("testclient", 50_000),
            "server": ("testserver", 80),
            "extensions": {},
        },
    )

    asyncio.run(app(scope, cast(Receive, receive), cast(Send, send)))

    assert sent_messages[0]["status"] == 413
    assert json.loads(sent_messages[1]["body"]) == {
        "error": {
            "code": "request_too_large",
            "message": "Request body exceeds the server request limit.",
        }
    }
    assert flow.payloads == []


def test_endpoint_rejects_an_invalid_content_length_without_calling_flow() -> None:
    from cheiron_core.http_api import create_http_api

    flow = FakeQueryToChartFlow(make_response())

    status, _, response = invoke(
        TestClient(create_http_api(flow)),
        content_length="invalid",
    )

    assert status == 400
    assert error_code(response) == "invalid_content_length"
    assert flow.payloads == []


def test_endpoint_maps_known_flow_errors_to_safe_status_codes() -> None:
    from cheiron_core.http_api import create_http_api

    cases = (
        (
            RequestValidationError("query is required"),
            400,
            "invalid_request",
        ),
        (
            UnsupportedQueryError("query is unsupported"),
            422,
            "unsupported_query",
        ),
        (
            TrialRetrievalDependencyError("source unavailable"),
            503,
            "source_unavailable",
        ),
        (
            TrialRetrievalQueryError("source query is invalid"),
            422,
            "source_query_invalid",
        ),
        (
            TrialRetrievalSourceDataError("source data is invalid"),
            502,
            "source_data_invalid",
        ),
        (
            IncompleteTrialRetrievalError("source result was truncated"),
            503,
            "source_result_incomplete",
        ),
        (
            TrialResultLimitExceededError(total_count=12_000, max_studies=1_000),
            422,
            "source_result_too_large",
        ),
        (
            ClinicalTrialsRecordMappingError("source record is malformed"),
            502,
            "source_data_invalid",
        ),
        (
            ChartDataBuilderError("invalid plan"),
            500,
            "internal_error",
        ),
        (
            ChartDataBuilderLimitError("network_graph exceeds the maximum number"),
            422,
            "visualization_too_complex",
        ),
        (
            LlmQueryPlannerError("query interpreter timed out"),
            503,
            "query_interpreter_unavailable",
        ),
        (
            LlmPlanningCapacityError("query interpreter is at capacity"),
            429,
            "query_interpreter_capacity_exceeded",
        ),
        (
            LlmPlanningRateLimitError(retry_after_seconds=3),
            429,
            "query_interpreter_rate_limited",
        ),
    )

    for error, expected_status, expected_code in cases:
        status, _, response = invoke(
            TestClient(
                create_http_api(FakeQueryToChartFlow(error)),
                raise_server_exceptions=False,
            )
        )

        assert status == expected_status
        assert error_code(response) == expected_code


def test_endpoint_explains_how_to_refine_an_oversized_source_result() -> None:
    from cheiron_core.http_api import create_http_api

    status, _, response = invoke(
        TestClient(
            create_http_api(
                FakeQueryToChartFlow(
                    TrialResultLimitExceededError(
                        total_count=12_000,
                        max_studies=1_000,
                    )
                )
            ),
            raise_server_exceptions=False,
        )
    )

    assert status == 422
    assert response == {
        "error": {
            "code": "source_result_too_large",
            "message": (
                "This query matches 12,000 trials, which exceeds the 1,000-trial "
                "limit. Narrow the query with a condition, intervention, phase, or "
                "date-range filter."
            ),
        }
    }


def test_llm_rate_limit_response_includes_a_retry_after_header() -> None:
    from cheiron_core.http_api import create_http_api

    status, headers, response = invoke(
        TestClient(
            create_http_api(
                FakeQueryToChartFlow(LlmPlanningRateLimitError(retry_after_seconds=3))
            ),
            raise_server_exceptions=False,
        )
    )

    assert status == 429
    assert error_code(response) == "query_interpreter_rate_limited"
    assert headers["retry-after"] == "3"


def test_endpoint_enforces_response_body_size() -> None:
    from cheiron_core.http_api import create_http_api

    flow = FakeQueryToChartFlow(make_response())

    status, _, response = invoke(
        TestClient(create_http_api(flow, max_response_bytes=20))
    )

    assert status == 422
    assert response == {
        "error": {
            "code": "visualization_response_too_large",
            "message": (
                "Chart response exceeds the server response limit. Narrow the query."
            ),
        }
    }


def test_endpoint_trims_extra_citations_to_fit_the_response_limit() -> None:
    from cheiron_core.http_api import create_http_api

    one_citation_response = make_citation_response(1)
    two_citation_response = make_citation_response(2)
    one_citation_size = _compact_json_size(one_citation_response.to_dict())
    two_citation_size = _compact_json_size(two_citation_response.to_dict())
    max_response_bytes = (one_citation_size + two_citation_size) // 2

    status, _, response = invoke(
        TestClient(
            create_http_api(
                FakeQueryToChartFlow(two_citation_response),
                max_response_bytes=max_response_bytes,
            )
        )
    )

    assert status == 200
    result = response["results"]
    assert isinstance(result, list)
    visualization = result[0]["visualization"]
    assert isinstance(visualization, dict)
    data = visualization["data"]
    assert isinstance(data, list)
    assert data[0]["citations_truncated"] is True
    assert len(data[0]["citations"]) == 1
    meta = result[0]["meta"]
    assert isinstance(meta, dict)
    assert meta["citations_truncated"] is True


def test_endpoint_explains_when_the_minimum_citation_payload_cannot_fit() -> None:
    from cheiron_core.http_api import create_http_api

    response_with_one_citation = make_citation_response(1, evidence_size=300)
    max_response_bytes = _compact_json_size(response_with_one_citation.to_dict()) - 1

    status, _, response = invoke(
        TestClient(
            create_http_api(
                FakeQueryToChartFlow(response_with_one_citation),
                max_response_bytes=max_response_bytes,
            )
        )
    )

    assert status == 422
    assert response == {
        "error": {
            "code": "visualization_response_too_large",
            "message": (
                "Chart response exceeds the server response limit. Narrow the query "
                "or set include_citations to false."
            ),
        }
    }


def _compact_json_size(payload: object) -> int:
    """Match the HTTP adapter's compact UTF-8 JSON serialization."""

    return len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def test_default_app_uses_the_llm_planner_when_openai_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cheiron_core.http_api as http_api

    class FakeDspyProgram:
        def __init__(
            self,
            *,
            api_key: str,
            model: str,
            chart_registry: object,
        ) -> None:
            self.api_key = api_key
            self.model = model
            self.chart_registry = chart_registry

        def run(self, *, question: str, explicit_filters_json: str) -> str:
            return """
                {
                  "is_supported": false,
                  "visualization_needed": false,
                  "clinicaltrials_query": {},
                  "reason": "The question is incomplete."
                }
            """

    monkeypatch.setattr(http_api, "DspyClinicalTrialsQueryProgram", FakeDspyProgram)
    app = http_api.create_default_http_api(
        Settings(
            environment="test",
            log_level="INFO",
            openai=OpenAiLlmSettings(api_key="test-key", model="test-model"),
        )
    )

    status, _, response = invoke(
        TestClient(app),
        body=b'{"query":"Show trials by phase.","filters":{}}',
    )

    assert status == 422
    assert error_code(response) == "unsupported_query"
