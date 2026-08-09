# Commit log

This log records each project commit in simple language. Each entry is added by the `/commit` command and is included in the same commit it describes.

## 2026-08-08 — FEAT: add plan-driven trial retrieval

- **Changed:** Added a trial retriever that turns a validated chart plan into a safe, limited ClinicalTrials.gov search. It supports condition, drug, phase, and date filters, returns raw study records with search details, and gives a clear error when the API is unavailable. Added local fake-client tests and documentation. Also added a stable dependency order to the component DAG and a commit instruction for staging new ignored documentation files.
- **Why:** The backend can now safely obtain the trial records needed for later cleaning and chart building, without mixing API details into the planner. The new limits and phase allowlist prevent a broad or malformed search from doing unnecessary work or changing the intended search meaning.
- **Validated:** Ran targeted trial-retrieval tests (8 passed), Ruff lint and format checks, mypy (19 source files), the full pytest suite (48 passed), `python -m compileall -q apps/backend/src`, `python -m pip check`, and `git diff --check`.

## 2026-08-08 — FEAT: add request validation and query planning

- **Changed:** Added a request validator that checks incoming question data, accepts only the supported filters, limits request size, and returns a clean request model. Added a simple planner that turns questions about trials by year or by phase into chart plans, with tests and clear documentation. Removed empty placeholder folders that are no longer needed, and clarified that future commit-log entries must describe changes and reasons in plain language.
- **Why:** The backend now has safe, testable steps for checking a request and deciding the first supported chart. This keeps later API and chart work separate from untrusted input and makes project history easier to understand.
- **Validated:** Ran targeted validator and planner tests (12 passed), Ruff lint and format checks, mypy (17 source files), the full pytest suite (40 passed), `python -m compileall -q apps/backend/src`, `python -m pip check`, and `git diff --check`.

## 2026-08-08 — FEAT: add ClinicalTrials API client foundation

- **Changed:** Moved backend code into `apps/backend/`, added a bounded ClinicalTrials.gov API client with local fake-transport tests, configured Ruff and mypy, and clarified backend folder and development-command rules.
- **Why:** Keep backend code in one clear location while establishing a reliable, tested API boundary for later retrieval and chart-building work.
- **Validated:** Ran Ruff lint and format checks, mypy (13 source files), the full `python -m pytest` suite (28 passed), `python -m compileall -q apps/backend/src`, `python -m pip check`, and `git diff --check`.

## 2026-08-08 — FEAT: add validated query and chart models

- **Changed:** Added validated request, filter, internal-plan, and visualization-response models with unit tests and model-contract documentation. Updated commit rules to report reviewer findings and block commits on failed tests.
- **Why:** Give future API, planner, retrieval, and chart-building components stable contracts that can be tested independently.
- **Validated:** Ran the full `python -m pytest` suite (14 passed), `python -m compileall -q packages`, `python -m pip check`, and `git diff --check`.

## 2026-08-08 — FEAT: add project foundation and local test setup

- **Changed:** Added the monorepo scaffold, reusable development commands, Python settings, local pytest setup, and a saved public ClinicalTrials.gov test fixture.
- **Why:** Establish a small, reliable base that can be developed and tested locally before building the clinical-trial query flow.
- **Validated:** Ran `python -m pytest` (6 passed), `python -m compileall -q packages`, `python -m pip check`, and `git diff --check`.
