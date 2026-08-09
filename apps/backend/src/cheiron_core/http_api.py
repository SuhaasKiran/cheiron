"""FastAPI adapter for the query-to-chart application flow."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Protocol

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
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
from cheiron_core.http_security import (
    ApiKeyAuthenticator,
    ClientRequestRateLimiter,
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
from cheiron_core.models import VisualizationBatchResponse
from cheiron_core.query_planning import SimpleQueryPlanner, UnsupportedQueryError
from cheiron_core.query_to_chart import (
    IncompleteTrialRetrievalError,
    QueryToChartFlow,
    TrialResultLimitExceededError,
)
from cheiron_core.request_validation import RequestValidationError, RequestValidator
from cheiron_core.settings import HttpSecuritySettings, Settings, load_settings
from cheiron_core.trial_retrieval import (
    TrialRetrievalDependencyError,
    TrialRetrievalQueryError,
    TrialRetrievalSourceDataError,
    TrialRetriever,
)

CHARTS_PATH = "/api/v1/charts"
HEALTH_PATH = "/health"
DEFAULT_MAX_REQUEST_BYTES = 8_192
DEFAULT_MAX_RESPONSE_BYTES = 1_048_576

_JSON_CONTENT_TYPE = "application/json"
# Use Uvicorn's logger hierarchy so application diagnostics are visible when the
# server is started with `--log-level debug` without configuring another handler.
_LOGGER = logging.getLogger("uvicorn.error.cheiron_core.http_api")


class QueryToChartExecutor(Protocol):
    """The narrow application-flow contract used by the HTTP adapter."""

    def execute(self, payload: object) -> VisualizationBatchResponse:
        """Return visualization responses for one validated HTTP payload."""


class HttpApiError(Exception):
    """A safe, stable HTTP error raised by the FastAPI adapter."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = dict(headers or {})
        super().__init__(message)


class _RequestBodyTooLargeError(Exception):
    """Stop an ASGI request before its body is fully buffered."""


