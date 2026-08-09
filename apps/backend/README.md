# Backend design

The Cheiron backend changes a clinical-trial question into one or more
visualization specifications. It is designed as a series of small components.
Each component has one job and can be tested or replaced without changing the
whole application.

## Where the code lives

All backend source code is in `src/cheiron_core/`. The main HTTP application is
`cheiron_core.http_api:app`.

```text
HTTP request
  -> HTTP API and security checks
  -> request validation
  -> query planning
  -> ClinicalTrials.gov retrieval
  -> trial record mapping
  -> chart data building
  -> JSON visualization response
```

The flow itself is in `query_to_chart.py`. It does not know about FastAPI,
HTTP headers, or environment variables. This keeps the application logic easy
to test with small fake components.

## Request flow

### 1. HTTP API

`http_api.py` exposes two endpoints:

- `GET /health` returns a simple public liveness response.
- `POST /api/v1/charts` accepts a JSON request and returns visualization data.

The HTTP layer checks the content type, request size, and response size. It
turns expected application errors into stable JSON error responses. It also runs
the main flow in a worker thread so synchronous planning and retrieval code does
not block the async server loop.

`http_security.py` protects the chart endpoint. It supports exact-origin CORS,
optional `X-API-Key` authentication, and a bounded per-client rate limiter. The
rate limiter is local to one backend process; a multi-replica deployment needs a
shared rate limiter at the platform edge or in a data store.

### 2. Request validation

`request_validation.py` turns untrusted JSON into a `TrialQueryRequest` model.
It rejects malformed requests and invalid optional filters before the backend
does expensive work.

The models in `models/` define the shared data contracts: requests, filters,
plans, trial records, visualization specifications, and response metadata.

### 3. Query planning

The planner decides whether a question is supported, whether a visualization is
needed, which chart type is appropriate, and which ClinicalTrials.gov search
filters should be used. It can split a question into a small number of
independent chart plans.

- `query_planning.py` contains the deterministic planner. It is the safe
  fallback for explicit supported question patterns.
- `llm_query_planning.py` contains the DSPy and Pydantic-based LLM interpreter.
  It validates the LLM output before it becomes a query plan. When configured,
  it can send trace information to LangSmith. It also applies concurrency and
  request-rate limits to model calls.
- `query_interpretation_batch.py` runs the interpreter against JSON Lines input
  files. It can test planning alone or planning plus a ClinicalTrials.gov fetch.

The LLM is not trusted to produce unchecked API parameters. Structured Pydantic
models and planner validation keep its output within the backend's supported
chart and filter contracts.

### 4. Trial retrieval and mapping

`trial_retrieval.py` translates a validated plan into a bounded
ClinicalTrials.gov request. It reports source failures separately from invalid
queries and malformed source data.

The `clinicaltrials/` package contains the API client and record mapper. The
mapper converts nested source records into compact `TrialRecord` values that are
easier for chart code to use.

The flow rejects a general chart response if retrieval was truncated. This avoids
returning a partial result that looks complete. Individual chart renderers may
make clearly marked, safe summaries where their own output limit requires it.

### 5. Chart building

`chart_rendering.py` contains the chart renderer registry and the renderers for
each supported chart type. A renderer owns the grouping, sorting, and output
shape for its chart type.

`chart_data_builder.py` selects the renderer for a plan and builds a
`VisualizationResponse`. Adding a chart normally means adding one renderer and
registering it; request validation, retrieval, and HTTP code do not need to be
rewritten.

### Deep citations (source traceability)

By default, every visible chart datum includes **deep citations**: small,
structured references to the ClinicalTrials.gov records that contributed to its
value. This lets a client explain where a displayed count, time bucket, scatter
point, or network edge came from without having to guess from the aggregate.

For example, a phase bar can include a citation like this:

```json
{
  "trial_phase": "PHASE3",
  "trial_count": 41,
  "citations": [
    {
      "nct_id": "NCT01234567",
      "evidence": [
        {
          "field": "protocolSection.designModule.phases",
          "value": "PHASE3"
        }
      ]
    }
  ]
}
```

`nct_id` identifies the contributing trial. Each `evidence` entry gives the
ClinicalTrials.gov response field and the normalized field value used to build
the datum. A grouped bar or network edge has evidence for each grouping value;
a time-series bucket uses the source start-date value rather than only the
derived year. Citations are deterministic: matching records are ordered by NCT
ID, so a same input and source response produces the same citation order.

`chart_citations.py` performs this work after chart rendering. It matches each
rendered value back to the already retrieved and cleaned `TrialRecord` objects,
then attaches only source-backed references. The chart renderer still owns the
aggregation; the citation component does not change counts, grouping, sorting,
or chart selection. If a displayed value cannot be traced to at least one
record, the response fails instead of returning an unsupported claim.

