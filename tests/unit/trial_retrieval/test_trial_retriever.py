from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest
from cheiron_core.clinicaltrials import (
    ClinicalTrialsApiHttpError,
    ClinicalTrialsApiProtocolError,
    ClinicalTrialsApiTransportError,
    ClinicalTrialsSearchResult,
)
from cheiron_core.models import (
    ChartType,
    GroupBy,
    QueryPlan,
    TrialFilters,
)
from cheiron_core.trial_retrieval import (
    TrialRetrievalDependencyError,
    TrialRetrievalError,
    TrialRetrievalQueryError,
    TrialRetrievalSourceDataError,
    TrialRetriever,
)


@dataclass
class FakeStudySearchClient:
    result: ClinicalTrialsSearchResult | Exception
    calls: list[tuple[dict[str, str], int, int]] = field(default_factory=list)

    def fetch_studies(
        self,
        query_parameters: Mapping[str, str],
        *,
        page_size: int,
        max_studies: int,
    ) -> ClinicalTrialsSearchResult:
        self.calls.append((dict(query_parameters), page_size, max_studies))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def invalid_json_source_error() -> ClinicalTrialsApiTransportError:
    """Create the transport error used when the source returns invalid JSON."""

    try:
        json.loads("{")
    except json.JSONDecodeError as error:
        try:
            raise ClinicalTrialsApiTransportError(
                "ClinicalTrials.gov returned invalid JSON."
            ) from error
        except ClinicalTrialsApiTransportError as source_error:
            return source_error
    raise AssertionError("The invalid JSON fixture must raise JSONDecodeError.")


def test_retriever_translates_plan_filters_and_preserves_search_metadata() -> None:
    client = FakeStudySearchClient(
        ClinicalTrialsSearchResult(
            studies=({"id": "first"},),
            total_count=2_451,
            pages_fetched=10,
            truncated=True,
        )
    )
    plan = QueryPlan(
        filters=TrialFilters(
            condition="Melanoma",
            drug_name="Pembrolizumab",
            trial_phase="PHASE2",
            start_year=2020,
            end_year=2024,
        ),
        chart_type=ChartType.TIME_SERIES,
        group_by=GroupBy.START_YEAR,
    )

    result = TrialRetriever(client).retrieve(plan)

    assert client.calls == [
        (
            {
                "query.cond": "Melanoma",
                "query.intr": "Pembrolizumab",
                "filter.advanced": (
                    "AREA[Phase]PHASE2 AND AREA[StartDate]RANGE[2020-01-01,2024-12-31]"
                ),
            },
            100,
            1_000,
        )
    ]
    assert result.studies == ({"id": "first"},)
    assert result.total_count == 2_451
    assert result.pages_fetched == 10
    assert result.truncated is True
    assert result.max_studies == 1_000
    assert result.has_more_results is None
    assert result.query_parameters == client.calls[0][0]


def test_retriever_uses_open_ended_dates_and_allows_an_unfiltered_plan() -> None:
    client = FakeStudySearchClient(
        ClinicalTrialsSearchResult(
            studies=(), total_count=None, pages_fetched=1, truncated=False
        )
    )
    retriever = TrialRetriever(client)

    retriever.retrieve(
        QueryPlan(
            filters=TrialFilters(end_year=2024),
            chart_type=ChartType.BAR_CHART,
            group_by=GroupBy.TRIAL_PHASE,
        )
    )
    retriever.retrieve(
        QueryPlan(
            filters=TrialFilters(start_year=2020),
            chart_type=ChartType.BAR_CHART,
            group_by=GroupBy.TRIAL_PHASE,
        )
    )
    retriever.retrieve(
        QueryPlan(
            filters=TrialFilters(),
            chart_type=ChartType.BAR_CHART,
            group_by=GroupBy.TRIAL_PHASE,
        )
    )

    assert client.calls[0][0] == {
        "filter.advanced": "AREA[StartDate]RANGE[MIN,2024-12-31]"
    }
    assert client.calls[1][0] == {
        "filter.advanced": "AREA[StartDate]RANGE[2020-01-01,MAX]"
    }
    assert client.calls[2][0] == {}


