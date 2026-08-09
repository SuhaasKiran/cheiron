# Commit log

This log records each project commit in simple language. Each entry is added by the `/commit` command and is included in the same commit it describes.

## 2026-08-08 — FEAT: add project foundation and local test setup

- **Changed:** Added the monorepo scaffold, reusable development commands, Python settings, local pytest setup, and a saved public ClinicalTrials.gov test fixture.
- **Why:** Establish a small, reliable base that can be developed and tested locally before building the clinical-trial query flow.
- **Validated:** Ran `python -m pytest` (6 passed), `python -m compileall -q packages`, `python -m pip check`, and `git diff --check`.
