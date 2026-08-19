"""Optional LangGraph boundary for the standalone Fundamental Trader.

Mirrors ``technical_trader.langgraph_adapter`` exactly. This module
intentionally builds only a one-node Fundamental Trader graph. The
team-owned production topology, parallel trader reducers, A2A lifecycle,
checkpointer implementation, and downstream routing remain outside this
package.

Install the ``langgraph`` project extra before importing this module.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Required, TypedDict

from langgraph.graph import END, START, StateGraph

from .runtime import FundamentalTraderRuntime, make_langgraph_node


FUNDAMENTAL_TRADER_NODE = "fundamental_trader"
LANGGRAPH_VERSION_SPEC = ">=1.2,<2"


class FundamentalTraderGraphState(TypedDict, total=False):
    """Checkpoint-safe state owned only by the compatibility subgraph."""

    pm_mandate: Required[dict[str, Any]]
    run_id: str
    round_number: int
    trader_attempt: int
    canonical_universe_id: str | None
    evaluation_policy_id: str | None
    fundamental_trader_package: dict[str, Any]


FundamentalTraderGraphNode = Callable[
    [Mapping[str, Any]],
    Awaitable[dict[str, Any]],
]


def compile_fundamental_trader_node(
    node: FundamentalTraderGraphNode,
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Compile one injected Fundamental Trader node.

    ``checkpointer`` is accepted but never selected or configured here. The
    production workflow or persistence owner must provide it.
    """

    builder: Any = StateGraph(state_schema=FundamentalTraderGraphState)
    builder.add_node(FUNDAMENTAL_TRADER_NODE, node)
    builder.add_edge(START, FUNDAMENTAL_TRADER_NODE)
    builder.add_edge(FUNDAMENTAL_TRADER_NODE, END)
    return builder.compile(checkpointer=checkpointer)


def compile_fundamental_trader_graph(
    runtime: FundamentalTraderRuntime,
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Compile the real Fundamental Trader runtime as an isolated subgraph."""

    return compile_fundamental_trader_node(
        make_langgraph_node(runtime),
        checkpointer=checkpointer,
    )


__all__ = [
    "FUNDAMENTAL_TRADER_NODE",
    "LANGGRAPH_VERSION_SPEC",
    "FundamentalTraderGraphNode",
    "FundamentalTraderGraphState",
    "compile_fundamental_trader_graph",
    "compile_fundamental_trader_node",
]
