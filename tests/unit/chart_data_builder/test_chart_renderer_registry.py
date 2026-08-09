"""Tests for the extensible renderer registry and the additional chart types."""

from __future__ import annotations

import pytest
from cheiron_core.chart_data_builder import (
    ChartDataBuilder,
    ChartDataBuilderError,
)
from cheiron_core.chart_rendering import (
    MAX_NETWORK_EDGES,
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
    countries: tuple[str, ...] = (),
) -> TrialRecord:
    return TrialRecord(
        nct_id=nct_id,
        start_date=start_date,
        phases=phases,
        interventions=interventions,
        sponsor=sponsor,
        recruitment_status=None,
        countries=countries,
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


def test_grouped_bar_chart_limits_an_explicit_drug_comparison_to_named_drugs() -> None:
    plan = QueryPlan(
        filters=TrialFilters(
            condition="Melanoma",
            drug_names=("Pembrolizumab", "Nivolumab"),
        ),
        chart_type=ChartType.GROUPED_BAR_CHART,
        group_by=GroupBy.TRIAL_PHASE,
        series_by=GroupBy.INTERVENTION,
        comparison_values=("Pembrolizumab", "Nivolumab"),
    )

    response = ChartDataBuilder().build(
        plan,
        (
            make_record(
                "NCT00000001",
                phases=("PHASE2",),
                interventions=("Pembrolizumab", "Other drug"),
            ),
            make_record(
                "NCT00000002",
                phases=("PHASE2",),
                interventions=("Nivolumab",),
            ),
        ),
    )

    assert response.visualization.data == (
        {"trial_phase": "PHASE2", "intervention": "Nivolumab", "trial_count": 1},
        {"trial_phase": "PHASE2", "intervention": "Pembrolizumab", "trial_count": 1},
    )


def test_bar_chart_groups_trials_by_country() -> None:
    response = ChartDataBuilder().build(
        make_plan(ChartType.BAR_CHART, GroupBy.COUNTRY),
        (
            make_record("NCT00000001", countries=("United States", "Canada")),
            make_record("NCT00000002", countries=("United States",)),
        ),
    )

    assert response.visualization.data == (
        {"country": "Canada", "trial_count": 1},
        {"country": "United States", "trial_count": 2},
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


def test_network_graph_caps_excessive_entity_values_per_source_record() -> None:
    response = ChartDataBuilder().build(
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

    assert len(response.visualization.data) == 20
    assert response.meta.truncated is True


def test_network_graph_omits_an_overlong_entity_label_from_one_record() -> None:
    response = ChartDataBuilder().build(
        make_plan(
            ChartType.NETWORK_GRAPH,
            GroupBy.CONDITION,
            series_by=GroupBy.SITE,
        ),
        (
            make_record(
                "NCT00000001",
                conditions=("Asthma", "x" * 501),
                sites=("Site A",),
            ),
        ),
    )

    assert response.visualization.data == (
        {
            "source": "condition:Asthma",
            "target": "site:Site A",
            "trial_count": 1,
        },
    )
    assert response.meta.truncated is True


def test_network_graph_keeps_the_strongest_edges_within_its_rendering_limit() -> None:
    records = tuple(
        make_record(
            f"NCT{index:08d}",
            conditions=(f"Condition {index // 45}",),
            sites=(f"Site {index % 45}",),
        )
        for index in range(MAX_NETWORK_EDGES + 1)
    )

    response = ChartDataBuilder().build(
        make_plan(
            ChartType.NETWORK_GRAPH,
            GroupBy.CONDITION,
            series_by=GroupBy.SITE,
        ),
        records,
    )

    assert len(response.visualization.data) == MAX_NETWORK_EDGES
    assert len(response.visualization.nodes) == 90
    assert response.meta.truncated is True
    assert response.to_dict()["meta"] == {
        "filters": {"condition": "asthma"},
        "source": "clinicaltrials.gov",
        "units": "trials",
        "grouping": "condition,site",
        "sorting": "source_ascending,target_ascending",
        "truncated": True,
    }


def test_network_graph_keeps_a_bounded_subgraph_when_node_limit_is_reached() -> None:
    records = tuple(
        make_record(
            f"NCT{index:08d}",
            conditions=(f"Condition {index}",),
            sites=(f"Site {index}",),
        )
        for index in range(501)
    )

    response = ChartDataBuilder().build(
        make_plan(
            ChartType.NETWORK_GRAPH,
            GroupBy.CONDITION,
            series_by=GroupBy.SITE,
        ),
        records,
    )

    assert len(response.visualization.data) == 500
    assert len(response.visualization.nodes) == 1_000
    assert response.meta.truncated is True


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
