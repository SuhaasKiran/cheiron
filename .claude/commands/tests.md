---
description: Add and run tests that protect functional correctness, reliability, and security.
---

Use this command whenever behavior is added, changed, or repaired.

## Keep this command current

As the project evolves, update this command during the task only when a newly discovered instruction, constraint, or recurring consideration is specific enough to improve future testing work. Keep additions concise and actionable; do not add speculative, redundant, or task-local details that do not belong in this standing command.

## Required testing workflow

1. Identify the behavior, risk, and affected boundary.
2. Add or update a focused test before implementation when practical; otherwise add it in the same change.
3. Run the narrowest relevant test locally while iterating.
4. Run the affected test suite plus configured formatting, linting, and type checks before handoff.
5. Report exactly what ran, what passed/failed, and any validation that could not be performed.

Never claim a change is verified when tests were not run. Explain the reason and remaining risk instead.

## What to test

- **Functional correctness:** expected outputs, state changes, request/response schemas, validation, sorting, pagination, serialization, and public contracts.
- **Edge cases:** absent/empty values, nulls, malformed data, boundary values, duplicated inputs, large-but-allowed inputs, and conflicting options.
- **Reliability:** timeouts, retries, cancellation, partial dependency failure, idempotency, concurrency where relevant, and safe recovery/error messages.
- **Security:** authentication/authorization boundaries, input validation, injection/path traversal/SSRF risks, secret redaction, unsafe deserialization, and resource exhaustion limits where applicable.
- **Regressions:** write a minimal reproducer first for each fixed bug whenever possible.

## Test design

- Test behavior through public interfaces, not private methods or incidental implementation details.
- Keep unit tests deterministic, fast, and local. Use fixtures, fakes, stubs, dependency injection, and fake clocks rather than live networks, production services, credentials, or uncontrolled LLM calls.
- Use contract tests for adapters and schema boundaries. Keep a small, clearly marked integration/end-to-end tier for real component composition.
- Make test data minimal, readable, representative, and free of secrets or sensitive production data.
- Test failure paths as deliberately as success paths. Assert on stable error types/codes/messages rather than raw stack traces.
- Do not weaken, skip, or delete a test merely to make a suite pass unless its behavior is intentionally replaced and the reason is documented.

## Running tests locally

- Discover repository-specific commands from the project configuration and README; do not invent a test command when one exists.
- Run targeted tests first, then the full affected suite. Run live/external checks only when explicitly configured and safe.
- When the repository configures a formatter, linter, or static type checker, run each configured check locally before handoff. Treat a failure in any of them as a verification failure and fix it or report the remaining risk clearly.
- For each new externally visible behavior, add a local test path using mocks/fakes whenever possible.
- If a test requires unavailable infrastructure, add the best deterministic local coverage possible and state the missing integration validation clearly.
