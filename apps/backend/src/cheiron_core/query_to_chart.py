"""Compose validation, planning, retrieval, mapping, and chart building."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Protocol

from cheiron_core.clinicaltrials import map_trial_records
from cheiron_core.models import (
    QueryPlan,
    TrialQueryRequest,
    TrialRecord,
    VisualizationResponse,
)
from cheiron_core.trial_retrieval import TrialRetrievalResult


class IncompleteTrialRetrievalError(RuntimeError):
    """Raised when a bounded retrieval cannot support a complete chart answer."""


class RequestPayloadValidator(Protocol):
    """Validate an external payload into the internal request contract."""

    def validate(self, payload: object) -> TrialQueryRequest:
        """Return a validated request."""


class QueryPlanner(Protocol):
    """Turn a validated request into a chart plan."""

    def plan(self, request: TrialQueryRequest) -> QueryPlan:
        """Return the requested chart plan."""


class TrialRecordsRetriever(Protocol):
    """Retrieve raw trial records for a validated chart plan."""

    def retrieve(self, plan: QueryPlan) -> TrialRetrievalResult:
        """Return the bounded result of a trial search."""


class TrialChartDataBuilder(Protocol):
    """Build one visualization response from cleaned records and a plan."""

    def build(
        self,
        plan: QueryPlan,
        records: Iterable[TrialRecord],
    ) -> VisualizationResponse:
        """Return a frontend-ready visualization response."""


TrialRecordsMapper = Callable[[Iterable[object]], tuple[TrialRecord, ...]]

_LOGGER = logging.getLogger("uvicorn.error.cheiron_core.query_to_chart")


class QueryToChartFlow:
    """Run the minimal, framework-independent request-to-chart use case.

    The flow has no transport concerns. It delegates validation, planning, retrieval,
    record cleaning, and aggregation to their owning components. A truncated retrieval
    is rejected so callers never receive a chart that appears to be complete.
    """

    def __init__(
        self,
        *,
        request_validator: RequestPayloadValidator,
        query_planner: QueryPlanner,
        trial_retriever: TrialRecordsRetriever,
        chart_data_builder: TrialChartDataBuilder,
        record_mapper: TrialRecordsMapper = map_trial_records,
    ) -> None:
        self._request_validator = request_validator
        self._query_planner = query_planner
        self._trial_retriever = trial_retriever
        self._chart_data_builder = chart_data_builder
        self._record_mapper = record_mapper

    def execute(self, payload: object) -> VisualizationResponse:
        """Turn one external request payload into one complete chart response."""

        request = self._request_validator.validate(payload)
        filter_names = ",".join(sorted(request.filters.to_dict())) or "none"
        _LOGGER.debug("chart_flow_validated filter_names=%s", filter_names)
        plan = self._query_planner.plan(request)
        _LOGGER.debug(
            "chart_flow_planned chart_type=%s group_by=%s",
            plan.chart_type.value,
            plan.group_by.value,
        )
        retrieval = self._trial_retriever.retrieve(plan)
        total_count = (
            str(retrieval.total_count)
            if retrieval.total_count is not None
            else "unknown"
        )
        has_more_results = (
            str(retrieval.has_more_results).lower()
            if retrieval.has_more_results is not None
            else "unknown"
        )
        _LOGGER.debug(
            "chart_flow_retrieval_finished "
            "retrieved_studies=%d source_total_count=%s pages_fetched=%d "
            "configured_max_studies=%s truncated=%s",
            len(retrieval.studies),
            total_count,
            retrieval.pages_fetched,
            retrieval.max_studies,
            retrieval.truncated,
        )
        if retrieval.truncated:
            truncation_reason = (
                "configured_max_studies_reached"
                if retrieval.max_studies is not None
                and len(retrieval.studies) >= retrieval.max_studies
                else "source_result_truncated"
            )
            _LOGGER.warning(
                "chart_flow_retrieval_incomplete reason=%s retrieved_studies=%d "
                "configured_max_studies=%s pages_fetched=%d "
                "source_total_count=%s source_has_more_results=%s",
                truncation_reason,
                len(retrieval.studies),
                retrieval.max_studies,
                retrieval.pages_fetched,
                total_count,
                has_more_results,
            )
            raise IncompleteTrialRetrievalError(
                "Trial retrieval was truncated, so a complete chart cannot be built."
            )

        records = self._record_mapper(retrieval.studies)
        response = self._chart_data_builder.build(plan, records)
        _LOGGER.debug(
            "chart_flow_completed chart_type=%s data_points=%d",
            response.visualization.chart_type.value,
            len(response.visualization.data),
        )
        return response
