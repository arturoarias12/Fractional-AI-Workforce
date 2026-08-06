# Integration Guide

The Technical Trader cannot run end to end until its real adapters, registered
executor set, and shared validation policy are supplied.

Cross-component contracts are defined once in `src/protocols`. Agent-local
models contain only technical-analysis evidence.

## 1. Model adapter

Implement `ModelClient.generate_structured(...)`.

It receives:

- system and user prompts;
- the required Pydantic response model; and
- `ModelRequestContext` containing agent, operation, workflow, task, call, and
  attempt identifiers.

It must return `ModelCallResult`, containing structured output and `ModelUsage`.
If usage is unavailable, return `ModelUsage.unavailable(...)`.

Model integration details to confirm:

- provider and model;
- structured-output mechanism;
- retry boundaries;
- token and cost field availability; and
- provider request identifiers.

## 2. Data Service adapter

Implement:

```python
class DataService(Protocol):
    async def fetch(self, request: DataRequest) -> DataResponse: ...
```

The Technical Trader requires point-in-time:

- timezone-aware timestamps;
- high;
- low;
- close;
- preferably open and volume;
- frequency and adjustment metadata;
- asset identity;
- coverage dates;
- immutable data references; and
- provenance with `point_in_time_verified`.

The provisional default `ArtifactPayloadTechnicalInputAdapter` accepts a
`price_volume` artifact whose `analysis_payload` is either:

- one `PriceSeries`;
- a mapping containing `symbol`, `frequency`, and `bars`; or
- `{"series": [<one or more series>]}`.

When the teammate contract is known, implement a new
`TechnicalAnalysisInputAdapter`. The agent-local support/resistance and pattern
tools will remain unchanged.

Data Service integration details to confirm:

- returned transport and payload types;
- adjusted versus unadjusted bars;
- trading-calendar treatment;
- timestamp convention;
- missing-bar and delisting behavior;
- artifact-reference resolution;
- maximum payload size; and
- provenance semantics.

The agent deterministically resolves the PM's investment horizon after the
training-only report is built. It supports horizon-compatible moving-average
pairs from 3/10 through 50/200, requires at least 252 training observations for
the opportunity screen, and records unavailable assets instead of fabricating
short histories. This is an agent-local interpretation of the PM mandate; it
does not change the shared Data Service contract.

## 3. Backtest Engine adapter

Implement:

```python
class BacktestEngine(Protocol):
    async def run(self, request: BacktestRequest) -> BacktestResult: ...
```

The request contains:

- code-owned workflow-run, round, attempt, universe, and evaluation-policy
  context;
- an exact `candidate.executor_id` from the engine registry;
- exact codeable rule fields documenting what that executor must implement;
- computed specialty evidence IDs;
- parameters;
- start/end/frequency preferences;
- transaction-cost assumptions;
- requested metrics and a code-owned validation split;
- data references; and
- PM mandate constraints.

The selected rule carries a mandate-derived maximum holding period and cites
only opportunities that passed the Technical horizon screen. The historical
validation window may be much longer: it measures repeated occurrences of the
same horizon-length decision and must not be interpreted as the strategy's
holding horizon. No new Backtest Engine request field is required.

The engine must return
`computed_by="deterministic_backtest_engine"`. The Technical Trader rejects
other values and rejects metric interpretations that cite metrics absent from
the engine result. The shared engine also attaches one `BacktestRunLedgerEntry`
to every successful or failed result. A storage adapter may persist that entry
through `BacktestRunLedgerSink`; persistence references are returned separately
and persistence failure does not erase the in-result audit record.
Every engine execution receives an attempt-unique identity derived from its
workflow-run ID, request ID, and lineage attempt. The workflow-run identity also
remains a separate ledger field for grouping all Backtest Engine attempts in
one research run.

Construct the runtime with the engine's actual executor IDs:

```python
runtime = create_technical_trader_runtime(
    model_client=model_client,
    data_service=data_service,
    backtest_engine=engine,
    available_executors=engine.registered_executor_ids,
    validation_split_policy=shared_validation_policy,
)
```

For the complete current Technical path, register both the model-selectable
`technical.multi_asset_portfolio.v1` executor and the code-owned
`technical.benchmark_buy_and_hold_fallback.v1` executor. The latter is hidden
from proposal prompts. If the reviewed Technical candidate does not strictly
beat the requested benchmark's out-of-sample `total_return`, the agent builds
that fallback itself and asks the engine to evaluate it under the same plan.
An engine that has not yet registered the additive fallback executor receives
no changed protocol or method call, but that underperforming run settles as
partial instead of silently returning a weaker strategy.

The gate currently requires the requested plan window and validation split to
coincide because the shared engine reports benchmark metrics for the complete
requested window. A mismatch settles the Technical run as partial instead of
performing an invalid cross-period comparison. The shared engine's benchmark
reference enters at its first bar, while the executable fallback observes the
plan's ordinary signal delay. The agent records the resulting tracking
difference explicitly; it does not alter shared execution or benchmark
semantics.

An unknown executor is rejected before the engine runs. If no registered
executor exactly implements the proposed logic, the run settles as partial;
the system must not backtest a merely similar strategy.

`validation_split_policy` is intentionally injected. The Technical Trader does
not define the team's train/test ratio or dates, allowing all three traders to
use the same evaluation policy.

Backtest Engine integration details still to confirm:

- registered executor descriptions and parameter schemas;
- supported indicator and level semantics;
- metric names;
- shared held-out/walk-forward policy;
- transaction-cost configuration;
- artifact references; and
- durable run-ledger storage and round-audit aggregation; and
- failure/status conventions.

## 4. Risk handoff

Until Risk publishes its schema, consume `TraderStrategyPackage` directly.
Only packages with `eligible_for_risk_review=true` are complete and backtested.
Risk should still independently review look-ahead bias, overfitting, weak
out-of-sample behavior, technical-pattern selection, mandate alignment, and
execution assumptions.

The public runtime produces one shared package containing either the winning
multi-ETF Technical rule or its benchmark fallback:

```python
package = await runtime.research(
    mandate,
    execution_context=execution_context,
)
```

Route that ordinary `TraderStrategyPackage` through the existing Risk handoff.
The Technical candidate's deterministic executor owns its internal
equal-weight ETF sleeves. If the benchmark fallback becomes final, Risk can
inspect the rejected Technical candidate and its original backtest under
`additional_fields.technical_candidate_before_benchmark_fallback`. In both
cases Risk receives one ordinary package, not multiple artifacts.

## 5. LangGraph integration

`make_langgraph_node` implements the required Technical Trader boundary:

- input: `pm_mandate`
- output: `technical_trader_package`

Both keys are configurable. The node returns a state update dictionary and
does not mutate the input mapping.

The output is the same singular shared contract expected from the Fundamental
and Quant trader branches. No production-graph batch adapter is required.

The project's optional `langgraph` dependency installs `langgraph>=1.2,<2`.
`agents.technical_trader.langgraph_adapter` can compile the real runtime as a
single-node compatibility graph:

```python
from agents.technical_trader.langgraph_adapter import (
    compile_technical_trader_graph,
)

graph = compile_technical_trader_graph(
    runtime,
    checkpointer=project_checkpointer,
)
```

The checkpointer is injected and never selected by this agent. The adapter
defines only `START → Technical Trader → END`; it does not implement the
production topology, parallel branch reducers, PM interrupts, A2A messaging,
Risk routing, Memory, or dashboard streaming.

Graph integration details to confirm:

- final state object;
- serialization convention;
- specialist registry/hiring state;
- retry and checkpoint boundaries;
- graph-level cancellation; and
- Risk routing key.