class PublicApiSecurityMiddleware:
    """Apply optional API-key authentication and rate limits to chart requests."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        authenticator: ApiKeyAuthenticator,
        rate_limiter: ClientRequestRateLimiter,
    ) -> None:
        self._app = app
        self._authenticator = authenticator
        self._rate_limiter = rate_limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._requires_protection(scope):
            await self._app(scope, receive, send)
            return

        api_key = _header_value(scope, b"x-api-key")
        if not self._authenticator.is_authorized(api_key):
            await _send_error_response(
                send,
                HttpApiError(
                    401,
                    "authentication_required",
                    "A valid X-API-Key is required.",
                    headers={"WWW-Authenticate": "ApiKey"},
                ),
            )
            return

        decision = self._rate_limiter.check(_client_identifier(scope))
        if not decision.allowed:
            await _send_error_response(
                send,
                HttpApiError(
                    429,
                    "rate_limited",
                    "Too many chart requests. Please retry shortly.",
                    headers={"Retry-After": str(decision.retry_after_seconds)},
                ),
            )
            return
        await self._app(scope, receive, send)

    @staticmethod
    def _requires_protection(scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and scope.get("path") == CHARTS_PATH
            and scope.get("method") == "POST"
        )


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
    security: HttpSecuritySettings | None = None,
    rate_limiter: ClientRequestRateLimiter | None = None,
) -> FastAPI:
    """Create the injected FastAPI app for the chart endpoint."""

    max_request_bytes = _validate_limit(max_request_bytes, "max_request_bytes")
    max_response_bytes = _validate_limit(max_response_bytes, "max_response_bytes")
    resolved_security = HttpSecuritySettings() if security is None else security
    if not isinstance(resolved_security, HttpSecuritySettings):
        raise ValueError("security must be an HttpSecuritySettings instance.")
    public_rate_limiter = rate_limiter or ClientRequestRateLimiter(
        max_requests=resolved_security.rate_limit_requests,
        window_seconds=resolved_security.rate_limit_window_seconds,
    )

    app = FastAPI(title="Cheiron API", version="0.1.0")
    app.add_middleware(
        PublicApiSecurityMiddleware,
        authenticator=ApiKeyAuthenticator(resolved_security.api_keys),
        rate_limiter=public_rate_limiter,
    )
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_request_bytes=max_request_bytes,
    )
    if resolved_security.cors_allowed_origins:
        # Starlette applies the most recently added middleware first. CORS must
        # wrap security and body-limit errors so browser clients can read them.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_security.cors_allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-API-Key"],
            max_age=600,
        )

    @app.exception_handler(HttpApiError)
    async def handle_http_api_error(_: Request, error: HttpApiError) -> JSONResponse:
        return _error_response(
            error.status_code,
            error.code,
            error.message,
            headers=error.headers,
        )

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
        error: TrialRetrievalDependencyError,
    ) -> JSONResponse:
        source_error = error.__cause__
        source_cause = source_error.__cause__ if source_error is not None else None
        _LOGGER.debug(
            "chart_http_source_unavailable dependency_error_type=%s "
            "source_error_type=%s source_cause_type=%s",
            type(error).__name__,
            type(source_error).__name__ if source_error is not None else "none",
            type(source_cause).__name__ if source_cause is not None else "none",
        )
        return _error_response(
            503,
            "source_unavailable",
            "ClinicalTrials.gov is temporarily unavailable.",
        )

    @app.exception_handler(TrialRetrievalQueryError)
    async def handle_retrieval_query_error(
        _: Request,
        __: TrialRetrievalQueryError,
    ) -> JSONResponse:
        return _error_response(
            422,
            "source_query_invalid",
            "ClinicalTrials.gov could not process the requested query.",
        )

    @app.exception_handler(TrialRetrievalSourceDataError)
    async def handle_retrieval_source_data_error(
        _: Request,
        __: TrialRetrievalSourceDataError,
    ) -> JSONResponse:
        return _error_response(
            502,
            "source_data_invalid",
            "ClinicalTrials.gov returned data that could not be used.",
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

    @app.exception_handler(TrialResultLimitExceededError)
    async def handle_result_limit_exceeded_error(
        _: Request,
        error: TrialResultLimitExceededError,
    ) -> JSONResponse:
        return _error_response(
            422,
            "source_result_too_large",
            "This query matches "
            f"{error.total_count:,} trials, which exceeds the "
            f"{error.max_studies:,}-trial limit. Narrow the query with a condition, "
            "intervention, phase, or date-range filter.",
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

    @app.get(HEALTH_PATH, include_in_schema=False)
    async def health_check() -> JSONResponse:
        """Return a dependency-free liveness response for Railway."""

        return JSONResponse(
            content={"status": "ok"},
            headers={"Cache-Control": "no-store"},
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
            "chart_request_completed result_count=%d data_points=%d",
            len(chart_response.results),
            sum(len(result.visualization.data) for result in chart_response.results),
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
        trial_retriever=TrialRetriever(
            api_client,
            max_studies=application_settings.retrieval_max_studies,
        ),
        chart_data_builder=ChartDataBuilder(chart_registry),
    )
    return create_http_api(flow, security=application_settings.http_security)


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
    response: VisualizationBatchResponse,
    max_response_bytes: int,
) -> Response:
    payload = response.to_dict()
    body = _encode_json(payload)
    if len(body) > max_response_bytes:
        payload = json.loads(body)
        body, citations_trimmed = _trim_citations_to_fit(
            payload,
            max_response_bytes,
        )
        if len(body) <= max_response_bytes:
            _LOGGER.debug(
                "chart_response_citations_trimmed response_bytes=%d limit=%d",
                len(body),
                max_response_bytes,
            )
            return Response(
                content=body,
                media_type=_JSON_CONTENT_TYPE,
                headers={"Cache-Control": "no-store"},
            )
        citations_present = bool(_citation_rows(payload))
        raise HttpApiError(
            422,
            "visualization_response_too_large",
            (
                "Chart response exceeds the server response limit. Narrow the query "
                "or set include_citations to false."
                if citations_trimmed or citations_present
                else (
                    "Chart response exceeds the server response limit. "
                    "Narrow the query."
                )
            ),
        )
    return Response(
        content=body,
        media_type=_JSON_CONTENT_TYPE,
        headers={"Cache-Control": "no-store"},
    )


def _trim_citations_to_fit(
    payload: dict[str, object],
    max_response_bytes: int,
) -> tuple[bytes, bool]:
    """Fairly remove only extra citations until the serialized response fits.

    Every visualized item retains its first citation. If even that minimum
    traceability payload cannot fit, the caller returns a clear client error.
    """

    citation_rows = _citation_rows(payload)
    citations_trimmed = False
    body = _encode_json(payload)
    while len(body) > max_response_bytes:
        removed_this_round = False
        for result, row in citation_rows:
            citations = row.get("citations")
            if not isinstance(citations, list) or len(citations) <= 1:
                continue
            citations.pop()
            row["citations_truncated"] = True
            meta = result.get("meta")
            if isinstance(meta, dict):
                meta["citations_truncated"] = True
            citations_trimmed = True
            removed_this_round = True
        if not removed_this_round:
            break
        body = _encode_json(payload)
    return body, citations_trimmed


def _citation_rows(
    payload: dict[str, object],
) -> tuple[tuple[dict[str, object], dict[str, object]], ...]:
    """Return citation-bearing data and node rows in stable response order."""

    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return ()

    rows: list[tuple[dict[str, object], dict[str, object]]] = []
    for result in raw_results:
        if not isinstance(result, dict):
            continue
        visualization = result.get("visualization")
        if not isinstance(visualization, dict):
            continue
        for field_name in ("data", "nodes"):
            values = visualization.get(field_name)
            if not isinstance(values, list):
                continue
            for row in values:
                if isinstance(row, dict) and isinstance(row.get("citations"), list):
                    rows.append((result, row))
    return tuple(rows)


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


def _header_value(scope: Scope, name: bytes) -> str | None:
    """Read one ASCII request header without depending on a framework request."""

    for header in scope.get("headers", []):
        if (
            not isinstance(header, tuple)
            or len(header) != 2
            or header[0] != name
            or not isinstance(header[1], bytes)
        ):
            continue
        try:
            return header[1].decode("ascii")
        except UnicodeDecodeError:
            return None
    return None


def _client_identifier(scope: Scope) -> str:
    """Return the ASGI client's host without trusting caller-supplied headers."""

    client = scope.get("client")
    if isinstance(client, tuple) and client and isinstance(client[0], str):
        return client[0]
    return "unknown"


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
                *[
                    (name.lower().encode("ascii"), value.encode("ascii"))
                    for name, value in error.headers.items()
                ],
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