To keep responses practical, the backend includes at most five citations per
visualized item and 3,000 citations across one chart. It first gives every item
one citation, then distributes additional references fairly. When a complete
citation list would exceed a limit, the item includes
`"citations_truncated": true`, and response metadata includes the same flag.
The aggregate count remains complete; only the list of supporting references is
bounded. The HTTP response limit can apply an additional citation bound: it
removes extra references fairly while keeping one per visible item and marks
the affected citations as truncated. If even that minimum traceability payload
cannot fit, the API returns a clear `422` error; narrow the query or opt out of
citations.

Clients can opt out when a smaller response is more important than traceability:

```json
{
  "query": "Show congenital adrenal hyperplasia trials by phase.",
  "filters": {"condition": "Congenital Adrenal Hyperplasia"},
  "include_citations": false
}
```

`include_citations` must be a JSON boolean and defaults to `true`. Setting it
to `false` skips citation enrichment for every result from that request,
including a multi-request query. Source-level provenance such as
`source_query`, `source_total_count`, and `source_trial_ids` remains available
in response metadata; it is separate from per-datum deep citations.

### Citation limits and meaning

Deep citations show **which retrieved records support a displayed value**. They
do not make a clinical conclusion, prove causation, or replace reading the full
trial record. A citation also does not include the full source response; it
contains only the NCT ID and the field values used for the chart.

The backend deliberately limits citation work and response size:

- A chart can have at most 3,000 visible items that need citations. A larger
  chart returns a clear chart-complexity error rather than silently leaving some
  visible items without evidence.
- A visible item normally has up to five citations. Extra matching trials are
  omitted and marked as truncated.
- The HTTP response limit can remove further extra citations. It still keeps one
  citation per visible item when possible. If that minimum response is too large,
  the caller must narrow the query or disable citations.
- ClinicalTrials.gov is live data. A later request can return different records
  or field values, so citations describe the source records retrieved for that
  particular response.

## Important design considerations and tradeoffs

- **Small, independent components:** validation, planning, retrieval, record
  mapping, chart rendering, citations, and HTTP delivery have separate owners.
  This makes unit tests and changes simpler. The tradeoff is more modules than a
  small single-file prototype.

- **Validated plans before external calls:** user text and LLM output become a
  restricted `QueryPlan` before they are used for a ClinicalTrials.gov search.
  This reduces hallucinated or unsupported searches. The tradeoff is that some
  useful but unfamiliar question wording can be rejected rather than guessed.

- **Pure chart logic:** renderers work with cleaned `TrialRecord` values, not
  HTTP or ClinicalTrials.gov objects. This keeps chart behavior deterministic
  and easy to test. The tradeoff is that a new source field must first be added
  to the record mapper before a chart can use it.

- **Bounded work instead of hidden partial results:** source retrieval, chart
  complexity, citations, LLM calls, and HTTP payloads have limits. The backend
  returns a clear error or explicit truncation metadata rather than pretending a
  partial result is complete. The tradeoff is that broad questions may need to
  be narrowed by the caller.

- **Traceability by default:** citations and response provenance help a client
  inspect where chart data came from. They make responses larger, so callers can
  set `include_citations` to `false` when response size matters more than
  datum-level traceability.

- **Per-process protections:** the built-in HTTP and LLM rate limits keep one
  backend process safe. A deployment with multiple replicas needs a shared edge
  or data-store rate limiter for one global quota.

## Error handling

The backend keeps common error types separate so clients receive useful status
codes:

- invalid request data returns `400`;
- unsupported or incomplete questions return `422`;
- source service problems return `503`;
- source data that cannot be used returns `502`;
- API-key failures return `401` and rate limits return `429`;
- unexpected failures return a safe `500` response.

Error responses do not include secrets, full request content, or raw provider
errors. Debug logs keep safe operational details such as counts and error types.

## Configuration

`settings.py` reads the repository-root `.env` file automatically. Deployment
environment variables take priority over values in that file. `.env.example`
lists every supported setting.

Important groups are:

- OpenAI model credentials and LLM limits;
- LangSmith tracing settings;
- ClinicalTrials.gov retrieval limit;
- allowed browser origins, API keys, and HTTP rate limits.

Keep real credentials in deployment secrets, not in committed files.

## Run the backend locally

From the repository root:

```bash
PYTHONPATH=apps/backend/src .venv/bin/uvicorn cheiron_core.http_api:app --reload
```

The root [README](../../README.md) explains setup and API usage. The
[tests README](../../tests/README.md) explains how to run the backend's test
suite.
