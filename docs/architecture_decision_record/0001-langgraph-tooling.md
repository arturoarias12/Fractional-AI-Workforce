# Architecture Decision Record 0001: LangGraph Tooling Boundary

- Status: Accepted
- Date: 2026-07-27
- Scope: Project framework tooling and Technical Trader compatibility

## Context

The revised architecture uses three independent traders and a later
integrated workflow. Framework compatibility can be evaluated independently,
while the production State Graph, A2A scaffolding, and end-to-end loop remain
separate project workstreams.

A framework decision is needed now, but implementing the production graph here
would prematurely freeze shared contracts that are still evolving.

## Proposed decision

Use the LangGraph Python Graph API from the `1.2` major-compatible line:

```text
langgraph>=1.2,<2
```

The Technical Trader subpackage exposes:

1. a framework-neutral async node through `make_langgraph_node`; and
2. an optional LangGraph adapter that compiles only a single Technical Trader
   node.

LangGraph remains an optional project dependency so the Technical Trader
runtime, models, tools, and service Protocols stay replaceable and do not
depend on the orchestrator.

The optional adapter:

- uses a `TypedDict` state;
- returns state updates without mutating input state;
- supports async execution;
- serializes the Technical Trader package to JSON-compatible data;
- accepts an externally supplied checkpointer; and
- defines no production routing beyond `START → Technical Trader → END`.

## Integration boundaries

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

Those remain project-level integration decisions. The Technical Trader adapter
is intended to be embedded as a node or subgraph after the relevant contracts
are confirmed.

## Integration requirements

- Parallel writers must use branch-isolated keys or explicit associative
  reducers.
- Human interrupts require a checkpointer and stable `thread_id`.
- Production state must be checkpoint-serializable.
- Node callables should remain async because the traders call model and service
  dependencies.
- Durable persistence, retention, and replay policies must be selected by the
  project.
- The production graph should inject agent and service dependencies rather than
  import provider-specific clients into graph topology.

## Consequences

The proposed framework and version boundary allow Technical Trader
compatibility to be validated without defining the final project state,
reducers, A2A lifecycle, or full-loop topology.

## Official references

- https://docs.langchain.com/oss/python/langgraph/install
- https://docs.langchain.com/oss/python/langgraph/use-graph-api
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://docs.langchain.com/oss/python/langgraph/persistence
