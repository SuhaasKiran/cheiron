"""Tests for the extensible renderer registry and the additional chart types."""

from __future__ import annotations

import pytest
from cheiron_core.chart_data_builder import (
    ChartDataBuilder,
    ChartDataBuilderError,
    ChartDataBuilderLimitError,
)
from cheiron_core.chart_rendering import (
    ChartRendererRegistry,
    HistogramRenderer,
    TimeSeriesRenderer,
    create_default_chart_renderer_registry,
)
from cheiron_core.models import (
    ChartType,
    GroupBy,
    QueryPlan,
    SortOrder,
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
    conditions: tuple[str, ...] = (),
    investigators: tuple[str, ...] = (),
    sites: tuple[str, ...] = (),
) -> TrialRecord:
    return TrialRecord(
        nct_id=nct_id,
        start_date=start_date,
        phases=phases,
        interventions=interventions,
        sponsor=sponsor,
        recruitment_status=None,
        countries=(),
        source_fields={"nct_id": nct_id},
        conditions=conditions,
        investigators=investigators,
        sites=sites,
    )


def make_plan(
    chart_type: ChartType,
    group_by: GroupBy,
    *,
    series_by: GroupBy | None = None,
    sort: SortOrder = SortOrder.ASCENDING,
) -> QueryPlan:
    return QueryPlan(
        filters=TrialFilters(condition="asthma"),
        chart_type=chart_type,
        group_by=group_by,
        series_by=series_by,
        sort=sort,
    )


def test_default_registry_builds_a_grouped_bar_chart() -> None:
    response = ChartDataBuilder().build(
        make_plan(
            ChartType.GROUPED_BAR_CHART,
            GroupBy.TRIAL_PHASE,
            series_by=GroupBy.SPONSOR,
        ),
        (
            make_record("NCT00000001", phases=("PHASE1",), sponsor="Sponsor A"),
            make_record("NCT00000002", phases=("PHASE1",), sponsor="Sponsor B"),
            make_record("NCT00000003", phases=("PHASE2",), sponsor="Sponsor A"),
        ),
    )

    assert response.visualization.chart_type is ChartType.GROUPED_BAR_CHART
    assert response.visualization.encoding == {
        "x": "trial_phase",
        "y": "trial_count",
        "series": "sponsor",
    }
    assert response.visualization.data == (
        {"trial_phase": "PHASE1", "sponsor": "Sponsor A", "trial_count": 1},
        {"trial_phase": "PHASE1", "sponsor": "Sponsor B", "trial_count": 1},
        {"trial_phase": "PHASE2", "sponsor": "Sponsor A", "trial_count": 1},
    )


def test_default_registry_builds_scatter_and_histogram_views() -> None:
    records = (
        make_record(
            "NCT00000001",
            start_date="2020",
            interventions=("Drug A", "Drug B"),
        ),
        make_record("NCT00000002", start_date="2020", interventions=("Drug C",)),
        make_record("NCT00000003", start_date="2021"),
    )
    builder = ChartDataBuilder()

    scatter = builder.build(
        make_plan(
            ChartType.SCATTER_PLOT,
            GroupBy.START_YEAR,
            series_by=GroupBy.INTERVENTION,
        ),
        records,
    )
    histogram = builder.build(
        make_plan(ChartType.HISTOGRAM, GroupBy.START_YEAR),
        records,
    )

    assert scatter.visualization.data == (
        {
            "nct_id": "NCT00000001",
            "start_year": 2020,
            "intervention_count": 2,
        },
        {
            "nct_id": "NCT00000002",
            "start_year": 2020,
            "intervention_count": 1,
        },
        {
            "nct_id": "NCT00000003",
            "start_year": 2021,
            "intervention_count": 0,
        },
    )
    assert histogram.visualization.data == (
        {"start_year": 2020, "trial_count": 2},
        {"start_year": 2021, "trial_count": 1},
    )


def test_default_registry_builds_a_network_of_trial_entities() -> None:
    response = ChartDataBuilder().build(
        make_plan(
            ChartType.NETWORK_GRAPH,
            GroupBy.CONDITION,
            series_by=GroupBy.SITE,
        ),
        (
            make_record(
                "NCT00000001",
                conditions=("Asthma",),
                sites=("Site A", "Site B"),
            ),
            make_record(
                "NCT00000002",
                conditions=("Asthma",),
                sites=("Site A",),
            ),
        ),
    )

    assert response.visualization.encoding == {
        "node_id": "id",
        "source": "source",
        "target": "target",
        "weight": "trial_count",
    }
    assert response.visualization.data == (
        {
            "source": "condition:Asthma",
            "target": "site:Site A",
            "trial_count": 2,
        },
        {
            "source": "condition:Asthma",
            "target": "site:Site B",
            "trial_count": 1,
        },
    )
    assert response.visualization.nodes == (
        {"id": "condition:Asthma", "label": "Asthma", "type": "condition"},
        {"id": "site:Site A", "label": "Site A", "type": "site"},
        {"id": "site:Site B", "label": "Site B", "type": "site"},
    )


def test_network_graph_rejects_excessive_entity_values_before_expanding_edges() -> None:
    with pytest.raises(ChartDataBuilderLimitError, match="maximum values"):
        ChartDataBuilder().build(
            make_plan(
                ChartType.NETWORK_GRAPH,
                GroupBy.CONDITION,
                series_by=GroupBy.SITE,
            ),
            (
                make_record(
                    "NCT00000001",
                    conditions=tuple(f"Condition {index}" for index in range(21)),
                    sites=("Site A",),
                ),
            ),
        )


def test_registry_can_disable_chart_types_without_changing_the_builder() -> None:
    registry = ChartRendererRegistry((TimeSeriesRenderer(), HistogramRenderer()))
    builder = ChartDataBuilder(registry)

    response = builder.build(
        make_plan(ChartType.HISTOGRAM, GroupBy.START_YEAR),
        (make_record("NCT00000001", start_date="2020"),),
    )

    assert response.visualization.chart_type is ChartType.HISTOGRAM
    with pytest.raises(ChartDataBuilderError, match="bar_chart is not enabled"):
        builder.build(
            make_plan(ChartType.BAR_CHART, GroupBy.TRIAL_PHASE),
            (),
        )


def test_default_registry_advertises_every_supported_chart_type() -> None:
    registry = create_default_chart_renderer_registry()

    assert registry.supported_chart_types == frozenset(ChartType)
