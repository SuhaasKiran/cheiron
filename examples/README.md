# Examples

This folder contains a reusable set of query variations for trying the running
Cheiron API. The examples are useful for checking chart selection, invalid or
incomplete questions, multiple requests, noisy wording, and prompt-injection
attempts.

- `query-variation-inputs.jsonl` — named input cases. Every line is one JSON
  object containing an `id`, a category, a short description, and the exact API
  request body.
- `query-variation-results.jsonl` — saved output from the most recent example
  run. It includes the HTTP status and returned JSON for each input case.
- `deliverable-sample-inputs.jsonl` — six small cases for the submission's
  example-run deliverable: four valid requests, including one composite query,
  and two intentional errors.
- `run_query_variations.py` — sends every input case to a local or remote
  Cheiron API and writes the results file.

## Run the examples

Start the API from the repository root in one terminal:

```bash
PYTHONPATH=apps/backend/src .venv/bin/uvicorn cheiron_core.http_api:app --log-level debug
```

Then, from a second terminal, run all saved cases:

```bash
PYTHONPATH=apps/backend/src .venv/bin/python examples/run_query_variations.py
```

The runner calls ClinicalTrials.gov. Results can therefore differ when the
source service or live trial data changes. LLM-based language variations need
`OPENAI_API_KEY` and `OPENAI_MODEL` in `.env`; the deterministic fallback covers
only its explicitly supported phrases.

Use `--api-url` to target another server and `--output` to keep a separate
result file:

```bash
PYTHONPATH=apps/backend/src .venv/bin/python examples/run_query_variations.py \
  --api-url http://127.0.0.1:8000/api/v1/charts \
  --output /tmp/cheiron-example-results.jsonl
```

Review results by `id`. Cases that intentionally request unsupported or invalid
behavior should return a documented error response rather than a chart.

## Create the deliverable sample outputs

Run the same six inputs twice: once with deep citations and once without them.
The `--include-citations` option overrides the setting for every request in the
file, so the two outputs are directly comparable.

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
