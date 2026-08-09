from __future__ import annotations

import logging
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

import pytest
from cheiron_core.clinicaltrials import (
    ClinicalTrialsApiClient,
    ClinicalTrialsApiError,
    ClinicalTrialsApiHttpError,
    ClinicalTrialsApiTransportError,
)


@dataclass
class FakeJsonTransport:
    responses: list[object]
    urls: list[str] = field(default_factory=list)

    def get_json(self, url: str, *, timeout_seconds: float) -> object:
        self.urls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class TimeoutTransport:
    """Raise a locally controlled timeout through the production error boundary."""

    def get_json(self, url: str, *, timeout_seconds: float) -> object:
        try:
            raise TimeoutError("source request timed out")
        except TimeoutError as error:
            raise ClinicalTrialsApiTransportError(
                "ClinicalTrials.gov could not be reached."
            ) from error


class DnsFailureTransport:
    """Raise a controlled DNS failure through the production error boundary."""

    def get_json(self, url: str, *, timeout_seconds: float) -> object:
        try:
            raise socket.gaierror("name resolution failed")
        except socket.gaierror as error:
            try:
                raise URLError(error)
            except URLError as url_error:
                raise ClinicalTrialsApiTransportError(
                    "ClinicalTrials.gov could not be reached."
                ) from url_error


def test_fetch_studies_builds_a_json_search_request() -> None:
    transport = FakeJsonTransport(
        responses=[
            {"studies": [], "totalCount": 1},
            {
                "studies": [{"protocolSection": {"identificationModule": {}}}],
                "totalCount": 1,
            },
        ]
    )
    client = ClinicalTrialsApiClient(
        transport,
        base_url="https://api.example.test/v2/studies",
    )

    result = client.fetch_studies({"query.cond": "Melanoma"})

    count_query = parse_qs(urlparse(transport.urls[0]).query)
    query = parse_qs(urlparse(transport.urls[1]).query)
    assert count_query == {
        "query.cond": ["Melanoma"],
        "countTotal": ["true"],
        "format": ["json"],
        "pageSize": ["1"],
    }
    assert query == {
        "query.cond": ["Melanoma"],
        "format": ["json"],
        "pageSize": ["100"],
    }
    assert result.studies == ({"protocolSection": {"identificationModule": {}}},)
    assert result.total_count == 1
    assert result.pages_fetched == 1
    assert result.truncated is False
    assert result.has_more_results is False


def test_fetch_studies_follows_pagination_tokens() -> None:
    transport = FakeJsonTransport(
        responses=[
            {"studies": [], "totalCount": 2},
            {
                "studies": [{"id": "first"}],
                "nextPageToken": "second-page",
                "totalCount": 2,
            },
            {"studies": [{"id": "second"}], "totalCount": 2},
        ]
    )
    client = ClinicalTrialsApiClient(
        transport,
        base_url="https://api.example.test/v2/studies",
    )

    result = client.fetch_studies({"query.term": "melanoma"})

    assert [study["id"] for study in result.studies] == ["first", "second"]
    assert parse_qs(urlparse(transport.urls[2]).query)["pageToken"] == ["second-page"]
    assert result.pages_fetched == 2
    assert result.truncated is False
    assert result.has_more_results is False


def test_fetch_studies_stops_at_the_requested_record_limit() -> None:
    transport = FakeJsonTransport(
        responses=[
            {"studies": [], "totalCount": 2},
            {
                "studies": [{"id": "first"}, {"id": "second"}],
                "nextPageToken": "more-results",
            },
        ]
    )
    client = ClinicalTrialsApiClient(
        transport,
        base_url="https://api.example.test/v2/studies",
    )

    result = client.fetch_studies({}, page_size=2, max_studies=2)

    assert [study["id"] for study in result.studies] == ["first", "second"]
    assert result.truncated is True
    assert result.has_more_results is True
    assert len(transport.urls) == 2


