"""Extensible, deterministic renderers for supported trial visualizations."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from cheiron_core.models import (
    ChartType,
    GroupBy,
    QueryPlan,
    SortOrder,
    TrialRecord,
    VisualizationMeta,
    VisualizationResponse,
    VisualizationSpec,
)

_NETWORK_ENTITY_GROUPS = frozenset(
    {
        GroupBy.INTERVENTION,
        GroupBy.SPONSOR,
        GroupBy.CONDITION,
        GroupBy.INVESTIGATOR,
        GroupBy.SITE,
    }
)
MAX_ENTITY_VALUES_PER_RECORD = 20
MAX_GROUPED_BAR_ROWS = 2_000
MAX_NETWORK_NODES = 1_000
MAX_NETWORK_EDGES = 2_000
MAX_ENTITY_LABEL_CHARACTERS = 500


class ChartCapabilityError(ValueError):
    """Raised when a plan is not supported by an enabled chart renderer."""


class ChartRenderLimitError(ChartCapabilityError):
    """Raised before a chart requires unsafe rendering work or response size."""


class ChartRenderer(Protocol):
    """A single chart type's plan validation and pure rendering contract."""

    @property
    def chart_type(self) -> ChartType:
        """Return the chart type exclusively owned by this renderer."""

    def validate_plan(self, plan: QueryPlan) -> None:
        """Raise ChartCapabilityError when the plan is invalid for this chart."""

    def build(
        self,
        plan: QueryPlan,
        records: Iterable[TrialRecord],
    ) -> VisualizationResponse:
        """Build one deterministic visualization without I/O."""

    def default_sort(self) -> SortOrder:
        """Return the stable default ordering for this chart type."""

    def prompt_description(self) -> str:
        """Describe the chart plan shape that an LLM may select."""


class ChartRendererRegistry:
    """Resolve enabled chart renderers at the composition boundary.

    Applications can provide a smaller or extended registry without changing query
    orchestration or the generic chart-data builder. Every renderer owns the plan
    shapes and data semantics for exactly one chart type.
    """

    def __init__(self, renderers: Iterable[ChartRenderer]) -> None:
        resolved: dict[ChartType, ChartRenderer] = {}
        for renderer in renderers:
            if not isinstance(renderer.chart_type, ChartType):
                raise ValueError("renderers must declare a supported ChartType.")
            if renderer.chart_type in resolved:
                raise ValueError(f"duplicate renderer for {renderer.chart_type.value}.")
            resolved[renderer.chart_type] = renderer
        if not resolved:
            raise ValueError("at least one chart renderer must be enabled.")
        self._renderers = resolved

    @property
    def supported_chart_types(self) -> frozenset[ChartType]:
        """Return the types enabled in this registry."""

        return frozenset(self._renderers)

    def supports(self, plan: QueryPlan) -> bool:
        """Return whether this registry can safely render a plan."""

        try:
            self.validate(plan)
        except ChartCapabilityError:
            return False
        return True

    def validate(self, plan: QueryPlan) -> None:
        """Validate the plan against the enabled renderer's contract."""

        if not isinstance(plan, QueryPlan):
            raise ChartCapabilityError("plan must be a QueryPlan instance.")
        renderer = self._renderers.get(plan.chart_type)
        if renderer is None:
            raise ChartCapabilityError(f"{plan.chart_type.value} is not enabled.")
        renderer.validate_plan(plan)

    def build(
        self,
        plan: QueryPlan,
        records: Iterable[TrialRecord],
    ) -> VisualizationResponse:
        """Render a previously validated plan with its owning renderer."""

        self.validate(plan)
        return self._renderers[plan.chart_type].build(plan, records)

    def default_sort(self, plan: QueryPlan) -> SortOrder:
        """Return the default sort from the renderer that owns this plan."""

        self.validate(plan)
        return self._renderers[plan.chart_type].default_sort()

    def prompt_descriptions(self) -> str:
        """Return safe, schema-level descriptions for LLM prompt construction."""

        return "\n".join(
            self._renderers[chart_type].prompt_description()
            for chart_type in sorted(self._renderers, key=lambda item: item.value)
        )


