"""Deterministic executor for Fundamental Trader's category-deviation rule.

This is the only piece of Fundamental Trader logic that touches simulated
money, and it contains no LLM calls and no statistics beyond a rolling
mean/std of a return spread - the same "intelligence around the
computation, never inside it" split Quant Trader's executor follows.
``rule_generator.py`` decides WHICH ticker, category benchmark, and
parameters to try; this module only knows HOW to turn those parameters into
day-by-day buy/hold/sell decisions once the Backtest Engine calls it.

Registered under ``CATEGORY_DEVIATION_EXECUTOR_ID`` so a
``CandidateRuleSpecification.executor_id`` can reference it directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from protocols import BacktestRequest
from tools import (
    FunctionalStrategyExecutor,
    StrategyEvaluationContext,
)

CATEGORY_DEVIATION_EXECUTOR_ID = "fundamental_trader.category_benchmark_deviation.v1"

_REQUIRED_PARAMETERS = (
    "ticker",
    "category",
    "lookback_days",
    "entry_zscore",
    "exit_zscore",
    "benchmark_tickers",
)


@dataclass(frozen=True, slots=True)
class CategoryDeviationParameters:
    ticker: str
    category: str
    lookback_days: int
    entry_zscore: float
    exit_zscore: float
    benchmark_tickers: tuple[str, ...]

    @classmethod
    def from_mapping(cls, parameters: dict) -> "CategoryDeviationParameters":
        missing = [name for name in _REQUIRED_PARAMETERS if name not in parameters]
        if missing:
            raise ValueError(
                "Category-deviation candidate is missing required parameters: "
                + ", ".join(missing)
            )
        benchmark = tuple(str(t) for t in parameters["benchmark_tickers"])
        return cls(
            ticker=str(parameters["ticker"]),
            category=str(parameters["category"]),
            lookback_days=int(parameters["lookback_days"]),
            entry_zscore=float(parameters["entry_zscore"]),
            exit_zscore=float(parameters["exit_zscore"]),
            benchmark_tickers=benchmark,
        )

    def __post_init__(self) -> None:
        if self.ticker in self.benchmark_tickers:
            raise ValueError("ticker must not also be one of its own benchmark_tickers.")
        if not self.benchmark_tickers:
            raise ValueError("benchmark_tickers must be non-empty.")
        if self.lookback_days < 2:
            raise ValueError("lookback_days must be at least 2.")
        if self.entry_zscore <= 0 or self.exit_zscore < 0:
            raise ValueError("entry_zscore must be positive and exit_zscore non-negative.")
        if self.exit_zscore >= self.entry_zscore:
            raise ValueError("exit_zscore must be smaller than entry_zscore.")


class CategoryDeviationSession:
    """One isolated, stateful session per backtest run (per engine contract)."""

    def __init__(self, parameters: CategoryDeviationParameters) -> None:
        self._params = parameters
        self._in_position = False

    def target_weights(
        self,
        context: StrategyEvaluationContext,
    ) -> dict[str, float] | None:
        params = self._params
        history = context.history.get(params.ticker, ())
        if len(history) < params.lookback_days + 1:
            return None  # not enough history yet - keep current positions

        benchmark_histories = [
            context.history.get(symbol, ()) for symbol in params.benchmark_tickers
        ]
        if any(len(h) < params.lookback_days + 1 for h in benchmark_histories):
            return None  # a benchmark peer hasn't got enough history yet

        ticker_returns = self._returns(history, params.lookback_days + 1)
        benchmark_returns_by_peer = [
            self._returns(h, params.lookback_days + 1) for h in benchmark_histories
        ]
        n = min(len(ticker_returns), *(len(r) for r in benchmark_returns_by_peer))
        if n < params.lookback_days:
            return None
        ticker_returns = ticker_returns[-n:]
        benchmark_returns = [
            sum(peer_returns[-n:][i] for peer_returns in benchmark_returns_by_peer)
            / len(benchmark_returns_by_peer)
            for i in range(n)
        ]

        spread = [t - b for t, b in zip(ticker_returns, benchmark_returns)]
        window = spread[-params.lookback_days:]
        mean_spread = sum(window) / len(window)
        variance = sum((v - mean_spread) ** 2 for v in window) / len(window)
        std_spread = variance ** 0.5
        if std_spread == 0:
            return None

        current_zscore = (spread[-1] - mean_spread) / std_spread

        if self._in_position:
            if current_zscore >= -params.exit_zscore:
                self._in_position = False
                return {}
            return {params.ticker: 1.0}

        if current_zscore <= -params.entry_zscore:
            self._in_position = True
            return {params.ticker: 1.0}

        return None

    @staticmethod
    def _returns(history: tuple, count: int) -> list[float]:
        closes = [bar.close for bar in history[-count:]]
        return [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1] != 0
        ]


def _session_factory(request: BacktestRequest) -> CategoryDeviationSession:
    parameters = CategoryDeviationParameters.from_mapping(dict(request.candidate.parameters))
    return CategoryDeviationSession(parameters)


category_deviation_executor = FunctionalStrategyExecutor(
    executor_id=CATEGORY_DEVIATION_EXECUTOR_ID,
    session_factory=_session_factory,
)

__all__ = [
    "CATEGORY_DEVIATION_EXECUTOR_ID",
    "CategoryDeviationParameters",
    "CategoryDeviationSession",
    "category_deviation_executor",
]
