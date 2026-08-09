---
description: Explicitly evaluate the current project against the submission rubric without changing code or blocking commits.
---

Use this command only when an explicit rubric evaluation is requested. It is an assessment tool, not a replacement for `/reviewer`, `/reliability`, or `/commit`.

This command does not stage, commit, modify code, or decide whether a commit is allowed. `/commit` continues to use `/reviewer` as its only quality gate.

## Keep this command current

As the project evolves, update this command during the task only when a newly discovered instruction, constraint, or recurring consideration is specific enough to improve future rubric evaluations. Keep additions concise and actionable; do not add speculative, redundant, or task-local details that do not belong in this standing command.

## Evaluation principles

- Evaluate the code, tests, configuration, and runnable behavior that exist now. Do not give credit for plans, comments, future ideas, or unverified claims.
- State the current project scope first. Evaluate implemented capabilities fairly, but clearly identify required rubric capabilities that are not implemented yet.
- Do not invent a numeric grade. For each criterion, use one of: **met**, **partially met**, **not met**, or **not applicable in the current milestone**. Explain the evidence behind the status.
- Treat a missing LLM or agent feature as **not implemented**, not as proof that the project is safe from hallucinations. If the expected submission requires an AI or agent component, report that gap explicitly.
- Prefer direct evidence: source files, public contracts, tests, local check output, and reproducible request/response behavior. Use live external services only when explicitly requested and safe.
- Separate functional defects from rubric gaps. A project can pass local tests while still lacking breadth, traceability, or an expected capability.
- Do not broaden the codebase, create documentation, or change project files during an evaluation unless the user separately asks for fixes or a report file.

## Evaluation workflow

1. Read the task requirements, relevant project commands, repository status, and the implementation/test layout. Preserve unrelated local changes.
2. Identify the current end-to-end path: input contract, validation, planning, external data access, transformation, visualization response, error behavior, and tests.
3. Inspect the public request and response schemas. Trace at least one supported request through the real local components using deterministic fixtures or fakes when possible.
4. Run the narrowest relevant tests and configured lint, formatting, type, and dependency checks. Run the full test suite when practical. Report checks that could not be run.
5. Evaluate every weighted rubric below. Record the status, concrete evidence, missing evidence, and the most useful next improvement.
6. List all findings using the severity categories in this command. Include an exact file/line reference when the issue is code-specific.
7. Finish with a short, prioritized improvement path. Do not make changes, stage files, or create a commit unless the user explicitly asks in a separate request.

## Rubric evaluation

### 1. System Design — 35%

Check whether the system has clear, rational boundaries and behaves safely with real-world API data.

- Identify the delivery layer, application workflow, domain models, data transformation, and external-provider adapter. Check that dependencies flow in one direction and avoid circular imports.
- Check that external dependencies are injected or composed at a clear boundary, rather than created deep inside domain logic.
- Inspect handling for timeouts, retries, pagination, repeated page tokens, malformed responses, missing fields, empty results, duplicates, limits, and partial/truncated results.
- Confirm that partial source data cannot be silently presented as a complete chart. Inspect safe logs and error responses for useful, non-sensitive diagnostic context.
- Check whether configuration, limits, and defaults are explicit, validated, and practical for local and future deployment use.
- Assess whether adding a new query type, data source, chart type, or delivery adapter can be done by extending a focused component rather than rewriting unrelated code.

### 2. AI / Agent Design — 20%

Check every LLM, agent, planner, tool, retrieval, or model-driven decision that is implemented. If none exists, state that clearly.

- Distinguish deterministic rules from model-based reasoning. Do not describe simple keyword matching as an AI agent.
- For each LLM/agent path, verify structured inputs and outputs, post-model validation, bounded retries, tool allowlists, time/token/call limits, failure fallback, and protection against prompt injection.
- Check that factual claims and visualization data come from validated tools or source records, not model invention. The model must not be able to silently change filters, fabricate counts, or cite unavailable sources.
- Check that planning is constrained: supported intents, required fields, ambiguity handling, and unsupported questions must be explicit and testable.
- For LangChain and LangSmith use, inspect separation of provider adapters, configuration, tracing/redaction, evaluation datasets, and regression tests. Do not require these frameworks when no LLM feature is in scope.
- If the project uses deterministic planning only, evaluate its explicit supported patterns, validation, rejection behavior, and whether its limits are communicated accurately.

### 3. Code Quality — 20%

Check readability, organization, correctness, and robustness.

