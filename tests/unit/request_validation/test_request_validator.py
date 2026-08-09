from __future__ import annotations

import pytest
from cheiron_core.models import TrialFilters, TrialQueryRequest
from cheiron_core.request_validation import RequestValidationError, RequestValidator


def test_validator_builds_a_normalized_request_from_a_valid_payload() -> None:
    request = RequestValidator().validate(
        {
            "query": "  How many melanoma trials started each year?  ",
            "filters": {
                "condition": " Melanoma ",
                "start_year": 2020,
                "end_year": 2024,
            },
        }
    )

    assert request == TrialQueryRequest(
        query="How many melanoma trials started each year?",
        filters=TrialFilters(condition="Melanoma", start_year=2020, end_year=2024),
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"query": "trials by phase", "unexpected": "value"}, "unexpected"),
        ({"query": "trials by phase", "filters": {"site": "Boston"}}, "site"),
        ({"query": "trials by phase", "filters": []}, "filters must be an object"),
        ({"query": "trials by phase", "filters": {"start_year": True}}, "integer"),
        ({"filters": {}}, "query"),
    ],
)
def test_validator_rejects_an_invalid_payload_shape(
    payload: object, message: str
) -> None:
    with pytest.raises(RequestValidationError, match=message):
        RequestValidator().validate(payload)


def test_validator_reports_model_validation_errors_at_the_request_boundary() -> None:
    with pytest.raises(RequestValidationError, match="end_year"):
        RequestValidator().validate(
            {
                "query": "trials by phase",
                "filters": {"start_year": 2024, "end_year": 2020},
            }
        )


def test_validator_rejects_payloads_larger_than_its_configured_limit() -> None:
    validator = RequestValidator(max_payload_bytes=20)

    with pytest.raises(RequestValidationError, match="must not exceed 20 bytes"):
        validator.validate({"query": "trials by phase", "filters": {}})
