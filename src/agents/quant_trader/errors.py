"""Domain exceptions exposed by the Quant Trader package."""

from __future__ import annotations


class QuantTraderError(Exception):
    """Base class for errors raised by this package."""


class MandateValidationError(QuantTraderError):
    """The normalized Portfolio Manager mandate is invalid."""


class DiscoveryError(QuantTraderError):
    """The statistical pair-discovery stage could not produce a candidate."""


class ServiceContractError(QuantTraderError):
    """A shared service (DataService/BacktestEngine) violated its contract."""
