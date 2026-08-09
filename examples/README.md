# Query-variation workflow runs

`query-variation-inputs.jsonl` contains named test cases for valid chart requests, non-visual requests, invalid input, unrelated or incomplete questions, all six supported chart types, multiple independent requests, noisy language, and prompt-injection attempts. Each line wraps the exact API body in a `request` field so that the `id`, category, and expected outcome stay with the result.

`query-variation-results.jsonl` is overwritten by the runner. It contains the HTTP status and complete JSON response for every input line, including expected error responses.

## Run the complete workflow

The full suite uses the FastAPI endpoint, the configured query planner, ClinicalTrials.gov retrieval, record mapping, and chart rendering. To exercise varied language, multiple independent queries, and every chart type, configure `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env`. Without them, the safe deterministic fallback supports only a smaller set of explicit chart phrases. The run also calls ClinicalTrials.gov, so source availability and result-size limits can affect individual cases.

In one terminal, start the local API from the repository root:

```bash
PYTHONPATH=apps/backend/src .venv/bin/uvicorn cheiron_core.http_api:app --log-level debug
```

In a second terminal, run every case and write the results:

```bash
PYTHONPATH=apps/backend/src .venv/bin/python examples/run_query_variations.py
```

The results are saved to `examples/query-variation-results.jsonl`. To use a different server or keep a dated output file, pass `--api-url` or `--output`:

```bash
PYTHONPATH=apps/backend/src .venv/bin/python examples/run_query_variations.py \
  --api-url http://127.0.0.1:8000/api/v1/charts \
  --output examples/query-variation-results-2026-08-09.jsonl
```

Review every line by its `id`. A case that expects an error is successful when it receives the documented safe error response; it is not expected to produce a visualization.
