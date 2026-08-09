"""Tests for local JSON Lines example-runner options."""

from __future__ import annotations

import pytest

import examples.run_query_variations as runner
from examples.run_query_variations import _with_citation_preference


def test_citation_override_copies_each_request_without_mutating_input() -> None:
    cases = [{"id": "one", "request": {"query": "Show trials by phase."}}]

    updated = _with_citation_preference(cases, "false")

    assert updated[0]["request"]["include_citations"] is False
    assert "include_citations" not in cases[0]["request"]


def test_missing_citation_override_keeps_the_original_cases() -> None:
    cases = [{"id": "one", "request": {"query": "Show trials by phase."}}]

    assert _with_citation_preference(cases, None) is cases


def test_timeout_is_recorded_without_aborting_the_example_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timed_out_urlopen(*_: object, **__: object) -> object:
        raise TimeoutError

    monkeypatch.setattr(runner, "urlopen", timed_out_urlopen)

    result = runner._run_case(
        {"id": "one", "request": {"query": "Show trials by phase."}},
        "http://127.0.0.1:8000/api/v1/charts",
        30.0,
    )

    assert result["status"] == "timeout"
    assert result["error"] == "Request timed out after 30 seconds."