@dataclass(frozen=True, slots=True)
class TimeSeriesRenderer:
    """Render counts of unique trials by their known start year."""

    chart_type: ChartType = ChartType.TIME_SERIES

    def validate_plan(self, plan: QueryPlan) -> None:
        _require_plan_shape(
            plan,
            chart_type=self.chart_type,
            group_by=GroupBy.START_YEAR,
            series_by=None,
        )

    def build(
        self,
        plan: QueryPlan,
        records: Iterable[TrialRecord],
    ) -> VisualizationResponse:
        data = _year_counts(records, plan.sort)
        return VisualizationResponse(
            visualization=VisualizationSpec(
                chart_type=self.chart_type,
                title="Trials by Start Year",
                encoding={"x": "start_year", "y": "trial_count"},
                data=data,
            ),
            meta=_trial_count_meta(
                plan,
                time_granularity="year",
                sorting=f"start_year_{plan.sort.value}",
            ),
        )

    def default_sort(self) -> SortOrder:
        return SortOrder.ASCENDING

    def prompt_description(self) -> str:
        return "time_series: group_by=start_year and series_by=null."


@dataclass(frozen=True, slots=True)
class HistogramRenderer:
    """Render a start-year distribution as a histogram."""

    chart_type: ChartType = ChartType.HISTOGRAM

    def validate_plan(self, plan: QueryPlan) -> None:
        _require_plan_shape(
            plan,
            chart_type=self.chart_type,
            group_by=GroupBy.START_YEAR,
            series_by=None,
        )

    def build(
        self,
        plan: QueryPlan,
        records: Iterable[TrialRecord],
    ) -> VisualizationResponse:
        data = _year_counts(records, plan.sort)
        return VisualizationResponse(
            visualization=VisualizationSpec(
                chart_type=self.chart_type,
                title="Distribution of Trials by Start Year",
                encoding={"x": "start_year", "y": "trial_count"},
                data=data,
            ),
            meta=_trial_count_meta(
                plan,
                time_granularity="year",
                sorting=f"start_year_{plan.sort.value}",
            ),
        )

    def default_sort(self) -> SortOrder:
        return SortOrder.ASCENDING

    def prompt_description(self) -> str:
        return "histogram: group_by=start_year and series_by=null."


@dataclass(frozen=True, slots=True)
class BarChartRenderer:
    """Render counts by one normalized trial field."""

    chart_type: ChartType = ChartType.BAR_CHART

    def validate_plan(self, plan: QueryPlan) -> None:
        if plan.chart_type is not self.chart_type:
            raise ChartCapabilityError(
                "bar_chart renderer received the wrong chart type."
            )
        if plan.series_by is not None:
            raise ChartCapabilityError("bar_chart does not support series_by.")

    def build(
        self,
        plan: QueryPlan,
        records: Iterable[TrialRecord],
    ) -> VisualizationResponse:
        data = _group_counts(records, plan.group_by, plan.sort)
        field = plan.group_by.value
        return VisualizationResponse(
            visualization=VisualizationSpec(
                chart_type=self.chart_type,
                title=f"Trials by {_display_name(plan.group_by)}",
                encoding={"x": field, "y": "trial_count"},
                data=data,
            ),
            meta=_trial_count_meta(
                plan,
                sorting=f"trial_count_{plan.sort.value}",
            ),
        )

    def default_sort(self) -> SortOrder:
        return SortOrder.DESCENDING

    def prompt_description(self) -> str:
        return "bar_chart: choose one group_by field and set series_by=null."


@dataclass(frozen=True, slots=True)
class GroupedBarChartRenderer:
    """Render trial counts for combinations of two normalized fields."""

    chart_type: ChartType = ChartType.GROUPED_BAR_CHART

    def validate_plan(self, plan: QueryPlan) -> None:
        if plan.chart_type is not self.chart_type:
            raise ChartCapabilityError(
                "grouped_bar_chart renderer received the wrong chart type."
            )
        if plan.series_by is None:
            raise ChartCapabilityError("grouped_bar_chart requires series_by.")
        if plan.group_by is plan.series_by:
            raise ChartCapabilityError(
                "grouped_bar_chart group_by and series_by must differ."
            )

    def build(
        self,
        plan: QueryPlan,
        records: Iterable[TrialRecord],
    ) -> VisualizationResponse:
        if plan.series_by is None:
            raise AssertionError("validated grouped bar plans require series_by.")
        data = _grouped_counts(
            records,
            plan.group_by,
            plan.series_by,
            plan.sort,
            comparison_values=plan.comparison_values,
        )
        return VisualizationResponse(
            visualization=VisualizationSpec(
                chart_type=self.chart_type,
                title=(
                    f"Trials by {_display_name(plan.group_by)} and "
                    f"{_display_name(plan.series_by)}"
                ),
                encoding={
                    "x": plan.group_by.value,
                    "y": "trial_count",
                    "series": plan.series_by.value,
                },
                data=data,
            ),
            meta=_trial_count_meta(
                plan,
                sorting=(
                    f"{plan.group_by.value}_{plan.sort.value},"
                    f"{plan.series_by.value}_ascending"
                ),
            ),
        )

    def default_sort(self) -> SortOrder:
        return SortOrder.ASCENDING

    def prompt_description(self) -> str:
        return "grouped_bar_chart: choose distinct group_by and series_by fields."


