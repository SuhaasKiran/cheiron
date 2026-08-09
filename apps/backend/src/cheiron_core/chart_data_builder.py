"""Build frontend-ready chart data through enabled, isolated renderers."""

from __future__ import annotations

from collections.abc import Iterable

from cheiron_core.chart_citations import (
    ChartCitationAnnotator,
    ChartCitationError,
    ChartCitationLimitError,
)
from cheiron_core.chart_rendering import (
    ChartCapabilityError,
    ChartRendererRegistry,
    ChartRenderLimitError,
    create_default_chart_renderer_registry,
)
from cheiron_core.models import QueryPlan, TrialRecord, VisualizationResponse


class ChartDataBuilderError(ChartCapabilityError):
    """Raised when chart data cannot be built from the supplied plan or records."""


class ChartDataBuilderLimitError(ChartDataBuilderError):
    """Raised when a valid chart would exceed a configured rendering limit."""


class ChartDataBuilder:
    """Deduplicate cleaned records before delegating to an enabled renderer.

    A repeated NCT identifier is represented once, using its first record in input
    order. The renderer registry owns chart-specific validation and aggregation.
    """

    def __init__(self, registry: ChartRendererRegistry | None = None) -> None:
        self._registry = registry or create_default_chart_renderer_registry()
        self._citation_annotator = ChartCitationAnnotator()

    def build(
        self,
        plan: QueryPlan,
        records: Iterable[TrialRecord],
    ) -> VisualizationResponse:
        """Return a deterministic chart response without performing I/O."""

        if not isinstance(plan, QueryPlan):
            raise ChartDataBuilderError("plan must be a QueryPlan instance.")
        unique_records = self._unique_records(records)
        try:
            response = self._registry.build(plan, unique_records)
            if not plan.include_citations:
                return response
            return self._citation_annotator.annotate(plan, unique_records, response)
        except ChartRenderLimitError as error:
            raise ChartDataBuilderLimitError(str(error)) from error
        except ChartCitationLimitError as error:
            raise ChartDataBuilderLimitError(str(error)) from error
        except ChartCitationError as error:
            raise ChartDataBuilderError(str(error)) from error
        except ChartCapabilityError as error:
            raise ChartDataBuilderError(str(error)) from error

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
