# Risk / Skeptic Agent

Implementation of the collective review defined by the team's 3-way
cherry-picking checklist (CP-1 … CP-13). Source: `src/agents/risk_agent/`
(`risk_agent.py` is the Protocol, `risk_agent_impl.py` the implementation).
Tests: `tests/risk_agent/test_risk_agent_impl.py` (unit) and
`tests/risk_agent/test_risk_agent_graph_integration.py` (real compiled graph).

## What it does

The three traders are competing lenses on the same validation window, and the
PM can request more rounds. That creates three places selection bias can hide,
and the Risk agent is the only node that sees all of them:

- **within one trader** — hidden trials, undisclosed sweeps, trimmed universes;
- **across the three traders** — "best of 3" framed as one hypothesis;
- **across rounds** — unbounded re-touching of the same data.

Risk receives one `RiskReviewRequest` containing the settled batch and returns
one `RiskReviewResponse` with a per-candidate verdict plus round-level results.

## Two stages, in this order

1. **Deterministic gate.** Every mechanically checkable item is computed from
   engine-produced evidence — the `BacktestRunLedgerEntry` embedded in each
   result, request counts, and package identity fields. No model call.
2. **Model judgment.** An optional `ModelClient` reviews what code cannot
   judge, grounded in the deterministic results. It may **escalate** severity
   (`PASS → FLAG → VETO`) with justification; escalations at equal or lower
   severity are discarded. It can never downgrade a deterministic verdict, and
   a model failure degrades to deterministic-only review rather than aborting.

Evidence that cannot be reached returns `FLAG` with
`requires_human_review=True` — never a manufactured `PASS`.

## Check-by-check status

| Check | Scope | Basis | Runs today? |
| --- | --- | --- | --- |
| CP-1 report-everything-tried | candidate | ledger run count vs. declared count | needs `RoundAuditReader` |
| CP-2 best-of-N disclosure | candidate | undeclared sweep → veto; declared sweep over threshold → flag | needs `RoundAuditReader` |
| CP-3 full-period metrics | candidate | backtest succeeded, split applied, out-of-sample metrics present | yes |
| CP-4 no post-hoc universe trimming | candidate | `resolved_symbols` first run vs. last run | needs `RoundAuditReader` |
| CP-5 full canonical metric set | candidate | every required metric present and non-null | yes |
| CP-6 same-terms baseline | candidate | benchmark configured and benchmark metrics computed | yes |
| CP-7 multiple-comparison disclosure | round | candidate count and declared hypothesis count; always a flag | yes |
| CP-8 lens duplication | round | identical executor + identical parameters (proxy); model escalates on semantics | yes (proxy) |
| CP-9 no borrowed evidence | candidate | result/request/trader identity, cited foreign run IDs | yes |
| CP-10 nothing is deleted | round | every prior round present in history | needs `RoundHistoryReader` |
| CP-11 validation-touch budget | candidate | past round budget, approval requires stability evidence | yes |
| CP-12 no cosmetic resurrection | candidate | match against prior vetoed strategies without declared lineage | needs `RoundHistoryReader` |
| CP-13 test-set lock | candidate | resolved data end and split end vs. the mandate as-of date | yes |

## What other workstreams must supply

**Backtest/ledger owner — two small readers.** `WorkflowState` already carries
`round_audit_summary_reference` and `round_history_reference`, but nothing
dereferences them. Risk needs injected adapters satisfying:

```python
class RoundAuditReader(Protocol):
    async def ledger_entries(self, *, reference: str) -> Sequence[BacktestRunLedgerEntry]: ...

class RoundHistoryReader(Protocol):
    async def prior_round_summaries(self, *, reference: str) -> Sequence[Mapping[str, Any]]: ...
```

Without them, five checks degrade to human review. This is the single highest
-value dependency for the Risk agent.

**Trader owners — three optional disclosure fields** in
`TraderStrategyPackage.additional_fields`:

| Key | Meaning | Feeds |
| --- | --- | --- |
| `declared_backtest_run_count` | how many variants were run before choosing this candidate | CP-1, CP-2, CP-7 |
| `stability_evidence` | parameter-perturbation results | CP-11 |
| `parent_strategy_id` | lineage when resubmitting after a veto | CP-12 |

Omitting `declared_backtest_run_count` means "one hypothesis" — so a trader
that sweeps and stays silent is vetoed once the ledger is readable. That is
the intended incentive.

**Reporting owner.** `RiskReviewResponse.required_reporting_flags()` returns
every flag the memo must carry verbatim, including the CP-7 disclosure of how
many hypotheses competed. Dropping a flag is itself cherry-picking the
critique.

## Wiring

```python
from agents import RiskAgentImpl, make_risk_review_node
from graph.production import ProductionNodeSet, compile_production_workflow

risk_agent = RiskAgentImpl(
    model_client=my_model_client,      # optional; omit for deterministic-only
    metrics_sink=my_metrics_sink,      # optional; feeds productivity metrics
    audit_reader=my_audit_reader,      # unlocks CP-1, CP-2, CP-4
    history_reader=my_history_reader,  # unlocks CP-10, CP-12
)
nodes = ProductionNodeSet(..., risk_review=make_risk_review_node(risk_agent))
```

## Policy thresholds still open with the team

`RiskPolicy` holds every value the checklist left open, so a meeting ruling is
a one-line change:

| Field | Default | Question for the team |
| --- | --- | --- |
| `round_budget` | 3 | how many rounds before stability evidence is required |
| `sweep_flag_threshold` | 20 | disclosed variant count that earns a flag |
| `duplication_overlap_threshold` | 0.7 | trade-overlap cutoff (not yet used — the current CP-8 test is exact rule equality) |
| `required_metrics` | return, annualized return, max drawdown, volatility, Sharpe | the canonical Rubric A metric set |

## Firing the Risk agent

Benching Risk (leaving `risk_agent` out of `active_specialists`) does not
silently approve anything: the graph records a `risk_failure` requiring PM
action, Reporting never runs, and no candidate becomes selectable. The
"fire Risk → suspiciously good result → rehire → specific veto" demo works
through the real topology; see
`test_benched_risk_agent_blocks_reporting_and_escalates_to_pm`.
