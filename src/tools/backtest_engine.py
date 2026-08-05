"""Deterministic shared backtest engine for trader agents.

The engine preserves the simplified implementation's defaults for callers that
omit execution assumptions: signals execute one bar later at the close, costs
default to zero, and the constructor's initial capital is used. Callers may
additively request next-bar-open fills, costs, other supported metrics, and a
benchmark through the existing ``BacktestPlan`` fields.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite, sqrt
from typing import Any, Protocol, runtime_checkable

from protocols import (
    BacktestRequest,
    BacktestResult,
    BacktestRunLedgerEntry,
    BacktestStatus,
)

ENGINE_NAME = "fractional_ai_workforce_backtest_engine"
ENGINE_VERSION = "0.7.0"

BACKTEST_METRIC_DEFINITIONS: Mapping[str, Mapping[str, str]] = {
    "total_return": {"description": "Simple return over the equity curve."},
    "annualized_return": {
        "description": "Annualized geometric return for the plan frequency."
    },
    "max_drawdown": {"description": "Worst peak-to-trough equity decline."},
    "annualized_volatility": {
        "description": "Sample volatility of periodic returns, annualized."
    },
    "sharpe_ratio": {
        "description": "Annualized Sharpe of periodic returns (rf=0)."
    },
    "transaction_count": {"description": "Number of simulated trades."},
    "transaction_costs": {
        "description": "Total modeled commissions and slippage cost."
    },
    "turnover": {
        "description": "Gross reference notional divided by initial capital."
    },
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
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
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


@dataclass(frozen=True, slots=True)
class _ExecutionAssumptions:
    initial_capital: float
    commission_bps: float
    slippage_bps: float
    fill_price_field: str
    signal_delay_bars: int
    liquidate_at_end: bool
    allow_short: bool
    max_gross_leverage: float
    annualization_factor: int

    @classmethod
    def from_request(
        cls,
        request: BacktestRequest,
        *,
        default_initial_capital: float,
    ) -> "_ExecutionAssumptions":
        raw = request.plan.transaction_cost_assumptions
        mandate_constraints = request.mandate_constraints
        short_constraints = mandate_constraints.get(
            "short_selling_constraints", {}
        )
        if not isinstance(short_constraints, Mapping):
            short_constraints = {}
        leverage_constraints = mandate_constraints.get(
            "leverage_constraints", {}
        )
        if not isinstance(leverage_constraints, Mapping):
            leverage_constraints = {}
        frequency = request.plan.frequency.casefold().replace("-", "_")
        default_annualization = {
            "daily": 252,
            "1d": 252,
            "weekly": 52,
            "1w": 52,
            "monthly": 12,
            "1m": 12,
        }.get(frequency, 252)

        fill_price_field = str(
            raw.get("fill_price_field", "close")
        ).strip().casefold()
        if fill_price_field not in {"open", "close"}:
            raise ValueError("fill_price_field must be 'open' or 'close'.")

        signal_delay_bars = _positive_integer(
            raw.get("signal_delay_bars", 1),
            "signal_delay_bars",
        )
        liquidate_at_end = raw.get("liquidate_at_end", True)
        if not isinstance(liquidate_at_end, bool):
            raise ValueError("liquidate_at_end must be boolean.")

        return cls(
            initial_capital=_finite_number(
                raw.get("initial_capital", default_initial_capital),
                "initial_capital",
                minimum=0.0,
                strictly_greater=True,
            ),
            commission_bps=_finite_number(
                raw.get(
                    "commission_bps",
                    raw.get("transaction_cost_bps", 0.0),
                ),
                "commission_bps",
                minimum=0.0,
            ),
            slippage_bps=_finite_number(
                raw.get("slippage_bps", 0.0),
                "slippage_bps",
                minimum=0.0,
            ),
            fill_price_field=fill_price_field,
            signal_delay_bars=signal_delay_bars,
            liquidate_at_end=liquidate_at_end,
            allow_short=_boolean(
                short_constraints.get(
                    "allow_short",
                    mandate_constraints.get(
                        "allow_short",
                        raw.get("allow_short", False),
                    ),
                ),
                "allow_short",
            ),
            max_gross_leverage=_finite_number(
                leverage_constraints.get(
                    "max_gross_leverage",
                    mandate_constraints.get(
                        "max_gross_leverage",
                        raw.get("max_gross_leverage", 1.0),
                    ),
                ),
                "max_gross_leverage",
                minimum=0.0,
                strictly_greater=True,
            ),
            annualization_factor=_positive_integer(
                raw.get("annualization_factor", default_annualization),
                "annualization_factor",
            ),
        )


@dataclass(frozen=True, slots=True)
class _Transaction:
    symbol: str
    execution_timestamp: datetime
    reference_notional: float
    commission: float
    slippage_cost: float


@dataclass(frozen=True, slots=True)
class _SimulationResult:
    equity_curve: tuple[tuple[datetime, float], ...]
    transactions: tuple[_Transaction, ...]
    warnings: tuple[str, ...]


@dataclass(slots=True)
class _ExecutionWarningSummary:
    count: int
    first_timestamp: datetime
    last_timestamp: datetime

    def record(self, timestamp: datetime) -> None:
        self.count += 1
        if timestamp < self.first_timestamp:
            self.first_timestamp = timestamp
        if timestamp > self.last_timestamp:
            self.last_timestamp = timestamp


class _ExecutionWarningAccumulator:
    """Bound repeated per-symbol execution warnings to one summary each."""

    def __init__(self) -> None:
        self._summaries: dict[
            tuple[str, str], _ExecutionWarningSummary
        ] = {}

    def record(
        self,
        reason: str,
        symbol: str,
        timestamp: datetime,
    ) -> None:
        key = (reason, symbol)
        summary = self._summaries.get(key)
        if summary is None:
            self._summaries[key] = _ExecutionWarningSummary(
                count=1,
                first_timestamp=timestamp,
                last_timestamp=timestamp,
            )
            return
        summary.record(timestamp)

    def messages(self) -> tuple[str, ...]:
        messages: list[str] = []
        for (reason, symbol), summary in sorted(self._summaries.items()):
            interval = (
                f"first: {summary.first_timestamp.isoformat()}; "
                f"last: {summary.last_timestamp.isoformat()}"
            )
            if reason == "stale_close":
                messages.append(
                    f"Used the latest available close for {symbol} in "
                    f"{summary.count} rebalance attempt(s) because no current "
                    f"execution bar was available ({interval})."
                )
            elif reason == "missing_current_bar":
                messages.append(
                    f"Skipped {summary.count} rebalance attempt(s) for "
                    f"{symbol} because no current execution bar was available "
                    f"({interval})."
                )
        return tuple(messages)


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
        warnings: list[str] = []
        try:
            executor = self._executors.get(request.candidate.executor_id)
            if executor is None:
                raise ValueError(
                    f"Unknown executor '{request.candidate.executor_id}'. "
                    f"Registered: {', '.join(self.registered_executor_ids) or 'none'}"
                )

            assumptions = _ExecutionAssumptions.from_request(
                request,
                default_initial_capital=self._initial_capital,
            )
            resolved = await self._data_resolver.resolve(request)
            bars = _filter_bars(request, resolved.bars)
            if len({bar.timestamp for bar in bars}) < 2:
                raise ValueError("Need at least two trading days of bars.")

            session = executor.create_session(request)
            simulation = _simulate(request, bars, session, assumptions)
            warnings.extend(simulation.warnings)

            metrics = _compute_metrics(
                simulation.equity_curve,
                simulation.transactions,
                assumptions,
            )
            out_of_sample_metrics = _out_of_sample_metrics(
                request,
                simulation,
                assumptions,
            )
            if (
                request.plan.validation_split is not None
                and not out_of_sample_metrics
            ):
                warnings.append(
                    "Held-out metrics were unavailable because the test "
                    "window contained fewer than two equity observations."
                )

            benchmark_metrics, benchmark_warnings = _benchmark_metrics(
                request,
                bars,
                assumptions,
            )
            warnings.extend(benchmark_warnings)
            warnings.extend(_requested_metric_warnings(request, metrics))
            warnings = _deduplicate(warnings)

            result = BacktestResult(
                result_id=f"{request.request_id}.result",
                execution_attempt_id=request.request_id,
                request_id=request.request_id,
                candidate_id=request.candidate.candidate_id,
                status=BacktestStatus.SUCCEEDED,
                engine_name=ENGINE_NAME,
                engine_version=ENGINE_VERSION,
                metrics=metrics,
                out_of_sample_metrics=out_of_sample_metrics,
                benchmark_metrics=benchmark_metrics,
                warnings=warnings,
                additional_fields={
                    "executor_id": request.candidate.executor_id,
                    "bar_count": len(bars),
                    "data_references": list(resolved.data_references),
                    "applied_assumptions": asdict(assumptions),
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
                warnings=_deduplicate(warnings),
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
    assumptions: _ExecutionAssumptions,
) -> _SimulationResult:
    by_day: dict[datetime, dict[str, PriceBar]] = defaultdict(dict)
    for bar in bars:
        by_day[bar.timestamp][bar.symbol] = bar
    timeline = sorted(by_day)

    histories: dict[str, list[PriceBar]] = defaultdict(list)
    latest: dict[str, PriceBar] = {}
    positions: dict[str, float] = {}
    cash = assumptions.initial_capital
    pending: dict[int, list[Mapping[str, float]]] = defaultdict(list)
    equity_curve: list[tuple[datetime, float]] = []
    transactions: list[_Transaction] = []
    warnings: list[str] = []
    execution_warnings = _ExecutionWarningAccumulator()
    known_symbols = {bar.symbol for bar in bars}

    for index, timestamp in enumerate(timeline):
        today = by_day[timestamp]

        for target in pending.pop(index, ()):
            cash = _rebalance(
                target,
                timestamp,
                today,
                latest,
                positions,
                cash,
                assumptions,
                transactions,
                warnings,
                execution_warnings,
            )

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
            execution_index = index + assumptions.signal_delay_bars
            normalized = _validate_target_weights(
                target,
                known_symbols,
                assumptions,
            )
            if execution_index < len(timeline):
                pending[execution_index].append(normalized)
            else:
                warnings.append(
                    "A strategy signal could not execute because its delay "
                    "extended beyond the available data."
                )

        equity_curve.append((timestamp, equity))

    if assumptions.liquidate_at_end and positions and timeline:
        last_timestamp = timeline[-1]
        liquidation_assumptions = _ExecutionAssumptions(
            **{
                **asdict(assumptions),
                "fill_price_field": "close",
            }
        )
        cash = _rebalance(
            {},
            last_timestamp,
            {symbol: latest[symbol] for symbol in positions},
            latest,
            positions,
            cash,
            liquidation_assumptions,
            transactions,
            warnings,
            execution_warnings,
        )
        equity_curve[-1] = (
            last_timestamp,
            _equity(cash, positions, latest),
        )

    return _SimulationResult(
        equity_curve=tuple(equity_curve),
        transactions=tuple(transactions),
        warnings=tuple(
            _deduplicate([*warnings, *execution_warnings.messages()])
        ),
    )


def _rebalance(
    target_weights: Mapping[str, float],
    execution_timestamp: datetime,
    current_bars: Mapping[str, PriceBar],
    latest_bars: Mapping[str, PriceBar],
    positions: dict[str, float],
    cash: float,
    assumptions: _ExecutionAssumptions,
    transactions: list[_Transaction],
    warnings: list[str],
    execution_warnings: _ExecutionWarningAccumulator,
) -> float:
    equity = _execution_equity(
        cash,
        positions,
        current_bars,
        latest_bars,
        assumptions.fill_price_field,
    )
    if equity <= 0:
        raise ValueError("Portfolio equity must remain positive.")

    desired_quantities: dict[str, float] = {}
    execution_bars: dict[str, PriceBar] = {}
    for symbol in sorted(set(positions) | set(target_weights)):
        bar = current_bars.get(symbol)
        if bar is None and assumptions.fill_price_field == "close":
            bar = latest_bars.get(symbol)
            if bar is not None:
                execution_warnings.record(
                    "stale_close",
                    symbol,
                    execution_timestamp,
                )
        if bar is None:
            if abs(positions.get(symbol, 0.0)) > 1e-12 or abs(
                target_weights.get(symbol, 0.0)
            ) > 1e-12:
                execution_warnings.record(
                    "missing_current_bar",
                    symbol,
                    execution_timestamp,
                )
            continue
        execution_bars[symbol] = bar
        reference_price = float(getattr(bar, assumptions.fill_price_field))
        desired_quantities[symbol] = (
            equity * float(target_weights.get(symbol, 0.0)) / reference_price
        )

    orders = [
        (symbol, desired - positions.get(symbol, 0.0))
        for symbol, desired in desired_quantities.items()
        if abs(desired - positions.get(symbol, 0.0)) > 1e-12
    ]
    orders.sort(key=lambda item: (item[1] >= 0.0, item[0]))

    commission_rate = assumptions.commission_bps / 10_000.0
    slippage_rate = assumptions.slippage_bps / 10_000.0
    requested_long_gross = sum(
        max(float(weight), 0.0) for weight in target_weights.values()
    )
    for symbol, requested_delta in orders:
        bar = execution_bars[symbol]
        reference_price = float(getattr(bar, assumptions.fill_price_field))
        delta = requested_delta
        if delta > 0:
            per_share_cash = reference_price * (
                1.0 + slippage_rate + commission_rate
            )
            affordable = max(cash, 0.0) / per_share_cash
            if delta > affordable:
                delta = affordable
                if requested_long_gross > 1.0 + 1e-9:
                    warnings.append(
                        f"Buy for {symbol} was cash-capped after costs."
                    )
        if abs(delta) <= 1e-12:
            continue

        execution_price = reference_price * (
            1.0 + slippage_rate if delta > 0 else 1.0 - slippage_rate
        )
        quantity = abs(delta)
        reference_notional = quantity * reference_price
        commission = reference_notional * commission_rate
        slippage_cost = quantity * abs(execution_price - reference_price)

        cash -= delta * execution_price
        cash -= commission
        updated_quantity = positions.get(symbol, 0.0) + delta
        if abs(updated_quantity) <= 1e-12:
            positions.pop(symbol, None)
        else:
            positions[symbol] = updated_quantity
        transactions.append(
            _Transaction(
                symbol=symbol,
                execution_timestamp=execution_timestamp,
                reference_notional=reference_notional,
                commission=commission,
                slippage_cost=slippage_cost,
            )
        )
    return cash


def _execution_equity(
    cash: float,
    positions: Mapping[str, float],
    current_bars: Mapping[str, PriceBar],
    latest_bars: Mapping[str, PriceBar],
    fill_price_field: str,
) -> float:
    total = cash
    for symbol, quantity in positions.items():
        current = current_bars.get(symbol)
        if current is not None:
            price = float(getattr(current, fill_price_field))
        else:
            latest = latest_bars.get(symbol)
            if latest is None:
                raise ValueError(f"No valuation price is available for {symbol}.")
            price = latest.close
        total += quantity * price
    return total


def _validate_target_weights(
    target: Mapping[str, float],
    known_symbols: set[str],
    assumptions: _ExecutionAssumptions,
) -> dict[str, float]:
    if not isinstance(target, Mapping):
        raise ValueError(
            "Strategy target_weights must return a mapping or None."
        )

    normalized: dict[str, float] = {}
    for raw_symbol, raw_weight in target.items():
        symbol = str(raw_symbol).strip()
        if not symbol:
            raise ValueError("Strategy target symbols must be non-empty.")
        if symbol in normalized:
            raise ValueError(
                f"Strategy target contains duplicate normalized symbol '{symbol}'."
            )
        if symbol not in known_symbols:
            raise ValueError(f"Strategy targeted unknown symbol '{symbol}'.")
        weight = _finite_number(raw_weight, f"weight[{symbol}]")
        if not assumptions.allow_short and weight < 0:
            raise ValueError(
                f"Negative weight for {symbol} violates the mandate's "
                "short-selling constraint."
            )
        if abs(weight) > 1e-12:
            normalized[symbol] = weight

    gross_leverage = sum(abs(weight) for weight in normalized.values())
    if gross_leverage > assumptions.max_gross_leverage + 1e-9:
        raise ValueError(
            f"Target gross leverage {gross_leverage:.6f} exceeds the "
            f"mandate maximum {assumptions.max_gross_leverage:.6f}."
        )
    return normalized


def _equity(
    cash: float, positions: Mapping[str, float], prices: Mapping[str, PriceBar]
) -> float:
    total = cash
    for symbol, quantity in positions.items():
        bar = prices.get(symbol)
        if bar is not None:
            total += quantity * bar.close
    return total


def _compute_metrics(
    equity_curve: Sequence[tuple[datetime, float]],
    transactions: Sequence[_Transaction],
    assumptions: _ExecutionAssumptions,
) -> dict[str, float | int | None]:
    if len(equity_curve) < 2 or equity_curve[0][1] <= 0:
        transaction_costs = sum(
            item.commission + item.slippage_cost for item in transactions
        )
        turnover = sum(
            item.reference_notional for item in transactions
        ) / assumptions.initial_capital
        return {
            "transaction_count": len(transactions),
            "transaction_costs": transaction_costs,
            "turnover": turnover,
        }

    values = [value for _, value in equity_curve]
    start, end = values[0], values[-1]
    total_return = end / start - 1.0
    periods = len(equity_curve) - 1
    annualized_return = (
        (end / start) ** (assumptions.annualization_factor / periods) - 1.0
        if end > 0
        else -1.0
    )

    peak = start
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)

    returns = [
        values[index] / values[index - 1] - 1.0
        for index in range(1, len(values))
        if values[index - 1] > 0
    ]
    annualized_volatility: float | None = None
    sharpe_ratio: float | None = None
    if len(returns) >= 2:
        mean = sum(returns) / len(returns)
        variance = sum((item - mean) ** 2 for item in returns) / (
            len(returns) - 1
        )
        period_std = sqrt(variance)
        annualized_volatility = period_std * sqrt(
            assumptions.annualization_factor
        )
        if period_std > 0:
            sharpe_ratio = (
                mean / period_std * sqrt(assumptions.annualization_factor)
            )

    transaction_costs = sum(
        item.commission + item.slippage_cost for item in transactions
    )
    turnover = sum(item.reference_notional for item in transactions) / (
        assumptions.initial_capital
    )
    return {
        "total_return": total_return,
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
        "annualized_volatility": annualized_volatility,
        "sharpe_ratio": sharpe_ratio,
        "transaction_count": len(transactions),
        "transaction_costs": transaction_costs,
        "turnover": turnover,
    }


def _out_of_sample_metrics(
    request: BacktestRequest,
    simulation: _SimulationResult,
    assumptions: _ExecutionAssumptions,
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
        for point in simulation.equity_curve
        if split.test_start_date <= point[0].date() <= split.test_end_date
    ]
    transactions = [
        item
        for item in simulation.transactions
        if split.test_start_date
        <= item.execution_timestamp.date()
        <= split.test_end_date
    ]
    if len(points) < 2:
        return {}
    return _compute_metrics(points, transactions, assumptions)


def _benchmark_metrics(
    request: BacktestRequest,
    bars: Sequence[PriceBar],
    assumptions: _ExecutionAssumptions,
) -> tuple[dict[str, float | int | None], tuple[str, ...]]:
    benchmark = request.plan.benchmark
    if not benchmark:
        return {}, ()

    benchmark_bars = sorted(
        (bar for bar in bars if bar.symbol.casefold() == benchmark.casefold()),
        key=lambda item: item.timestamp,
    )
    if len(benchmark_bars) < 2:
        return {}, (
            f"Benchmark '{benchmark}' was requested but fewer than two bars "
            "were resolved for it.",
        )

    first = benchmark_bars[0]
    last = benchmark_bars[-1]
    reference_price = float(getattr(first, assumptions.fill_price_field))
    commission_rate = assumptions.commission_bps / 10_000.0
    slippage_rate = assumptions.slippage_bps / 10_000.0
    entry_price = reference_price * (1.0 + slippage_rate)
    per_share_cash = entry_price + reference_price * commission_rate
    quantity = assumptions.initial_capital / per_share_cash
    entry_commission = quantity * reference_price * commission_rate
    cash = assumptions.initial_capital - quantity * entry_price - entry_commission
    transactions = [
        _Transaction(
            symbol=benchmark,
            execution_timestamp=first.timestamp,
            reference_notional=quantity * reference_price,
            commission=entry_commission,
            slippage_cost=quantity * (entry_price - reference_price),
        )
    ]

    curve: list[tuple[datetime, float]] = [
        (first.timestamp, assumptions.initial_capital)
    ]
    curve.extend(
        (bar.timestamp, cash + quantity * bar.close)
        for bar in benchmark_bars[1:]
    )

    if assumptions.liquidate_at_end:
        exit_reference = last.close
        exit_price = exit_reference * (1.0 - slippage_rate)
        exit_commission = quantity * exit_reference * commission_rate
        cash += quantity * exit_price - exit_commission
        transactions.append(
            _Transaction(
                symbol=benchmark,
                execution_timestamp=last.timestamp,
                reference_notional=quantity * exit_reference,
                commission=exit_commission,
                slippage_cost=quantity * (exit_reference - exit_price),
            )
        )
        curve[-1] = (last.timestamp, cash)

    return _compute_metrics(curve, transactions, assumptions), ()


def _requested_metric_warnings(
    request: BacktestRequest,
    metrics: Mapping[str, float | int | None],
) -> tuple[str, ...]:
    requested = set(request.plan.requested_metrics)
    unsupported = sorted(requested - set(metrics))
    unavailable = sorted(
        name for name in requested.intersection(metrics) if metrics[name] is None
    )
    warnings: list[str] = []
    if unsupported:
        warnings.append(
            "Unsupported requested metrics were not computed: "
            + ", ".join(unsupported)
            + "."
        )
    if unavailable:
        warnings.append(
            "Requested metrics were unavailable for this run: "
            + ", ".join(unavailable)
            + "."
        )
    return tuple(warnings)


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
        canonical_universe_id=request.execution_context.canonical_universe_id,
        evaluation_policy_id=request.execution_context.evaluation_policy_id,
        resolved_symbols=sorted({bar.symbol for bar in bars}),
        data_references=list(data_references),
        requested_start_date=request.plan.requested_start_date,
        requested_end_date=request.plan.requested_end_date,
        resolved_start_time=bars[0].timestamp if bars else None,
        resolved_end_time=bars[-1].timestamp if bars else None,
        benchmark=request.plan.benchmark,
        status=result.status,
        metrics=dict(result.metrics),
        out_of_sample_metrics=dict(result.out_of_sample_metrics),
        benchmark_metrics=dict(result.benchmark_metrics),
        warnings=list(result.warnings),
        constraint_violations=list(result.constraint_violations),
        artifact_references=list(result.artifact_references),
        failure_reason=result.failure_reason,
    )
    return result.model_copy(update={"ledger_entry": entry})


def _finite_number(
    value: Any,
    name: str,
    *,
    minimum: float | None = None,
    strictly_greater: bool = False,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(float(value))
    ):
        raise ValueError(f"{name} must be a finite number.")
    number = float(value)
    if minimum is not None and (
        number <= minimum if strictly_greater else number < minimum
    ):
        comparator = "greater than" if strictly_greater else "at least"
        raise ValueError(f"{name} must be {comparator} {minimum}.")
    return number


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean.")
    return value


def _deduplicate(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
