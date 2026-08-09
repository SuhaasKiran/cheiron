"""Tests for public HTTP authentication, CORS, health, and rate limiting."""

from __future__ import annotations

from dataclasses import dataclass, field

from cheiron_core.http_security import ClientRequestRateLimiter
from cheiron_core.models import (
    ChartType,
    TrialFilters,
    VisualizationBatchResponse,
    VisualizationMeta,
    VisualizationResponse,
    VisualizationSpec,
)
from cheiron_core.settings import HttpSecuritySettings
from fastapi.testclient import TestClient


@dataclass
class FakeFlow:
    calls: list[object] = field(default_factory=list)

    def execute(self, payload: object) -> VisualizationBatchResponse:
        self.calls.append(payload)
        return VisualizationBatchResponse(
            results=(
                VisualizationResponse(
                    visualization=VisualizationSpec(
                        chart_type=ChartType.TIME_SERIES,
                        title="Trials by Start Year",
                        encoding={"x": "start_year", "y": "trial_count"},
                        data=(),
                    ),
                    meta=VisualizationMeta(filters=TrialFilters()),
                ),
            )
        )


@dataclass
class FakeClock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value


def create_client(
    *,
    security: HttpSecuritySettings | None = None,
    rate_limiter: ClientRequestRateLimiter | None = None,
) -> tuple[TestClient, FakeFlow]:
    from cheiron_core.http_api import create_http_api

    flow = FakeFlow()
    return TestClient(
        create_http_api(flow, security=security, rate_limiter=rate_limiter)
    ), flow


def test_health_check_is_public_and_does_not_call_the_chart_flow() -> None:
    client, flow = create_client(
        security=HttpSecuritySettings(api_keys=frozenset({"test-api-key"}))
    )

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert flow.calls == []


def test_chart_endpoint_requires_a_configured_api_key() -> None:
    client, flow = create_client(
        security=HttpSecuritySettings(
            api_keys=frozenset({"test-api-key"}),
            cors_allowed_origins=("https://app.example.test",),
        )
    )

    missing_key = client.post(
        "/api/v1/charts",
        json={"query": "Trials by year"},
        headers={"Origin": "https://app.example.test"},
    )
    valid_key = client.post(
        "/api/v1/charts",
        json={"query": "Trials by year"},
        headers={"X-API-Key": "test-api-key"},
    )

    assert missing_key.status_code == 401
    assert missing_key.headers["www-authenticate"] == "ApiKey"
    assert (
        missing_key.headers["access-control-allow-origin"] == "https://app.example.test"
    )
    assert missing_key.json()["error"]["code"] == "authentication_required"
    assert valid_key.status_code == 200
    assert len(flow.calls) == 1


def test_cors_allows_only_configured_origin_and_preflight() -> None:
    client, _ = create_client(
        security=HttpSecuritySettings(
            cors_allowed_origins=("https://app.example.test",)
        )
    )

    allowed = client.options(
        "/api/v1/charts",
        headers={
            "Origin": "https://app.example.test",
            "Access-Control-Request-Method": "POST",
        },
    )
    rejected = client.options(
        "/api/v1/charts",
        headers={
            "Origin": "https://untrusted.example.test",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://app.example.test"
    assert "X-API-Key" in allowed.headers["access-control-allow-headers"]
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_rate_limiter_rejects_excess_chart_requests_and_recovers() -> None:
    clock = FakeClock()
    limiter = ClientRequestRateLimiter(
        max_requests=2,
        window_seconds=60,
        clock=clock,
    )
    client, flow = create_client(rate_limiter=limiter)

    first = client.post("/api/v1/charts", json={"query": "Trials by year"})
    second = client.post("/api/v1/charts", json={"query": "Trials by year"})
    limited = client.post("/api/v1/charts", json={"query": "Trials by year"})
    clock.value = 60
    recovered = client.post("/api/v1/charts", json={"query": "Trials by year"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.json()["error"]["code"] == "rate_limited"
    assert recovered.status_code == 200
    assert len(flow.calls) == 3


def test_rate_limiter_bounds_distinct_client_state() -> None:
    clock = FakeClock()
    limiter = ClientRequestRateLimiter(
        max_requests=1,
        window_seconds=60,
        max_clients=2,
        clock=clock,
    )

    limiter.check("client-a")
    limiter.check("client-b")
    limiter.check("client-c")

    assert limiter.tracked_client_count == 2
