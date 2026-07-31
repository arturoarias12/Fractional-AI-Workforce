"""Domain exceptions exposed by the Technical Trader package."""

from __future__ import annotations


class TechnicalTraderError(Exception):
    """Base class for errors raised by this package."""


class MandateValidationError(TechnicalTraderError):
    """The normalized Portfolio Manager mandate is invalid."""


class AgentInputValidationError(TechnicalTraderError):
    """An agent received an input that violates its contract."""


class ModelInvocationError(TechnicalTraderError):
    """The configured model client could not complete a request."""


class ModelTimeoutError(ModelInvocationError):
    """A model call exceeded its configured deadline."""


class AgentTimeoutError(TechnicalTraderError):
    """An agent exceeded its configured end-to-end deadline."""


class AgentOutputValidationError(TechnicalTraderError):
    """A model response did not satisfy the agent output contract."""


class StrategyBoundaryError(AgentOutputValidationError):
    """An output crossed a stage-specific strategy boundary."""


class ServiceContractError(TechnicalTraderError):
    """A shared service returned data that violated its declared contract."""


class TechnicalAnalysisInputError(ServiceContractError):
    """Point-in-time data could not be adapted for the owned analysis tools."""
