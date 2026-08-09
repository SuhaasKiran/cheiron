# Tests

Cheiron tests are local and deterministic by default. They use fakes and saved
ClinicalTrials.gov fixtures instead of requiring a live API, LLM credentials, or
LangSmith access.

## Test layout

- `unit/` — small tests for one component at a time: settings, validation,
  query planning, retrieval, record mapping, chart building, HTTP behavior, and
  example-file structure.
- `fixtures/` — stable sample data used by tests. The ClinicalTrials.gov fixture
  has its own [README](fixtures/clinicaltrials/README.md).
- `e2e/` — fixture-backed checks of the full request-to-visualization flow.

Important coverage includes unsupported and incomplete questions, LLM fallback
behavior, ClinicalTrials.gov failure handling, chart limits, public API
authentication, CORS, rate limiting, and response contracts.

## Run tests

From the repository root:

```bash
.venv/bin/python -m pytest
```

Run one test file or one test by name when working on a focused change:

```bash
.venv/bin/python -m pytest tests/unit/http_api/test_public_api_security.py
.venv/bin/python -m pytest -k rate_limiter
```

## Other local checks

Run these before committing application changes:

```bash
.venv/bin/python -m ruff check apps/backend/src tests
.venv/bin/python -m ruff format --check apps/backend/src tests
.venv/bin/python -m mypy --no-incremental
```

Tests must not depend on current ClinicalTrials.gov responses, real secrets, or
timing-sensitive sleeps. Add a small fixture or fake when a new behavior needs
external data.
