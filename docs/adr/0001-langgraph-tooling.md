# ADR 0001: LangGraph Tooling Boundary

- Status: Accepted for Arturo-owned tooling
- Date: 2026-07-27
- Scope: Framework confirmation and Technical Trader compatibility only

## Context

The revised architecture uses three independent traders and a later
team-integrated workflow. Arturo owns confirmation of the agent framework and
tooling plus the Technical Trader implementation. Emma owns the State Graph
and workflow update, while Shaurya owns A2A scaffolding and the complete
end-to-end loop.

A framework decision is needed now, but implementing the production graph here
would conflict with those assignments and prematurely freeze teammate-owned
contracts.

## Decision

Use the LangGraph Python Graph API from the `1.2` major-compatible line:

```text
langgraph>=1.2,<2
```

The Technical Trader package exposes:

1. a framework-neutral async node through `make_langgraph_node`; and
2. an optional LangGraph adapter that compiles only a single Technical Trader
   node.

LangGraph remains an optional package extra so the Technical Trader runtime,
models, tools, and service Protocols stay replaceable and do not depend on the
orchestrator.

The optional adapter:

- uses a `TypedDict` state;
- returns state updates without mutating input state;
- supports async execution;
- serializes the Technical Trader package to JSON-compatible data;
- accepts an externally supplied checkpointer; and
- defines no production routing beyond `START → Technical Trader → END`.

## Ownership boundaries

This decision does not implement or finalize:

- the team production `StateGraph`;
- PM intake or human-decision interrupts;
- parallel Technical/Fundamental/Quant fan-out;
- parallel state reducers or fan-in behavior;
- A2A message lifecycle;
- Risk, Reporting, or Memory nodes;
- checkpointer or store technology;
- thread-ID policy;
- retry, global timeout, or cancellation policy;
- dashboard streaming; or
- final shared state and serialization contracts.

Those remain with their assigned owners. The Technical Trader adapter is
intended to be embedded as a node or subgraph after they publish those
contracts.

## Integration requirements for the production owners

- Parallel writers must use branch-isolated keys or explicit associative
  reducers.
- Human interrupts require a checkpointer and stable `thread_id`.
- Production state must be checkpoint-serializable.
- Node callables should remain async because the traders call model and service
  dependencies.
- Durable persistence, retention, and replay policies must be selected by the
  relevant workflow and Memory owners.
- The production graph should inject agent and service dependencies rather than
  import provider-specific clients into graph topology.

## Consequences

The framework and version boundary are confirmed without taking ownership of
the production workflow. Arturo can validate Technical Trader compatibility
now, while Emma and Shaurya remain free to define the final state, reducers,
A2A lifecycle, and full-loop topology.

## Official references

- https://docs.langchain.com/oss/python/langgraph/install
- https://docs.langchain.com/oss/python/langgraph/use-graph-api
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://docs.langchain.com/oss/python/langgraph/persistence
