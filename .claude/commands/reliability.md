---
description: Review changed behavior for reliability risks, failure handling, data integrity, and operational safety.
---

Use this command when a change handles external data or dependencies, transforms data, changes request limits or retries, introduces state, or can affect correctness under failure or load. Use it during implementation and as part of `/reviewer` before a commit when applicable.

## Keep this command current

As the project evolves, update this command during the task only when a newly discovered instruction, constraint, or recurring consideration is specific enough to improve future reliability reviews. Keep additions concise and actionable; do not add speculative, redundant, or task-local details that do not belong in this standing command.

## Review workflow

1. Identify the changed boundary, dependency, data flow, and failure modes.
2. Check the applicable sections below. Do not require irrelevant infrastructure for a small pure component.
3. Inspect tests for both expected behavior and meaningful failure paths.
4. Report each issue with its severity, location, impact, and a concrete correction.

## Data completeness and semantics

- Ensure a partial, sampled, paginated, or truncated result is visible in returned metadata. Never present it as a complete answer.
- Check deterministic ordering, grouping, sorting, and count behavior.
- Define and test handling for empty data, duplicates, missing values, unknown categories, multi-valued fields, and partial dates or time zones.
- Preserve source identifiers and supporting source data when later outputs need to be traceable or auditable.
- Do not silently discard malformed external records unless the contract explicitly permits that behavior and reports it.

## External dependencies and API changes

- Verify request parameters, response mappings, default values, and provider-specific enums against the current supported contract.
- Handle timeouts, rate limits, retries, malformed responses, missing fields, repeated pagination tokens, and unexpected provider values explicitly.
- Retry only transient, idempotent operations. Bound retry count and delay, and preserve the original error when wrapping it.
- Keep dependency errors separate from validation and business-rule errors so an HTTP or CLI layer can respond predictably.
- Use deterministic fakes or fixtures for routine tests. Do not let unit tests depend on live networks, credentials, current provider data, or timing.

## Resource limits and safe degradation

- Check bounds for payload size, record/page count, pagination, retries, timeout, concurrency, queue/work size, and response size where applicable.
- Confirm each bound fails clearly or returns explicit truncation/degradation metadata; it must not silently produce a misleading success.
- Look for unbounded loops, recursion, task creation, memory growth, N+1 dependency calls, or expensive work inside loops.
- Ensure cancellation and resource cleanup are handled in asynchronous or streaming code.

## State, concurrency, and recovery

- For persistence, caches, queues, jobs, or retries, verify idempotency, atomicity, transaction boundaries, partial-write recovery, and duplicate-delivery behavior.
- Check shared mutable state, race conditions, ordering assumptions, cache invalidation, and concurrent update conflicts.
- Ensure a failed dependency or partial operation cannot leave an externally visible state that falsely appears complete.

## Error handling and observability

- Check that expected failures use stable, domain-specific errors or error results with useful safe context.
- Do not swallow errors, convert failures into empty success values, leak implementation details, or log the same failure repeatedly at multiple layers.
- At I/O boundaries, log the operation, safe identifiers, dependency name, and error type. Never log secrets, credentials, or complete untrusted payloads.
- When metrics or tracing exist, confirm that errors, latency, retries, and truncation can be observed without exposing sensitive data.

## Reliability test quality

- Test normal behavior and failure paths: validation, boundaries, dependency failure, malformed data, partial/no data, retry limits, and cleanup where relevant.
- Flag flaky tests, sleeps, timing assumptions, shared mutable fixtures, accidental live calls, and assertions tied to implementation details rather than contracts.
- Use minimal fixtures that directly represent the edge case under review.

## Severity guide

- **MUST_FIX:** silent partial or corrupted results; unbounded work; incorrect retry of non-idempotent work; data loss; unsafe recovery; a dependency or data failure reported as false success; secret exposure; or missing evidence for a critical failure path.
- **SHOULD_FIX:** incomplete but non-misleading metadata; a missing focused test for a meaningful failure branch; weak safe observability; avoidable nondeterminism; or a likely provider-schema drift issue with a clear low-risk correction.
- **GOOD_TO_FIX:** additional low-risk edge-case coverage, metric/tracing polish, readability improvements to failure handling, or a future resilience enhancement that is not needed by the current component.
