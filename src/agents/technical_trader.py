"""Technical Trader integration placeholder.

The implementation is currently developed separately under
``project_agents/technical_trader_agent``. This module must remain a boundary,
not a duplicate implementation, until the package is ready for integration.
"""

from __future__ import annotations

from typing import Protocol

from .base import TraderAgent


class TechnicalTraderAgent(TraderAgent, Protocol):
    """Dynamically generate technical candidates using owned coded tools."""
