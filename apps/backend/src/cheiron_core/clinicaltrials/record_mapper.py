"""Pure conversion of ClinicalTrials.gov studies into internal trial records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from cheiron_core.models import ModelValidationError, TrialRecord


class ClinicalTrialsRecordMappingError(ValueError):
    """Raised when a raw ClinicalTrials.gov study cannot be mapped safely."""


def map_trial_record(raw_study: object) -> TrialRecord:
    """Convert one raw API study into a normalized record for later chart code."""

    study = _require_mapping(raw_study, "study")
    protocol = _require_mapping(study.get("protocolSection"), "protocolSection")
    identification = _require_mapping(
        protocol.get("identificationModule"), "identificationModule"
    )
    status = _optional_mapping(protocol, "statusModule")
    design = _optional_mapping(protocol, "designModule")
    interventions = _optional_mapping(protocol, "armsInterventionsModule")
    sponsors = _optional_mapping(protocol, "sponsorCollaboratorsModule")
    locations = _optional_mapping(protocol, "contactsLocationsModule")

    nct_id = _require_text(identification.get("nctId"), "nctId")
    start_date = _start_date(status)
    phases = _text_values(design, "phases")
    intervention_names = _intervention_names(interventions)
    sponsor = _lead_sponsor_name(sponsors)
    recruitment_status = _optional_text(
        status.get("overallStatus") if status is not None else None,
        "overallStatus",
    )
    countries = _countries(locations)

    try:
        return TrialRecord(
            nct_id=nct_id,
            start_date=start_date,
            phases=phases,
            interventions=intervention_names,
            sponsor=sponsor,
            recruitment_status=recruitment_status,
            countries=countries,
            source_fields={
                "nct_id": nct_id,
                "start_date": start_date,
                "phases": phases,
                "interventions": intervention_names,
                "sponsor": sponsor,
                "recruitment_status": recruitment_status,
                "countries": countries,
            },
        )
    except ModelValidationError as error:
        raise ClinicalTrialsRecordMappingError(str(error)) from error


def map_trial_records(raw_studies: Iterable[object]) -> tuple[TrialRecord, ...]:
    """Map records in their retrieval order without changing or dropping them."""

    return tuple(map_trial_record(raw_study) for raw_study in raw_studies)


def _start_date(status: Mapping[str, object] | None) -> str | None:
    if status is None:
        return None
    start_date = _optional_mapping(status, "startDateStruct")
    if start_date is None:
        return None
    return _require_text(start_date.get("date"), "startDateStruct.date")


def _intervention_names(
    interventions_module: Mapping[str, object] | None,
) -> tuple[str, ...]:
    if interventions_module is None:
        return ()
    raw_interventions = interventions_module.get("interventions")
    if raw_interventions is None:
        return ()
    if not isinstance(raw_interventions, list):
        raise ClinicalTrialsRecordMappingError("interventions must be a list.")

    names: list[str] = []
    for index, intervention in enumerate(raw_interventions):
        intervention_record = _require_mapping(intervention, f"interventions[{index}]")
        name = _require_text(
            intervention_record.get("name"), f"interventions[{index}].name"
        )
        if name not in names:
            names.append(name)
    return tuple(names)


def _lead_sponsor_name(
    sponsors_module: Mapping[str, object] | None,
) -> str | None:
    if sponsors_module is None:
        return None
    lead_sponsor = _optional_mapping(sponsors_module, "leadSponsor")
    if lead_sponsor is None:
        return None
    return _optional_text(lead_sponsor.get("name"), "leadSponsor.name")


def _countries(locations_module: Mapping[str, object] | None) -> tuple[str, ...]:
    if locations_module is None:
        return ()
    raw_locations = locations_module.get("locations")
    if raw_locations is None:
        return ()
    if not isinstance(raw_locations, list):
        raise ClinicalTrialsRecordMappingError("locations must be a list.")

    countries: list[str] = []
    for index, location in enumerate(raw_locations):
        location_record = _require_mapping(location, f"locations[{index}]")
        country = _optional_text(
            location_record.get("country"), f"locations[{index}].country"
        )
        if country is not None and country not in countries:
            countries.append(country)
    return tuple(countries)


def _text_values(
    module: Mapping[str, object] | None,
    field_name: str,
) -> tuple[str, ...]:
    if module is None:
        return ()
    values = module.get(field_name)
    if values is None:
        return ()
    if not isinstance(values, list):
        raise ClinicalTrialsRecordMappingError(f"{field_name} must be a list.")

    normalized: list[str] = []
    for index, value in enumerate(values):
        text = _require_text(value, f"{field_name}[{index}]")
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized)


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ClinicalTrialsRecordMappingError(f"{field_name} must be an object.")
    return value


def _optional_mapping(
    values: Mapping[str, object], field_name: str
) -> Mapping[str, object] | None:
    value = values.get(field_name)
    if value is None:
        return None
    return _require_mapping(value, field_name)


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ClinicalTrialsRecordMappingError(f"{field_name} must be a string.")
    cleaned = value.strip()
    if not cleaned:
        raise ClinicalTrialsRecordMappingError(f"{field_name} must not be empty.")
    return cleaned


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name)
