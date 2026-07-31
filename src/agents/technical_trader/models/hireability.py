"""Technical Trader registry-card validation.

The repository-level JSON Agent Card is the single metadata source. This module
validates a registry mapping without repeating capabilities or dependencies in
Python.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from protocols import AgentCard


def technical_trader_agent_card(
    value: Mapping[str, Any],
) -> AgentCard:
    """Validate and normalize the registry's Technical Trader card."""

    card = AgentCard.from_mapping(value)
    if card.agent_id != "technical_trader_agent":
        raise ValueError(
            "Expected the technical_trader_agent registry card, got "
            f"{card.agent_id!r}."
        )
    return card


__all__ = ["technical_trader_agent_card"]
