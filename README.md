# Cheiron

Cheiron is a backend service that turns questions about clinical trials into
structured visualization specifications. It searches ClinicalTrials.gov and
returns data that a frontend can use to render charts. It does not render image
files itself.

Source repository: [github.com/SuhaasKiran/cheiron](https://github.com/SuhaasKiran/cheiron)

For example, a client can ask for trial counts over time, compare trial phases,
or explore relationships between drugs, conditions, sponsors, investigators,
and sites. The API returns a stable JSON response describing the chart, its
data, and source metadata.

## What Cheiron does

1. Checks the incoming question and optional filters.
2. Plans one or more ClinicalTrials.gov searches.
3. Fetches and maps matching trial records.
4. Builds a visualization specification from the records.
5. Returns either the requested chart data or a clear, safe error response.

The query planner can use DSPy with an OpenAI model when credentials are
configured. If that service is unavailable, the application falls back to its
deterministic keyword planner where possible. Optional LangSmith tracing records
LLM planning activity without changing the API response.

Supported visualizations include bar charts, grouped bar charts, time series,
scatter plots, histograms, and network graphs. The chart renderer registry keeps
chart types separate so they can be extended or removed without rewriting the
request, retrieval, or HTTP layers.

## Project layout

- `apps/backend/src/cheiron_core/` — application code.
- `apps/backend/README.md` — backend structure, request flow, and design notes.
- `tests/` — unit, fixture, and end-to-end tests. See [tests/README.md](tests/README.md).
- `examples/` — saved query variations and a runner for a local API. See
  [examples/README.md](examples/README.md).
- `.env.example` — every environment variable accepted by the application.

## Run locally

### 1. Install

Create and activate a local virtual environment, then install the required
packages:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 2. Configure

Copy the environment-variable template:

```bash
cp .env.example .env
```

The application automatically reads the repository-root `.env` file for local
development. Variables set by the shell or a deployment platform take priority.
`.env.example` is only a template and is not read directly.

Set `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env` to use LLM-based query
interpretation. Without them, the deterministic planner is still available for
its supported question patterns. Keep real keys only in `.env` or deployment
secrets, never in Git.

### 3. Start

Start the API from the repository root:

```bash
PYTHONPATH=apps/backend/src .venv/bin/uvicorn cheiron_core.http_api:app \
  --host 127.0.0.1 --port 8000 --reload
```

The endpoints are:

- `GET /health` — a public liveness check.
- `POST /api/v1/charts` — builds one or more visualization specifications.

Check that the API is running:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

### 4. Send a request

```bash
curl http://127.0.0.1:8000/api/v1/charts \
  -H 'Content-Type: application/json' \
  -d '{"query":"Show clinical trial counts by start year for melanoma"}'
```

## API request and response

### Request

Send a JSON object to `POST /api/v1/charts`.

| Field | Required | Meaning |
| --- | --- | --- |
| `query` | Yes | The clinical-trial question. It must be a non-empty string of at most 1,000 characters. |
| `filters` | No | Structured filters that narrow the question. |
| `include_citations` | No | Boolean. Defaults to `true`. Set it to `false` for a smaller response without per-datum citations. |

Supported `filters` fields are:

| Field | Meaning |
| --- | --- |
| `condition` | Clinical condition, such as `Melanoma`. |
| `drug_name` | One intervention or drug. |
| `drug_names` | Two to five named drugs for a comparison. Do not combine with `drug_name`. |
| `trial_phase` | Trial phase, such as `PHASE3`. |
| `start_year` / `end_year` | Inclusive years from 1900 to 2100. `end_year` cannot be before `start_year`. |

Example request with citations enabled by default:

```json
{
  "query": "Show melanoma clinical trials by phase",
  "filters": {
    "condition": "Melanoma"
  }
}
```

One user question can contain up to five independent chart requests. The API
returns the results in the same order as the requests in the question.

### Successful response

A successful response has a `results` array. Each result contains:

- `visualization.type` — one of `bar_chart`, `grouped_bar_chart`,
  `time_series`, `scatter_plot`, `histogram`, or `network_graph`.
- `visualization.title` — a readable chart title.
- `visualization.encoding` — tells a frontend which data field belongs on each
  visual channel, such as `x`, `y`, `series`, `source`, or `target`.
- `visualization.data` — the rows to plot. A network graph also has
  `visualization.nodes`.
- `meta` — filters, source query details, counts, trial IDs, the resolved chart
  plan, and any truncation flags.

Example shortened response (the counts are illustrative):

```json
{
  "results": [
    {
      "visualization": {
        "type": "bar_chart",
        "title": "Trials by Phase",
        "encoding": {"x": "trial_phase", "y": "trial_count"},
        "data": [
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
        ]
      },
      "meta": {
        "filters": {"condition": "Melanoma"},
        "source": "clinicaltrials.gov",
        "grouping": "trial_phase",
        "source_total_count": 193,
        "retrieved_study_count": 193
      }
    }
  ]
}
```

Deep citations connect a visible value to the contributing ClinicalTrials.gov
records. Each citation has an NCT ID plus the source field and value that
supports the plotted value. Citation lists can be shortened to keep responses
safe; `citations_truncated: true` tells the client when that happens.

### Error response

Errors use one stable shape:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "query must be a string."
  }
}
```

Common status codes are `400` for invalid request data, `401` for a missing or
invalid API key, `422` for unsupported questions or queries that are too large,
`429` for request limits, `502` for unusable ClinicalTrials.gov data, and `503`
when ClinicalTrials.gov or the optional LLM service is temporarily unavailable.

## Key design decisions and tradeoffs

- **Small backend components:** validation, planning, retrieval, record mapping,
  chart rendering, and HTTP handling are separate modules. This makes each part
  easier to test and change. It adds more files than a single script, but avoids
  tying chart logic to FastAPI or ClinicalTrials.gov response shapes.
- **Validated plans before source calls:** the LLM and deterministic planners
  produce a restricted internal plan, not unchecked API parameters. This reduces
  hallucinated searches and prevents unsupported chart requests from reaching the
  source API.
- **ClinicalTrials.gov is the source of truth:** the backend does not maintain a
  copy of trial data. Results stay close to the source, but depend on its
  availability and response limits.
- **Bounded work over partial answers:** retrieval, chart size, LLM concurrency,
  rate limits, and response size are capped. The service returns a clear error
  or truncation flag instead of silently presenting an incomplete chart as
  complete.
- **Citations are on by default:** traceability makes chart values easier to
  verify. It increases response size, so callers can opt out with
  `include_citations: false` when they need a smaller payload.

## Current limitations and most important improvements

- **Query understanding is not perfect.** The LLM can still reject or
  misunderstand unusual wording, while the deterministic fallback supports only
  known patterns. With more time, I would add a larger evaluation set and improve
  planner prompts and tests using real but safely stored question examples.
- **Large questions may be rejected.** The service intentionally limits source
  records, chart points, citations, and response bytes to avoid misleading or
  unsafe results. With more time, I would add an asynchronous large-query flow
  that stores a complete, reviewable result and lets the client request it in
  pages.
- **Operational limits are per application process.** The current API and LLM
  rate limits are reliable for one process, but not a global limit across many
  replicas. With more time, I would use a shared rate limiter and add production
  metrics and alerts for source failures, retries, and limit rejections.

## Example runs for the deliverable

The six-case input suite in
[examples/deliverable-sample-inputs.jsonl](examples/deliverable-sample-inputs.jsonl)
contains two valid requests with filters, one valid query-only request, one
composite query with two chart requests, and two intentional errors. Run it
twice against a running local API to save real JSON outputs with and without
deep citations:

```bash
PYTHONPATH=apps/backend/src .venv/bin/python examples/run_query_variations.py \
  --input examples/deliverable-sample-inputs.jsonl \
  --output examples/deliverable-sample-output-with-citations.jsonl \
  --include-citations true \
  --timeout-seconds 120

PYTHONPATH=apps/backend/src .venv/bin/python examples/run_query_variations.py \
  --input examples/deliverable-sample-inputs.jsonl \
  --output examples/deliverable-sample-output-without-citations.jsonl \
  --include-citations false \
  --timeout-seconds 120
```

The two output files contain the actual HTTP status and JSON response for every
input. Valid result values can change because ClinicalTrials.gov is a live data
source. See [examples/README.md](examples/README.md) for more details.

## Verify changes

Run the complete local checks from the repository root:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check apps/backend/src tests
.venv/bin/python -m ruff format --check apps/backend/src tests
.venv/bin/python -m mypy --no-incremental
```

See the test and example READMEs for more focused workflows.
