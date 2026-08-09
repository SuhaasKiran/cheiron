"""Contract checks for the manually runnable query-variation suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

INPUT_PATH = Path(__file__).parents[3] / "examples" / "query-variation-inputs.jsonl"

REQUIRED_CATEGORIES = {
    "query-vis-needed",
    "query-no-vis-needed",
    "only-query-input",
    "invalid-query-valid-fields",
    "empty-query",
    "unrelated-query",
    "incomplete-query",
    "multi-charts",
    "multi-queries",
    "noisy-queries",
    "adversarial-queries",
}

REQUIRED_CHART_TYPES = {
    "bar_chart",
    "grouped_bar_chart",
    "time_series",
    "scatter_plot",
    "histogram",
    "network_graph",
}


def test_query_variation_suite_has_unique_cases_and_required_coverage() -> None:
    cases = _load_cases()

    case_ids = [case["id"] for case in cases]
    assert all(isinstance(case_id, str) and case_id for case_id in case_ids)
    assert len(case_ids) == len(set(case_ids))
    assert REQUIRED_CATEGORIES.issubset({case["category"] for case in cases})
    assert REQUIRED_CHART_TYPES == {
        case["expected_chart_type"] for case in cases if "expected_chart_type" in case
    }
    assert all(isinstance(case.get("request"), dict) for case in cases)


def _load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line in INPUT_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = cast(object, json.loads(line))
        assert isinstance(value, dict)
        cases.append(cast(dict[str, Any], value))
    return cases
