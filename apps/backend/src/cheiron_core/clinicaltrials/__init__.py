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

__all__ = [
    "ClinicalTrialsApiClient",
    "ClinicalTrialsApiError",
    "ClinicalTrialsApiHttpError",
    "ClinicalTrialsApiProtocolError",
    "ClinicalTrialsApiTransportError",
    "ClinicalTrialsSearchResult",
    "JsonHttpTransport",
]
