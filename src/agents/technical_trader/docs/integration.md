# Provisional Integration Guide

The Technical Trader cannot run end to end until three adapters are supplied.
This is intentional; no fake production dependency is included.

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

## 3. Backtest Engine adapter

Implement:

```python
class BacktestEngine(Protocol):
    async def run(self, request: BacktestRequest) -> BacktestResult: ...
```

The request contains:

- exact codeable rule fields;
- computed technical evidence IDs;
- parameters;
- start/end/frequency preferences;
- transaction-cost assumptions;
- requested metrics and held-out requirements;
- data references; and
- PM mandate constraints.

The engine must return
`computed_by="deterministic_backtest_engine"`. The Technical Trader rejects
other values and rejects metric interpretations that cite metrics absent from
the engine result.

Backtest Engine integration details to confirm:

- executable rule representation;
- supported indicator and level semantics;
- parameter schema;
- metric names;
- held-out/walk-forward facilities;
- transaction-cost configuration;
- artifact references; and
- failure/status conventions.

## 4. Risk handoff

Until Risk publishes its schema, consume `TraderStrategyPackage` directly.
Only packages with `eligible_for_risk_review=true` are complete and backtested.
Risk should still independently review look-ahead bias, overfitting, weak
out-of-sample behavior, technical-pattern selection, mandate alignment, and
execution assumptions.

## 5. LangGraph integration

`make_langgraph_node` defaults to:

- input: `pm_mandate`
- output: `technical_trader_package`

Both keys are configurable. The node returns a state update dictionary and
does not mutate the input mapping.

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

## No runnable demonstration yet

A real demonstration would incorrectly imply final adapter behavior. Add one
only after the Model, Data, and Backtest contracts are confirmed.
