# Commit log

This log records each project commit in simple language. Each entry is added by the `/commit` command and is included in the same commit it describes.

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
