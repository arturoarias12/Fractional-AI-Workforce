"""Configurable local execution deadlines."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


# Individual provider/service calls remain bounded independently from the
# complete orchestration deadline.
MAX_TIMEOUT_SECONDS = 300.0
MAX_TRADER_TIMEOUT_SECONDS = 600.0
DEFAULT_MODEL_CALL_TIMEOUT_SECONDS = 100.0
DEFAULT_DATA_SERVICE_TIMEOUT_SECONDS = 30.0
DEFAULT_BACKTEST_TIMEOUT_SECONDS = 40.0
DEFAULT_TRADER_TIMEOUT_SECONDS = MAX_TRADER_TIMEOUT_SECONDS
EXPECTED_MODEL_CALLS_PER_TRADER_RUN = 4
EXPECTED_BACKTEST_CALLS_PER_TRADER_RUN = 2


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

        trader_timeout = self.trader_timeout_seconds
        if (
            isinstance(trader_timeout, bool)
            or not isinstance(trader_timeout, (int, float))
            or not isfinite(trader_timeout)
            or trader_timeout <= 0
        ):
            raise ValueError(
                "trader_timeout_seconds must be a positive number."
            )
        if trader_timeout > MAX_TRADER_TIMEOUT_SECONDS:
            raise ValueError(
                "trader_timeout_seconds cannot exceed "
                f"{MAX_TRADER_TIMEOUT_SECONDS:g} seconds."
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

        aggregate_component_budget = (
            self.model_call_timeout_seconds
            * EXPECTED_MODEL_CALLS_PER_TRADER_RUN
            + self.data_service_timeout_seconds
            + self.backtest_timeout_seconds
            * EXPECTED_BACKTEST_CALLS_PER_TRADER_RUN
        )
        if aggregate_component_budget >= self.trader_timeout_seconds:
            raise ValueError(
                "The aggregate component deadline budget must be less than "
                "trader_timeout_seconds so orchestration retains time to "
                "validate and package the result; configured aggregate is "
                f"{aggregate_component_budget:g} seconds."
            )
