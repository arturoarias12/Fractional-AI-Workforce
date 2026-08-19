# Integration Guide

The Technical Trader cannot run end to end until its real adapters, registered
executor set, and shared validation policy are supplied.

Cross-component contracts are defined once in `src/protocols`. Agent-local
models contain only technical-analysis evidence.

## 1. Model adapter

The repository includes interchangeable OpenAI and Anthropic implementations
of `ModelClient.generate_structured(...)` under
`agents.technical_trader.adapters`. Both receive:

- system and user prompts;
- the required Pydantic response model; and
- `ModelRequestContext` containing agent, operation, workflow, task, call, and
  attempt identifiers.

It must return `ModelCallResult`, containing structured output and `ModelUsage`.
If usage is unavailable, return `ModelUsage.unavailable(...)`.

Both adapters validate provider JSON against the requested Pydantic model and
return normalized input/output token usage, the provider request ID, model
identity, and provider metadata. Provider APIs do not report a monetary charge
per response, so `reported_cost` remains unset; the shared metrics layer may
calculate cost from its centrally maintained price table.

Install the optional provider SDKs without affecting the base installation:

```bash
pip install -e ".[technical-models]"
```

Provider selection is explicit and occurs only at the composition root. No API
key is read when the package is imported.

```bash
# OpenAI
export TECHNICAL_TRADER_MODEL_PROVIDER=openai
export TECHNICAL_TRADER_MODEL=<supported-openai-model>
export OPENAI_API_KEY=<secret>

# Anthropic
export TECHNICAL_TRADER_MODEL_PROVIDER=anthropic
export TECHNICAL_TRADER_MODEL=<supported-claude-model>
export ANTHROPIC_API_KEY=<secret>
```

On PowerShell, use `$env:VARIABLE_NAME="value"` for the current terminal
session. Secrets must remain in the deployment environment or secret manager;
they must not be stored in source files, examples, logs, or committed `.env`
files.

Create the selected adapter and inject it into the unchanged runtime factory:

```python
from agents.technical_trader import (
    ExecutionPolicy,
    create_technical_model_client_from_env,
    create_technical_trader_runtime,
)

execution_policy = ExecutionPolicy()
model_client = create_technical_model_client_from_env(
    execution_policy=execution_policy,
)
runtime = create_technical_trader_runtime(
    model_client=model_client,
    data_service=data_service,
    backtest_engine=engine,
    available_executors=engine.registered_executor_ids,
    validation_split_policy=shared_validation_policy,
    benchmark_symbol="IVV",  # or the PM-approved shared benchmark
    execution_policy=execution_policy,
)
```

`benchmark_symbol` is optional at the Python boundary for backward
compatibility, but production composition should inject the PM-approved shared
benchmark. If it is omitted, the model must declare a permitted benchmark and
the run fails closed if it does not. Code always replaces model-authored dates
with the exact horizon-matched dates returned by the shared validation policy.

Deterministic analysis continues to cover the full PM universe. By default,
the candidate and review prompts receive the 20 highest-ranked unique ETFs and
all horizon-eligible evidence for those symbols. The full report remains in the
final package. `candidate_prompt_max_assets` can be set from 10 through 120 at
runtime without changing either provider adapter. Code rejects a model proposal
that cites a symbol, evidence ID, or opportunity combination outside the exact
shortlist submitted to that call.

Common optional settings are:

- `TECHNICAL_TRADER_MAX_OUTPUT_TOKENS` (default `12000`);
- `TECHNICAL_TRADER_PROVIDER_TIMEOUT_SECONDS` (default `18`); and
- `TECHNICAL_TRADER_PROVIDER_MAX_RETRIES` (default `1`, maximum `3`).

OpenAI additionally accepts
`TECHNICAL_TRADER_OPENAI_REASONING_EFFORT` and
`TECHNICAL_TRADER_OPENAI_OUTPUT_MODE=json_schema|json_object`. Native JSON
Schema is the default; `json_object` retains local Pydantic validation for a
model/schema combination that cannot use native schema output.

Anthropic uses native structured outputs by default. The selected Claude model
must support that feature. Set
`TECHNICAL_TRADER_ANTHROPIC_NATIVE_STRUCTURED_OUTPUTS=false` only when testing a
model without native support; the adapter will request one JSON object through
the prompt and still validate it locally.

The provider factory requires the runtime's `ExecutionPolicy` and rejects
configurations where all provider attempts plus five seconds of retry headroom
would reach its model-call deadline. The runtime independently checks a
deadline-aware provider client against its own policy, so accidentally passing
different policies also fails during construction instead of cancelling a
retry during a paid call.

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
only opportunities that passed the Technical horizon screen. The primary
validation window must contain the mandate horizon's number of trading
sessions: for example, a 504-trading-day mandate requires a 504-session primary
holdout. Individual positions may enter, exit, and re-enter inside that window.
The injected shared policy owns exact exchange-session resolution; the
Technical Trader rejects a date span that is plainly incompatible with the PM
horizon. No new Backtest Engine request field is required.

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
    benchmark_symbol=pm_approved_benchmark,
)
```

For the complete current Technical path, register both the model-selectable
`technical.multi_asset_portfolio.v1` executor and the code-owned
`technical.benchmark_buy_and_hold_fallback.v1` executor. The latter is hidden
from proposal prompts. If the reviewed Technical candidate does not strictly
beat an executable benchmark's out-of-sample `total_return`, that benchmark
becomes the fallback. The agent builds and evaluates the baseline under the
same plan before applying the gate.
An engine that has not yet registered the additive fallback executor receives
no changed protocol or method call, but the Technical run settles as partial
because a like-for-like comparison cannot be completed.

The gate requires the requested plan window and validation split to coincide.
It always runs the executable benchmark before selection and compares the two
out-of-sample results. The Technical and benchmark requests must have identical
dates, transaction costs, signal delay, fill-price rule, constraints, data
references, and execution context. The shared engine's convenience benchmark
reference remains available for audit but is not used by the gate because its
entry timing may differ. A mismatch settles the Technical run as partial
instead of performing a cross-period or unequal-assumption comparison.

An unknown executor is rejected before the engine runs. If no registered
executor exactly implements the proposed logic, the run settles as partial;
the system must not backtest a merely similar strategy.

`validation_split_policy` is intentionally injected. The Technical Trader does
not choose calendar dates, allowing all three traders to use the same policy.
It is a required construction dependency, so missing wiring fails before data
or model calls. The policy receives a code-owned provisional daily plan with
the mandate as-of date, injected benchmark when available, required benchmark
metric, and held-out/horizon validation requirements. That shared policy must
resolve exactly the mandate horizon's number of market sessions. The agent
performs a calendar-span boundary check; the policy and Data Service remain
responsible for exact exchange-calendar counting.

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