@dataclass(frozen=True, slots=True)
class ScatterPlotRenderer:
    """Render a trial-level numeric entity count against its start year."""

    chart_type: ChartType = ChartType.SCATTER_PLOT

    def validate_plan(self, plan: QueryPlan) -> None:
        if plan.chart_type is not self.chart_type:
            raise ChartCapabilityError(
                "scatter_plot renderer received the wrong chart type."
            )
        if plan.group_by is not GroupBy.START_YEAR:
            raise ChartCapabilityError("scatter_plot must group by start_year.")
        if plan.series_by is None or plan.series_by is GroupBy.START_YEAR:
            raise ChartCapabilityError(
                "scatter_plot requires a non-start-year series_by field."
            )

    def build(
        self,
        plan: QueryPlan,
        records: Iterable[TrialRecord],
    ) -> VisualizationResponse:
        if plan.series_by is None:
            raise AssertionError("validated scatter plans require series_by.")
        count_field = f"{plan.series_by.value}_count"
        data = tuple(
            {
                "nct_id": record.nct_id,
                "start_year": record.start_year,
                count_field: len(_values_for(record, plan.series_by)),
            }
            for record in sorted(
                records, key=lambda item: (item.start_year or 0, item.nct_id)
            )
            if record.start_year is not None
        )
        return VisualizationResponse(
            visualization=VisualizationSpec(
                chart_type=self.chart_type,
                title=(
                    f"{_display_name(plan.series_by)} Count per Trial by Start Year"
                ),
                encoding={"x": "start_year", "y": count_field, "detail": "nct_id"},
                data=data,
            ),
            meta=_trial_count_meta(
                plan,
                time_granularity="year",
                sorting="start_year_ascending,nct_id_ascending",
            ),
        )

    def default_sort(self) -> SortOrder:
        return SortOrder.ASCENDING

    def prompt_description(self) -> str:
        return "scatter_plot: group_by=start_year and series_by is another field."


@dataclass(frozen=True, slots=True)
class NetworkGraphRenderer:
    """Render weighted relationships between two ClinicalTrials.gov entity types."""

    chart_type: ChartType = ChartType.NETWORK_GRAPH

    def validate_plan(self, plan: QueryPlan) -> None:
        if plan.chart_type is not self.chart_type:
            raise ChartCapabilityError(
                "network_graph renderer received the wrong chart type."
            )
        if plan.group_by not in _NETWORK_ENTITY_GROUPS:
            raise ChartCapabilityError(
                "network_graph group_by must be an entity field."
            )
        if plan.series_by not in _NETWORK_ENTITY_GROUPS:
            raise ChartCapabilityError(
                "network_graph series_by must be an entity field."
            )
        if plan.series_by is plan.group_by:
            raise ChartCapabilityError(
                "network_graph group_by and series_by must differ."
            )

    def build(
        self,
        plan: QueryPlan,
        records: Iterable[TrialRecord],
    ) -> VisualizationResponse:
        if plan.series_by is None:
            raise AssertionError("validated network plans require series_by.")
        edge_counts: Counter[tuple[str, str]] = Counter()
        truncated = False
        for record in records:
            sources, sources_truncated = _bounded_network_entity_values(
                record,
                plan.group_by,
            )
            targets, targets_truncated = _bounded_network_entity_values(
                record,
                plan.series_by,
            )
            truncated = truncated or sources_truncated or targets_truncated
            for source in sources:
                source_id = _node_id(plan.group_by, source)
                for target in targets:
                    target_id = _node_id(plan.series_by, target)
                    edge_counts[(source_id, target_id)] += 1

        edges, nodes, graph_truncated = _bounded_network_graph(edge_counts)
        return VisualizationResponse(
            visualization=VisualizationSpec(
                chart_type=self.chart_type,
                title=(
                    f"Trial Network: {_display_name(plan.group_by)} to "
                    f"{_display_name(plan.series_by)}"
                ),
                encoding={
                    "node_id": "id",
                    "source": "source",
                    "target": "target",
                    "weight": "trial_count",
                },
                data=edges,
                nodes=nodes,
            ),
            meta=_trial_count_meta(
                plan,
                sorting="source_ascending,target_ascending",
                truncated=truncated or graph_truncated,
            ),
        )

    def default_sort(self) -> SortOrder:
        return SortOrder.ASCENDING

    def prompt_description(self) -> str:
        return (
            "network_graph: choose distinct group_by and series_by from intervention, "
            "sponsor, condition, investigator, or site."
        )


