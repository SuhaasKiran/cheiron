# Cheiron

Cheiron is a backend service that turns questions about clinical trials into
structured visualization specifications. It searches ClinicalTrials.gov and
returns data that a frontend can use to render charts. It does not render image
files itself.

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

Create and activate a virtual environment, then install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `OPENAI_API_KEY` and `OPENAI_MODEL` if you
want LLM-based query interpretation. The application loads `.env`
automatically. Without these values, the deterministic planner is still
available for its supported requests.

Start the API from the repository root:

```bash
PYTHONPATH=apps/backend/src .venv/bin/uvicorn cheiron_core.http_api:app --reload
```

The endpoints are:

- `GET /health` — a public liveness check.
- `POST /api/v1/charts` — builds visualization specifications.

For example:

```bash
curl http://127.0.0.1:8000/api/v1/charts \
  -H 'Content-Type: application/json' \
  -d '{"query":"Show clinical trial counts by start year for melanoma"}'
```

The response contains a `results` array. Each item has a `visualization` object
with the chart type, title, encoding, and data, along with metadata that
describes the source search.

## Public deployment settings

For a browser frontend, set the exact allowed origin in
`CHEIRON_CORS_ALLOWED_ORIGINS`. Do not use a wildcard. To require callers to
authenticate, set one or more comma-separated values in `CHEIRON_API_KEYS`; a
caller must then send the chosen value in the `X-API-Key` header.

`CHEIRON_HTTP_RATE_LIMIT_REQUESTS` and
`CHEIRON_HTTP_RATE_LIMIT_WINDOW_SECONDS` control the per-client request limit.
The built-in limiter protects one application process. A deployment with several
replicas should also use a shared edge or data-store rate limiter.

Keep real API and LangSmith keys in Railway or another deployment secret store,
never in Git.

## Verify changes

Run the complete local checks from the repository root:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check apps/backend/src tests
.venv/bin/python -m ruff format --check apps/backend/src tests
.venv/bin/python -m mypy --no-incremental
```

See the test and example READMEs for more focused workflows.
