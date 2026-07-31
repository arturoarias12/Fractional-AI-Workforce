# TraderStrategyPackage

`TraderStrategyPackage` is the shared downstream handoff defined in
`protocols.trader`.

## Identity

- `package_id`: unique package identifier.
- `candidate_id`: identifier of the generated rule, if the run reached that
  stage.
- `trader_id`: `technical_trader_agent` for this agent.
- `lineage`: workflow, task, parent, source, and attempt identifiers.
- `backtest_request.execution_context`: code-owned workflow-run, round,
  attempt, universe, and evaluation-policy references propagated from the
  graph/runtime; the model cannot author these values.
- `mandate_reference`: stable PM mandate identifiers and as-of date.

## Research evidence

- `hypothesis`: LLM-authored testable hypothesis.
- `data_request`: point-in-time field and coverage request.
- `data_usage`: artifact, reference, provenance, limitation, and unavailable
  field summary.
- `specialty_evidence`: lens-specific evidence. Technical Trader stores its
  code-computed report under `technical_analysis`.

Raw OHLCV payloads are not copied into this summary.

## Executable candidate

- `candidate_rule`: exact codeable logic, parameters, required fields, mandate
  handling, specialty evidence IDs, and an explicit rule-use explanation for
  every cited ID.
- `candidate_rule.executor_id`: an exact registered deterministic executor.
- `backtest_request`: candidate, finalized plan, data references, and mandate
  constraints sent to the engine.

No rule becomes Risk-eligible without citing a non-fallback support/resistance
level on the correct side of the latest close.

## Evaluation

- `backtest_result`: immutable deterministic-engine status, attempt-unique
  identity, metrics, deterministic metric definitions, warnings, violations,
  ledger entry, and artifact references.
- `backtest_request.plan.validation_split`: fixed held-out window supplied by
  injected shared policy, never selected by the Technical Trader model.
- `interpretation`: LLM explanation restricted to metrics actually returned by
  the engine.
- `constraint_assessment`: declared mappings and violations requiring Risk
  validation.

## Status and resilience

- `status`: settled `completed`, `partial`, or `failed`.
- `failures`: stage, sanitized diagnostic message, and retryability.
- `eligible_for_risk_review`: true only for a complete, technically analyzed,
  successfully backtested, interpreted package.

Diagnostics are operational content. They are retained for orchestration and
must not be treated as trading instructions.
