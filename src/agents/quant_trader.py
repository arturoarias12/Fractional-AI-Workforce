"""Quant Trader integration placeholder."""

from __future__ import annotations

from typing import Protocol

from .base import TraderAgent


class QuantTraderAgent(TraderAgent, Protocol):
    """Dynamically generate candidates from statistical relationships."""
