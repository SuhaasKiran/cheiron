# ClinicalTrials.gov API client

## Responsibility

`ClinicalTrialsApiClient` is the only current component that knows how to call the public ClinicalTrials.gov studies endpoint. It uses:

```text
GET https://clinicaltrials.gov/api/v2/studies
```

It returns raw study records. It does not interpret a user question, normalize fields, aggregate data, or create chart output; those are later components.

## Public method

```python
fetch_studies(
    query_parameters: Mapping[str, str],
    *,
    page_size: int = 100,
    max_studies: int = 1000,
) -> ClinicalTrialsSearchResult
```

The caller supplies domain search parameters, for example:

```python
{"query.cond": "Melanoma"}
```

The client itself owns the `format`, `pageSize`, and `pageToken` parameters. This guarantees JSON responses and prevents callers from bypassing the pagination limits.

## Result

`ClinicalTrialsSearchResult` contains:

- `studies`: raw JSON study objects, copied into immutable top-level mappings;
- `total_count`: API total when the API provides it, otherwise `None`;
- `pages_fetched`: number of API pages read; and
- `truncated`: `True` when the configured `max_studies` limit stopped the search before all available pages were read.

The page size is limited to 1–1,000, which matches the documented maximum for this endpoint. The total number of records is also bounded at 10,000 so one request cannot create unbounded work.

## Errors and retries

The client raises clear, typed errors:

- `ClinicalTrialsApiTransportError` for connection, timeout, or invalid-JSON failures;
- `ClinicalTrialsApiHttpError` for unsuccessful HTTP responses; and
- `ClinicalTrialsApiProtocolError` for valid JSON with an unexpected response shape, including repeated page tokens.

GET requests are idempotent. The client retries transient transport failures and HTTP `429`, `500`, `502`, `503`, and `504` responses at most twice, using bounded exponential delays. It does not retry non-transient HTTP errors.

## Testing

Unit tests use an injected `JsonHttpTransport` fake. They cover URL construction, pagination, bounds, malformed responses, repeated tokens, transient retries, and non-retryable failures without network access. A live ClinicalTrials.gov call is intentionally not part of routine tests.

The API endpoint and its paginated JSON behavior are based on the official [ClinicalTrials.gov Data API documentation](https://clinicaltrials.gov/data-api/api) and [API migration guide](https://clinicaltrials.gov/data-about-studies/api-migration).
