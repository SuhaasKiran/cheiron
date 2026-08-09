"""FastAPI adapter for the query-to-chart application flow."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Protocol

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHttpException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cheiron_core.chart_data_builder import (
    ChartDataBuilder,
    ChartDataBuilderLimitError,
)
from cheiron_core.chart_rendering import (
    ChartRendererRegistry,
    create_default_chart_renderer_registry,
)
from cheiron_core.clinicaltrials import (
    ClinicalTrialsApiClient,
    ClinicalTrialsRecordMappingError,
)
from cheiron_core.llm_query_planning import (
    BoundedLlmQueryPlanner,
    DspyClinicalTrialsQueryInterpreter,
    DspyClinicalTrialsQueryProgram,
    LangSmithDspyQueryProgramTracer,
    LlmPlanningCapacityError,
    LlmPlanningRateLimitError,
    LlmQueryPlanner,
    LlmQueryPlannerError,
    TracedDspyQueryProgram,
)
from cheiron_core.models import VisualizationResponse
from cheiron_core.query_planning import SimpleQueryPlanner, UnsupportedQueryError
from cheiron_core.query_to_chart import (
    IncompleteTrialRetrievalError,
    QueryToChartFlow,
)
from cheiron_core.request_validation import RequestValidationError, RequestValidator
from cheiron_core.settings import Settings, load_settings
from cheiron_core.trial_retrieval import TrialRetrievalDependencyError, TrialRetriever

CHARTS_PATH = "/api/v1/charts"
DEFAULT_MAX_REQUEST_BYTES = 8_192
DEFAULT_MAX_RESPONSE_BYTES = 1_048_576

_JSON_CONTENT_TYPE = "application/json"
# Use Uvicorn's logger hierarchy so application diagnostics are visible when the
# server is started with `--log-level debug` without configuring another handler.
_LOGGER = logging.getLogger("uvicorn.error.cheiron_core.http_api")


class QueryToChartExecutor(Protocol):
    """The narrow application-flow contract used by the HTTP adapter."""

    def execute(self, payload: object) -> VisualizationResponse:
        """Return a visualization response for one validated HTTP payload."""


class HttpApiError(Exception):
    """A safe, stable HTTP error raised by the FastAPI adapter."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


class _RequestBodyTooLargeError(Exception):
    """Stop an ASGI request before its body is fully buffered."""


class RequestBodyLimitMiddleware:
    """Reject oversized HTTP request bodies before the application flow runs."""

    def __init__(self, app: ASGIApp, *, max_request_bytes: int) -> None:
        self._app = app
        self._max_request_bytes = max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        content_length_error = self._content_length_error(scope)
        if content_length_error is not None:
            await _send_error_response(send, content_length_error)
            return

        received_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self._max_request_bytes:
                    raise _RequestBodyTooLargeError
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLargeError:
            if response_started:
                raise
            await _send_error_response(
                send,
                HttpApiError(
                    413,
                    "request_too_large",
                    "Request body exceeds the server request limit.",
                ),
            )

    def _content_length_error(self, scope: Scope) -> HttpApiError | None:
        raw_content_length = next(
            (
                value
                for name, value in scope.get("headers", [])
                if name == b"content-length"
            ),
            None,
        )
        if raw_content_length is None:
            return None
        try:
            content_length = raw_content_length.decode("ascii")
        except UnicodeDecodeError:
            return HttpApiError(
                400,
                "invalid_content_length",
                "Content-Length must be a non-negative integer.",
            )
        if not content_length.isdecimal():
            return HttpApiError(
                400,
                "invalid_content_length",
                "Content-Length must be a non-negative integer.",
            )
        if int(content_length) > self._max_request_bytes:
            return HttpApiError(
                413,
                "request_too_large",
                "Request body exceeds the server request limit.",
            )
        return None


