"""Send every saved query variation to the local Cheiron HTTP API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

EXAMPLES_DIRECTORY = Path(__file__).parent
DEFAULT_INPUT_PATH = EXAMPLES_DIRECTORY / "query-variation-inputs.jsonl"
DEFAULT_OUTPUT_PATH = EXAMPLES_DIRECTORY / "query-variation-results.jsonl"
DEFAULT_API_URL = "http://127.0.0.1:8000/api/v1/charts"


def main() -> int:
    """Run every JSON Lines case and replace the output file with its results."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--include-citations",
        choices=("true", "false"),
        help="Override the citation preference for every request in this run.",
    )
    arguments = parser.parse_args()

    if arguments.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive.")

    cases = _with_citation_preference(
        _load_cases(arguments.input),
        arguments.include_citations,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("w", encoding="utf-8") as output_file:
        for case in cases:
            result = _run_case(case, arguments.api_url, arguments.timeout_seconds)
            output_file.write(
                json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            )
            output_file.write("\n")
    return 0


def _load_cases(path: Path) -> list[dict[str, Any]]:
    """Read a well-formed, named suite of JSON Lines cases."""

    cases: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Input line {line_number} must be a JSON object.")
            case_id = value.get("id")
            request = value.get("request")
            if not isinstance(case_id, str) or not case_id:
                raise ValueError(f"Input line {line_number} must have a non-empty id.")
            if not isinstance(request, dict):
                raise ValueError(
                    f"Input line {line_number} must have an object request."
                )
            cases.append(value)
    if not cases:
        raise ValueError("The input file does not contain any test cases.")
    return cases


def _with_citation_preference(
    cases: list[dict[str, Any]],
    preference: str | None,
) -> list[dict[str, Any]]:
    """Copy cases with one optional citation setting applied to every request."""

    if preference is None:
        return cases
    include_citations = preference == "true"
    return [
        {
            **case,
            "request": {
                **case["request"],
                "include_citations": include_citations,
            },
        }
        for case in cases
    ]


def _run_case(
    case: dict[str, Any],
    api_url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Call the public HTTP endpoint once and keep the complete safe response."""

    body = json.dumps(case["request"], ensure_ascii=False).encode("utf-8")
    request = Request(
        api_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    result: dict[str, Any] = {
        "id": case["id"],
        "category": case.get("category"),
        "description": case.get("description"),
        "request": case["request"],
    }
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            result["http_status"] = response.status
            result["response"] = _decode_response(response.read())
    except HTTPError as error:
        result["http_status"] = error.code
        result["response"] = _decode_response(error.read())
    except TimeoutError:
        result["status"] = "timeout"
        result["error"] = f"Request timed out after {timeout_seconds:g} seconds."
    except URLError as error:
        result["status"] = "transport_error"
        result["error"] = str(error.reason)
    return result


def _decode_response(body: bytes) -> object:
    """Decode a JSON API response without hiding a malformed error body."""

    decoded = body.decode("utf-8", errors="replace")
    try:
        return json.loads(decoded)
    except json.JSONDecodeError:
        return {"raw_response": decoded}


if __name__ == "__main__":
    raise SystemExit(main())