def test_retriever_keeps_multi_drug_comparison_retrieval_condition_scoped() -> None:
    client = FakeStudySearchClient(
        ClinicalTrialsSearchResult(
            studies=(), total_count=0, pages_fetched=0, truncated=False
        )
    )
    plan = QueryPlan(
        filters=TrialFilters(
            condition="Melanoma",
            drug_names=("Pembrolizumab", "Nivolumab"),
        ),
        chart_type=ChartType.GROUPED_BAR_CHART,
        group_by=GroupBy.TRIAL_PHASE,
        series_by=GroupBy.INTERVENTION,
        comparison_values=("Pembrolizumab", "Nivolumab"),
    )

    TrialRetriever(client).retrieve(plan)

    assert client.calls[0][0] == {"query.cond": "Melanoma"}


def test_retriever_converts_an_api_failure_to_a_clear_application_error() -> None:
    client = FakeStudySearchClient(
        ClinicalTrialsApiTransportError("ClinicalTrials.gov could not be reached.")
    )
    plan = QueryPlan(
        filters=TrialFilters(condition="Melanoma"),
        chart_type=ChartType.BAR_CHART,
        group_by=GroupBy.TRIAL_PHASE,
    )

    with pytest.raises(
        TrialRetrievalDependencyError, match="could not retrieve"
    ) as error:
        TrialRetriever(client).retrieve(plan)

    assert isinstance(error.value.__cause__, ClinicalTrialsApiTransportError)


@pytest.mark.parametrize(
    ("source_error", "expected_error"),
    (
        (ClinicalTrialsApiHttpError(status_code=400), TrialRetrievalQueryError),
        (
            ClinicalTrialsApiProtocolError("invalid response"),
            TrialRetrievalSourceDataError,
        ),
        (invalid_json_source_error(), TrialRetrievalSourceDataError),
        (ClinicalTrialsApiHttpError(status_code=503), TrialRetrievalDependencyError),
    ),
)
def test_retriever_preserves_source_failure_categories(
    source_error: Exception,
    expected_error: type[TrialRetrievalError],
) -> None:
    client = FakeStudySearchClient(source_error)
    plan = QueryPlan(
        filters=TrialFilters(condition="Melanoma"),
        chart_type=ChartType.BAR_CHART,
        group_by=GroupBy.TRIAL_PHASE,
    )

    with pytest.raises(expected_error) as raised_error:
        TrialRetriever(client).retrieve(plan)

    assert raised_error.value.__cause__ is source_error


def test_retriever_rejects_an_unknown_phase_before_calling_the_api() -> None:
    client = FakeStudySearchClient(
        ClinicalTrialsSearchResult(
            studies=(), total_count=None, pages_fetched=1, truncated=False
        )
    )
    plan = QueryPlan(
        filters=TrialFilters(trial_phase="PHASE2 OR AREA[Phase]PHASE3"),
        chart_type=ChartType.BAR_CHART,
        group_by=GroupBy.TRIAL_PHASE,
    )

    with pytest.raises(TrialRetrievalError, match="trial_phase"):
        TrialRetriever(client).retrieve(plan)

    assert client.calls == []


@pytest.mark.parametrize(
    ("page_size", "max_studies"),
    [(0, 100), (1_001, 100), (100, 0), (100, 10_001)],
)
def test_retriever_rejects_unsafe_configured_limits(
    page_size: int, max_studies: int
) -> None:
    client = FakeStudySearchClient(
        ClinicalTrialsSearchResult(
            studies=(), total_count=None, pages_fetched=1, truncated=False
        )
    )

    with pytest.raises(ValueError, match="page_size|max_studies"):
        TrialRetriever(client, page_size=page_size, max_studies=max_studies)
