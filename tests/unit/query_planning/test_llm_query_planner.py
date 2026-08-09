"""Tests for LLM-backed ClinicalTrials.gov query interpretation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from cheiron_core.llm_query_planning import (
    ClinicalTrialsGovQuery,
    ClinicalTrialsQueryInterpretation,
    DspyClinicalTrialsQueryInterpreter,
    FallbackQueryPlanner,
    LangSmithDspyQueryProgramTracer,
    LlmQueryPlanner,
    QueryInterpretationProviderError,
    TracedDspyQueryProgram,
)
from cheiron_core.models import (
    ChartType,
    GroupBy,
    TrialFilters,
    TrialQueryRequest,
)
from cheiron_core.query_planning import SimpleQueryPlanner, UnsupportedQueryError
from cheiron_core.settings import LangSmithTracingSettings


@dataclass
class FakeInterpreter:
    result: ClinicalTrialsQueryInterpretation | Exception

    def interpret(
        self,
        request: TrialQueryRequest,
    ) -> ClinicalTrialsQueryInterpretation:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@dataclass
class FakeDspyProgram:
    result: str | Exception

    def run(self, *, question: str, explicit_filters_json: str) -> str:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@dataclass
class FakeLangSmithClientFactory:
    calls: list[dict[str, str]] = field(default_factory=list)

    def __call__(self, **kwargs: str) -> object:
        self.calls.append(kwargs)
        return object()


@dataclass
class FakeTraceableFactory:
    configuration: dict[str, Any] | None = None
    traced_inputs: dict[str, Any] | None = None
    traced_outputs: dict[str, Any] | None = None

    def __call__(self, **kwargs: Any) -> Any:
        self.configuration = kwargs

        def decorate(function: Any) -> Any:
            def wrapped(**call_kwargs: Any) -> Any:
                process_inputs = kwargs["process_inputs"]
                process_outputs = kwargs["process_outputs"]
                self.traced_inputs = process_inputs(call_kwargs)
                output = function(**call_kwargs)
                self.traced_outputs = process_outputs({"output": output})
                return output

            return wrapped

        return decorate


def supported_time_series_interpretation(
    *,
    condition: str | None = None,
) -> ClinicalTrialsQueryInterpretation:
    return ClinicalTrialsQueryInterpretation(
        is_supported=True,
        visualization_needed=True,
        chart_type=ChartType.TIME_SERIES,
        group_by=GroupBy.START_YEAR,
        clinicaltrials_query=ClinicalTrialsGovQuery(condition=condition),
        reason="The question asks for a count over time.",
    )


def test_llm_planner_converts_an_interpretation_to_a_query_plan() -> None:
    planner = LlmQueryPlanner(
        FakeInterpreter(supported_time_series_interpretation(condition="Bowel cancer"))
    )

    plan = planner.plan(
        TrialQueryRequest(query="Plot yearly registered studies for bowel cancer.")
    )

    assert plan.chart_type is ChartType.TIME_SERIES
    assert plan.group_by is GroupBy.START_YEAR
    assert plan.filters == TrialFilters(condition="Bowel cancer")


def test_llm_planner_preserves_explicit_request_filters_over_model_output() -> None:
    planner = LlmQueryPlanner(
        FakeInterpreter(supported_time_series_interpretation(condition="Lung cancer"))
    )

    plan = planner.plan(
        TrialQueryRequest(
            query="Show yearly trials for melanoma.",
            filters=TrialFilters(condition="Melanoma", start_year=2020),
        )
    )

    assert plan.filters == TrialFilters(condition="Melanoma", start_year=2020)


@pytest.mark.parametrize(
    "interpretation",
    [
        ClinicalTrialsQueryInterpretation(
            is_supported=False,
            visualization_needed=False,
            clinicaltrials_query=ClinicalTrialsGovQuery(),
            reason="This request is not about registered clinical studies.",
        ),
        ClinicalTrialsQueryInterpretation(
            is_supported=True,
            visualization_needed=False,
            clinicaltrials_query=ClinicalTrialsGovQuery(condition="Melanoma"),
            reason="The question asks for individual studies, not an aggregation.",
        ),
    ],
)
def test_llm_planner_rejects_non_visual_or_out_of_scope_queries(
    interpretation: ClinicalTrialsQueryInterpretation,
) -> None:
    planner = LlmQueryPlanner(FakeInterpreter(interpretation))

    with pytest.raises(UnsupportedQueryError, match="ClinicalTrials.gov"):
        planner.plan(TrialQueryRequest(query="A question"))


def test_fallback_planner_uses_keyword_matching_when_the_llm_fails() -> None:
    planner = FallbackQueryPlanner(
        primary=LlmQueryPlanner(
            FakeInterpreter(QueryInterpretationProviderError("provider timed out"))
        ),
        fallback=SimpleQueryPlanner(),
    )

    plan = planner.plan(
        TrialQueryRequest(query="How many melanoma trials started each year?")
    )

    assert plan.chart_type is ChartType.TIME_SERIES
    assert plan.group_by is GroupBy.START_YEAR


def test_fallback_planner_does_not_override_an_llm_unsupported_decision() -> None:
    planner = FallbackQueryPlanner(
        primary=LlmQueryPlanner(
            FakeInterpreter(
                ClinicalTrialsQueryInterpretation(
                    is_supported=False,
                    visualization_needed=False,
                    clinicaltrials_query=ClinicalTrialsGovQuery(),
                    reason="The question is incomplete.",
                )
            )
        ),
        fallback=SimpleQueryPlanner(),
    )

    with pytest.raises(UnsupportedQueryError, match="incomplete"):
        planner.plan(TrialQueryRequest(query="Show trials by phase."))


def test_dspy_interpreter_validates_the_program_json_response() -> None:
    interpreter = DspyClinicalTrialsQueryInterpreter(
        FakeDspyProgram(
            """
            {
              "is_supported": true,
              "visualization_needed": true,
              "chart_type": "bar_chart",
              "group_by": "trial_phase",
              "clinicaltrials_query": {"condition": "Melanoma"},
              "reason": "The question requests a phase distribution."
            }
            """
        )
    )

    interpretation = interpreter.interpret(
        TrialQueryRequest(query="Chart melanoma studies by phase.")
    )

    assert interpretation.chart_type is ChartType.BAR_CHART
    assert interpretation.group_by is GroupBy.TRIAL_PHASE
    assert interpretation.clinicaltrials_query.condition == "Melanoma"


def test_dspy_interpreter_wraps_invalid_model_output_as_an_operational_failure() -> (
    None
):
    interpreter = DspyClinicalTrialsQueryInterpreter(FakeDspyProgram("not JSON"))

    with pytest.raises(QueryInterpretationProviderError, match="valid response"):
        interpreter.interpret(
            TrialQueryRequest(query="Chart melanoma studies by phase.")
        )


def test_langsmith_tracer_redacts_query_content_and_preserves_dspy_execution() -> None:
    traceable_factory = FakeTraceableFactory()
    client_factory = FakeLangSmithClientFactory()
    tracer = LangSmithDspyQueryProgramTracer(
        settings=LangSmithTracingSettings(
            enabled=True,
            api_key="test-key",
            endpoint="https://smith.example.test",
            project="cheiron-test",
        ),
        model="gpt-5.1",
        traceable_factory=traceable_factory,
        client_factory=client_factory,
    )
    program = TracedDspyQueryProgram(
        FakeDspyProgram('{"is_supported": false}'),
        tracer,
    )

    response = program.run(
        question="Sensitive melanoma question",
        explicit_filters_json='{"condition":"Melanoma","start_year":2020}',
    )

    assert response == '{"is_supported": false}'
    assert client_factory.calls == [
        {"api_key": "test-key", "api_url": "https://smith.example.test"}
    ]
    assert traceable_factory.configuration is not None
    assert traceable_factory.configuration["run_type"] == "llm"
    assert traceable_factory.configuration["project_name"] == "cheiron-test"
    assert traceable_factory.traced_inputs == {
        "question_characters": 27,
        "explicit_filter_names": ["condition", "start_year"],
    }
    assert traceable_factory.traced_outputs == {"response_characters": 23}
