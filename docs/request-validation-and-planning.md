# Request validation and simple planning

## Request validation

The request validator is the single boundary for an incoming JSON object. It rejects an unknown field, malformed object, invalid model value, non-JSON value, or a request larger than 8,192 bytes before the rest of the backend uses it.

Supported payload shape:

```json
{
  "query": "How many melanoma trials started each year?",
  "filters": {
    "drug_name": "Pembrolizumab",
    "condition": "Melanoma",
    "trial_phase": "PHASE2",
    "start_year": 2020,
    "end_year": 2024
  }
}
```

`query` is required. `filters` is optional. When present, a filter may contain only the five fields shown above. The validator returns a normalized `TrialQueryRequest`, not the original dictionary.

## Simple query planner

The simple planner does not call an LLM or external API. It accepts a validated `TrialQueryRequest` and supports two clear question types:

- A question containing `per year`, `each year`, `by year`, `over time`, or `yearly` becomes a time-series trial-count plan grouped by start year.
- A question containing `by phase`, `across phases`, `phase distribution`, or `distributed across phases` becomes a bar-chart trial-count plan grouped by trial phase.

The request filters are copied into the plan. A question with neither pattern, or with both patterns, raises `UnsupportedQueryError` so a later LLM planner or user-facing API can handle it clearly instead of guessing.