def create_http_api(
    flow: QueryToChartExecutor,
    *,
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> FastAPI:
    """Create the injected FastAPI app for the chart endpoint."""

    max_request_bytes = _validate_limit(max_request_bytes, "max_request_bytes")
    max_response_bytes = _validate_limit(max_response_bytes, "max_response_bytes")

    app = FastAPI(title="Cheiron API", version="0.1.0")
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_request_bytes=max_request_bytes,
    )

    @app.exception_handler(HttpApiError)
    async def handle_http_api_error(_: Request, error: HttpApiError) -> JSONResponse:
        return _error_response(error.status_code, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        _: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(400, "invalid_request", str(error))

    @app.exception_handler(UnsupportedQueryError)
    async def handle_unsupported_query_error(
        _: Request,
        error: UnsupportedQueryError,
    ) -> JSONResponse:
        return _error_response(422, "unsupported_query", str(error))

    @app.exception_handler(TrialRetrievalDependencyError)
    async def handle_retrieval_dependency_error(
        _: Request,
        __: TrialRetrievalDependencyError,
    ) -> JSONResponse:
        return _error_response(
            503,
            "source_unavailable",
            "ClinicalTrials.gov is temporarily unavailable.",
        )

    @app.exception_handler(IncompleteTrialRetrievalError)
    async def handle_incomplete_retrieval_error(
        _: Request,
        __: IncompleteTrialRetrievalError,
    ) -> JSONResponse:
        return _error_response(
            503,
            "source_result_incomplete",
            "ClinicalTrials.gov returned an incomplete result.",
        )

    @app.exception_handler(ClinicalTrialsRecordMappingError)
    async def handle_source_mapping_error(
        _: Request,
        __: ClinicalTrialsRecordMappingError,
    ) -> JSONResponse:
        return _error_response(
            502,
            "source_data_invalid",
            "ClinicalTrials.gov returned data that could not be used.",
        )

    @app.exception_handler(LlmQueryPlannerError)
    async def handle_llm_planner_error(
        _: Request,
        __: LlmQueryPlannerError,
    ) -> JSONResponse:
        return _error_response(
            503,
            "query_interpreter_unavailable",
            "The query interpreter is temporarily unavailable.",
        )

    @app.exception_handler(LlmPlanningCapacityError)
    async def handle_llm_planning_capacity_error(
        _: Request,
        __: LlmPlanningCapacityError,
    ) -> JSONResponse:
        return _error_response(
            429,
            "query_interpreter_capacity_exceeded",
            "The query interpreter is busy. Please retry shortly.",
            headers={"Retry-After": "1"},
        )

    @app.exception_handler(LlmPlanningRateLimitError)
    async def handle_llm_planning_rate_limit_error(
        _: Request,
        error: LlmPlanningRateLimitError,
    ) -> JSONResponse:
        return _error_response(
            429,
            "query_interpreter_rate_limited",
            "The query interpreter is busy. Please retry shortly.",
            headers={"Retry-After": str(error.retry_after_seconds)},
        )

    @app.exception_handler(ChartDataBuilderLimitError)
    async def handle_chart_limit_error(
        _: Request,
        __: ChartDataBuilderLimitError,
    ) -> JSONResponse:
        return _error_response(
            422,
            "visualization_too_complex",
            "The requested visualization exceeds the server rendering limit.",
        )

    @app.exception_handler(StarletteHttpException)
    async def handle_starlette_http_error(
        _: Request,
        error: StarletteHttpException,
    ) -> JSONResponse:
        if error.status_code == 404:
            return _error_response(404, "not_found", "Endpoint not found.")
        if error.status_code == 405:
            return _error_response(
                405,
                "method_not_allowed",
                "Only POST is allowed.",
                headers={"Allow": "POST"},
            )
        return _error_response(error.status_code, "http_error", "Request failed.")

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, error: Exception) -> JSONResponse:
        _LOGGER.exception("query_to_chart_http_api_unexpected_error", exc_info=error)
        return _error_response(
            500,
            "internal_error",
            "The server could not build a chart response.",
        )

    @app.post(CHARTS_PATH)
    async def create_chart(request: Request) -> Response:
        """Parse one JSON request and return the flow's visualization response."""

        _LOGGER.debug(
            "chart_request_received has_content_length=%s",
            "content-length" in request.headers,
        )
        _validate_content_type(request.headers.get("content-type"))
        payload = await _parse_request_json(request)
        _LOGGER.debug(
            "chart_request_json_parsed payload_type=%s",
            type(payload).__name__,
        )
        chart_response = await run_in_threadpool(flow.execute, payload)
        _LOGGER.debug(
            "chart_request_completed chart_type=%s data_points=%d",
            chart_response.visualization.chart_type.value,
            len(chart_response.visualization.data),
        )
        return _success_response(chart_response, max_response_bytes)

    return app


