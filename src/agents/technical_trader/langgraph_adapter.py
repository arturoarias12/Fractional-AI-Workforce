"""Optional LangGraph boundary for the standalone Technical Trader.

This module intentionally builds only a one-node Technical Trader graph. The
team-owned production topology, parallel trader reducers, A2A lifecycle,
checkpointer implementation, and downstream routing remain outside this
package.

Install the ``langgraph`` project extra before importing this module.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Required, TypedDict

from langgraph.graph import END, START, StateGraph

from .runtime import TechnicalTraderRuntime, make_langgraph_node


TECHNICAL_TRADER_NODE = "technical_trader"
LANGGRAPH_VERSION_SPEC = ">=1.2,<2"


class TechnicalTraderGraphState(TypedDict, total=False):
    """Checkpoint-safe state owned only by the compatibility subgraph."""

    pm_mandate: Required[dict[str, Any]]
    run_id: str
    round_number: int
    trader_attempt: int
    canonical_universe_id: str | None
    evaluation_policy_id: str | None
    technical_trader_package: dict[str, Any]


TechnicalTraderGraphNode = Callable[
    [Mapping[str, Any]],
    Awaitable[dict[str, Any]],
]


def compile_technical_trader_node(
    node: TechnicalTraderGraphNode,
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Compile one injected Technical Trader node.

    ``checkpointer`` is accepted but never selected or configured here. The
    production workflow or persistence owner must provide it.
    """

    # LangGraph intentionally accepts multiple callable state shapes. Keep the
    # builder dynamic while this adapter's public node boundary remains typed.
    builder: Any = StateGraph(state_schema=TechnicalTraderGraphState)
    builder.add_node(TECHNICAL_TRADER_NODE, node)
    builder.add_edge(START, TECHNICAL_TRADER_NODE)
    builder.add_edge(TECHNICAL_TRADER_NODE, END)
    return builder.compile(checkpointer=checkpointer)


def compile_technical_trader_graph(
    runtime: TechnicalTraderRuntime,
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Compile the real Technical Trader runtime as an isolated subgraph."""

    return compile_technical_trader_node(
        make_langgraph_node(runtime),
        checkpointer=checkpointer,
    )


__all__ = [
    "LANGGRAPH_VERSION_SPEC",
    "TECHNICAL_TRADER_NODE",
    "TechnicalTraderGraphNode",
    "TechnicalTraderGraphState",
    "compile_technical_trader_graph",
    "compile_technical_trader_node",
]
