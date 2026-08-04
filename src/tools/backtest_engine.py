"""Minimal deterministic backtest engine for trader agents.

It resolves OHLC bars, runs a registered strategy day by day, and returns
full-period plus held-out metrics. A signal produced on day t is executed at
day t+1 close. The prototype assumes no costs and keeps unused capital as cash.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt
from typing import Protocol, runtime_checkable

from protocols import (
    BacktestRequest,
    BacktestResult,
    BacktestRunLedgerEntry,
    BacktestStatus,
)

ENGINE_NAME = "fractional_ai_workforce_backtest_engine"
ENGINE_VERSION = "0.6.0"

BACKTEST_METRIC_DEFINITIONS: Mapping[str, Mapping[str, str]] = {
    "total_return": {"description": "Simple return over the equity curve."},
    "annualized_return": {"description": "Annualized geometric return (252-day)."},
    "max_drawdown": {"description": "Worst peak-to-trough equity decline."},
    "sharpe_ratio": {"description": "Annualized Sharpe of daily returns (rf=0)."},
    "transaction_count": {"description": "Number of simulated trades."},
}


@dataclass(frozen=True, slots=True)
class PriceBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("PriceBar.symbol must be non-empty.")
        if self.timestamp.tzinfo is None:
            raise ValueError("PriceBar.timestamp must be timezone-aware.")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("PriceBar OHLC must be positive.")


@dataclass(frozen=True, slots=True)
class ResolvedBacktestData:
    data_references: tuple[str, ...]
    bars: tuple[PriceBar, ...]


@dataclass(frozen=True, slots=True)
class StrategyEvaluationContext:
    timestamp: datetime
    current_bars: Mapping[str, PriceBar]
    history: Mapping[str, tuple[PriceBar, ...]]
    positions: Mapping[str, float]
    cash: float
    equity: float
    parameters: Mapping[str, Any]


@runtime_checkable
class BacktestDataResolver(Protocol):
    async def resolve(self, request: BacktestRequest) -> ResolvedBacktestData: ...


@runtime_checkable
class StrategySession(Protocol):
    def target_weights(
        self, context: StrategyEvaluationContext
    ) -> Mapping[str, float] | None: ...


@runtime_checkable
class StrategyExecutor(Protocol):
    executor_id: str

    def create_session(self, request: BacktestRequest) -> StrategySession: ...


@runtime_checkable
class BacktestEngine(Protocol):
    async def run(self, request: BacktestRequest) -> BacktestResult: ...


@dataclass(frozen=True, slots=True)
class FunctionalStrategyExecutor:
    executor_id: str
    session_factory: Callable[[BacktestRequest], StrategySession]

    def create_session(self, request: BacktestRequest) -> StrategySession:
        return self.session_factory(request)


class DeterministicBacktestEngine:
    def __init__(
        self,
        *,
        data_resolver: BacktestDataResolver,
        strategy_executors: Iterable[StrategyExecutor],
        initial_capital: float = 100_000.0,
    ) -> None:
        self._data_resolver = data_resolver
        self._executors = {e.executor_id: e for e in strategy_executors}
        self._initial_capital = initial_capital

    @property
    def registered_executor_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._executors))

    async def run(self, request: BacktestRequest) -> BacktestResult:
        try:
            executor = self._executors.get(request.candidate.executor_id)
            if executor is None:
                raise ValueError(
                    f"Unknown executor '{request.candidate.executor_id}'. "
                    f"Registered: {', '.join(self.registered_executor_ids) or 'none'}"
                )

            resolved = await self._data_resolver.resolve(request)
            bars = _filter_bars(request, resolved.bars)
            if len({bar.timestamp for bar in bars}) < 2:
                raise ValueError("Need at least two trading days of bars.")

            session = executor.create_session(request)
            equity_curve, trade_dates = _simulate(
                request, bars, session, self._initial_capital
            )
            metrics = _compute_metrics(equity_curve, len(trade_dates))
            oos = _out_of_sample_metrics(request, equity_curve, trade_dates)

            result = BacktestResult(
                result_id=f"{request.request_id}.result",
                execution_attempt_id=request.request_id,
                request_id=request.request_id,
                candidate_id=request.candidate.candidate_id,
                status=BacktestStatus.SUCCEEDED,
                engine_name=ENGINE_NAME,
                engine_version=ENGINE_VERSION,
                metrics=metrics,
                out_of_sample_metrics=oos,
                additional_fields={
                    "executor_id": request.candidate.executor_id,
                    "bar_count": len(bars),
                    "data_references": list(resolved.data_references),
                },
            )
            return _with_ledger(request, result, bars, resolved.data_references)
        except Exception as exc:
            result = BacktestResult(
                result_id=f"{request.request_id}.result",
                execution_attempt_id=request.request_id,
                request_id=request.request_id,
                candidate_id=request.candidate.candidate_id,
                status=BacktestStatus.FAILED,
                engine_name=ENGINE_NAME,
                engine_version=ENGINE_VERSION,
                failure_reason=f"{type(exc).__name__}: {exc}",
            )
            return _with_ledger(request, result, (), tuple(request.data_references))


def _filter_bars(
    request: BacktestRequest, bars: Sequence[PriceBar]
) -> tuple[PriceBar, ...]:
    start = request.plan.requested_start_date
    end = request.plan.requested_end_date or request.as_of_date
    kept = [
        bar
        for bar in bars
        if bar.timestamp.date() <= request.as_of_date
        and bar.timestamp.date() <= end
        and (start is None or bar.timestamp.date() >= start)
    ]
    return tuple(sorted(kept, key=lambda b: (b.timestamp, b.symbol)))


def _simulate(
    request: BacktestRequest,
    bars: tuple[PriceBar, ...],
    session: StrategySession,
    initial_capital: float,
) -> tuple[tuple[tuple[datetime, float], ...], tuple[datetime, ...]]:
    by_day: dict[datetime, dict[str, PriceBar]] = defaultdict(dict)
    for bar in bars:
        by_day[bar.timestamp][bar.symbol] = bar
    timeline = sorted(by_day)

    histories: dict[str, list[PriceBar]] = defaultdict(list)
    latest: dict[str, PriceBar] = {}
    positions: dict[str, float] = {}
    cash = initial_capital
    pending_target: Mapping[str, float] | None = None
    equity_curve: list[tuple[datetime, float]] = []
    trade_dates: list[datetime] = []

    for timestamp in timeline:
        today = by_day[timestamp]

        if pending_target is not None:
            cash = _rebalance(
                pending_target,
                timestamp,
                today,
                latest,
                positions,
                cash,
                trade_dates,
            )
            pending_target = None

        latest.update(today)
        for symbol, bar in today.items():
            histories[symbol].append(bar)

        equity = _equity(cash, positions, latest)
        target = session.target_weights(
            StrategyEvaluationContext(
                timestamp=timestamp,
                current_bars=dict(today),
                history={s: tuple(h) for s, h in histories.items()},
                positions=dict(positions),
                cash=cash,
                equity=equity,
                parameters=request.candidate.parameters,
            )
        )
        if target is not None:
            pending_target = {str(k): float(v) for k, v in target.items() if float(v) != 0.0}

        equity_curve.append((timestamp, equity))

    if positions and timeline:
        last_ts = timeline[-1]
        cash = _rebalance(
            {}, last_ts, by_day[last_ts], latest, positions, cash, trade_dates
        )
        equity_curve[-1] = (last_ts, _equity(cash, positions, latest))

    return tuple(equity_curve), tuple(trade_dates)


def _rebalance(
    target_weights: Mapping[str, float],
    exec_ts: datetime,
    today: Mapping[str, PriceBar],
    latest: Mapping[str, PriceBar],
    positions: dict[str, float],
    cash: float,
    trade_dates: list[datetime],
) -> float:
    prices = dict(latest)
    prices.update(today)
    equity = _equity(cash, positions, prices)
    if equity <= 0:
        return cash

    symbols = set(positions) | set(target_weights)
    for symbol in symbols:
        bar = prices.get(symbol)
        if bar is None:
            continue
        price = bar.close
        desired_qty = equity * float(target_weights.get(symbol, 0.0)) / price
        current_qty = positions.get(symbol, 0.0)
        delta = desired_qty - current_qty
        if abs(delta) * price < 1e-6:
            continue
        cash -= delta * price
        if abs(desired_qty) < 1e-8:
            positions.pop(symbol, None)
        else:
            positions[symbol] = desired_qty
        trade_dates.append(exec_ts)
    return cash


def _equity(
    cash: float, positions: Mapping[str, float], prices: Mapping[str, PriceBar]
) -> float:
    total = cash
    for symbol, qty in positions.items():
        bar = prices.get(symbol)
        if bar is not None:
            total += qty * bar.close
    return total


def _compute_metrics(
    equity_curve: Sequence[tuple[datetime, float]],
    trade_count: int,
) -> dict[str, float | int | None]:
    if len(equity_curve) < 2 or equity_curve[0][1] <= 0:
        return {"transaction_count": trade_count}

    values = [value for _, value in equity_curve]
    start, end = values[0], values[-1]
    total_return = end / start - 1.0
    n = len(equity_curve) - 1
    annualized = (end / start) ** (252 / n) - 1.0 if end > 0 else -1.0

    peak = start
    max_dd = 0.0
    for value in values:
        peak = max(peak, value)
        max_dd = min(max_dd, value / peak - 1.0)

    returns = [
        values[i] / values[i - 1] - 1.0
        for i in range(1, len(values))
        if values[i - 1] > 0
    ]
    sharpe = None
    if len(returns) >= 2:
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        std = sqrt(var)
        if std > 0:
            sharpe = (mean / std) * sqrt(252)

    return {
        "total_return": total_return,
        "annualized_return": annualized,
        "max_drawdown": max_dd,
        "sharpe_ratio": sharpe,
        "transaction_count": trade_count,
    }


def _out_of_sample_metrics(
    request: BacktestRequest,
    equity_curve: Sequence[tuple[datetime, float]],
    trade_dates: Sequence[datetime],
) -> dict[str, float | int | None]:
    split = request.plan.validation_split
    if split is None:
        if request.plan.held_out_evaluation_required:
            raise ValueError(
                "held_out_evaluation_required is true but validation_split is missing."
            )
        return {}

    points = [
        point
        for point in equity_curve
        if split.test_start_date <= point[0].date() <= split.test_end_date
    ]
    trade_count = sum(
        1
        for timestamp in trade_dates
        if split.test_start_date
        <= timestamp.date()
        <= split.test_end_date
    )
    if len(points) < 2:
        return {}
    return _compute_metrics(points, trade_count)


def _with_ledger(
    request: BacktestRequest,
    result: BacktestResult,
    bars: Sequence[PriceBar],
    data_references: Sequence[str],
) -> BacktestResult:
    now = datetime.now(timezone.utc)
    entry = BacktestRunLedgerEntry(
        ledger_entry_id=f"{result.result_id}.ledger",
        recorded_at=now,
        run_id=request.execution_context.run_id,
        workflow_run_id=request.execution_context.run_id,
        workflow_id=request.lineage.workflow_id,
        round_number=request.execution_context.round_number,
        task_id=request.lineage.task_id,
        attempt=request.lineage.attempt,
        request_id=request.request_id,
        result_id=result.result_id,
        trader_id=request.trader_id,
        candidate_id=request.candidate.candidate_id,
        strategy_name=request.candidate.strategy_name,
        executor_id=request.candidate.executor_id,
        parameters=dict(request.candidate.parameters),
        resolved_symbols=sorted({bar.symbol for bar in bars}),
        data_references=list(data_references),
        requested_start_date=request.plan.requested_start_date,
        requested_end_date=request.plan.requested_end_date,
        resolved_start_time=bars[0].timestamp if bars else None,
        resolved_end_time=bars[-1].timestamp if bars else None,
        status=result.status,
        metrics=dict(result.metrics),
        out_of_sample_metrics=dict(result.out_of_sample_metrics),
        failure_reason=result.failure_reason,
    )
    return result.model_copy(update={"ledger_entry": entry})