- Inspect module names, public types, focused interfaces, error types, dependency direction, duplicated logic, comments/docstrings, and configuration.
- Check validation at external boundaries; immutable or well-defined internal contracts; deterministic ordering and serialization; safe error mapping; and sensitive-data redaction in logs.
- Review tests for normal behavior and meaningful edge/failure paths. Prefer local deterministic fixtures over live external calls.
- Run the configured test suite, formatter, linter, static type checker, and dependency check when available. A passing check is evidence, not proof that an untested requirement is met.
- Flag dead code, accidental generated files, hard-coded secrets, broad exception handling, silent fallback, hidden global state, or unbounded work.

### 4. Query and Visualization Coverage — 15%

Check breadth and whether supported behavior is general rather than a collection of one-off examples.

- List every query class actually supported, the required input fields, the chart type returned, and the tests proving it.
- Check whether natural-language filters, intent, and ambiguity are interpreted correctly. Do not count a query class as supported when the words are accepted but its requested meaning is ignored.
- Test or inspect multiple conditions, drugs, phases, date ranges, empty results, missing source fields, unsupported questions, and ambiguous questions where those capabilities are claimed.
- Assess whether query planning and chart construction use reusable plans, groupings, measures, and encodings rather than hard-coded response bodies.
- Identify unimplemented classes such as comparisons, geographic analyses, intervention distributions, networks, or richer visualizations. Give no credit for them unless they are reachable through the public interface and have evidence.
- Evaluate whether the visualization is appropriate to the question and whether ordering, labels, units, and empty-result behavior are clear to a frontend.

### 5. Input / Output Design — 10%

Check that contracts are unambiguous, safe, and useful to a frontend.

- Inspect request schema fields, optional versus required values, validation limits, unknown-field behavior, versioning or route conventions, and stable error shape/status codes.
- Inspect the visualization response for a clear chart type, title, encoding, data rows, filters, source, units, grouping, sorting, and relevant time granularity.
- Verify that response data is JSON-safe, deterministic, and sufficient for a frontend to render without guessing business meaning.
- Check error responses for stable machine-readable codes, safe human-readable messages, and clear distinction between invalid input, unsupported intent, source failure, and incomplete data.
- Flag information that a frontend must infer ambiguously, undocumented breaking changes, or output that cannot be traced to the supplied request.

### Bonus: Source citations and traceability

Check whether a chart can be traced back to supporting source records without exposing unnecessary raw data.

- Look for preserved source identifiers (for example, ClinicalTrials.gov NCT IDs), source URL/query metadata, retrieval timestamp or version, and a way to associate chart counts with source records.
- Verify that identifiers or drill-down provenance are available in the response or through a documented, tested follow-up contract when citation/traceability is claimed.
- Do not claim deep citations merely because an internal mapper retains source fields that never reach the API response.

## Finding severity

Use the same categories as `/reviewer`, but apply them to the expected submission quality as well as the current diff.

### MUST_FIX

Use for a functional, security, or integrity problem that makes a claimed capability unsafe or incorrect; a chart based on silent partial/corrupt data; missing validation on an implemented AI/tool boundary; fabricated provenance; a broken public contract; or a required core submission capability that is entirely absent.

### SHOULD_FIX

Use for a meaningful rubric gap that does not make the current behavior false or unsafe: incomplete query coverage, weak extensibility, missing deterministic coverage for a key failure path, unclear schema metadata, insufficient source traceability, or incomplete but non-misleading observability.

### GOOD_TO_FIX

Use for non-blocking improvements such as richer chart types, more example queries, extra tests, clearer developer documentation, optional metrics/tracing polish, or a refactor with limited immediate value.

## Required evaluation report

Use this structure in the response:

```markdown
## Scope assessed

One short description of the current implemented system and the checks run.

## Rubric assessment

| Criterion | Weight | Status | Evidence and main gap |
| --- | ---: | --- | --- |
| System Design | 35% | met / partially met / not met | ... |
| AI / Agent Design | 20% | ... | ... |
| Code Quality | 20% | ... | ... |
| Query and Visualization Coverage | 15% | ... | ... |
| Input / Output Design | 10% | ... | ... |
| Bonus: traceability | bonus | ... | ... |

## Findings

### MUST_FIX

- `[path:line]` Issue, impact, and concrete correction.

### SHOULD_FIX

- `[path:line]` Issue, impact, and concrete correction.

### GOOD_TO_FIX

- `[path:line]` Issue, impact, and concrete correction.

## Priority path

1. ...
2. ...
```

Use `None found` for an empty severity group. Clearly distinguish findings already fixed during the evaluation from intentionally deferred suggestions. Never use this report to block a commit unless the user explicitly changes the commit workflow.
