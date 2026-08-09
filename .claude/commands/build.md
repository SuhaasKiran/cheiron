---
description: Plan and implement a change by selecting the project commands that match its requirements.
---

Use this command whenever asked to implement, modify, or extend the project. It is the high-level entry point: first understand the requested behavior, then use the specific commands below that apply to the work.

## Keep this command current

As the project evolves, update this command during the task only when a newly discovered instruction, constraint, or recurring consideration is specific enough to improve future build work. Keep additions concise and actionable; do not add speculative, redundant, or task-local details that do not belong in this standing command.

## Required workflow

1. Restate the intended behavior, scope, and acceptance criteria in simple terms.
2. Read and follow `/development-approach` for every non-trivial change. Start with the smallest useful, independently testable component.
3. Select the applicable commands from the table below. Use more than one when the change crosses concerns.
4. Identify the tests to add or update before changing behavior, then use `/tests` throughout implementation.
5. Implement the smallest correct change. Keep public contracts, dependency direction, and error behavior explicit.
6. Run the narrowest relevant local checks first, then the affected suite. Report what was run and any remaining validation gap.
7. Update project documentation when the change affects a public contract, supported behavior, important design decision, or operating procedure.

## Command selection

| Requirement type | Command to use | When it applies |
| --- | --- | --- |
| Any non-trivial feature, fix, or refactor | `/development-approach` | Always start here for modular, incremental, test-driven work. |
| Python backend work | `/backend` | APIs, services, data access, configuration, external integrations, background jobs, errors, performance, or security. |
| Code structure or design change | `/lld` | New components, module boundaries, abstractions, dependency changes, refactoring, or circular-dependency risk. |
| LLM, agent, tool, LangChain, or LangSmith work | `/llm` | Prompts, structured outputs, model calls, retrieval, tools, agents, evaluations, tracing, or LLM safety/reliability. |
| Any behavior change or bug fix | `/tests` | Add/update tests and run local verification. This is required for implementation work whenever practical. |
| Preparing a commit | `/commit`, then `/reviewer` | Only when the user explicitly asks to commit. |

## Simple decision guide

- For a small pure Python rule: use `/development-approach`, `/lld`, and `/tests`.
- For an HTTP endpoint or external API integration: also use `/backend`.
- For a change that calls or interprets an LLM: also use `/llm` and `/backend`.
- For a refactor that changes how modules depend on each other: use `/lld` and `/tests`, even when behavior should stay the same.
- For documentation-only work: use the smallest relevant workflow; do not load implementation commands unnecessarily.

If the request is ambiguous, make the smallest safe assumption and state it. Do not add infrastructure or broad abstractions unless the requested behavior requires them.