def create_default_chart_renderer_registry() -> ChartRendererRegistry:
    """Create the production set of independently removable chart capabilities."""

    return ChartRendererRegistry(
        (
            BarChartRenderer(),
            GroupedBarChartRenderer(),
            TimeSeriesRenderer(),
            ScatterPlotRenderer(),
            HistogramRenderer(),
            NetworkGraphRenderer(),
        )
    )


def _require_plan_shape(
    plan: QueryPlan,
    *,
    chart_type: ChartType,
    group_by: GroupBy,
    series_by: GroupBy | None,
) -> None:
    if plan.chart_type is not chart_type:
        raise ChartCapabilityError(
            f"{chart_type.value} renderer received the wrong chart type."
        )
    if plan.group_by is not group_by or plan.series_by is not series_by:
        expected_series = "null" if series_by is None else series_by.value
        raise ChartCapabilityError(
            f"{chart_type.value} requires group_by={group_by.value} and "
            f"series_by={expected_series}."
        )


def _values_for(record: TrialRecord, group_by: GroupBy) -> tuple[str | int, ...]:
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


def _group_counts(
    records: Iterable[TrialRecord],
    group_by: GroupBy,
    sort: SortOrder,
) -> tuple[dict[str, object], ...]:
    counts: Counter[str | int] = Counter(
        value for record in records for value in _values_for(record, group_by)
    )
    values = _sort_values(counts, sort)
    return tuple(
        {group_by.value: value, "trial_count": counts[value]} for value in values
    )


def _grouped_counts(
    records: Iterable[TrialRecord],
    group_by: GroupBy,
    series_by: GroupBy,
    sort: SortOrder,
    *,
    comparison_values: tuple[str, ...] = (),
) -> tuple[dict[str, object], ...]:
    counts: Counter[tuple[str | int, str | int]] = Counter()
    for record in records:
        group_values = _bounded_entity_values(record, group_by)
        series_values = _bounded_entity_values(record, series_by)
        if comparison_values:
            allowed_values = {value.casefold() for value in comparison_values}
            series_values = tuple(
                value
                for value in series_values
                if isinstance(value, str) and value.casefold() in allowed_values
            )
        for group_value in group_values:
            for series_value in series_values:
                pair = (group_value, series_value)
                if pair not in counts and len(counts) >= MAX_GROUPED_BAR_ROWS:
                    raise ChartRenderLimitError(
                        "grouped_bar_chart exceeds the maximum number of rows."
                    )
                counts[pair] += 1
    pairs = sorted(
        counts,
        key=lambda pair: (_sort_key(pair[0], sort), _text_sort_key(pair[1])),
    )
    return tuple(
        {
            group_by.value: group_value,
            series_by.value: series_value,
            "trial_count": counts[(group_value, series_value)],
        }
        for group_value, series_value in pairs
    )


def _year_counts(
    records: Iterable[TrialRecord],
    sort: SortOrder,
) -> tuple[dict[str, object], ...]:
    counts: Counter[int] = Counter(
        record.start_year for record in records if record.start_year is not None
    )
    years = sorted(counts, reverse=sort is SortOrder.DESCENDING)
    return tuple({"start_year": year, "trial_count": counts[year]} for year in years)


def _sort_values(
    counts: Mapping[str | int, int],
    sort: SortOrder,
) -> list[str | int]:
    return sorted(
        counts,
        key=lambda value: (
            counts[value] if sort is SortOrder.ASCENDING else -counts[value],
            _text_sort_key(value),
        ),
    )


def _sort_key(value: str | int, sort: SortOrder) -> tuple[int, str] | tuple[int, int]:
    if isinstance(value, int):
        return (0, value if sort is SortOrder.ASCENDING else -value)
    return (
        1,
        value.casefold() if sort is SortOrder.ASCENDING else _descending_text(value),
    )


def _text_sort_key(value: str | int) -> tuple[int, str] | tuple[int, int]:
    if isinstance(value, int):
        return (0, value)
    return (1, value.casefold())


