"""Small, synchronous adapter for the public ClinicalTrials.gov studies API."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_STUDIES = 1_000
MAX_PAGE_SIZE = 1_000
MAX_STUDIES = 10_000
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 0.25
_CLIENT_CONTROLLED_PARAMETERS = frozenset({"format", "pageSize", "pageToken"})
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class ClinicalTrialsApiError(RuntimeError):
    """Base error for ClinicalTrials.gov API failures."""


class ClinicalTrialsApiTransportError(ClinicalTrialsApiError):
    """The API could not be reached or did not return valid JSON."""


class ClinicalTrialsApiProtocolError(ClinicalTrialsApiError):
    """The API returned JSON that does not match the expected response shape."""


class ClinicalTrialsApiHttpError(ClinicalTrialsApiError):
    """The API returned an unsuccessful HTTP response."""

    def __init__(self, *, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"ClinicalTrials.gov returned HTTP status {status_code}.")


class JsonHttpTransport(Protocol):
    """The narrow transport contract needed by the ClinicalTrials.gov client."""

    def get_json(self, url: str, *, timeout_seconds: float) -> object:
        """Return a decoded JSON response or raise a ClinicalTrialsApiError."""


class UrllibJsonTransport:
    """Production JSON transport using only Python's standard library."""

    def get_json(self, url: str, *, timeout_seconds: float) -> object:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "cheiron/0.1",
            },
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                response_body = response.read()
        except HTTPError as error:
            raise ClinicalTrialsApiHttpError(status_code=error.code) from error
        except (TimeoutError, URLError) as error:
            raise ClinicalTrialsApiTransportError(
                "ClinicalTrials.gov could not be reached."
            ) from error

        try:
            return json.loads(response_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ClinicalTrialsApiTransportError(
                "ClinicalTrials.gov returned invalid JSON."
            ) from error


@dataclass(frozen=True, slots=True)
class ClinicalTrialsSearchResult:
    """Raw studies and bounded-pagination metadata from one API search."""

    studies: tuple[Mapping[str, object], ...]
    total_count: int | None
    pages_fetched: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class _StudyPage:
    studies: tuple[Mapping[str, object], ...]
    next_page_token: str | None
    total_count: int | None


class ClinicalTrialsApiClient:
    """Fetch bounded, paginated study records from ClinicalTrials.gov."""

    def __init__(
        self,
        transport: JsonHttpTransport | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 10.0,
        max_retries: int = MAX_RETRIES,
        retry_delay_seconds: float = RETRY_DELAY_SECONDS,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport or UrllibJsonTransport()
        self._base_url = self._validate_base_url(base_url)
        self._timeout_seconds = self._validate_timeout(timeout_seconds)
        self._max_retries = self._validate_retries(max_retries)
        self._retry_delay_seconds = self._validate_retry_delay(retry_delay_seconds)
        self._sleeper = sleeper

    def fetch_studies(
        self,
        query_parameters: Mapping[str, str],
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_studies: int = DEFAULT_MAX_STUDIES,
    ) -> ClinicalTrialsSearchResult:
        """Fetch study records until the API is exhausted or the limit is reached.

        This client owns JSON format and pagination parameters. Callers supply only
        domain-specific ClinicalTrials.gov search parameters, such as query.cond.
        """

        parameters = self._validate_query_parameters(query_parameters)
        page_size = self._validate_page_size(page_size)
        max_studies = self._validate_max_studies(max_studies)

        studies: list[Mapping[str, object]] = []
        seen_page_tokens: set[str] = set()
        page_token: str | None = None
        total_count: int | None = None
        pages_fetched = 0
        truncated = False

        while len(studies) < max_studies:
            request_parameters = dict(parameters)
            remaining_studies = max_studies - len(studies)
            request_parameters["format"] = "json"
            request_parameters["pageSize"] = str(min(page_size, remaining_studies))
            if page_token is not None:
                request_parameters["pageToken"] = page_token

            page = self._parse_page(
                self._get_json_with_retries(self._build_url(request_parameters))
            )
            pages_fetched += 1
            if page.total_count is not None:
                total_count = page.total_count

            remaining_studies = max_studies - len(studies)
            studies.extend(page.studies[:remaining_studies])
            if len(page.studies) > remaining_studies:
                truncated = True

            page_token = page.next_page_token
            if page_token is None:
                break
            if len(studies) >= max_studies:
                truncated = True
                break
            if page_token in seen_page_tokens:
                raise ClinicalTrialsApiProtocolError(
                    "ClinicalTrials.gov returned a repeated page token."
                )
            seen_page_tokens.add(page_token)

        return ClinicalTrialsSearchResult(
            studies=tuple(studies),
            total_count=total_count,
            pages_fetched=pages_fetched,
            truncated=truncated,
        )

    def _get_json_with_retries(self, url: str) -> object:
        for attempt in range(self._max_retries + 1):
            try:
                return self._transport.get_json(
                    url,
                    timeout_seconds=self._timeout_seconds,
                )
            except ClinicalTrialsApiError as error:
                if not self._should_retry(error, attempt):
                    raise
                self._sleeper(self._retry_delay_seconds * (2**attempt))

        raise AssertionError("The retry loop must return or raise.")

    @staticmethod
    def _parse_page(payload: object) -> _StudyPage:
        if not isinstance(payload, Mapping):
            raise ClinicalTrialsApiProtocolError(
                "ClinicalTrials.gov response must be a JSON object."
            )

        raw_studies = payload.get("studies")
        if not isinstance(raw_studies, list):
            raise ClinicalTrialsApiProtocolError(
                "ClinicalTrials.gov response field studies must be a list."
            )

        studies: list[Mapping[str, object]] = []
        for raw_study in raw_studies:
            if not isinstance(raw_study, Mapping):
                raise ClinicalTrialsApiProtocolError(
                    "Each ClinicalTrials.gov study must be a JSON object."
                )
            studies.append(MappingProxyType(dict(raw_study)))

        next_page_token = payload.get("nextPageToken")
        if next_page_token is not None and (
            not isinstance(next_page_token, str) or not next_page_token
        ):
            raise ClinicalTrialsApiProtocolError(
                "ClinicalTrials.gov nextPageToken must be a non-empty string."
            )

        total_count = payload.get("totalCount")
        if total_count is not None and (
            type(total_count) is not int or total_count < 0
        ):
            raise ClinicalTrialsApiProtocolError(
                "ClinicalTrials.gov totalCount must be a non-negative integer."
            )

        return _StudyPage(
            studies=tuple(studies),
            next_page_token=next_page_token,
            total_count=total_count,
        )

    def _build_url(self, parameters: Mapping[str, str]) -> str:
        return f"{self._base_url}?{urlencode(parameters)}"

    def _should_retry(self, error: ClinicalTrialsApiError, attempt: int) -> bool:
        return attempt < self._max_retries and (
            isinstance(error, ClinicalTrialsApiTransportError)
            or (
                isinstance(error, ClinicalTrialsApiHttpError)
                and error.status_code in _RETRYABLE_STATUS_CODES
            )
        )

    @staticmethod
    def _validate_base_url(base_url: object) -> str:
        if not isinstance(base_url, str):
            raise ValueError("base_url must be an HTTPS URL without query parameters.")
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be an HTTPS URL without query parameters.")
        return base_url.rstrip("/")

    @staticmethod
    def _validate_timeout(timeout_seconds: float) -> float:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= 60
        ):
            raise ValueError("timeout_seconds must be greater than 0 and at most 60.")
        return float(timeout_seconds)

    @staticmethod
    def _validate_retries(max_retries: int) -> int:
        if type(max_retries) is not int or not 0 <= max_retries <= 5:
            raise ValueError("max_retries must be an integer from 0 to 5.")
        return max_retries

    @staticmethod
    def _validate_retry_delay(retry_delay_seconds: float) -> float:
        if (
            isinstance(retry_delay_seconds, bool)
            or not isinstance(retry_delay_seconds, (int, float))
            or not 0 <= retry_delay_seconds <= 10
        ):
            raise ValueError("retry_delay_seconds must be from 0 to 10 seconds.")
        return float(retry_delay_seconds)

    @staticmethod
    def _validate_page_size(page_size: int) -> int:
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ClinicalTrialsApiError(
                f"page_size must be an integer from 1 to {MAX_PAGE_SIZE}."
            )
        return page_size

    @staticmethod
    def _validate_max_studies(max_studies: int) -> int:
        if type(max_studies) is not int or not 1 <= max_studies <= MAX_STUDIES:
            raise ClinicalTrialsApiError(
                f"max_studies must be an integer from 1 to {MAX_STUDIES}."
            )
        return max_studies

    @staticmethod
    def _validate_query_parameters(
        query_parameters: Mapping[str, str],
    ) -> dict[str, str]:
        if not isinstance(query_parameters, Mapping):
            raise ClinicalTrialsApiError("query_parameters must be a mapping.")
        if len(query_parameters) > 25:
            raise ClinicalTrialsApiError(
                "query_parameters must contain at most 25 values."
            )

        normalized: dict[str, str] = {}
        for name, value in query_parameters.items():
            if not isinstance(name, str) or not name.strip():
                raise ClinicalTrialsApiError(
                    "ClinicalTrials.gov parameter names must be non-empty strings."
                )
            if name in _CLIENT_CONTROLLED_PARAMETERS:
                raise ClinicalTrialsApiError(
                    f"{name} is controlled by the ClinicalTrials.gov API client."
                )
            if not isinstance(value, str) or not value.strip():
                raise ClinicalTrialsApiError(
                    f"ClinicalTrials.gov parameter {name} must be a non-empty string."
                )
            if len(value) > 2_000:
                raise ClinicalTrialsApiError(
                    f"ClinicalTrials.gov parameter {name} is too long."
                )
            normalized[name] = value
        return normalized
