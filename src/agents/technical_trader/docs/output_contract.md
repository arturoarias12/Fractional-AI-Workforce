# TraderStrategyPackage

`TraderStrategyPackage` is the provisional downstream handoff until the final
Risk schema is available.

## Identity

- `package_id`: unique package identifier.
- `candidate_id`: identifier of the generated rule, if the run reached that
  stage.
- `trader_type`: always `technical` for this agent.
- `lineage`: workflow, task, parent, and source identifiers.
- `mandate_reference`: stable PM mandate identifiers and as-of date.

## Research evidence

- `hypothesis`: LLM-authored testable hypothesis.
- `data_request`: point-in-time field and coverage request.
- `data_usage`: artifact, reference, provenance, limitation, and unavailable
  field summary.
- `technical_analysis`: code-computed support/resistance and pattern evidence.

Raw OHLCV payloads are not copied into this summary.

## Executable candidate

- `candidate_rule`: exact codeable logic, parameters, required fields, mandate
  handling, technical evidence IDs, and an explicit rule-use explanation for
  every cited ID.
- `backtest_request`: candidate, plan, data references, and mandate constraints
  sent to the engine.

No rule becomes Risk-eligible without citing a computed support/resistance
level.

## Evaluation

- `backtest_result`: immutable deterministic-engine status, metrics, warnings,
  violations, and artifact references.
- `interpretation`: LLM explanation restricted to metrics actually returned by
  the engine.
- `constraint_assessment`: declared mappings and violations requiring Risk
  validation.

## Status and resilience

- `status`: `completed`, `partial`, or `failed`.
- `failures`: stage, sanitized diagnostic message, and retryability.
- `eligible_for_risk_review`: true only for a complete, technically analyzed,
  successfully backtested, interpreted package.

Diagnostics are operational content. They are retained for orchestration and
must not be treated as trading instructions.
