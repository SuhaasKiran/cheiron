---
description: Apply low-level design practices for modular, extensible, testable code.
---

Use this command for implementation design, refactoring, and code-structure decisions.

## Keep this command current

As the project evolves, update this command during the task only when a newly discovered instruction, constraint, or recurring consideration is specific enough to improve future low-level design work. Keep additions concise and actionable; do not add speculative, redundant, or task-local details that do not belong in this standing command.

## Design checklist

Before coding, identify:

1. The behavior to change and its acceptance criteria.
2. The owning module/component.
3. Its public contract: valid inputs, outputs, invariants, errors, and side effects.
4. Direct dependencies and whether each is an abstraction or a concrete infrastructure concern.
5. The test seam: how correctness will be verified without unrelated components.

## Modularity and abstraction

- Use composition over inheritance unless an inheritance relationship is genuinely stable and substitutable.
- Keep classes and modules cohesive: one reason to change, one clear owner for each responsibility.
- Prefer small interfaces tailored to the consumer's need over broad god interfaces.
- Hide implementation details behind explicit boundaries; do not let consumers reach into another component's internals.
- Keep pure transformation/business logic free of I/O and framework state whenever possible.
- Introduce abstractions only for real variation, testing seams, or boundary protection. Do not add indirection solely for hypothetical future use.

## Interfaces, extensibility, and SOLID principles

- Design interfaces around the needs of their consumers. Keep them small, explicit, typed, and stable; do not expose implementation details or create broad all-purpose interfaces.
- Add an extension point only when there is a real or imminent variation, such as an external provider, storage adapter, or strategy that has more than one meaningful implementation. Keep the default path simple until then.
- Prefer adding a new implementation behind an existing contract over changing consumers or adding conditionals throughout the codebase. Validate the new implementation with contract tests.
- Apply SOLID as practical design guidance, not as a reason to add layers:
  - **Single responsibility:** a module or class should have one clear reason to change.
  - **Open/closed:** extend behavior through well-defined contracts when it is safer than modifying stable code.
  - **Liskov substitution:** every implementation of an interface must honor its input, output, error, and side-effect promises.
  - **Interface segregation:** consumers should depend only on methods they use.
  - **Dependency inversion:** core logic depends on domain contracts; infrastructure provides implementations at the boundary.
- Document the contract, supported behavior, error semantics, and compatibility expectations before adding a shared extension point. Do not break existing consumers without an explicit migration path.

## Dependency discipline

- Maintain a directed acyclic dependency graph. If two modules need each other, extract the shared contract or neutral domain concept into a lower-level module.
- Dependencies should point inward from delivery/infrastructure code toward domain/application contracts—not the reverse.
- Pass collaborators in through constructors, function parameters, or a composition root; avoid global mutable state and hidden service locators.
- Keep shared utilities narrowly scoped. A generic `utils` module must not become an unowned dependency sink.
- Do not leak framework, database, HTTP, or provider types across domain boundaries; map them at adapters.

## Correctness and maintainability

- Make invalid states hard to represent through validated models, enums, value objects, and narrow types where appropriate.
- Make state transitions and side effects explicit. Preserve idempotency for operations that may be retried.
- Use deterministic behavior for ordering, time, randomness, and serialization; inject those dependencies when they affect tests.
- Optimize only with evidence. Preserve clear boundaries before introducing caches, batching, concurrency, or other complexity.
- Keep public names, errors, and return types predictable; document non-obvious invariants and trade-offs near the boundary. Add or update files under `docs/` only when the user explicitly requests it.

## Error handling and logging

- Validate untrusted input at the boundary and fail early with clear, stable error types or error results.
- Use domain-specific exceptions or structured errors for expected failures. Do not use bare `except`, silently ignore errors, or expose implementation details in public error messages.
- Catch errors at the layer that can add useful context or recover safely. Preserve the original cause when wrapping an error, and do not convert a failure into false success.
- Separate expected business errors from unexpected faults. Map them to transport-specific responses only in the delivery adapter.
- Log structured, useful context such as operation name, safe identifiers, dependency name, and error type. Never log secrets, tokens, passwords, raw sensitive data, or full untrusted payloads.
- Keep logging at side-effect boundaries. Pure domain code should return values/errors rather than write logs directly.
- Use an appropriate level: `debug` for development diagnostics, `info` for meaningful lifecycle events, `warning` for recoverable problems, and `error` for failures requiring attention. Avoid duplicate logs for the same failure at every layer.

## Async and concurrency

- Use asynchronous code only when it provides a clear benefit for I/O-bound work or controlled concurrency. Keep pure domain logic synchronous unless there is a real reason otherwise.
- Do not call blocking I/O or long CPU-bound work directly in an async path. Use the appropriate async client, background worker, or explicit offloading mechanism.
- Set timeouts for every external operation. Handle cancellation, clean up resources, and propagate cancellation rather than swallowing it.
- Bound concurrency, retries, request sizes, and queue/work sizes. Do not create unbounded tasks or retries.
- Design externally visible operations to be idempotent when they can be retried. Make ordering and shared-state access explicit.
- Test async success, timeout, cancellation, retry, and partial-failure paths with deterministic fakes; do not rely on timing-sensitive tests.

## Python packages, virtual environments, and environment variables

- In this monorepo, place all backend/application code in `apps/` (currently `apps/backend/`). Reserve the repository's `packages/` directory for reusable shared libraries, not backend implementation code. Do not place backend source code in `services/`; that directory is currently unused.
- When this command refers to Python packages, it means installed third-party libraries and project libraries—not the monorepo's `packages/` directory unless a reusable library is deliberately being created.
- Use a project-local virtual environment named `.venv`. Create it with `python -m venv .venv` and activate it before installing or running project tools.
- Record required Python libraries and installed packages in `requirements.txt`. Add a dependency only when it is needed, remove unused dependencies, and use reproducible version constraints according to the repository convention.
- Install dependencies with `python -m pip install -r requirements.txt`; do not rely on globally installed packages or undocumented local tools.
- Keep package-installation changes focused. Review new dependencies for maintenance, security, license, and whether a standard-library or existing dependency solution is sufficient.
- Read configuration from environment variables at the application boundary through a validated settings object. Pass settings or narrow configuration values into components instead of reading environment variables throughout the codebase.
- Keep local secrets in an untracked environment file when needed, provide a safe documented example file without secrets, and never commit credentials, tokens, or private configuration.

## Refactoring rule

Refactor in small, behavior-preserving steps with tests green after each step. If a design flaw spans multiple modules, first add/strengthen tests at the relevant contracts, then change one dependency direction or interface at a time.
