"""Deterministic executor for Quant Trader's cross-asset spread rule.

This is the only piece of Quant Trader logic that touches simulated money,
and it contains no LLM calls and no statistics beyond a rolling mean/std -
exactly the "intelligence around the computation, never inside it" split
the project is built on. discovery.py decides WHICH pair and parameters to
try; this module only knows HOW to turn those parameters into day-by-day
buy/hold/sell decisions once the Backtest Engine calls it.

Registered under ``CROSS_ASSET_SPREAD_EXECUTOR_ID`` so a
``CandidateRuleSpecification.executor_id`` can reference it directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from protocols import BacktestRequest
from tools import (
    FunctionalStrategyExecutor,
    PriceBar,
    StrategyEvaluationContext,
)

CROSS_ASSET_SPREAD_EXECUTOR_ID = "quant_trader.cross_asset_spread_mean_reversion.v1"

_REQUIRED_PARAMETERS = (
    "ticker_a",
    "ticker_b",
    "lookback_days",
    "entry_zscore",
    "exit_zscore",
)


@dataclass(frozen=True, slots=True)
class PairSpreadParameters:
    ticker_a: str
    ticker_b: str
    lookback_days: int
    entry_zscore: float
    exit_zscore: float

    @classmethod
    def from_mapping(cls, parameters: dict) -> "PairSpreadParameters":
        missing = [name for name in _REQUIRED_PARAMETERS if name not in parameters]
        if missing:
            raise ValueError(
                "Cross-asset spread candidate is missing required parameters: "
                + ", ".join(missing)
            )
        return cls(
            ticker_a=str(parameters["ticker_a"]),
            ticker_b=str(parameters["ticker_b"]),
            lookback_days=int(parameters["lookback_days"]),
            entry_zscore=float(parameters["entry_zscore"]),
            exit_zscore=float(parameters["exit_zscore"]),
        )

    def __post_init__(self) -> None:
        if self.ticker_a == self.ticker_b:
            raise ValueError("ticker_a and ticker_b must be different symbols.")
        if self.lookback_days < 2:
            raise ValueError("lookback_days must be at least 2.")
        if self.entry_zscore <= 0 or self.exit_zscore < 0:
            raise ValueError("entry_zscore must be positive and exit_zscore non-negative.")
        if self.exit_zscore >= self.entry_zscore:
            raise ValueError("exit_zscore must be smaller than entry_zscore.")


class PairSpreadSession:
    """One isolated, stateful session per backtest run (per engine contract)."""

    def __init__(self, parameters: PairSpreadParameters) -> None:
        self._params = parameters
        self._in_position = False

    def target_weights(
        self,
        context: StrategyEvaluationContext,
    ) -> dict[str, float] | None:
        params = self._params
        history_a = context.history.get(params.ticker_a, ())
        history_b = context.history.get(params.ticker_b, ())
        if len(history_a) < params.lookback_days + 1 or not history_b:
            return None  # not enough history yet - keep current positions

        bars_b_by_date = {bar.timestamp: bar.close for bar in history_b}
        window = history_a[-params.lookback_days:]
        spread: list[float] = []
        for bar_a in window:
            close_b = bars_b_by_date.get(bar_a.timestamp)
            if close_b is None:
                return None  # symbols not aligned on this date - stay put
            spread.append(bar_a.close / close_b)

        mean_spread = sum(spread) / len(spread)
        variance = sum((value - mean_spread) ** 2 for value in spread) / len(spread)
        std_spread = variance ** 0.5
        if std_spread == 0:
            return None

        current_zscore = (spread[-1] - mean_spread) / std_spread

        if self._in_position:
            if current_zscore >= -params.exit_zscore:
                self._in_position = False
                return {}
            return {params.ticker_a: 1.0}

        if current_zscore <= -params.entry_zscore:
            self._in_position = True
            return {params.ticker_a: 1.0}

        return None


def _session_factory(request: BacktestRequest) -> PairSpreadSession:
    parameters = PairSpreadParameters.from_mapping(dict(request.candidate.parameters))
    return PairSpreadSession(parameters)


cross_asset_spread_executor = FunctionalStrategyExecutor(
    executor_id=CROSS_ASSET_SPREAD_EXECUTOR_ID,
    session_factory=_session_factory,
)

__all__ = [
    "CROSS_ASSET_SPREAD_EXECUTOR_ID",
    "PairSpreadParameters",
    "PairSpreadSession",
    "cross_asset_spread_executor",
]
