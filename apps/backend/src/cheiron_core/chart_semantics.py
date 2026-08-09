"""Shared, pure trial-field rules used by chart renderers and citations."""

from __future__ import annotations

from cheiron_core.models import GroupBy, TrialRecord

MAX_ENTITY_VALUES_PER_RECORD = 20
MAX_ENTITY_LABEL_CHARACTERS = 500


def values_for(record: TrialRecord, group_by: GroupBy) -> tuple[str | int, ...]:
    """Return the normalized record values that a chart may group or cite."""

    values: tuple[str | int, ...]
    if group_by is GroupBy.START_YEAR:
        values = () if record.start_year is None else (record.start_year,)
    elif group_by is GroupBy.TRIAL_PHASE:
        values = record.phases
    elif group_by is GroupBy.INTERVENTION:
        values = record.interventions
    elif group_by is GroupBy.SPONSOR:
        values = () if record.sponsor is None else (record.sponsor,)
    elif group_by is GroupBy.CONDITION:
        values = record.conditions
    elif group_by is GroupBy.INVESTIGATOR:
        values = record.investigators
    elif group_by is GroupBy.COUNTRY:
        values = record.countries
    else:
        values = record.sites
    return values


def bounded_network_values(
    record: TrialRecord,
    group_by: GroupBy,
) -> tuple[tuple[str | int, ...], bool]:
    """Return the same bounded entity values that a network chart can render."""

    values = values_for(record, group_by)
    valid_values = sorted(
        (value for value in values if len(str(value)) <= MAX_ENTITY_LABEL_CHARACTERS),
        key=_text_sort_key,
    )
    bounded_values = tuple(valid_values[:MAX_ENTITY_VALUES_PER_RECORD])
    return bounded_values, len(bounded_values) < len(values)


def _text_sort_key(value: str | int) -> tuple[int, str] | tuple[int, int]:
    if isinstance(value, int):
        return (0, value)
    return (1, value.casefold())
