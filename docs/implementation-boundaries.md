# Placeholder Implementation Boundaries

This scaffold is designed to receive teammate implementations without forcing
premature coupling.

## Trader implementations

Each trader implementation must structurally satisfy `agents.base.TraderAgent`:

```python
async def run(
    mandate: PMMandate,
    lineage: TaskLineage,
) -> TraderStrategyPackage:
    ...
```

The final adapter may accept a richer task object, but workflow/task lineage
must remain code-owned and observable.

## Technical Trader

The future integration should use the separately developed package rather than
copying its source. Before integration, confirm:

- packaging and version strategy;
- final PM mandate mapping;
- Data Service adapter;
- Backtest Engine adapter;
- Risk output mapping;
- graph state keys; and
- model/cost telemetry mapping.

## DataService

`services.DataService` is provisional. Confirm provider, timestamp convention,
adjustments, trading calendar, missing data, ETF fields, payload transport,
artifact references, and point-in-time provenance before implementation.

Do not introduce a Data Agent merely to wrap this interface.

## BacktestEngine

`tools.BacktestEngine` is provisional. Confirm executable rule representation,
supported signals, assumptions, transaction costs, benchmark handling,
held-out/walk-forward support, metrics, and artifact formats.

Do not add an LLM Backtest Agent. LLMs may generate or interpret structured
rules, but only code returns performance results.

## Risk and Reporting

Risk must receive all settled trader outcomes in one `RiskReviewRequest`.
Reporting must consume only Risk-approved candidates. Neither component may
silently combine strategies.

## MemoryStore

Memory is external persistence. Confirm database/backend, record versioning,
retention, privacy, and retrieval semantics before implementation. Only
controlled lessons should re-enter the next round.

## Agent registry

Agent Cards distinguish:

- `hireable`: a PM staffing property; and
- `implementation_status`: technical readiness.

A specialist can be hireable in the planned roster while its adapters remain
pending. Bench/fire actions belong to graph/registry state, not prompt changes.

## Observability

Every future model and task adapter should preserve:

- workflow ID;
- task and parent task IDs;
- stable agent ID;
- stage/operation;
- attempt;
- model-call ID;
- tokens;
- reported cost and currency;
- latency;
- status and error type.

This is necessary for per-agent productivity and staffing decisions.
