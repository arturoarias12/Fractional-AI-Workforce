"""ETF-level Fundamental Trader integration placeholder."""

from __future__ import annotations

from typing import Protocol

from .base import TraderAgent


class FundamentalTraderAgent(TraderAgent, Protocol):
    """Dynamically generate candidates from point-in-time ETF fundamentals."""
