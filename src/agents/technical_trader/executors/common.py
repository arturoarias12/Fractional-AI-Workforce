"""Shared deterministic state and validation for Technical executors."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any, Mapping

from protocols import BacktestRequest


def number(
    values: Mapping[str, Any],
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = values.get(name)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{name} must be numeric.")
    value = float(raw)
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}.")
    return value


def positive_integer(
    values: Mapping[str, Any],
    name: str,
    *,
    minimum: int = 1,
    maximum: int,
) -> int:
    raw = values.get(name)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{name} must be an integer.")
    if not minimum <= raw <= maximum:
        raise ValueError(
            f"{name} must be from {minimum} through {maximum}."
        )
    return raw


def symbol(values: Mapping[str, Any]) -> str:
    value = str(values.get("symbol", "")).strip()
    if not value:
        raise ValueError("symbol must be non-empty.")
    return value


@dataclass(frozen=True, slots=True)
class RiskManagedParameters:
    symbol: str
    target_weight: float
    max_holding_bars: int
    volatility_lookback_bars: int
    profit_target_sigma_multiple: float
    stop_loss_sigma_multiple: float

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "RiskManagedParameters":
        return cls(
            symbol=symbol(values),
            target_weight=number(
                values, "target_weight", minimum=0.01, maximum=1.0
            ),
            max_holding_bars=positive_integer(
                values, "max_holding_bars", maximum=252
            ),
            volatility_lookback_bars=positive_integer(
                values,
                "volatility_lookback_bars",
                minimum=2,
                maximum=252,
            ),
            profit_target_sigma_multiple=number(
                values,
                "profit_target_sigma_multiple",
                minimum=0.01,
                maximum=2.0,
            ),
            stop_loss_sigma_multiple=number(
                values,
                "stop_loss_sigma_multiple",
                minimum=0.01,
                maximum=5.0,
            ),
        )


@dataclass(frozen=True, slots=True)
class ExecutionSettings:
    fill_price_field: str
    slippage_rate: float

    @classmethod
    def from_request(cls, request: BacktestRequest) -> "ExecutionSettings":
        assumptions = request.plan.transaction_cost_assumptions
        fill_price_field = str(
            assumptions.get("fill_price_field", "close")
        ).strip().casefold()
        if fill_price_field not in {"open", "close"}:
            raise ValueError("fill_price_field must be 'open' or 'close'.")
        slippage_bps = assumptions.get("slippage_bps", 0.0)
        if isinstance(slippage_bps, bool) or not isinstance(
            slippage_bps, (int, float)
        ):
            raise ValueError("slippage_bps must be numeric.")
        if float(slippage_bps) < 0:
            raise ValueError("slippage_bps must be nonnegative.")
        return cls(
            fill_price_field=fill_price_field,
            slippage_rate=float(slippage_bps) / 10_000.0,
        )


class VolatilityManagedSession:
    """State shared by directional Technical strategies."""

    def __init__(
        self,
        risk: RiskManagedParameters,
        settings: ExecutionSettings,
        *,
        direction: int = 1,
    ) -> None:
        if direction not in {-1, 1}:
            raise ValueError("direction must be -1 or 1.")
        self.risk = risk
        self.settings = settings
        self.direction = direction
        self.invested_bars = 0
        self.entry_price: float | None = None
        self.entry_holding_volatility: float | None = None
        self.pending_holding_volatility: float | None = None

    @property
    def desired_weight(self) -> float:
        return self.direction * self.risk.target_weight

    def observe_position(self, bar: Any, positions: Mapping[str, float]) -> bool:
        position = float(positions.get(self.risk.symbol, 0.0))
        invested = abs(position) > 1e-12
        if invested and position * self.direction <= 0:
            raise RuntimeError("Observed position direction contradicts executor.")
        if invested and self.entry_price is None:
            self._record_entry(bar)
        elif invested:
            self.invested_bars += 1
        else:
            self.invested_bars = 0
            self.entry_price = None
            self.entry_holding_volatility = None
        return invested

    def prepare_entry(self, history: Any) -> Mapping[str, float] | None:
        holding_volatility = self._holding_period_volatility(history)
        if holding_volatility is None:
            return None
        self.pending_holding_volatility = holding_volatility
        return {self.risk.symbol: self.desired_weight}

    def exit_required(
        self,
        *,
        close: float,
        technical_invalidation: float | None = None,
    ) -> bool:
        if self.entry_price is None or self.entry_holding_volatility is None:
            raise RuntimeError("Invested session has incomplete entry state.")
        risk = self.risk
        volatility = self.entry_holding_volatility
        if self.direction > 0:
            stop = self.entry_price * (
                1.0 - risk.stop_loss_sigma_multiple * volatility
            )
            if technical_invalidation is not None:
                stop = max(stop, technical_invalidation)
            target_hit = close >= self.entry_price * (
                1.0 + risk.profit_target_sigma_multiple * volatility
            )
            stop_hit = close <= stop
        else:
            stop = self.entry_price * (
                1.0 + risk.stop_loss_sigma_multiple * volatility
            )
            if technical_invalidation is not None:
                stop = min(stop, technical_invalidation)
            target_hit = close <= self.entry_price * (
                1.0 - risk.profit_target_sigma_multiple * volatility
            )
            stop_hit = close >= stop
        return (
            stop_hit
            or target_hit
            or self.invested_bars >= risk.max_holding_bars
        )

    def _record_entry(self, bar: Any) -> None:
        if self.pending_holding_volatility is None:
            raise RuntimeError(
                "Executed entry has no point-in-time volatility estimate."
            )
        reference = float(getattr(bar, self.settings.fill_price_field))
        self.entry_price = reference * (
            1.0 + self.direction * self.settings.slippage_rate
        )
        self.entry_holding_volatility = self.pending_holding_volatility
        self.pending_holding_volatility = None
        self.invested_bars = 1

    def _holding_period_volatility(self, history: Any) -> float | None:
        lookback = self.risk.volatility_lookback_bars
        if len(history) < lookback + 1:
            return None
        closes = [float(bar.close) for bar in history[-(lookback + 1) :]]
        returns = [
            current / previous - 1.0
            for previous, current in zip(closes, closes[1:], strict=False)
        ]
        mean_return = sum(returns) / len(returns)
        variance = sum(
            (period_return - mean_return) ** 2
            for period_return in returns
        ) / (len(returns) - 1)
        daily_volatility = sqrt(max(variance, 0.0))
        if daily_volatility <= 0:
            return None
        return daily_volatility * sqrt(self.risk.max_holding_bars)


__all__ = [
    "ExecutionSettings",
    "RiskManagedParameters",
    "VolatilityManagedSession",
    "number",
    "positive_integer",
    "symbol",
]
