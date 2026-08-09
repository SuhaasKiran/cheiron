"""Tests for source-backed citations attached to rendered chart data."""

from __future__ import annotations

import pytest
from cheiron_core.chart_citations import MAX_CITATIONS_PER_CHART
from cheiron_core.chart_data_builder import (
    ChartDataBuilder,
    ChartDataBuilderLimitError,
)
from cheiron_core.models import (
    ChartType,
    GroupBy,
    QueryPlan,
    TrialFilters,
    TrialRecord,
)


def make_record(
    nct_id: str,
    *,
    start_date: str | None = None,
    phases: tuple[str, ...] = (),
    interventions: tuple[str, ...] = (),
    sponsor: str | None = None,
) -> TrialRecord:
    """Create one minimal normalized record with source-backed field values."""

    return TrialRecord(
        nct_id=nct_id,
        start_date=start_date,
        phases=phases,
        interventions=interventions,
        sponsor=sponsor,
        recruitment_status=None,
        countries=(),
        source_fields={
            "nct_id": nct_id,
            "start_date": start_date,
            "phases": phases,
            "interventions": interventions,
            "sponsor": sponsor,
        },
    )


def test_time_bucket_includes_the_contributing_trial_and_exact_source_value() -> None:
    response = ChartDataBuilder().build(
        QueryPlan(
            filters=TrialFilters(condition="Melanoma"),
            chart_type=ChartType.TIME_SERIES,
            group_by=GroupBy.START_YEAR,
        ),
        (make_record("NCT00000001", start_date="2021-05"),),
    )

    assert response.visualization.data == (
        {
            "start_year": 2021,
            "trial_count": 1,
            "citations": [
                {
                    "nct_id": "NCT00000001",
                    "evidence": [
                        {
                            "field": (
                                "protocolSection.statusModule.startDateStruct.date"
                            ),
                            "value": "2021-05",
                        }
                    ],
                }
            ],
        },
    )


def test_grouped_datum_cites_both_source_values_that_support_the_pair() -> None:
    response = ChartDataBuilder().build(
        QueryPlan(
            filters=TrialFilters(condition="Melanoma"),
            chart_type=ChartType.GROUPED_BAR_CHART,
            group_by=GroupBy.TRIAL_PHASE,
            series_by=GroupBy.SPONSOR,
        ),
        (
            make_record(
                "NCT00000001",
                phases=("PHASE2",),
                sponsor="Sponsor A",
            ),
        ),
    )

    assert response.visualization.data[0]["citations"] == [
        {
            "nct_id": "NCT00000001",
            "evidence": [
                {
                    "field": "protocolSection.designModule.phases",
                    "value": "PHASE2",
                },
                {
                    "field": (
                        "protocolSection.sponsorCollaboratorsModule.leadSponsor.name"
                    ),
                    "value": "Sponsor A",
                },
            ],
        }
    ]


def test_network_edge_cites_the_trial_and_both_connected_source_values() -> None:
    response = ChartDataBuilder().build(
        QueryPlan(
            filters=TrialFilters(condition="Melanoma"),
            chart_type=ChartType.NETWORK_GRAPH,
            group_by=GroupBy.INTERVENTION,
            series_by=GroupBy.SPONSOR,
        ),
        (
            make_record(
                "NCT00000001",
                interventions=("Pembrolizumab",),
                sponsor="Sponsor A",
            ),
        ),
    )

    assert response.visualization.data[0]["citations"] == [
        {
            "nct_id": "NCT00000001",
            "evidence": [
                {
                    "field": (
                        "protocolSection.armsInterventionsModule.interventions.name"
                    ),
                    "value": "Pembrolizumab",
                },
                {
                    "field": (
                        "protocolSection.sponsorCollaboratorsModule.leadSponsor.name"
                    ),
                    "value": "Sponsor A",
                },
            ],
        }
    ]
    assert response.visualization.nodes[0]["citations"] == [
        {
            "nct_id": "NCT00000001",
            "evidence": [
                {
                    "field": (
                        "protocolSection.armsInterventionsModule.interventions.name"
                    ),
                    "value": "Pembrolizumab",
                }
            ],
        }
    ]


def test_citation_lists_are_bounded_and_marked_when_not_complete() -> None:
    response = ChartDataBuilder().build(
        QueryPlan(
            filters=TrialFilters(condition="Melanoma"),
            chart_type=ChartType.BAR_CHART,
            group_by=GroupBy.TRIAL_PHASE,
        ),
        tuple(
            make_record(f"NCT0000000{index}", phases=("PHASE2",))
            for index in range(1, 7)
        ),
    )

    datum = response.visualization.data[0]
    citations = datum["citations"]
    assert isinstance(citations, list)
    assert len(citations) == 5
    assert datum["citations_truncated"] is True
    assert response.meta.citations_truncated is True


def test_chart_with_more_visible_items_than_the_citation_limit_is_a_chart_limit() -> (
    None
):
    records = tuple(
        TrialRecord(
            nct_id=f"NCT{index:08d}",
            start_date=None,
            phases=(),
            interventions=(),
            sponsor=None,
            recruitment_status=None,
            countries=(),
            source_fields={},
            sites=(f"Site {index}",),
        )
        for index in range(1, MAX_CITATIONS_PER_CHART + 2)
    )

    with pytest.raises(ChartDataBuilderLimitError, match="too many data points"):
        ChartDataBuilder().build(
            QueryPlan(
                filters=TrialFilters(condition="Melanoma"),
                chart_type=ChartType.BAR_CHART,
                group_by=GroupBy.SITE,
            ),
            records,
        )


def test_citations_can_be_disabled_for_a_smaller_chart_response() -> None:
    response = ChartDataBuilder().build(
        QueryPlan(
            filters=TrialFilters(condition="Melanoma"),
            chart_type=ChartType.BAR_CHART,
            group_by=GroupBy.TRIAL_PHASE,
            include_citations=False,
        ),
        (make_record("NCT00000001", phases=("PHASE2",)),),
    )

    assert response.visualization.data == ({"trial_phase": "PHASE2", "trial_count": 1},)
    assert response.meta.citations_truncated is False
