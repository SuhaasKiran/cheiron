---
description: Implement or modify Python backend code using robust, maintainable service design.
---

Use this command for any Python backend change, including APIs, services, persistence, integrations, configuration, background work, and error handling.

Place all backend implementation code in `apps/` (currently `apps/backend/`). Do not place backend source code in `packages/` or `services/`; `packages/` is reserved for reusable libraries and `services/` is currently unused.

## Keep this command current

As the project evolves, update this command during the task only when a newly discovered instruction, constraint, or recurring consideration is specific enough to improve future Python backend work. Keep additions concise and actionable; do not add speculative, redundant, or task-local details that do not belong in this standing command.

## Design boundaries

- Begin with the request/response or service contract; make schemas, validation, defaults, and error semantics explicit.
- Separate transport concerns (HTTP/CLI/worker), application orchestration, domain logic, and infrastructure adapters.
- Keep business rules and transformations in framework-independent, unit-testable modules.
- Inject external dependencies—HTTP clients, repositories, clocks, configuration, and LLM clients—through narrow interfaces or factories. Do not instantiate them deep inside domain logic.
- Keep imports directional and avoid circular dependencies. Shared code must not import application entry points.
- Prefer small, cohesive functions/classes with clear ownership of side effects.

## Python quality

- Use explicit type hints for public functions, data models, and non-obvious internal boundaries.
- Use validated data models for external inputs and outputs; do not pass unvalidated dictionaries throughout the application.
- Choose domain-specific exception types or structured error results. Never use bare `except`, silently discard errors, or expose internal tracebacks/secrets to clients.
- Manage resource lifecycles explicitly: timeouts, retries with bounded backoff, connection cleanup, cancellation, and idempotency where operations can be retried.
- Keep configuration in environment-backed settings with safe defaults. Never commit credentials, tokens, production data, or secret-bearing logs.
- Use structured logging with useful request/correlation context, while redacting sensitive values.

## API and data reliability

- Validate all untrusted input at the boundary; enforce size, type, enum, range, and pagination limits.
- Make success and error response schemas stable and documented. Use appropriate status codes and avoid ambiguous partial-success behavior.
- Make ordering, pagination, filtering, sorting, time zones, and null/missing-data handling deterministic.
- Treat external API data as unreliable: validate mappings, handle pagination, timeouts, rate limits, malformed records, and partial failures explicitly.
- Keep database/network/LLM calls out of tight loops where batching is possible; avoid N+1 queries.
- Do not add persistence or caching until its ownership, invalidation behavior, and failure handling are clear.

## FastAPI HTTP boundaries

- Use FastAPI as the HTTP/ASGI adapter only. Keep validation, planning, retrieval, mapping, and chart construction in framework-independent components.
- Create FastAPI applications through an app factory. Pass the application flow or a narrow protocol into the factory so tests can use local fakes and routes do not construct dependencies per request.
- Keep route handlers thin: parse transport input, call the flow once, and return the validated response contract. Use synchronous route functions for synchronous dependencies; if an async route must read the request body before calling synchronous work, run that work in FastAPI's thread pool rather than blocking the event loop.
- Define stable success and error response shapes. Map expected domain errors with explicit exception handlers; log unexpected failures safely and return a generic internal-error response.
- Enforce body and response-size limits at the HTTP boundary. Reject malformed JSON, unsupported media types, invalid methods, and oversized requests before calling the application flow.
- Test the ASGI application locally with FastAPI's `TestClient`. Cover route and method handling, request parsing, response schema, error status codes, dependency failures, and resource limits without calling live services.

## Security

- Apply least privilege and authenticate/authorize every protected operation at the correct boundary.
- Use parameterized queries or safe ORM APIs; never build commands, SQL, URLs, or paths from unsanitized input.
- Enforce server-side limits on request size, concurrency, pagination, timeouts, and expensive operations.
- Avoid SSRF, unsafe deserialization, path traversal, unsafe file handling, and logging of secrets or personal data.
- Treat dependency updates and new packages as supply-chain decisions: add only needed, reputable dependencies and pin/lock them according to repository conventions.

## Verification

- Use `/tests` instructions while implementing.
- Add or update unit tests for every behavior change and contract tests for integrations or schemas.
- Run the narrowest relevant local tests first, then the affected suite and formatting/type/lint checks available in the repository.
- Do not add or update files under `docs/` unless the user explicitly requests it. Keep public-contract details clear through code, tests, and concise inline documentation.
