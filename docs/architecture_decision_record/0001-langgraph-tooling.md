# Architecture Decision Record 0001: LangGraph Tooling Boundary

- Status: Accepted
- Date: 2026-07-27
- Scope: Project framework tooling and Technical Trader compatibility

## Context

The current architecture uses three independent traders in parallel, followed
by collective Risk review, Reporting, a human Portfolio Manager decision, and
round-to-round Memory. Data and backtesting are injected shared tools, not
hireable agent nodes.

The framework must expose this workflow explicitly while keeping agent logic,
cross-agent contracts, persistence, telemetry, and provider choices
replaceable.

## Decision

Use the LangGraph Python Graph API from the `1.2` major-compatible line:

```text
langgraph>=1.2,<2
```

The project graph implementation:

- uses typed shared state and explicit branch-isolated reducers;
- fans out Technical, Fundamental, and Quant Traders in parallel;
- waits for all active trader branches to settle before collective Risk
  review;
- converts ordinary trader failures into settled packages so one branch does
  not erase successful sibling work;
- routes Risk or Reporting infrastructure failures to human review;
- pauses for the Portfolio Manager through a durable LangGraph interrupt;
- writes Memory before termination or another bounded research round;
- accepts an externally supplied checkpointer; and
- injects every agent/service node instead of importing provider-specific
  implementations into the topology.

The Technical Trader also retains a one-node compatibility graph so it can run
independently during integration.

## Integration boundaries

LangGraph owns workflow execution, fan-out/fan-in, routing, loops, interrupts,
and checkpoint integration. It does not own:

- model-provider selection or agent prompts;
- the Data Service or deterministic Backtest Engine;
- centralized A2A envelopes or the Agent Card registry;
- Risk judgment, Reporting content, or Memory storage;
- the dashboard event adapter or historical productivity analytics;
- the production persistence backend and retention policy; or
- team policy decisions such as the canonical benchmark and validation-touch
  limits.

Those components remain behind versioned, framework-neutral interfaces.

## Runtime requirements

- Production compilation requires an injected checkpointer.
- Each invocation must use a stable LangGraph `thread_id`.
- Nodes return partial state updates and must not mutate input state.
- Checkpointed values must remain JSON-serializable or use an agreed serializer.
- Large datasets, engine ledgers, and reports remain external artifacts; state
  stores references and validated summaries.
- Node adapters must propagate cancellation and use idempotency keys before
  automatic retries are enabled.

## Acceptance status

The executable topology and human-interrupt boundary are implemented. Full
framework acceptance still requires integrated teammate nodes, a selected
persistent checkpointer, bounded retry/idempotency policy, centralized domain
event translation, automated integration tests, and a documented clone/run
procedure.

## Consequences

The graph can be assembled before all teammate implementations exist because
its dependencies are injected. Missing agents are not simulated in production;
their real graph-compatible adapters are required for an end-to-end run.

The orchestration can be replaced later because agent, service, and domain
contracts do not import LangGraph.

## Official references

- https://docs.langchain.com/oss/python/langgraph/graph-api
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://reference.langchain.com/python/langgraph/graph/state/StateGraph/compile
