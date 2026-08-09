"""Compose validation, planning, retrieval, mapping, and chart building."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Protocol

from cheiron_core.clinicaltrials import map_trial_records
from cheiron_core.models import (
    QueryPlan,
    TrialQueryRequest,
    TrialRecord,
    VisualizationBatchResponse,
    VisualizationResponse,
)
from cheiron_core.trial_retrieval import TrialRetrievalResult


class IncompleteTrialRetrievalError(RuntimeError):
    """Raised when a bounded retrieval cannot support a complete chart answer."""


class TrialResultLimitExceededError(IncompleteTrialRetrievalError):
    """Raised when a known source result count exceeds the chart record limit."""

    def __init__(self, *, total_count: int, max_studies: int) -> None:
        self.total_count = total_count
        self.max_studies = max_studies
        super().__init__(
            "The source returned more trial records than this chart can process."
        )


class RequestPayloadValidator(Protocol):
    """Validate an external payload into the internal request contract."""

    def validate(self, payload: object) -> TrialQueryRequest:
        """Return a validated request."""


class QueryPlanner(Protocol):
    """Turn a validated request into one or more independent chart plans."""

    def plan_many(self, request: TrialQueryRequest) -> tuple[QueryPlan, ...]:
        """Return ordered plans for independent requests in one user question."""


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
        max_concurrent_retrievals: int = 4,
    ) -> None:
        self._request_validator = request_validator
        self._query_planner = query_planner
        self._trial_retriever = trial_retriever
        self._chart_data_builder = chart_data_builder
        self._record_mapper = record_mapper
        self._max_concurrent_retrievals = self._validate_max_concurrent_retrievals(
            max_concurrent_retrievals
        )

    def execute(self, payload: object) -> VisualizationBatchResponse:
        """Turn one external payload into complete ordered chart responses."""

        request = self._request_validator.validate(payload)
        filter_names = ",".join(sorted(request.filters.to_dict())) or "none"
        _LOGGER.debug("chart_flow_validated filter_names=%s", filter_names)
        plans = self._query_planner.plan_many(request)
        _LOGGER.debug(
            "chart_flow_planned request_count=%d",
            len(plans),
        )
        retrievals = self._retrieve_all(plans)
        responses = tuple(
            self._build_response(plan, retrieval)
            for plan, retrieval in zip(plans, retrievals, strict=True)
        )
        return VisualizationBatchResponse(results=responses)

    @staticmethod
    def _validate_max_concurrent_retrievals(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                "max_concurrent_retrievals must be an integer from 1 to 5."
            )
        if not 1 <= value <= 5:
            raise ValueError(
                "max_concurrent_retrievals must be an integer from 1 to 5."
            )
        return value

    def _retrieve_all(
        self,
        plans: tuple[QueryPlan, ...],
    ) -> tuple[TrialRetrievalResult, ...]:
        """Fetch independent source searches concurrently while preserving order."""

        if not plans:
            raise ValueError("query_planner must return at least one QueryPlan.")
        if len(plans) == 1:
            return (self._trial_retriever.retrieve(plans[0]),)

        worker_count = min(self._max_concurrent_retrievals, len(plans))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = tuple(
                executor.submit(self._trial_retriever.retrieve, plan) for plan in plans
            )
            return tuple(future.result() for future in futures)

    def _build_response(
        self,
        plan: QueryPlan,
        retrieval: TrialRetrievalResult,
    ) -> VisualizationResponse:
        """Reject incomplete source data before mapping and chart construction."""

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
        if (
            retrieval.total_count is not None
            and retrieval.max_studies is not None
            and retrieval.total_count > retrieval.max_studies
        ):
            _LOGGER.warning(
                "chart_flow_result_limit_exceeded source_total_count=%d "
                "configured_max_studies=%d",
                retrieval.total_count,
                retrieval.max_studies,
            )
            raise TrialResultLimitExceededError(
                total_count=retrieval.total_count,
                max_studies=retrieval.max_studies,
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
        response = self._with_provenance(response, plan, retrieval, records)
        _LOGGER.debug(
            "chart_flow_completed chart_type=%s data_points=%d",
            response.visualization.chart_type.value,
            len(response.visualization.data),
        )
        return response

    @staticmethod
    def _with_provenance(
        response: VisualizationResponse,
        plan: QueryPlan,
        retrieval: TrialRetrievalResult,
        records: tuple[TrialRecord, ...],
    ) -> VisualizationResponse:
        """Attach compact source and planning context to a successful chart."""

        query_plan: dict[str, object] = {
            "chart_type": plan.chart_type.value,
            "group_by": plan.group_by.value,
            "series_by": plan.series_by.value if plan.series_by is not None else None,
            "measure": plan.measure.value,
            "sort": plan.sort.value,
        }
        if plan.comparison_values:
            query_plan["comparison_values"] = list(plan.comparison_values)
        return replace(
            response,
            meta=replace(
                response.meta,
                source_query=retrieval.query_parameters,
                source_total_count=retrieval.total_count,
                retrieved_study_count=len(records),
                source_trial_ids=tuple(sorted({record.nct_id for record in records})),
                query_plan=query_plan,
            ),
        )