def _descending_text(value: str) -> str:
    return "".join(chr(0x10FFFF - ord(character)) for character in value.casefold())


def _display_name(group_by: GroupBy) -> str:
    labels = {
        GroupBy.START_YEAR: "Start Year",
        GroupBy.TRIAL_PHASE: "Phase",
        GroupBy.INTERVENTION: "Intervention",
        GroupBy.SPONSOR: "Sponsor",
        GroupBy.CONDITION: "Condition",
        GroupBy.INVESTIGATOR: "Investigator",
        GroupBy.SITE: "Site",
        GroupBy.COUNTRY: "Country",
    }
    return labels[group_by]


def _trial_count_meta(
    plan: QueryPlan,
    *,
    sorting: str,
    time_granularity: str | None = None,
    truncated: bool = False,
) -> VisualizationMeta:
    grouping = plan.group_by.value
    if plan.series_by is not None:
        grouping = f"{grouping},{plan.series_by.value}"
    return VisualizationMeta(
        filters=plan.filters,
        units="trials",
        time_granularity=time_granularity,
        grouping=grouping,
        sorting=sorting,
        truncated=truncated,
    )


def _bounded_entity_values(
    record: TrialRecord,
    group_by: GroupBy,
) -> tuple[str | int, ...]:
    """Return bounded source values before a multi-entity chart expands them."""

    values = _values_for(record, group_by)
    if len(values) > MAX_ENTITY_VALUES_PER_RECORD:
        raise ChartRenderLimitError(
            f"{group_by.value} exceeds the maximum values allowed per trial."
        )
    for value in values:
        if len(str(value)) > MAX_ENTITY_LABEL_CHARACTERS:
            raise ChartRenderLimitError(
                f"{group_by.value} contains a value that exceeds the label limit."
            )
    return values


def _bounded_network_entity_values(
    record: TrialRecord,
    group_by: GroupBy,
) -> tuple[tuple[str | int, ...], bool]:
    """Keep a safe deterministic subset of one record's graph entities.

    A high-cardinality or overlong source field is valid ClinicalTrials.gov data, not
    a reason to discard the entire chart. Network graphs retain a bounded subset and
    expose that loss of detail through their response metadata.
    """

    values = _values_for(record, group_by)
    valid_values = sorted(
        (value for value in values if len(str(value)) <= MAX_ENTITY_LABEL_CHARACTERS),
        key=_text_sort_key,
    )
    bounded_values = tuple(valid_values[:MAX_ENTITY_VALUES_PER_RECORD])
    return bounded_values, len(bounded_values) < len(values)


def _bounded_network_graph(
    edge_counts: Counter[tuple[str, str]],
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, str], ...], bool]:
    """Select a deterministic, bounded graph without returning an unsafe payload.

    Higher-count edges are retained first. Ties use the source and target IDs, so the
    same source records always produce the same bounded graph.
    """

    selected_edges: list[tuple[str, str, int]] = []
    selected_node_ids: set[str] = set()
    truncated = False
    ranked_edges = sorted(
        edge_counts.items(),
        key=lambda item: (-item[1], item[0][0], item[0][1]),
    )
    for (source, target), count in ranked_edges:
        if len(selected_edges) >= MAX_NETWORK_EDGES:
            truncated = True
            break
        new_node_ids = {source, target}.difference(selected_node_ids)
        if len(selected_node_ids) + len(new_node_ids) > MAX_NETWORK_NODES:
            truncated = True
            continue
        selected_edges.append((source, target, count))
        selected_node_ids.update(new_node_ids)

    edges = tuple(
        {"source": source, "target": target, "trial_count": count}
        for source, target, count in sorted(selected_edges)
    )
    nodes = tuple(_node_from_id(node_id) for node_id in sorted(selected_node_ids))
    return edges, nodes, truncated


def _node_from_id(node_id: str) -> dict[str, str]:
    """Rebuild one selected node from its stable, renderer-owned identifier."""

    group_by_value, separator, value = node_id.partition(":")
    if not separator:
        raise AssertionError("network node IDs must contain a group separator.")
    return _node(GroupBy(group_by_value), value)


def _node_id(group_by: GroupBy, value: str | int) -> str:
    return f"{group_by.value}:{value}"


def _node(group_by: GroupBy, value: str | int) -> dict[str, str]:
    return {
        "id": _node_id(group_by, value),
        "label": str(value),
        "type": group_by.value,
    }
