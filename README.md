# Cheiron

Initial monorepo scaffold. It currently includes only the Python settings and local test foundation needed to begin implementation; task-specific backend functionality has not been added.

## Layout

- `apps/` — deployable user-facing applications, if needed later.
- `services/` — independently deployable backend services.
- `packages/` — shared, versioned libraries and contracts.
- `docs/` — project decisions, requirements, and operating documentation.
- `tests/` — cross-package or end-to-end test suites.
- `tooling/` — shared development and automation configuration.

The repository uses Python and `pytest` for the initial foundation, while leaving framework, database, deployment, and other infrastructure choices open until they are needed.

## Local development

This first foundation uses Python and `pytest` only.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest
```
