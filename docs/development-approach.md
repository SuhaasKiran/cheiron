# Incremental modular development approach

## Objective

Build the project as a monorepo of small backend components with clear contracts. Begin with basic, independently useful capabilities, verify each one in isolation, and then compose them into progressively richer flows. Avoid committing to a complex end-state architecture before the core behavior is demonstrated and tested.

## Guiding principles

### 1. Start with independent capabilities

Identify components that can be developed, modified, verified, and tested without requiring the rest of the system. Typical component categories include external-data access, domain normalization, validation, business services, persistence adapters, and shared contracts.

Each component should have one clear responsibility, a narrow public interface, and explicit inputs, outputs, failure modes, and ownership of its data transformations.

### 2. Define contracts before composition

Components communicate through stable, typed, documented contracts rather than through knowledge of each other's internals. The contract should cover:

- input and output shapes;
- validation rules and defaults;
- expected errors and retry/timeout behavior where applicable;
- ordering, pagination, nullability, and other semantic guarantees; and
- versioning or compatibility expectations when a contract evolves.

This lets internal implementations change without forcing downstream changes, and it makes contract tests possible before integration work begins.

### 3. Build the smallest useful vertical slices

Prefer a simple end-to-end capability that is real, observable, and tested over speculative infrastructure or a broad but unverified architecture. A slice should deliver one clearly defined outcome using the minimum components necessary. Once verified, extend it by adding one capability or variation at a time.

### 4. Verify at the component boundary

Every component should be testable independently. Use the appropriate level of verification:

- unit tests for pure transformations and business rules;
- contract tests for public interfaces and adapters;
- fixture-based tests for external API mapping and unusual data shapes; and
- a small number of integration tests for composed flows.

Tests should focus on behavior at the boundary, including invalid inputs, empty data, partial failures, and representative edge cases—not the internal implementation details.

### 5. Keep dependencies directional

Use dependency inversion at integration points: core domain behavior should depend on interfaces/contracts, while infrastructure-specific implementations live at the edge. Shared packages must not import deployable services or applications. Avoid circular dependencies and avoid placing cross-cutting logic in an unowned catch-all module.

### 6. Delay irreversible choices

Do not introduce a framework, database, queue, caching layer, deployment topology, or AI provider simply because it might be needed later. Add a dependency only when a verified capability requires it and its trade-offs are understood. Keep adapters thin so later replacement is localized.

### 7. Favor observability and repeatability

Make behavior understandable during development: use structured errors, clear logs/diagnostics, deterministic transformations where possible, and reproducible fixtures/examples. Record assumptions and decisions in documentation as they are made.

## Suggested monorepo responsibilities

The initial folders are intentionally generic. As requirements become concrete, they can take on the following roles without forcing a particular language or tooling choice:

| Location | Intended responsibility |
| --- | --- |
| `apps/` | Deployable applications and all backend implementations. The current backend belongs in `apps/backend/`; optional clients or demos can also live here. |
| `services/` | Currently unused. Do not place backend source code here. If it gains a future purpose, document that purpose before using it. |
| `packages/` | Reusable shared libraries with explicit ownership. Do not place application/backend code here. |
| `tests/` | Cross-component, contract, integration, and end-to-end tests. Component-local unit tests may live beside code if the chosen ecosystem favors it. |
| `tooling/` | Shared linting, formatting, build, test, CI, and developer automation configuration. |
| `docs/` | Requirements, architecture decisions, schemas, examples, and operational notes. |

This is a convention, not an architecture commitment. A new component should be placed according to its ownership and deployment boundary, not merely by technical category.

## Delivery sequence

1. **Discover and specify.** Convert the task into explicit user-facing contracts, supported behaviors, acceptance criteria, and known unknowns.
2. **Implement foundational components.** Build pure and external-facing components separately, with unit and contract tests first.
3. **Verify each component.** Exercise happy paths, invalid input, edge cases, and external-data failures with fixtures or controlled test doubles.
4. **Compose a minimal flow.** Connect only the components necessary for one basic end-to-end use case; preserve seams through interfaces.
5. **Validate the integration.** Add end-to-end tests and real example outputs; inspect error handling and observability.
6. **Expand deliberately.** Add one query type, data source, service capability, or visualization class at a time, updating contracts and tests together.
7. **Harden when justified.** Introduce performance, caching, persistence, deployment, security, and operational concerns in response to demonstrated needs and measured constraints.

## Change-management rules

- A component change should be accompanied by tests for its public behavior.
- Changes to shared contracts should be explicit, documented, and compatibility-reviewed before dependent components are updated.
- Prefer additive changes and adapters during transitions; avoid broad rewrites when a small boundary-preserving change will work.
- Do not let an unverified integration drive changes inside multiple components at once. First isolate the failing boundary, then make the smallest corrective change.
- Keep task-specific decisions out of generic infrastructure until they are stable enough to justify a shared abstraction.

## Definition of ready for the next layer

A component is ready to be integrated when its purpose and contract are documented, expected behavior is tested, errors are intelligible, dependencies are explicit, and a consumer can use it without relying on undocumented internal behavior. A composed flow is ready to expand when it has an observed end-to-end result, reproducible examples, and tests that protect its core contract.
