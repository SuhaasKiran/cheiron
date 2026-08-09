"""Batch CLI for testing ClinicalTrials.gov query interpretation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Protocol, TextIO

from cheiron_core.clinicaltrials import (
    ClinicalTrialsApiClient,
    ClinicalTrialsApiError,
    ClinicalTrialsSearchResult,
)
from cheiron_core.llm_query_planning import (
    ClinicalTrialsQueryInterpreter,
    DspyClinicalTrialsQueryInterpreter,
    DspyClinicalTrialsQueryProgram,
    LangSmithDspyQueryProgramTracer,
    QueryInterpretationProviderError,
    TracedDspyQueryProgram,
)
from cheiron_core.request_validation import RequestValidationError, RequestValidator
from cheiron_core.settings import Settings, load_settings


class ClinicalTrialsQueryFetcher(Protocol):
    """Fetch the smallest result set needed to validate a generated query."""

    def fetch_studies(
        self,
        query_parameters: dict[str, str],
        *,
        page_size: int,
        max_studies: int,
    ) -> ClinicalTrialsSearchResult:
        """Return a bounded ClinicalTrials.gov search result."""


def main() -> int:
    """Run the configured LLM interpreter over a JSON Lines input file."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON Lines input file")
    parser.add_argument("output", type=Path, help="JSON Lines output file")
    parser.add_argument(
        "--fetch-results",
        action="store_true",
        help="Validate generated queries with a one-record ClinicalTrials.gov search.",
    )
    arguments = parser.parse_args()

    settings = load_settings()
    if settings.openai is None:
        parser.error("OPENAI_API_KEY and OPENAI_MODEL must be configured.")
    interpreter = _create_interpreter(settings)
    query_fetcher = ClinicalTrialsApiClient() if arguments.fetch_results else None

    with (
        arguments.input.open(encoding="utf-8") as input_file,
        arguments.output.open("w", encoding="utf-8") as output_file,
    ):
        for line_number, line in enumerate(input_file, start=1):
            _write_result(
                output_file,
                _interpret_line(line_number, line, interpreter, query_fetcher),
            )
    return 0


def _create_interpreter(settings: Settings) -> DspyClinicalTrialsQueryInterpreter:
    if settings.openai is None:
        raise ValueError("OpenAI settings are required.")
    program = DspyClinicalTrialsQueryProgram(
        api_key=settings.openai.api_key,
        model=settings.openai.model,
    )
    traced_program = (
        TracedDspyQueryProgram(
            program,
            LangSmithDspyQueryProgramTracer(
                settings=settings.langsmith,
                model=settings.openai.model,
            ),
        )
        if settings.langsmith.enabled
        else program
    )
    return DspyClinicalTrialsQueryInterpreter(traced_program)


def _interpret_line(
    line_number: int,
    line: str,
    interpreter: ClinicalTrialsQueryInterpreter,
    query_fetcher: ClinicalTrialsQueryFetcher | None,
) -> dict[str, object]:
    try:
        payload = json.loads(line)
        request = RequestValidator().validate(payload)
        interpretation = interpreter.interpret(request)
        query_parameters = interpretation.clinicaltrials_query.to_api_query_parameters()
        result: dict[str, object] = {
            "line": line_number,
            "status": "ok",
            "interpretation": interpretation.model_dump(mode="json"),
            "clinicaltrials_gov_query": query_parameters,
        }
        if query_fetcher is not None:
            result["clinicaltrials_gov_fetch"] = (
                _fetch_query(query_fetcher, query_parameters)
                if interpretation.is_supported
                else {"status": "skipped", "reason": "query_not_supported"}
            )
        return result
    except (
        json.JSONDecodeError,
        QueryInterpretationProviderError,
        RequestValidationError,
        ValueError,
    ) as error:
        return {"line": line_number, "status": "error", "error": str(error)}


def _fetch_query(
    query_fetcher: ClinicalTrialsQueryFetcher,
    query_parameters: dict[str, str],
) -> dict[str, object]:
    """Test query validity without downloading more than one study."""

    try:
        result = query_fetcher.fetch_studies(
            query_parameters,
            page_size=1,
            max_studies=1,
        )
    except ClinicalTrialsApiError as error:
        return {"status": "error", "error": str(error)}
    return {
        "status": "ok",
        "total_count": result.total_count,
        "returned_studies": len(result.studies),
        "has_more_results": result.has_more_results,
    }


def _write_result(output_file: TextIO, result: dict[str, object]) -> None:
    output_file.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    output_file.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
