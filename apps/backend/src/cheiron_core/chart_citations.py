"""Attach bounded, source-backed citations to rendered chart data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from cheiron_core.chart_semantics import bounded_network_values, values_for
from cheiron_core.models import (
    ChartType,
    GroupBy,
    QueryPlan,
    TrialRecord,
    VisualizationResponse,
)

MAX_CITATIONS_PER_DATUM = 5
MAX_CITATIONS_PER_CHART = 3_000

_SOURCE_FIELD_PATHS = {
    GroupBy.START_YEAR: "protocolSection.statusModule.startDateStruct.date",
    GroupBy.TRIAL_PHASE: "protocolSection.designModule.phases",
    GroupBy.INTERVENTION: "protocolSection.armsInterventionsModule.interventions.name",
    GroupBy.SPONSOR: ("protocolSection.sponsorCollaboratorsModule.leadSponsor.name"),
    GroupBy.CONDITION: "protocolSection.conditionsModule.conditions",
    GroupBy.INVESTIGATOR: (
        "protocolSection.contactsLocationsModule.overallOfficials.name"
    ),
    GroupBy.SITE: "protocolSection.contactsLocationsModule.locations.facility",
    GroupBy.COUNTRY: "protocolSection.contactsLocationsModule.locations.country",
}


class ChartCitationError(ValueError):
    """Raised if a rendered datum cannot be traced to a contributing record."""


class ChartCitationLimitError(ChartCitationError):
    """Raised when a chart cannot include one citation for every visible item."""


class ChartCitationAnnotator:
    """Add deterministic citations without changing chart aggregation semantics.

    The response keeps at least one source reference for every rendered datum. Extra
    references are allocated fairly and deterministically until the per-datum or
    per-chart limit is reached. A datum and chart metadata explicitly state when
    their citation list is only a bounded subset.
    """

    def annotate(
        self,
        plan: QueryPlan,
        records: tuple[TrialRecord, ...],
        response: VisualizationResponse,
    ) -> VisualizationResponse:
        """Return the response with source citations for every visible datum."""

        rendered_item_count = len(response.visualization.data) + len(
            response.visualization.nodes
        )
        if rendered_item_count > MAX_CITATIONS_PER_CHART:
            raise ChartCitationLimitError(
                "Chart has too many data points for source citations."
            )
        data_candidate_lists = tuple(
            self._candidates_for_datum(plan, row, records)
            for row in response.visualization.data
        )
        node_candidate_lists = tuple(
            self._candidates_for_node(plan, node, records)
            for node in response.visualization.nodes
        )
        candidate_lists = data_candidate_lists + node_candidate_lists
        if any(not candidates for candidates in candidate_lists):
            raise ChartCitationError(
                "A rendered chart datum has no contributing source record."
            )

        citation_lists, citations_truncated = self._allocate(candidate_lists)
        data_citations = citation_lists[: len(data_candidate_lists)]
        data_truncated = citations_truncated[: len(data_candidate_lists)]
        node_citations = citation_lists[len(data_candidate_lists) :]
        node_truncated = citations_truncated[len(data_candidate_lists) :]
        data = tuple(
            self._row_with_citations(row, citations, truncated)
            for row, citations, truncated in zip(
                response.visualization.data,
                data_citations,
                data_truncated,
                strict=True,
            )
        )
        nodes = tuple(
            self._row_with_citations(node, citations, truncated)
            for node, citations, truncated in zip(
                response.visualization.nodes,
                node_citations,
                node_truncated,
                strict=True,
            )
        )
        return replace(
            response,
            visualization=replace(response.visualization, data=data, nodes=nodes),
            meta=replace(
                response.meta,
                citations_truncated=any(citations_truncated),
            ),
        )

    def _candidates_for_datum(
        self,
        plan: QueryPlan,
        row: Mapping[str, object],
        records: tuple[TrialRecord, ...],
    ) -> tuple[dict[str, object], ...]:
        if plan.chart_type in {ChartType.TIME_SERIES, ChartType.HISTOGRAM}:
            year = self._row_value(row, "start_year")
            return self._matching_citations(
                records,
                ((GroupBy.START_YEAR, year),),
            )
        if plan.chart_type is ChartType.BAR_CHART:
            group_value = self._row_value(row, plan.group_by.value)
            return self._matching_citations(records, ((plan.group_by, group_value),))
        if plan.chart_type is ChartType.GROUPED_BAR_CHART:
            if plan.series_by is None:
                raise ChartCitationError("grouped bar data requires a series field.")
            group_value = self._row_value(row, plan.group_by.value)
            series_value = self._row_value(row, plan.series_by.value)
            return self._matching_citations(
                records,
                ((plan.group_by, group_value), (plan.series_by, series_value)),
            )
        if plan.chart_type is ChartType.SCATTER_PLOT:
            if plan.series_by is None:
                raise ChartCitationError("scatter data requires a series field.")
            nct_id = self._row_value(row, "nct_id")
            matching_records = tuple(
                record for record in records if record.nct_id == nct_id
            )
            return tuple(
                self._citation(
                    record,
                    (
                        (GroupBy.START_YEAR, record.start_date),
                        (plan.series_by, list(values_for(record, plan.series_by))),
                    ),
                )
                for record in matching_records
            )
        if plan.chart_type is ChartType.NETWORK_GRAPH:
            if plan.series_by is None:
                raise ChartCitationError("network data requires a series field.")
            source = self._row_value(row, "source")
            target = self._row_value(row, "target")
            return tuple(
                self._citation(
                    record,
                    ((plan.group_by, source_value), (plan.series_by, target_value)),
                )
                for record in sorted(records, key=lambda item: item.nct_id)
                for source_value in bounded_network_values(record, plan.group_by)[0]
                if self._node_id(plan.group_by, source_value) == source
                for target_value in bounded_network_values(record, plan.series_by)[0]
                if self._node_id(plan.series_by, target_value) == target
            )
        raise ChartCitationError("The chart type does not support source citations.")

    def _candidates_for_node(
        self,
        plan: QueryPlan,
        node: Mapping[str, object],
        records: tuple[TrialRecord, ...],
    ) -> tuple[dict[str, object], ...]:
        """Trace a visible network node to records containing its exact value."""

        if plan.chart_type is not ChartType.NETWORK_GRAPH:
            return ()
        raw_type = node.get("type")
        label = node.get("label")
        if not isinstance(raw_type, str) or not isinstance(label, str):
            raise ChartCitationError("Rendered network node has invalid source fields.")
        try:
            group_by = GroupBy(raw_type)
        except ValueError as error:
            raise ChartCitationError(
                "Rendered network node has an unknown type."
            ) from error
        return tuple(
            self._citation(record, ((group_by, label),))
            for record in sorted(records, key=lambda item: item.nct_id)
            if label in bounded_network_values(record, group_by)[0]
        )

    @staticmethod
    def _row_value(row: Mapping[str, object], field_name: str) -> str | int:
        value = row.get(field_name)
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ChartCitationError(
                f"Rendered chart data has an invalid {field_name} value."
            )
        return value

    @staticmethod
    def _matching_citations(
        records: tuple[TrialRecord, ...],
        evidence: tuple[tuple[GroupBy, str | int], ...],
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            ChartCitationAnnotator._citation(record, evidence)
            for record in sorted(records, key=lambda item: item.nct_id)
            if all(
                value in values_for(record, group_by) for group_by, value in evidence
            )
        )

    @staticmethod
    def _citation(
        record: TrialRecord,
        evidence: tuple[tuple[GroupBy, object], ...],
    ) -> dict[str, object]:
        return {
            "nct_id": record.nct_id,
            "evidence": [
                {
                    "field": _SOURCE_FIELD_PATHS[group_by],
                    "value": ChartCitationAnnotator._source_value(
                        record, group_by, value
                    ),
                }
                for group_by, value in evidence
            ],
        }

    @staticmethod
    def _source_value(
        record: TrialRecord,
        group_by: GroupBy,
        value: object,
    ) -> object:
        """Prefer the exact source date over a derived calendar bucket."""

        if group_by is GroupBy.START_YEAR and isinstance(value, int):
            if record.start_date is None:
                raise ChartCitationError(
                    "A start-year citation requires a source date."
                )
            return record.start_date
        return value

    @staticmethod
    def _node_id(group_by: GroupBy, value: str | int) -> str:
        return f"{group_by.value}:{value}"

    @staticmethod
    def _allocate(
        candidate_lists: tuple[tuple[dict[str, object], ...], ...],
    ) -> tuple[tuple[tuple[dict[str, object], ...], ...], tuple[bool, ...]]:
        """Give each datum one citation before allocating deterministic extras."""

        selected = [[candidates[0]] for candidates in candidate_lists]
        remaining = MAX_CITATIONS_PER_CHART - len(candidate_lists)
        next_indexes = [1] * len(candidate_lists)
        while remaining > 0:
            added = False
            for index, candidates in enumerate(candidate_lists):
                if len(selected[index]) >= MAX_CITATIONS_PER_DATUM or next_indexes[
                    index
                ] >= len(candidates):
                    continue
                selected[index].append(candidates[next_indexes[index]])
                next_indexes[index] += 1
                remaining -= 1
                added = True
                if remaining == 0:
                    break
            if not added:
                break

        citation_lists = tuple(tuple(citations) for citations in selected)
        truncated = tuple(
            len(citations) < len(candidates)
            for citations, candidates in zip(
                citation_lists, candidate_lists, strict=True
            )
        )
        return citation_lists, truncated

    @staticmethod
    def _row_with_citations(
        row: Mapping[str, object],
        citations: tuple[dict[str, object], ...],
        truncated: bool,
    ) -> dict[str, object]:
        enriched = dict(row)
        enriched["citations"] = list(citations)
        if truncated:
            enriched["citations_truncated"] = True
        return enriched
