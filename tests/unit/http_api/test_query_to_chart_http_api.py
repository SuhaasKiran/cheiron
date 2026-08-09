"""Tests for the FastAPI adapter around the query-to-chart flow."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import cast

from cheiron_core.chart_data_builder import ChartDataBuilderError
from cheiron_core.clinicaltrials import ClinicalTrialsRecordMappingError
from cheiron_core.models import (
    ChartType,
    TrialFilters,
    VisualizationMeta,
    VisualizationResponse,
    VisualizationSpec,
)
from cheiron_core.query_planning import UnsupportedQueryError
from cheiron_core.query_to_chart import IncompleteTrialRetrievalError
from cheiron_core.request_validation import RequestValidationError
from cheiron_core.trial_retrieval import TrialRetrievalDependencyError
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send


@dataclass
class FakeQueryToChartFlow:
    """A local flow double that captures the HTTP payload."""

    result: VisualizationResponse | Exception
    payloads: list[object] = field(default_factory=list)

    def execute(self, payload: object) -> VisualizationResponse:
        self.payloads.append(payload)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def make_response() -> VisualizationResponse:
    """Build a valid response the HTTP adapter should serialize unchanged."""

    return VisualizationResponse(
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
            IncompleteTrialRetrievalError("source result was truncated"),
            503,
            "source_result_incomplete",
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


def test_endpoint_enforces_response_body_size() -> None:
    from cheiron_core.http_api import create_http_api

    flow = FakeQueryToChartFlow(make_response())

    status, _, response = invoke(
        TestClient(create_http_api(flow, max_response_bytes=20))
    )

    assert status == 500
    assert response == {
        "error": {
            "code": "response_too_large",
            "message": "Chart response exceeds the server response limit.",
        }
    }
