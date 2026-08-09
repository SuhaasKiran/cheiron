---
description: Implement reliable LLM, agent, tool, and LangChain/LangSmith integrations.
---

Use this command for any LLM inference, prompt, structured-output, agent, retrieval, tool, evaluation, or LangChain/LangSmith change.

## Keep this command current

As the project evolves, update this command during the task only when a newly discovered instruction, constraint, or recurring consideration is specific enough to improve future LLM work. Keep additions concise and actionable; do not add speculative, redundant, or task-local details that do not belong in this standing command.

## System design

- Treat the LLM as an untrusted probabilistic component, not a source of authoritative facts or a substitute for deterministic business logic.
- Separate orchestration, prompts, model/provider adapters, tools, retrieval, validation, domain policy, and presentation. Keep provider-specific LangChain code at an adapter boundary.
- Define a narrow capability and success criteria before adding an agent. Prefer a deterministic pipeline or a single structured call over an autonomous multi-step agent when that meets the requirement.
- Give each tool a precise purpose, typed input/output schema, least-privilege access, clear timeout, and predictable error behavior. Tools must enforce authorization and input validation themselves; never rely on the model to do so.
- Bound autonomy: allowlist tools, cap iterations/tool calls, token use, time, concurrency, and retrieval size. Provide safe termination and fallback behavior.

## Structured inputs and outputs

- Use explicit, versioned schemas (for example Pydantic models or JSON Schema) for request context, tool arguments, intermediate plans, and final outputs.
- Validate model output after every boundary. Reject, repair through a bounded retry, or fall back safely when parsing/schema validation fails; never pass unvalidated model text to downstream tools or clients.
- Make prompts specify the task, available context, constraints, source-of-truth rules, and required output schema. Keep instructions and user-provided content clearly separated.
- Treat all retrieved documents, tool responses, and user content as untrusted data. Do not allow them to override system/developer policy or tool permissions.
- Include provenance/source identifiers with claims derived from retrieval or tools. Do not fabricate citations, tool results, or facts not present in the provided source data.

## Reliability and safety

- Use low-variance settings where deterministic structured extraction/classification is needed. Do not rely on prompt wording alone for correctness.
- Handle provider failures, rate limits, malformed output, timeouts, duplicate tool calls, and partial execution explicitly. Use bounded retries with backoff only for transient, idempotent operations.
- Design idempotent tool operations or require explicit confirmation for side effects. Keep state transitions and human-approval gates explicit.
- Minimize data sent to models. Redact secrets and sensitive data from prompts, logs, traces, and evaluations; apply retention and access controls appropriate to the data.
- Protect against prompt injection, indirect prompt injection, data exfiltration, unsafe tool invocation, and resource exhaustion. Validate retrieval sources and enforce tool policy outside the prompt.

## LangChain and LangSmith

- Use LangChain for model/tool/retrieval orchestration behind internal interfaces. Do not spread framework-specific types across domain code.
- Centralize model configuration, credentials, timeouts, retry policy, callbacks, and prompt versions. Make model/provider selection configurable rather than hard-coded in business logic.
- Use LangSmith tracing for relevant runs, with stable run names, tags, metadata, prompt/model versions, latency, token/cost information where available, and safely redacted inputs/outputs.
- Build a small representative LangSmith evaluation dataset early. Include successful cases, malformed/ambiguous inputs, adversarial/prompt-injection cases, failures, and regressions.
- Establish measurable quality criteria before tuning prompts or switching models: schema-valid rate, groundedness/provenance, task accuracy, tool-error rate, latency, cost, and safety-policy compliance.
- Never put secrets or sensitive user data into LangSmith metadata, tags, feedback, datasets, or traces.

## Testing and evaluation

- Unit-test deterministic orchestration, schema validation, tool wrappers, policy gates, and fallbacks with mocked model/tool responses.
- Keep a versioned set of golden inputs and expected structured outputs. Add a regression case for every observed model or agent failure.
- Test parsing failures, refusal/fallback behavior, tool timeouts/errors, invalid tool arguments, repeated calls, source absence, and adversarial instructions.
- Use live model calls only in a clearly labeled integration/evaluation tier with controlled cost and data. Local CI must not require uncontrolled model output or real secrets.
- Report the model, prompt, schema, and evaluation version alongside material behavior changes.
