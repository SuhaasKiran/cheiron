"""Tests for LLM-backed ClinicalTrials.gov query interpretation."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread
from typing import Any

import pytest
from cheiron_core.chart_rendering import ChartRendererRegistry, TimeSeriesRenderer
from cheiron_core.llm_query_planning import (
    BoundedLlmQueryPlanner,
    ClinicalTrialsGovQuery,
    ClinicalTrialsQueryInterpretation,
    ClinicalTrialsQueryInterpretationBatch,
    DspyClinicalTrialsQueryInterpreter,
    LangSmithDspyQueryProgramTracer,
    LlmPlanningCapacityError,
    LlmPlanningRateLimitError,
    LlmQueryPlanner,
    LlmQueryPlannerError,
    QueryInterpretationProviderError,
    TracedDspyQueryProgram,
)
from cheiron_core.models import (
    ChartType,
    GroupBy,
    QueryPlan,
    TrialFilters,
    TrialQueryRequest,
)
from cheiron_core.query_planning import UnsupportedQueryError
from cheiron_core.settings import LangSmithTracingSettings


@dataclass
class FakeInterpreter:
    result: (
        ClinicalTrialsQueryInterpretation
        | tuple[ClinicalTrialsQueryInterpretation, ...]
        | Exception
    )

    def interpret(
        self,
        request: TrialQueryRequest,
    ) -> ClinicalTrialsQueryInterpretationBatch:
        if isinstance(self.result, Exception):
            raise self.result
        requests = self.result if isinstance(self.result, tuple) else (self.result,)
        return ClinicalTrialsQueryInterpretationBatch(requests=requests)


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


@dataclass
class BlockingPlanner:
    """Block one plan call so a capacity rejection can be tested locally."""

    started: Event
    release: Event

    def plan(self, request: TrialQueryRequest) -> QueryPlan:
        self.started.set()
        assert self.release.wait(timeout=1)
        return QueryPlan(
            filters=request.filters,
            chart_type=ChartType.BAR_CHART,
            group_by=GroupBy.TRIAL_PHASE,
        )

    def plan_many(self, request: TrialQueryRequest) -> tuple[QueryPlan, ...]:
        return (self.plan(request),)


@dataclass
class FakeClock:
    """A controllable monotonic clock for rolling-rate-limit tests."""

    now: float = 0

    def __call__(self) -> float:
        return self.now


def supported_time_series_interpretation(
    *,
    condition: str | None = None,
    trial_phase: str | None = None,
) -> ClinicalTrialsQueryInterpretation:
    return ClinicalTrialsQueryInterpretation(
        is_supported=True,
        visualization_needed=True,
        chart_type=ChartType.TIME_SERIES,
        group_by=GroupBy.START_YEAR,
        clinicaltrials_query=ClinicalTrialsGovQuery(
            condition=condition,
            trial_phase=trial_phase,
        ),
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


def test_llm_planner_uses_the_constrained_multi_drug_plan_without_llm_output() -> None:
    planner = LlmQueryPlanner(
        FakeInterpreter(QueryInterpretationProviderError("must not be called"))
    )

    plan = planner.plan(
        TrialQueryRequest(
            query="Compare these drugs by phase.",
            filters=TrialFilters(
                condition="Melanoma",
                drug_names=("Pembrolizumab", "Nivolumab"),
            ),
        )
    )

    assert plan.chart_type is ChartType.GROUPED_BAR_CHART
    assert plan.group_by is GroupBy.TRIAL_PHASE
    assert plan.series_by is GroupBy.INTERVENTION
    assert plan.comparison_values == ("Pembrolizumab", "Nivolumab")


def test_llm_planner_rejects_an_inferred_filter_not_in_the_question() -> None:
    planner = LlmQueryPlanner(
        FakeInterpreter(supported_time_series_interpretation(condition="Melanoma"))
    )

    with pytest.raises(UnsupportedQueryError, match="could not safely verify"):
        planner.plan(TrialQueryRequest(query="Show trials by year."))


def test_llm_planner_rejects_an_inferred_na_phase_in_an_unrelated_word() -> None:
    planner = LlmQueryPlanner(
        FakeInterpreter(supported_time_series_interpretation(trial_phase="NA"))
    )

    with pytest.raises(UnsupportedQueryError, match="could not safely verify"):
        planner.plan(TrialQueryRequest(query="Show national trials by year."))


def test_llm_planner_creates_an_extended_chart_plan() -> None:
    planner = LlmQueryPlanner(
        FakeInterpreter(
            ClinicalTrialsQueryInterpretation(
                is_supported=True,
                visualization_needed=True,
                chart_type=ChartType.NETWORK_GRAPH,
                group_by=GroupBy.INTERVENTION,
                series_by=GroupBy.SPONSOR,
                reason="The question asks for drug and sponsor relationships.",
            )
        )
    )

    plan = planner.plan(
        TrialQueryRequest(query="Show the network of interventions and sponsors.")
    )

    assert plan.chart_type is ChartType.NETWORK_GRAPH
    assert plan.group_by is GroupBy.INTERVENTION
    assert plan.series_by is GroupBy.SPONSOR


def test_llm_planner_rejects_an_ambiguous_phase_and_year_interpretation() -> None:
    planner = LlmQueryPlanner(
        FakeInterpreter(
            ClinicalTrialsQueryInterpretation(
                is_supported=True,
                visualization_needed=True,
                chart_type=ChartType.SCATTER_PLOT,
                group_by=GroupBy.START_YEAR,
                series_by=GroupBy.TRIAL_PHASE,
                reason="The question includes phase and year.",
            )
        )
    )

    with pytest.raises(UnsupportedQueryError, match="ambiguous phase-by-year"):
        planner.plan(TrialQueryRequest(query="Show trials by phase and year."))


def test_llm_planner_creates_ordered_plans_for_independent_requests() -> None:
    planner = LlmQueryPlanner(
        FakeInterpreter(
            (
                ClinicalTrialsQueryInterpretation(
                    is_supported=True,
                    visualization_needed=True,
                    chart_type=ChartType.BAR_CHART,
                    group_by=GroupBy.TRIAL_PHASE,
                    clinicaltrials_query=ClinicalTrialsGovQuery(condition="Melanoma"),
                    reason="Show a phase distribution.",
                ),
                supported_time_series_interpretation(condition="Lung cancer"),
            )
        )
    )

    plans = planner.plan_many(
        TrialQueryRequest(
            query=(
                "Show melanoma trials by phase and lung cancer trials by start year."
            )
        )
    )

    assert [plan.chart_type for plan in plans] == [
        ChartType.BAR_CHART,
        ChartType.TIME_SERIES,
    ]
    assert [plan.filters.condition for plan in plans] == ["Melanoma", "Lung cancer"]


def test_llm_planner_rejects_a_chart_disabled_by_the_registry() -> None:
    planner = LlmQueryPlanner(
        FakeInterpreter(
            ClinicalTrialsQueryInterpretation(
                is_supported=True,
                visualization_needed=True,
                chart_type=ChartType.BAR_CHART,
                group_by=GroupBy.TRIAL_PHASE,
                reason="The question asks for a phase distribution.",
            )
        ),
        ChartRendererRegistry((TimeSeriesRenderer(),)),
    )

    with pytest.raises(UnsupportedQueryError, match="bar_chart is not enabled"):
        planner.plan(TrialQueryRequest(query="Show trials by phase."))


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


def test_llm_planner_does_not_broaden_query_when_llm_is_unavailable() -> None:
    planner = LlmQueryPlanner(
        FakeInterpreter(QueryInterpretationProviderError("provider timed out"))
    )

    with pytest.raises(LlmQueryPlannerError, match="could not interpret"):
        planner.plan(TrialQueryRequest(query="Show melanoma trials by phase."))


def test_bounded_llm_planner_rejects_work_above_its_concurrency_limit() -> None:
    started = Event()
    release = Event()
    planner = BoundedLlmQueryPlanner(
        BlockingPlanner(started, release),
        max_concurrent_requests=1,
        max_requests_per_minute=10,
    )
    request = TrialQueryRequest(query="Show trials by phase.")
    completed_plans: list[QueryPlan] = []
    worker = Thread(target=lambda: completed_plans.append(planner.plan(request)))

    worker.start()
    assert started.wait(timeout=1)
    with pytest.raises(LlmPlanningCapacityError, match="at capacity"):
        planner.plan(request)

    release.set()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert len(completed_plans) == 1
    assert planner.plan(request).chart_type is ChartType.BAR_CHART


def test_bounded_llm_planner_rejects_work_above_its_request_rate_limit() -> None:
    clock = FakeClock()
    release = Event()
    release.set()
    planner = BoundedLlmQueryPlanner(
        BlockingPlanner(Event(), release),
        max_concurrent_requests=1,
        max_requests_per_minute=2,
        clock=clock,
    )
    request = TrialQueryRequest(query="Show trials by phase.")

    planner.plan(request)
    planner.plan(request)
    with pytest.raises(LlmPlanningRateLimitError, match="request rate limit") as error:
        planner.plan(request)

    assert error.value.retry_after_seconds == 60
    clock.now = 60
    assert planner.plan(request).chart_type is ChartType.BAR_CHART


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

    result = interpretation.requests[0]
    assert result.chart_type is ChartType.BAR_CHART
    assert result.group_by is GroupBy.TRIAL_PHASE
    assert result.clinicaltrials_query.condition == "Melanoma"


def test_dspy_interpreter_normalizes_extended_chart_terms() -> None:
    interpreter = DspyClinicalTrialsQueryInterpreter(
        FakeDspyProgram(
            """
            {
              "is_supported": true,
              "visualization_needed": true,
              "chart_type": "network",
              "group_by": "conditions",
              "series_by": "sites",
              "clinicaltrials_query": {},
              "reason": "The question requests condition and site relationships."
            }
            """
        )
    )

    interpretation = interpreter.interpret(
        TrialQueryRequest(query="Show conditions connected to sites.")
    )

    result = interpretation.requests[0]
    assert result.chart_type is ChartType.NETWORK_GRAPH
    assert result.group_by is GroupBy.CONDITION
    assert result.series_by is GroupBy.SITE


def test_dspy_interpreter_validates_multiple_independent_requests() -> None:
    interpreter = DspyClinicalTrialsQueryInterpreter(
        FakeDspyProgram(
            """
            {
              "requests": [
                {
                  "is_supported": true,
                  "visualization_needed": true,
                  "chart_type": "bar_chart",
                  "group_by": "trial_phase",
                  "clinicaltrials_query": {"condition": "Melanoma"},
                  "reason": "Show phases for melanoma."
                },
                {
                  "is_supported": true,
                  "visualization_needed": true,
                  "chart_type": "time_series",
                  "group_by": "start_year",
                  "clinicaltrials_query": {"condition": "Lung cancer"},
                  "reason": "Show yearly lung cancer trials."
                }
              ]
            }
            """
        )
    )

    interpretations = interpreter.interpret(
        TrialQueryRequest(
            query="Show melanoma trials by phase and lung cancer trials by year."
        )
    )

    assert [item.chart_type for item in interpretations.requests] == [
        ChartType.BAR_CHART,
        ChartType.TIME_SERIES,
    ]


def test_dspy_interpreter_converts_an_empty_request_list_to_out_of_scope() -> None:
    interpretation = DspyClinicalTrialsQueryInterpreter(
        FakeDspyProgram('{"requests": []}')
    ).interpret(TrialQueryRequest(query="What will the weather be in Boston tomorrow?"))

    assert len(interpretation.requests) == 1
    result = interpretation.requests[0]
    assert result.is_supported is False
    assert result.visualization_needed is False
    assert result.chart_type is None
    assert result.clinicaltrials_query == ClinicalTrialsGovQuery()


def test_dspy_interpreter_canonicalizes_an_unsupported_request() -> None:
    interpretation = DspyClinicalTrialsQueryInterpreter(
        FakeDspyProgram(
            """
            {
              "requests": [
                {
                  "is_supported": false,
                  "visualization_needed": true,
                  "chart_type": "bar_chart",
                  "group_by": "trial_phase",
                  "clinicaltrials_query": {"condition": "Boston"},
                  "reason": "Weather is outside the source scope."
                }
              ]
            }
            """
        )
    ).interpret(TrialQueryRequest(query="What will the weather be in Boston tomorrow?"))

    result = interpretation.requests[0]
    assert result.is_supported is False
    assert result.visualization_needed is False
    assert result.chart_type is None
    assert result.group_by is None
    assert result.clinicaltrials_query == ClinicalTrialsGovQuery()


@pytest.mark.parametrize(
    ("model_output", "chart_type", "group_by", "series_by"),
    [
        (
            """
            {
              "is_supported": true,
              "visualization_needed": true,
              "visualization_type": "grouped bar",
              "group": "phase",
              "series": "sponsors",
              "clinicaltrials_query": {},
              "reason": "Compare trial phases across sponsors."
            }
            """,
            ChartType.GROUPED_BAR_CHART,
            GroupBy.TRIAL_PHASE,
            GroupBy.SPONSOR,
        ),
        (
            """
            {
              "is_supported": true,
              "visualization_needed": true,
              "chart_type": "scatter plot",
              "x_field": "start year",
              "y_field": "intervention count",
              "clinicaltrials_query": {},
              "reason": "Compare intervention counts over start years."
            }
            """,
            ChartType.SCATTER_PLOT,
            GroupBy.START_YEAR,
            GroupBy.INTERVENTION,
        ),
        (
            """
            {
              "is_supported": true,
              "visualization_needed": true,
              "chart_type": "network",
              "source_entity": "sponsors",
              "target_entity": "drugs",
              "clinicaltrials_query": {},
              "reason": "Connect sponsors to interventions."
            }
            """,
            ChartType.NETWORK_GRAPH,
            GroupBy.SPONSOR,
            GroupBy.INTERVENTION,
        ),
        (
            """
            {
              "is_supported": true,
              "visualization_needed": true,
              "visualization": {
                "type": "line-chart",
                "grouping": "start year"
              },
              "clinicaltrials_gov_query": {},
              "reason": "Show how trials change over time."
            }
            """,
            ChartType.TIME_SERIES,
            GroupBy.START_YEAR,
            None,
        ),
    ],
)
def test_dspy_interpreter_normalizes_common_semantic_chart_fields(
    model_output: str,
    chart_type: ChartType,
    group_by: GroupBy,
    series_by: GroupBy | None,
) -> None:
    interpretation = DspyClinicalTrialsQueryInterpreter(
        FakeDspyProgram(model_output)
    ).interpret(TrialQueryRequest(query="A clinical-trial visualization question."))

    result = interpretation.requests[0]
    assert result.chart_type is chart_type
    assert result.group_by is group_by
    assert result.series_by is series_by


@pytest.mark.parametrize("wrapper_name", ("additional_filters", "other_filters"))
def test_dspy_interpreter_ignores_empty_legacy_filter_wrappers(
    wrapper_name: str,
) -> None:
    interpreter = DspyClinicalTrialsQueryInterpreter(
        FakeDspyProgram(
            f"""
            {{
              "is_supported": true,
              "visualization_needed": true,
              "chart_type": "time_series",
              "group_by": "start_year",
              "series_by": null,
              "clinicaltrials_query": {{
                "condition": "Melanoma",
                "{wrapper_name}": {{}}
              }},
              "reason": "Show change in trial counts over time."
            }}
            """
        )
    )

    interpretation = interpreter.interpret(
        TrialQueryRequest(query="How have melanoma trials changed over time?")
    )

    assert interpretation.requests[0].clinicaltrials_query.condition == "Melanoma"


def test_dspy_interpreter_rejects_an_unsupported_nested_filter() -> None:
    interpreter = DspyClinicalTrialsQueryInterpreter(
        FakeDspyProgram(
            """
            {
              "is_supported": true,
              "visualization_needed": true,
              "chart_type": "bar_chart",
              "group_by": "trial_phase",
              "clinicaltrials_query": {
                "additional_filters": {"sponsor": "Example Sponsor"}
              },
              "reason": "Show trial phases."
            }
            """
        )
    )

    with pytest.raises(QueryInterpretationProviderError, match="extra_forbidden"):
        interpreter.interpret(TrialQueryRequest(query="Show trials by phase."))


def test_dspy_interpreter_wraps_invalid_model_output_as_an_operational_failure() -> (
    None
):
    interpreter = DspyClinicalTrialsQueryInterpreter(FakeDspyProgram("not JSON"))

    with pytest.raises(QueryInterpretationProviderError, match="valid response"):
        interpreter.interpret(
            TrialQueryRequest(query="Chart melanoma studies by phase.")
        )


def test_dspy_interpreter_reports_safe_schema_diagnostics() -> None:
    interpreter = DspyClinicalTrialsQueryInterpreter(
        FakeDspyProgram(
            """
            {
              "is_supported": false,
              "visualization_needed": false,
              "reason": "Outside scope.",
              "unexpected": true
            }
            """
        )
    )

    with pytest.raises(
        QueryInterpretationProviderError,
        match=r"requests.0.unexpected:extra_forbidden",
    ):
        interpreter.interpret(TrialQueryRequest(query="Chart melanoma trials."))


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
