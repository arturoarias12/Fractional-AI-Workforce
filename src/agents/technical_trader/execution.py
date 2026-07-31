"""Configurable local execution deadlines."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


MAX_TIMEOUT_SECONDS = 300.0
DEFAULT_MODEL_CALL_TIMEOUT_SECONDS = 45.0
DEFAULT_DATA_SERVICE_TIMEOUT_SECONDS = 60.0
DEFAULT_BACKTEST_TIMEOUT_SECONDS = 90.0
DEFAULT_TRADER_TIMEOUT_SECONDS = MAX_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    """Finite deadlines for model calls, services, and complete trader runs.

    Component calls have shorter deadlines so they can emit structured failures
    before the containing trader deadline expires.
    """

    model_call_timeout_seconds: float = DEFAULT_MODEL_CALL_TIMEOUT_SECONDS
    data_service_timeout_seconds: float = DEFAULT_DATA_SERVICE_TIMEOUT_SECONDS
    backtest_timeout_seconds: float = DEFAULT_BACKTEST_TIMEOUT_SECONDS
    trader_timeout_seconds: float = DEFAULT_TRADER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        for field_name in (
            "model_call_timeout_seconds",
            "data_service_timeout_seconds",
            "backtest_timeout_seconds",
            "trader_timeout_seconds",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{field_name} must be a positive number.")
            if value > MAX_TIMEOUT_SECONDS:
                raise ValueError(
                    f"{field_name} cannot exceed "
                    f"{MAX_TIMEOUT_SECONDS:g} seconds."
                )

        if self.model_call_timeout_seconds >= self.trader_timeout_seconds:
            raise ValueError(
                "model_call_timeout_seconds must be less than "
                "trader_timeout_seconds."
            )
        if self.data_service_timeout_seconds >= self.trader_timeout_seconds:
            raise ValueError(
                "data_service_timeout_seconds must be less than "
                "trader_timeout_seconds."
            )
        if self.backtest_timeout_seconds >= self.trader_timeout_seconds:
            raise ValueError(
                "backtest_timeout_seconds must be less than "
                "trader_timeout_seconds."
            )
