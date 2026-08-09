from __future__ import annotations

import json
from pathlib import Path

import pytest
from cheiron_core.clinicaltrials.record_mapper import (
    ClinicalTrialsRecordMappingError,
    map_trial_record,
    map_trial_records,
)

FIXTURE_PATH = (
    Path(__file__).parents[2] / "fixtures" / "clinicaltrials" / "nct00000102.json"
)


def test_mapper_extracts_chart_fields_from_a_saved_api_record() -> None:
    raw_study = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    record = map_trial_record(raw_study)

    assert record.nct_id == "NCT00000102"
    assert record.start_date is None
    assert record.start_year is None
    assert record.phases == ("PHASE1", "PHASE2")
    assert record.conditions == ("Congenital Adrenal Hyperplasia",)
    assert record.interventions == ("Nifedipine",)
    assert record.sponsor == "National Center for Research Resources (NCRR)"
    assert record.investigators == ()
    assert record.sites == ("Medical University of South Carolina",)
    assert record.recruitment_status == "COMPLETED"
    assert record.countries == ("United States",)
    assert record.source_fields == {
        "nct_id": "NCT00000102",
        "start_date": None,
        "phases": ("PHASE1", "PHASE2"),
        "conditions": ("Congenital Adrenal Hyperplasia",),
        "interventions": ("Nifedipine",),
        "sponsor": "National Center for Research Resources (NCRR)",
        "investigators": (),
        "sites": ("Medical University of South Carolina",),
        "recruitment_status": "COMPLETED",
        "countries": ("United States",),
    }
    raw_study["protocolSection"]["identificationModule"]["nctId"] = "NCT99999999"
    assert record.source_fields["nct_id"] == "NCT00000102"
    with pytest.raises(TypeError):
        record.source_fields["nct_id"] = "NCT99999999"  # type: ignore[index]


def test_mapper_handles_missing_optional_fields_and_preserves_record_order() -> None:
    raw_studies = (
        {"protocolSection": {"identificationModule": {"nctId": "NCT00000101"}}},
        {"protocolSection": {"identificationModule": {"nctId": "NCT00000102"}}},
    )

    records = map_trial_records(raw_studies)

    assert [record.nct_id for record in records] == ["NCT00000101", "NCT00000102"]
    assert records[0].start_date is None
    assert records[0].phases == ()
    assert records[0].conditions == ()
    assert records[0].interventions == ()
    assert records[0].sponsor is None
    assert records[0].investigators == ()
    assert records[0].sites == ()
    assert records[0].recruitment_status is None
    assert records[0].countries == ()


@pytest.mark.parametrize(
    ("start_date", "start_year"),
    [("2024", 2024), ("2024-06", 2024), ("2024-06-30", 2024)],
)
def test_mapper_preserves_supported_date_precision(
    start_date: str, start_year: int
) -> None:
    raw_study = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000102"},
            "statusModule": {"startDateStruct": {"date": start_date}},
            "designModule": {"phases": ["PHASE2", "PHASE2", "PHASE3"]},
            "conditionsModule": {"conditions": ["Asthma", "Asthma", "COPD"]},
            "armsInterventionsModule": {
                "interventions": [
                    {"type": "DRUG", "name": "Drug A"},
                    {"type": "DRUG", "name": "Drug A"},
                    {"type": "DRUG", "name": "Drug B"},
                ]
            },
            "contactsLocationsModule": {
                "overallOfficials": [
                    {"name": "Dr. Smith"},
                    {"name": "Dr. Smith"},
                    {"name": "Dr. Jones"},
                ],
                "locations": [
                    {"country": "United States", "facility": "Site A"},
                    {"country": "United States", "facility": "Site A"},
                    {"country": "Canada", "facility": "Site B"},
                    {"city": "Unknown"},
                ],
            },
        }
    }

    record = map_trial_record(raw_study)

    assert record.start_date == start_date
    assert record.start_year == start_year
    assert record.phases == ("PHASE2", "PHASE3")
    assert record.conditions == ("Asthma", "COPD")
    assert record.interventions == ("Drug A", "Drug B")
    assert record.countries == ("United States", "Canada")
    assert record.investigators == ("Dr. Smith", "Dr. Jones")
    assert record.sites == ("Site A", "Site B")


def test_mapper_preserves_unknown_categorical_values() -> None:
    raw_study = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000102"},
            "statusModule": {"overallStatus": "UNKNOWN_STATUS"},
            "designModule": {"phases": ["UNKNOWN_PHASE"]},
            "contactsLocationsModule": {"locations": [{"country": "Unknownland"}]},
        }
    }

    record = map_trial_record(raw_study)

    assert record.recruitment_status == "UNKNOWN_STATUS"
    assert record.phases == ("UNKNOWN_PHASE",)
    assert record.countries == ("Unknownland",)


@pytest.mark.parametrize(
    ("raw_study", "message"),
    [
        ({}, "protocolSection"),
        ({"protocolSection": {"identificationModule": {}}}, "nctId"),
        (
            {
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT00000102"},
                    "statusModule": {"startDateStruct": {"date": "2024-13"}},
                }
            },
            "start_date",
        ),
        (
            {
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT00000102"},
                    "statusModule": {"startDateStruct": {"date": "0000-01-01"}},
                }
            },
            "start_date",
        ),
        (
            {
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT00000102"},
                    "designModule": {"phases": "PHASE2"},
                }
            },
            "phases",
        ),
    ],
)
def test_mapper_rejects_malformed_api_records(raw_study: object, message: str) -> None:
    with pytest.raises(ClinicalTrialsRecordMappingError, match=message):
        map_trial_record(raw_study)
