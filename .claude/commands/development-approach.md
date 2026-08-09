---
description: Apply the project's incremental, modular, test-driven development approach.
---

Use this command whenever planning or making a non-trivial change.

## Keep this command current

As the project evolves, update this command during the task only when a newly discovered instruction, constraint, or recurring consideration is specific enough to improve future use of this command. Keep additions concise and actionable; do not add speculative, redundant, or task-local details that do not belong in the standing workflow.

## Core approach

Build the system from independently useful, independently testable components. Start with the smallest verified capability, then compose components into a thin vertical slice before expanding coverage. Do not introduce a complex end-state architecture, framework, database, queue, cache, or deployment concern before a demonstrated need requires it.

For each change:

1. State the user-visible behavior and acceptance criteria.
2. Identify the smallest component boundary that owns that behavior.
3. Define or refine the component contract: inputs, outputs, validation, errors, ordering, nullability, and side effects.
4. Write a failing test that expresses the intended behavior, where practical.
5. Implement the minimum change that makes the test pass.
6. Refactor only after behavior is protected by tests.
7. Verify the component in isolation, then verify the smallest affected integration path.

## Test-driven development

- Prefer the Red → Green → Refactor loop: add a focused failing test, implement the smallest correct behavior, then improve the design while the tests remain green.
- Test public behavior and contracts rather than private implementation details.
- Cover normal behavior, validation failures, boundary values, empty/partial data, error handling, and relevant regressions.
- Use deterministic fixtures, fakes, or controlled test doubles for external dependencies. Do not make routine unit tests depend on network access, real credentials, clocks, or nondeterministic LLM output.
- Add a regression test before fixing a defect whenever feasible.
- Keep tests fast enough to run locally during development. Reserve slower end-to-end or live-service checks for a clearly labeled test tier.

## Modularity rules

- Give each module one clear responsibility and a small, documented public interface.
- Keep domain logic independent of frameworks, transport, persistence, and external providers.
- Depend on contracts/interfaces at integration boundaries; keep provider-specific code at the edge.
- Make dependencies directional. Shared packages must not depend on deployable applications or services.
- Prefer additive, backward-compatible changes. When a shared contract changes, update contract tests with every consumer; update files under `docs/` only when the user explicitly asks.
- Do not create a shared abstraction until at least one real use case justifies it.

## Definition of ready

Before composing a component into a broader flow, ensure its contract is explicit in code, tests, or concise inline documentation; behavior is tested; failure modes are intelligible; dependencies are explicit; and a consumer does not need undocumented knowledge of its internals.

When you make a design decision with meaningful trade-offs, record it near the relevant code or in a requested documentation file.
