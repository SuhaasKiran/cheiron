---
description: Review, document, and create a focused Git commit using the project's commit rules.
---

Use this command only when the user explicitly asks to commit changes. Before committing, follow `/reviewer` in full. The reviewer command is the quality gate for this command.

## Keep this command current

As the project evolves, update this command during the task only when a newly discovered instruction, constraint, or recurring consideration is specific enough to improve future commit work. Keep additions concise and actionable; do not add speculative, redundant, or task-local details that do not belong in this standing command.

## Commit workflow

1. Inspect repository status, staged and unstaged changes, and relevant repository commit conventions.
2. Run the `/reviewer` procedure. Review scope, correctness, edge cases, reliability, security, tests, documentation, and accidental files.
3. Report all findings as `MUST_FIX`, `SHOULD_FIX`, or `GOOD_TO_FIX`. The coding agent's answer must list every finding, including findings that were fixed before the commit and findings intentionally deferred.
4. If any `MUST_FIX` finding exists, do **not** commit. Resolve it and re-run the relevant review and checks, or wait for the user's explicit decision when the risk cannot be resolved.
5. Resolve `SHOULD_FIX` findings when they are in scope and safe. If one is intentionally deferred, clearly record the reason and user acceptance before committing.
6. Do not expand the change solely for a `GOOD_TO_FIX` item. Report it as a suggestion.
7. Run the full configured local test suite, in addition to the relevant lint, formatting, type, build, and other checks required by `/reviewer`. If any test fails, do **not** commit unless the user explicitly instructs you to ignore the failed test(s); report the failure, its impact, and the explicit exception in the final answer. Do not use `--no-verify` to bypass checks.
8. Write a new entry in `docs/commit-log.md` before committing. Include that log entry in the same focused commit.
9. Stage only the intended files, create one atomic commit, then report its hash, message, included files, checks run, and any explicitly accepted residual risk.

## Commit message format

Use this exact format:

```text
CATEGORY: short imperative summary
```

Use one of these uppercase categories:

| Category | Use for |
| --- | --- |
| `FEAT` | New user-visible capability. |
| `FIX` | Correction of incorrect behavior. |
| `TEST` | Tests or test infrastructure only. |
| `DOCS` | Documentation only. |
| `REFACTOR` | Internal structural change with no intended behavior change. |
| `PERF` | Measured performance improvement. |
| `SECURITY` | Security hardening or vulnerability fix. |
| `CHORE` | Build, tooling, dependency, or maintenance work. |

Examples:

```text
FEAT: add validated trial query request model
FIX: reject requests with an invalid date range
TEST: cover empty trial result handling
```

Keep the summary short, specific, and written in the imperative mood. Do not use vague messages such as `update files`, `changes`, or `fix stuff`.

## Commit log entry

For every commit, add an entry at the top of `docs/commit-log.md` using this format:

```markdown
## YYYY-MM-DD — CATEGORY: short imperative summary

- **Changed:** Describe what changed in simple, easy-to-understand language. Be descriptive enough that a reader can understand the behavior or files affected without opening the code.
- **Why:** Explain in simple, easy-to-understand language why the change is needed and what problem, requirement, or benefit it addresses.
- **Validated:** Tests and checks run, or a clear statement of what could not be run and why.
```

The log entry is intentionally included in the same commit as the work it describes. The commit hash is available directly in Git history, so it does not need to be written into the file before the commit exists.

Use plain language and short sentences, but include enough practical detail to make the entry useful to someone reviewing the project later. Avoid unexplained abbreviations, implementation-only jargon, and vague wording such as "updated logic" or "improved code".

## Safeguards

- Never commit secrets, credentials, private keys, local environment files, generated artifacts, or unrelated user changes.
- Do not amend, force-push, reset, or rewrite history without explicit user instruction.
- Keep each commit focused: include the implementation, tests, documentation, and commit-log entry needed for one coherent change.
- Do not commit if tests/checks reveal unresolved `MUST_FIX` risk.
- Always list reviewer findings and full-test-suite results in the final answer, whether or not a commit is created.
