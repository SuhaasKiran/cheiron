# Initial data model contracts

These are framework-independent Python models for the first backend components. They validate data before it reaches the API client, planner, or chart builder. An HTTP endpoint is not part of this step yet.

## Request model

`TrialQueryRequest` represents one user question.

| Field | Required | Type | Rules |
| --- | --- | --- | --- |
| `query` | Yes | string | Trimmed, non-empty, maximum 1,000 characters. |
| `filters.drug_name` | No | string | Trimmed, non-empty when supplied. |
| `filters.condition` | No | string | Trimmed, non-empty when supplied. |
| `filters.trial_phase` | No | string | Trimmed, non-empty when supplied. |
| `filters.start_year` | No | integer | From 1900 through 2100. |
| `filters.end_year` | No | integer | From 1900 through 2100 and not before `start_year`. |

`TrialFilters.to_dict()` returns only filters that were supplied. This prevents absent filters from being confused with applied filters.

## Internal query plan

`QueryPlan` is the backend's structured instruction for later retrieval and aggregation. It is not a frontend response and it does not contain any model-generated facts.

The first plan vocabulary is deliberately small:

| Field | Initial values |
| --- | --- |
| `chart_type` | `bar_chart`, `time_series` |
| `group_by` | `start_year`, `trial_phase` |
| `measure` | `trial_count` |
| `sort` | `ascending`, `descending` |

For example, a time-trend plan can mean: apply the condition and year filters, group matching trials by start year, count the trials in each group, sort by year, and return a time-series chart.

## Visualization response

`VisualizationResponse.to_dict()` produces the stable response shape intended for a future frontend adapter:

```json
{
  "visualization": {
    "type": "bar_chart",
    "title": "Trials by Phase for Pembrolizumab",
    "encoding": {
      "x": "phase",
      "y": "trial_count"
    },
    "data": [
      {"phase": "PHASE1", "trial_count": 32}
    ]
  },
  "meta": {
    "filters": {"drug_name": "Pembrolizumab"},
    "source": "clinicaltrials.gov",
    "grouping": "trial_phase",
    "sorting": "trial_count_descending"
  }
}
```

The response model validates the chart type, a non-empty title and encoding, JSON-serializable data records, applied filters, source, and optional display metadata. Actual retrieval and aggregation will be added in later steps.
