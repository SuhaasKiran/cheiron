# Trial retrieval

## Responsibility

`TrialRetriever` connects a validated `QueryPlan` to the ClinicalTrials.gov API client. It decides which safe API search parameters to use, keeps the search bounded, and returns raw study records with retrieval metadata.

It does not clean nested records, count trials, or create chart data. Those jobs belong to the later mapper and chart-data builder.

## Public contract

```python
TrialRetriever(api_client, page_size=100, max_studies=1000)
    .retrieve(plan: QueryPlan) -> TrialRetrievalResult
```

The retriever accepts the existing API client or a small compatible fake in tests. It limits every search to at most 1,000 studies. This prevents a broad request from creating unbounded work.

## Filter mapping

| Plan filter | ClinicalTrials.gov parameter | Example |
| --- | --- | --- |
| `condition` | `query.cond` | `Melanoma` |
| `drug_name` | `query.intr` | `Pembrolizumab` |
| `trial_phase` | `filter.advanced` | `AREA[Phase]PHASE2` |
| `start_year` and/or `end_year` | `filter.advanced` | `AREA[StartDate]RANGE[2020-01-01,2024-12-31]` |

When both phase and date filters are present, the retriever joins them with `AND`. An absent start or end year becomes `MIN` or `MAX` in the date range. A phase must be exactly one of `EARLY_PHASE1`, `PHASE1`, `PHASE2`, `PHASE3`, `PHASE4`, or `NA`; this prevents user input from changing the meaning of the advanced search expression.

The simple planner does not yet extract search terms from a natural-language question. Therefore, the first retriever uses only the plan's structured filters. A plan with no filters is allowed, but remains capped at 1,000 records and reports whether its result was truncated.

The retriever currently requests full raw study records rather than a selected `fields` list. The next mapper needs several nested fields, and retaining the raw record also supports later citation work. Field selection can be narrowed after the mapper defines the exact fields it consumes.

## Result and errors

`TrialRetrievalResult` contains the raw `studies`, API `total_count` when available, `pages_fetched`, `truncated`, and the exact query parameters used. The query parameters are immutable after the result is created.

If the API client fails, the retriever raises `TrialRetrievalDependencyError` and retains the original error as its cause. Invalid plans, limits, or phase values raise `TrialRetrievalError` or `ValueError` before an API call is made.

## Testing

Unit tests use a fake search client. They cover filter translation, open date ranges, no-filter plans, result metadata, configured limits, and API-failure handling without calling the network.

The external parameter names and advanced search syntax follow the official [ClinicalTrials.gov API](https://clinicaltrials.gov/data-api/api) and [Search Areas documentation](https://clinicaltrials.gov/data-api/about-api/search-areas).
