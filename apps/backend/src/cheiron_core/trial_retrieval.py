"""Retrieve bounded raw trial records for a validated query plan."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from cheiron_core.clinicaltrials import (
    ClinicalTrialsApiError,
    ClinicalTrialsApiHttpError,
    ClinicalTrialsApiProtocolError,
    ClinicalTrialsApiTransportError,
    ClinicalTrialsSearchResult,
)
from cheiron_core.clinicaltrials.api_client import MAX_STUDIES
from cheiron_core.models import QueryPlan

DEFAULT_RETRIEVAL_PAGE_SIZE = 100
DEFAULT_RETRIEVAL_MAX_STUDIES = 1_000
MAX_RETRIEVAL_PAGE_SIZE = 1_000
MAX_RETRIEVAL_STUDIES = MAX_STUDIES
_SUPPORTED_TRIAL_PHASES = frozenset(
    {"EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4", "NA"}
)
_LOGGER = logging.getLogger("uvicorn.error.cheiron_core.trial_retrieval")


class TrialRetrievalError(RuntimeError):
    """Raised when a plan cannot be safely retrieved."""


class TrialRetrievalDependencyError(TrialRetrievalError):
    """Raised when ClinicalTrials.gov cannot provide the requested records."""


class TrialRetrievalQueryError(TrialRetrievalError):
    """Raised when ClinicalTrials.gov rejects a query the backend constructed."""


class TrialRetrievalSourceDataError(TrialRetrievalError):
    """Raised when ClinicalTrials.gov returns unusable source data."""


class StudySearchClient(Protocol):
    """The narrow API-client contract needed by trial retrieval."""

    def fetch_studies(
        self,
        query_parameters: Mapping[str, str],
        *,
        page_size: int,
        max_studies: int,
    ) -> ClinicalTrialsSearchResult:
        """Return bounded raw records for the supplied API parameters."""


@dataclass(frozen=True, slots=True)
class TrialRetrievalResult:
    """Raw records and metadata from one plan-driven ClinicalTrials.gov search."""

    studies: tuple[Mapping[str, object], ...]
    total_count: int | None
    pages_fetched: int
    truncated: bool
    query_parameters: Mapping[str, str]
    max_studies: int | None = None
    has_more_results: bool | None = None

    def __post_init__(self) -> None:
        if self.max_studies is not None and (
            type(self.max_studies) is not int or self.max_studies <= 0
        ):
            raise ValueError("max_studies must be a positive integer or None.")
        if (
            self.has_more_results is not None
            and type(self.has_more_results) is not bool
        ):
            raise ValueError("has_more_results must be a boolean or None.")
        object.__setattr__(
            self,
            "query_parameters",
            MappingProxyType(dict(self.query_parameters)),
        )


class TrialRetriever:
    """Translate a validated plan into a bounded ClinicalTrials.gov search."""

    def __init__(
        self,
        api_client: StudySearchClient,
        *,
        page_size: int = DEFAULT_RETRIEVAL_PAGE_SIZE,
        max_studies: int = DEFAULT_RETRIEVAL_MAX_STUDIES,
    ) -> None:
        self._api_client = api_client
        self._page_size = self._validate_page_size(page_size)
        self._max_studies = self._validate_max_studies(max_studies)

    def retrieve(self, plan: QueryPlan) -> TrialRetrievalResult:
        """Fetch raw records for a plan or raise a clear retrieval error."""

        if not isinstance(plan, QueryPlan):
            raise TrialRetrievalError("plan must be a QueryPlan instance.")

        query_parameters = self._build_query_parameters(plan)
        parameter_names = ",".join(sorted(query_parameters)) or "none"
        _LOGGER.debug(
            "trial_retrieval_started parameter_names=%s page_size=%d max_studies=%d",
            parameter_names,
            self._page_size,
            self._max_studies,
        )
        try:
            search_result = self._api_client.fetch_studies(
                query_parameters,
                page_size=self._page_size,
                max_studies=self._max_studies,
            )
        except ClinicalTrialsApiError as error:
            mapped_error = self._map_api_error(error)
            _LOGGER.debug(
                "trial_retrieval_source_failure_mapped operation=study_retrieval "
                "source_error_type=%s mapped_error_type=%s status_code=%s",
                type(error).__name__,
                type(mapped_error).__name__,
                (
                    error.status_code
                    if isinstance(error, ClinicalTrialsApiHttpError)
                    else None
                ),
            )
            raise mapped_error from error

        _LOGGER.debug(
            "trial_retrieval_completed studies=%d total_count=%s pages=%d truncated=%s",
            len(search_result.studies),
            search_result.total_count,
            search_result.pages_fetched,
            search_result.truncated,
        )

        return TrialRetrievalResult(
            studies=search_result.studies,
            total_count=search_result.total_count,
            pages_fetched=search_result.pages_fetched,
            truncated=search_result.truncated,
            query_parameters=query_parameters,
            max_studies=self._max_studies,
            has_more_results=search_result.has_more_results,
        )

    @staticmethod
    def _map_api_error(error: ClinicalTrialsApiError) -> TrialRetrievalError:
        """Preserve source failure semantics for the transport adapter."""

        if isinstance(error, ClinicalTrialsApiProtocolError):
            return TrialRetrievalSourceDataError(
                "ClinicalTrials.gov returned an invalid source response."
            )
        if isinstance(error, ClinicalTrialsApiTransportError):
            if isinstance(error.__cause__, (UnicodeDecodeError, json.JSONDecodeError)):
                return TrialRetrievalSourceDataError(
                    "ClinicalTrials.gov returned invalid source data."
                )
            return TrialRetrievalDependencyError(
                "ClinicalTrials.gov could not retrieve trial records."
            )
        if isinstance(error, ClinicalTrialsApiHttpError):
            if 400 <= error.status_code < 500 and error.status_code not in {408, 429}:
                return TrialRetrievalQueryError(
                    "ClinicalTrials.gov could not process the requested query."
                )
            return TrialRetrievalDependencyError(
                "ClinicalTrials.gov could not retrieve trial records."
            )
        return TrialRetrievalSourceDataError(
            "ClinicalTrials.gov returned an invalid source response."
        )

    @staticmethod
    def _build_query_parameters(plan: QueryPlan) -> dict[str, str]:
        filters = plan.filters
        parameters: dict[str, str] = {}
        advanced_filters: list[str] = []

        if filters.condition is not None:
            parameters["query.cond"] = filters.condition
        if filters.drug_name is not None:
            parameters["query.intr"] = filters.drug_name
        if filters.trial_phase is not None:
            TrialRetriever._validate_trial_phase(filters.trial_phase)
            advanced_filters.append(f"AREA[Phase]{filters.trial_phase}")
        if filters.start_year is not None or filters.end_year is not None:
            start_date = (
                f"{filters.start_year}-01-01"
                if filters.start_year is not None
                else "MIN"
            )
            end_date = (
                f"{filters.end_year}-12-31" if filters.end_year is not None else "MAX"
            )
            advanced_filters.append(f"AREA[StartDate]RANGE[{start_date},{end_date}]")
        if advanced_filters:
            parameters["filter.advanced"] = " AND ".join(advanced_filters)
        return parameters

    @staticmethod
    def _validate_trial_phase(trial_phase: str) -> None:
        if trial_phase not in _SUPPORTED_TRIAL_PHASES:
            supported_values = ", ".join(sorted(_SUPPORTED_TRIAL_PHASES))
            raise TrialRetrievalError(
                f"trial_phase must be one of: {supported_values}."
            )

    @staticmethod
    def _validate_page_size(page_size: int) -> int:
        if type(page_size) is not int or not 1 <= page_size <= MAX_RETRIEVAL_PAGE_SIZE:
            raise ValueError(
                f"page_size must be an integer from 1 to {MAX_RETRIEVAL_PAGE_SIZE}."
            )
        return page_size

    @staticmethod
    def _validate_max_studies(max_studies: int) -> int:
        if (
            type(max_studies) is not int
            or not 1 <= max_studies <= MAX_RETRIEVAL_STUDIES
        ):
            raise ValueError(
                f"max_studies must be an integer from 1 to {MAX_RETRIEVAL_STUDIES}."
            )
        return max_studies