def create_default_http_api(settings: Settings | None = None) -> FastAPI:
    """Create the production composition, enabling LLM planning when configured."""

    application_settings = load_settings() if settings is None else settings
    api_client = ClinicalTrialsApiClient()
    chart_registry = create_default_chart_renderer_registry()
    flow = QueryToChartFlow(
        request_validator=RequestValidator(),
        query_planner=_create_default_query_planner(
            application_settings,
            chart_registry,
        ),
        trial_retriever=TrialRetriever(api_client),
        chart_data_builder=ChartDataBuilder(chart_registry),
    )
    return create_http_api(flow)


def _create_default_query_planner(
    settings: Settings,
    chart_registry: ChartRendererRegistry,
) -> SimpleQueryPlanner | BoundedLlmQueryPlanner:
    """Compose the LLM planner without changing the safe deterministic default."""

    if settings.openai is None:
        return SimpleQueryPlanner(chart_registry)

    program = DspyClinicalTrialsQueryProgram(
        api_key=settings.openai.api_key,
        model=settings.openai.model,
        chart_registry=chart_registry,
    )
    traced_program = (
        TracedDspyQueryProgram(
            program,
            LangSmithDspyQueryProgramTracer(
                settings=settings.langsmith,
                model=settings.openai.model,
            ),
        )
        if settings.langsmith.enabled
        else program
    )
    return BoundedLlmQueryPlanner(
        LlmQueryPlanner(
            DspyClinicalTrialsQueryInterpreter(traced_program),
            chart_registry,
        ),
        max_concurrent_requests=settings.openai.max_concurrent_requests,
        max_requests_per_minute=settings.openai.max_requests_per_minute,
    )


def _validate_content_type(content_type: str | None) -> None:
    if content_type is None:
        raise HttpApiError(
            415,
            "unsupported_media_type",
            "Content-Type must be application/json.",
        )
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != _JSON_CONTENT_TYPE:
        raise HttpApiError(
            415,
            "unsupported_media_type",
            "Content-Type must be application/json.",
        )


async def _parse_request_json(request: Request) -> object:
    try:
        return await request.json()
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HttpApiError(
            400,
            "invalid_json",
            "Request body must be valid UTF-8 JSON.",
        ) from error


def _success_response(
    response: VisualizationResponse,
    max_response_bytes: int,
) -> Response:
    body = _encode_json(response.to_dict())
    if len(body) > max_response_bytes:
        raise HttpApiError(
            500,
            "response_too_large",
            "Chart response exceeds the server response limit.",
        )
    return Response(
        content=body,
        media_type=_JSON_CONTENT_TYPE,
        headers={"Cache-Control": "no-store"},
    )


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    response_headers = {"Cache-Control": "no-store"}
    if headers is not None:
        response_headers.update(headers)
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=response_headers,
    )


async def _send_error_response(send: Send, error: HttpApiError) -> None:
    body = _encode_json({"error": {"code": error.code, "message": error.message}})
    await send(
        {
            "type": "http.response.start",
            "status": error.status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _encode_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _validate_limit(value: object, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


app = create_default_http_api()
