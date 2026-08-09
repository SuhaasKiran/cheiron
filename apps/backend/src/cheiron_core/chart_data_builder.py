"""Build deterministic, frontend-ready chart data from cleaned trial records."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from cheiron_core.models.plan import ChartType, GroupBy, QueryPlan, SortOrder
from cheiron_core.models.trial import TrialRecord
from cheiron_core.models.visualization import (
    VisualizationMeta,
    VisualizationResponse,
    VisualizationSpec,
)


class ChartDataBuilderError(ValueError):
    """Raised when chart data cannot be built from the supplied plan or records."""


class ChartDataBuilder:
    """Aggregate unique cleaned trial records using a validated query plan.

    A repeated NCT identifier is counted once, using its first record in input order.
    Records missing the requested grouping value are skipped. Non-empty phase values,
    including source-provided values such as ``UNKNOWN``, remain visible in phase
    charts.
    """

    def build(
        self,
        plan: QueryPlan,
        records: Iterable[TrialRecord],
    ) -> VisualizationResponse:
        """Return a deterministic chart response without performing I/O."""

        self._validate_plan(plan)
        unique_records = self._unique_records(records)

        if plan.group_by is GroupBy.START_YEAR:
            data = self._build_start_year_data(unique_records, plan.sort)
            visualization = VisualizationSpec(
                chart_type=plan.chart_type,
                title="Trials by Start Year",
                encoding={"x": "start_year", "y": "trial_count"},
                data=data,
            )
            meta = VisualizationMeta(
                filters=plan.filters,
                units="trials",
                time_granularity="year",
                grouping=plan.group_by.value,
                sorting=f"start_year_{plan.sort.value}",
            )
        else:
            data = self._build_trial_phase_data(unique_records, plan.sort)
            visualization = VisualizationSpec(
                chart_type=plan.chart_type,
                title="Trials by Phase",
                encoding={"x": "trial_phase", "y": "trial_count"},
                data=data,
            )
            meta = VisualizationMeta(
                filters=plan.filters,
                units="trials",
                grouping=plan.group_by.value,
                sorting=f"trial_count_{plan.sort.value}",
            )

        return VisualizationResponse(visualization=visualization, meta=meta)

    @staticmethod
    def _validate_plan(plan: QueryPlan) -> None:
        if not isinstance(plan, QueryPlan):
            raise ChartDataBuilderError("plan must be a QueryPlan instance.")

        supported_pairs = {
            (ChartType.TIME_SERIES, GroupBy.START_YEAR),
            (ChartType.BAR_CHART, GroupBy.TRIAL_PHASE),
        }
        if (plan.chart_type, plan.group_by) not in supported_pairs:
            raise ChartDataBuilderError(
                f"{plan.chart_type.value} charts must group by "
                f"{ChartDataBuilder._required_group_by(plan.chart_type).value}."
            )

    @staticmethod
    def _required_group_by(chart_type: ChartType) -> GroupBy:
        if chart_type is ChartType.TIME_SERIES:
            return GroupBy.START_YEAR
        return GroupBy.TRIAL_PHASE

    @staticmethod
    def _unique_records(records: Iterable[TrialRecord]) -> tuple[TrialRecord, ...]:
        unique_records: list[TrialRecord] = []
        seen_nct_ids: set[str] = set()

        for record in records:
            if not isinstance(record, TrialRecord):
                raise ChartDataBuilderError(
                    "records must contain TrialRecord instances."
                )
            if record.nct_id in seen_nct_ids:
                continue
            seen_nct_ids.add(record.nct_id)
            unique_records.append(record)

        return tuple(unique_records)

    @staticmethod
    def _build_start_year_data(
        records: Iterable[TrialRecord],
        sort: SortOrder,
    ) -> tuple[dict[str, object], ...]:
        counts: Counter[int] = Counter(
            record.start_year
            for record in records
            if record.start_year is not None
        )
        years = sorted(counts, reverse=sort is SortOrder.DESCENDING)
        return tuple(
            {"start_year": year, "trial_count": counts[year]} for year in years
        )

    @staticmethod
    def _build_trial_phase_data(
        records: Iterable[TrialRecord],
        sort: SortOrder,
    ) -> tuple[dict[str, object], ...]:
        counts: Counter[str] = Counter(
            phase for record in records for phase in record.phases
        )
        if sort is SortOrder.ASCENDING:
            phases = sorted(counts, key=lambda phase: (counts[phase], phase))
        else:
            phases = sorted(counts, key=lambda phase: (-counts[phase], phase))
        return tuple(
            {"trial_phase": phase, "trial_count": counts[phase]} for phase in phases
        )
