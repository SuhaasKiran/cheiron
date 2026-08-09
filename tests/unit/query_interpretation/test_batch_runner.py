"""Regression tests for batch query interpretation and optional API validation."""

from __future__ import annotations

from dataclasses import dataclass, field

from cheiron_core.clinicaltrials import (
    ClinicalTrialsApiTransportError,
    ClinicalTrialsSearchResult,
)
from cheiron_core.llm_query_planning import (
    ClinicalTrialsGovQuery,
    ClinicalTrialsQueryInterpretation,
)
from cheiron_core.models import TrialQueryRequest
from cheiron_core.query_interpretation_batch import _interpret_line


@dataclass
class FakeInterpreter:
    result: ClinicalTrialsQueryInterpretation
    requests: list[TrialQueryRequest] = field(default_factory=list)

    def interpret(
        self, request: TrialQueryRequest
    ) -> ClinicalTrialsQueryInterpretation:
        self.requests.append(request)
        return self.result


@dataclass
class FakeQueryFetcher:
    result: ClinicalTrialsSearchResult | Exception
    calls: list[dict[str, str]] = field(default_factory=list)

    def fetch_studies(
        self,
        query_parameters: dict[str, str],
        *,
        page_size: int,
        max_studies: int,
    ) -> ClinicalTrialsSearchResult:
        self.calls.append(query_parameters)
        assert page_size == 1
        assert max_studies == 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def supported_non_visual_interpretation() -> ClinicalTrialsQueryInterpretation:
    return ClinicalTrialsQueryInterpretation(
        is_supported=True,
        visualization_needed=False,
        clinicaltrials_query=ClinicalTrialsGovQuery(condition="Melanoma"),
        reason="The question requests individual study records.",
    )


def unsupported_interpretation() -> ClinicalTrialsQueryInterpretation:
    return ClinicalTrialsQueryInterpretation(
        is_supported=False,
        visualization_needed=False,
        reason="The question is outside ClinicalTrials.gov scope.",
    )


def search_result() -> ClinicalTrialsSearchResult:
    return ClinicalTrialsSearchResult(
        studies=({"id": "NCT00000001"},),
        total_count=12,
        pages_fetched=1,
        truncated=True,
        has_more_results=True,
    )


def test_batch_interpreter_only_mode_does_not_add_a_fetch_result() -> None:
    result = _interpret_line(
        1,
        '{"query":"List melanoma trials."}',
        FakeInterpreter(supported_non_visual_interpretation()),
        None,
    )

    assert result["status"] == "ok"
    assert result["clinicaltrials_gov_query"] == {"query.cond": "Melanoma"}
    assert "clinicaltrials_gov_fetch" not in result


def test_batch_fetches_supported_non_visual_queries() -> None:
    fetcher = FakeQueryFetcher(search_result())

    result = _interpret_line(
        1,
        '{"query":"List melanoma trials."}',
        FakeInterpreter(supported_non_visual_interpretation()),
        fetcher,
    )

    assert fetcher.calls == [{"query.cond": "Melanoma"}]
    assert result["clinicaltrials_gov_fetch"] == {
        "status": "ok",
        "total_count": 12,
        "returned_studies": 1,
        "has_more_results": True,
    }


def test_batch_skips_fetching_unsupported_queries() -> None:
    fetcher = FakeQueryFetcher(search_result())

    result = _interpret_line(
        1,
        '{"query":"What will the weather be tomorrow?"}',
        FakeInterpreter(unsupported_interpretation()),
        fetcher,
    )

    assert fetcher.calls == []
    assert result["clinicaltrials_gov_fetch"] == {
        "status": "skipped",
        "reason": "query_not_supported",
    }


def test_batch_serializes_clinicaltrials_fetch_failures() -> None:
    fetcher = FakeQueryFetcher(
        ClinicalTrialsApiTransportError("ClinicalTrials.gov could not be reached.")
    )

    result = _interpret_line(
        1,
        '{"query":"List melanoma trials."}',
        FakeInterpreter(supported_non_visual_interpretation()),
        fetcher,
    )

    assert result["status"] == "ok"
    assert result["clinicaltrials_gov_fetch"] == {
        "status": "error",
        "error": "ClinicalTrials.gov could not be reached.",
    }
