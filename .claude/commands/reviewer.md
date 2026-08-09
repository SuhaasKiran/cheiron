---
description: Review local changes, classify issues, run appropriate checks, and prepare a safe commit.
---

Use this command before every commit. Do not create a commit unless the user explicitly asks for one.

## Review procedure

1. Inspect repository status, staged and unstaged diffs, and the commit history/conventions relevant to the changed files.
2. Confirm the diff is scoped to the intended change. Identify accidental files, generated artifacts, secrets, unrelated formatting churn, and missing documentation/tests.
3. Review correctness, edge cases, reliability, security, API/schema compatibility, dependency direction, observability, and maintainability.
4. Run the narrowest relevant local test, lint, formatting, type, and build checks available in the repository; expand to the affected suite when practical.
5. Classify every finding using the categories below. Include file/line references, impact, and a concrete recommended correction.
6. If a commit is requested and no blocking findings remain, stage only the intended files and create one focused, descriptive commit using the repository's established message convention.
7. After committing, report the commit hash, message, files included, checks run, and any explicitly accepted residual risks.

## Finding severity

### MUST_FIX

Blocking defects that must be resolved before committing, unless the user explicitly accepts the risk. Examples include:

- incorrect behavior, missed important edge cases, or data corruption/loss;
- broken tests/builds or a change with no feasible evidence of core correctness;
- reliability failures such as unbounded retries, unsafe partial writes, unhandled critical failure paths, or severe performance/resource regressions;
- security vulnerabilities, secret exposure, missing authorization, injection, unsafe input handling, or sensitive-data leakage;
- breaking a documented public contract without a compatible migration; and
- circular dependencies or boundary violations that make the changed system unusable or materially unsafe to evolve.

### SHOULD_FIX

Non-blocking issues that should normally be resolved in the current change because they materially improve durability, maintenance, or future correctness. Examples include incomplete validation, missing focused tests for a meaningful new branch, unclear error handling, avoidable duplicate logic, weak observability, undocumented contract changes, or design choices likely to cause regressions as the feature expands.

### GOOD_TO_FIX

Optional improvements that do not affect current correctness or safety: naming/readability polish, minor simplification, additional low-risk tests, documentation clarity, or refactors with limited practical value today. Do not expand the commit scope solely to address these unless it is safe and requested.

## Commit safeguards

- Never commit generated files, credentials, tokens, private keys, local environments, or unrelated user changes.
- Do not amend, force-push, reset, or rewrite history without explicit user instruction.
- Keep a commit atomic: it should contain one coherent, working change with its tests and required documentation.
- Do not bypass checks or use `--no-verify` merely for convenience. If a check cannot run, disclose it and obtain explicit user direction before committing a change with unresolved MUST_FIX risk.
- Do not mark a finding resolved without confirming the relevant test or inspection result.
