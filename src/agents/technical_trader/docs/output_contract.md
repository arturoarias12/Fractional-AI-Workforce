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

The model-selectable package-level executor is
`technical.multi_asset_portfolio.v1`. Its parameters contain:

- `target_asset_count=10` and the actual `selected_asset_count`;
- the portfolio gross target and equal-weight allocation method;
- common sleeve risk parameters;
- an omission rationale when fewer than 10 ETFs qualify; and
- one to 10 unique sleeves, each containing a symbol, deterministic child
  executor, evidence IDs, positive-expectation rationale, and family-specific
  parameters. Evidence-derived numeric values are bound by code from the cited
  IDs rather than transcribed by the model.
- code-bound opportunity ID, rank, and score for every sleeve, proving that the
  selection matched the mandate-specific frozen-evidence screen.

Every sleeve is independently evidence-validated before the one portfolio
backtest begins. The top-level evidence IDs must equal the union of all sleeve
IDs, and evidence cannot be reused across symbols.

After a second LLM Technical review, the portfolio is backtested. Code retains
it only when its out-of-sample `total_return` strictly exceeds the requested
benchmark return. Otherwise, the final candidate uses the code-owned
`technical.benchmark_buy_and_hold_fallback.v1` executor and the benchmark is
backtested again under the same plan, costs, delayed-fill, and liquidation
assumptions. The model cannot select or author this fallback.

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
- `additional_fields.technical_horizon`: resolved holding limit, permitted
  lookbacks, actionability distance, evidence warm-up policy, and whether the
  horizon came from the PM mandate or the conservative audited fallback.
- `additional_fields.evaluation_semantics`: explicitly distinguishes the PM
  holding horizon from the longer repeated-occurrence evaluation window.
- `additional_fields.candidate_review`: records whether the second Technical
  review was applied and the before/after selected symbols.
- `additional_fields.benchmark_selection`: records the exact Technical and
  benchmark values, decision, and final fallback identity.
- `additional_fields.technical_candidate_before_benchmark_fallback`: when the
  fallback is used, preserves the rejected Technical candidate, request,
  result, and ledger for audit.

The default benchmark gate is an injectable Technical policy. It deliberately
uses the same held-out window as a prototype model-selection gate, so the
package marks independent post-selection validation as still required. It must
not be described as an untouched second out-of-sample test.

The current policy also requires the requested Backtest Plan window to exactly
equal the validation split. This prevents comparing held-out Technical metrics
with benchmark metrics calculated over a different period. When fallback is
used, `additional_fields.benchmark_selection.tracking_disclosure` records that
the shared benchmark reference enters on its first resolved bar while the
executable fallback obeys the plan's signal delay. It records both returns and
their difference rather than presenting ordinary execution lag as unexplained
underperformance.

## Status and resilience

- `status`: settled `completed`, `partial`, or `failed`.
- `failures`: stage, sanitized diagnostic message, and retryability.
- `eligible_for_risk_review`: true only for a complete, technically analyzed,
  successfully backtested, interpreted package.

Diagnostics are operational content. They are retained for orchestration and
must not be treated as trading instructions.

The result remains one ordinary shared package. Risk, Reporting, PM, Memory,
and productivity tooling do not need a Technical-specific batch schema.
