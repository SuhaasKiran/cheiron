from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

import pytest
from cheiron_core.clinicaltrials import (
    ClinicalTrialsApiClient,
    ClinicalTrialsApiError,
    ClinicalTrialsApiHttpError,
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


def test_fetch_studies_builds_a_json_search_request() -> None:
    transport = FakeJsonTransport(
        responses=[
            {
                "studies": [{"protocolSection": {"identificationModule": {}}}],
                "totalCount": 1,
            }
        ]
    )
    client = ClinicalTrialsApiClient(
        transport,
        base_url="https://api.example.test/v2/studies",
    )

    result = client.fetch_studies({"query.cond": "Melanoma"})

    query = parse_qs(urlparse(transport.urls[0]).query)
    assert query == {
        "query.cond": ["Melanoma"],
        "format": ["json"],
        "pageSize": ["100"],
    }
    assert result.studies == ({"protocolSection": {"identificationModule": {}}},)
    assert result.total_count == 1
    assert result.pages_fetched == 1
    assert result.truncated is False


def test_fetch_studies_follows_pagination_tokens() -> None:
    transport = FakeJsonTransport(
        responses=[
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
    assert parse_qs(urlparse(transport.urls[1]).query)["pageToken"] == ["second-page"]
    assert result.pages_fetched == 2
    assert result.truncated is False


def test_fetch_studies_stops_at_the_requested_record_limit() -> None:
    transport = FakeJsonTransport(
        responses=[
            {
                "studies": [{"id": "first"}, {"id": "second"}],
                "nextPageToken": "more-results",
            }
        ]
    )
    client = ClinicalTrialsApiClient(
        transport,
        base_url="https://api.example.test/v2/studies",
    )

    result = client.fetch_studies({}, page_size=2, max_studies=2)

    assert [study["id"] for study in result.studies] == ["first", "second"]
    assert result.truncated is True
    assert len(transport.urls) == 1


def test_fetch_studies_retries_a_transient_http_failure() -> None:
    transport = FakeJsonTransport(
        responses=[
            ClinicalTrialsApiHttpError(status_code=429),
            {"studies": []},
        ]
    )
    delays: list[float] = []
    client = ClinicalTrialsApiClient(
        transport,
        base_url="https://api.example.test/v2/studies",
        sleeper=delays.append,
    )

    result = client.fetch_studies({})

    assert result.studies == ()
    assert len(transport.urls) == 2
    assert delays == [0.25]


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
