"""ClinicalTrials.gov API transport and pagination adapter."""

from cheiron_core.clinicaltrials.api_client import (
    ClinicalTrialsApiClient,
    ClinicalTrialsApiError,
    ClinicalTrialsApiHttpError,
    ClinicalTrialsApiProtocolError,
    ClinicalTrialsApiTransportError,
    ClinicalTrialsSearchResult,
    JsonHttpTransport,
)
from cheiron_core.clinicaltrials.record_mapper import (
    ClinicalTrialsRecordMappingError,
    map_trial_record,
    map_trial_records,
)

__all__ = [
    "ClinicalTrialsApiClient",
    "ClinicalTrialsApiError",
    "ClinicalTrialsApiHttpError",
    "ClinicalTrialsApiProtocolError",
    "ClinicalTrialsApiTransportError",
    "ClinicalTrialsRecordMappingError",
    "ClinicalTrialsSearchResult",
    "JsonHttpTransport",
    "map_trial_record",
    "map_trial_records",
]