def test_fetch_studies_stops_after_the_count_when_the_result_is_too_large(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = FakeJsonTransport(responses=[{"studies": [], "totalCount": 12_000}])
    client = ClinicalTrialsApiClient(
        transport,
        base_url="https://api.example.test/v2/studies",
    )
    caplog.set_level(
        logging.DEBUG,
        logger="uvicorn.error.cheiron_core.clinicaltrials.api_client",
    )

    result = client.fetch_studies({}, max_studies=1_000)

    assert result.studies == ()
    assert result.total_count == 12_000
    assert result.pages_fetched == 0
    assert result.truncated is True
    assert result.has_more_results is True
    assert len(transport.urls) == 1
    assert (
        "clinicaltrials_result_count source_total_count=12000 "
        "configured_max_studies=1000" in caplog.messages
    )
    assert (
        "clinicaltrials_result_limit_exceeded source_total_count=12000 "
        "configured_max_studies=1000" in caplog.messages
    )


def test_fetch_studies_retries_a_transient_http_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = FakeJsonTransport(
        responses=[
            ClinicalTrialsApiHttpError(status_code=429),
            {"studies": [], "totalCount": 0},
        ]
    )
    delays: list[float] = []
    client = ClinicalTrialsApiClient(
        transport,
        base_url="https://api.example.test/v2/studies",
        sleeper=delays.append,
    )
    caplog.set_level(
        logging.DEBUG,
        logger="uvicorn.error.cheiron_core.clinicaltrials.api_client",
    )

    result = client.fetch_studies({})

    assert result.studies == ()
    assert len(transport.urls) == 2
    assert delays == [0.25]
    assert (
        "clinicaltrials_request_retry operation=total_count_preflight attempt=1 "
        "error_type=ClinicalTrialsApiHttpError status_code=429 "
        "cause_category=http_response cause_type=none cause_reason_type=none"
        in caplog.messages
    )


def test_fetch_studies_logs_the_final_source_failure_with_its_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = ClinicalTrialsApiClient(
        FakeJsonTransport(responses=[ClinicalTrialsApiHttpError(status_code=400)]),
        base_url="https://api.example.test/v2/studies",
    )
    caplog.set_level(
        logging.WARNING,
        logger="uvicorn.error.cheiron_core.clinicaltrials.api_client",
    )

    with pytest.raises(ClinicalTrialsApiHttpError):
        client.fetch_studies({})

    assert (
        "clinicaltrials_request_failed operation=total_count_preflight attempts=1 "
        "error_type=ClinicalTrialsApiHttpError status_code=400 "
        "cause_category=http_response cause_type=none cause_reason_type=none"
        in caplog.messages
    )


def test_fetch_studies_logs_a_safe_transport_failure_category(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = ClinicalTrialsApiClient(
        TimeoutTransport(),
        base_url="https://api.example.test/v2/studies",
        max_retries=0,
    )
    caplog.set_level(
        logging.WARNING,
        logger="uvicorn.error.cheiron_core.clinicaltrials.api_client",
    )

    with pytest.raises(ClinicalTrialsApiTransportError):
        client.fetch_studies({})

    assert (
        "clinicaltrials_request_failed operation=total_count_preflight attempts=1 "
        "error_type=ClinicalTrialsApiTransportError status_code=None "
        "cause_category=timeout cause_type=TimeoutError cause_reason_type=none"
        in caplog.messages
    )


def test_fetch_studies_logs_the_dns_failure_cause_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = ClinicalTrialsApiClient(
        DnsFailureTransport(),
        base_url="https://api.example.test/v2/studies",
        max_retries=0,
    )
    caplog.set_level(
        logging.WARNING,
        logger="uvicorn.error.cheiron_core.clinicaltrials.api_client",
    )

    with pytest.raises(ClinicalTrialsApiTransportError):
        client.fetch_studies({})

    assert (
        "clinicaltrials_request_failed operation=total_count_preflight attempts=1 "
        "error_type=ClinicalTrialsApiTransportError status_code=None "
        "cause_category=network cause_type=URLError cause_reason_type=gaierror"
        in caplog.messages
    )


def test_fetch_studies_does_not_retry_a_non_retryable_http_failure() -> None:
    transport = FakeJsonTransport(
        responses=[ClinicalTrialsApiHttpError(status_code=400)]
    )
    delays: list[float] = []
    client = ClinicalTrialsApiClient(
        transport,
        base_url="https://api.example.test/v2/studies",
        sleeper=delays.append,
    )

    with pytest.raises(ClinicalTrialsApiHttpError, match="400"):
        client.fetch_studies({})

    assert len(transport.urls) == 1
    assert delays == []


def test_fetch_studies_rejects_malformed_api_data() -> None:
    client = ClinicalTrialsApiClient(
        FakeJsonTransport(responses=[{"studies": "not-a-list"}]),
        base_url="https://api.example.test/v2/studies",
    )

    with pytest.raises(ClinicalTrialsApiError, match="studies"):
        client.fetch_studies({})


@pytest.mark.parametrize(
    "base_url",
    [
        None,
        "http://api.example.test/v2/studies",
        "https://api.example.test/v2/studies?format=json",
    ],
)
def test_client_rejects_an_invalid_base_url(base_url: object) -> None:
    with pytest.raises(ValueError, match="base_url"):
        ClinicalTrialsApiClient(
            FakeJsonTransport(responses=[]),
            base_url=base_url,  # type: ignore[arg-type]
        )


def test_fetch_studies_rejects_a_repeated_page_token() -> None:
    client = ClinicalTrialsApiClient(
        FakeJsonTransport(
            responses=[
                {"studies": []},
                {"studies": [], "nextPageToken": "same-token"},
                {"studies": [], "nextPageToken": "same-token"},
            ]
        ),
        base_url="https://api.example.test/v2/studies",
    )

    with pytest.raises(ClinicalTrialsApiError, match="repeated page token"):
        client.fetch_studies({})


@pytest.mark.parametrize(
    "parameters",
    [
        {"countTotal": "false"},
        {"pageSize": "100"},
        {"pageToken": "untrusted-token"},
        {"format": "csv"},
        {"query.cond": ""},
    ],
)
def test_fetch_studies_rejects_parameters_owned_by_the_client(
    parameters: Mapping[str, str],
) -> None:
    client = ClinicalTrialsApiClient(
        FakeJsonTransport(responses=[]),
        base_url="https://api.example.test/v2/studies",
    )

    with pytest.raises(ClinicalTrialsApiError):
        client.fetch_studies(parameters)
