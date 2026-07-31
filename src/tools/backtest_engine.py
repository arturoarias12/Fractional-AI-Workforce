"""Strategy-agnostic deterministic Backtest Engine.

The engine is shared infrastructure for every trader. It does not generate a
strategy, execute free-form model text, select market data, or depend on
LangGraph. Instead, it:

1. resolves immutable data references through an injected adapter;
2. selects an explicitly registered deterministic strategy executor;
3. exposes only point-in-time history to that executor;
4. applies common portfolio, cost, slippage, and timing assumptions; and
5. returns the project-wide structured ``BacktestResult``.

Strategy implementations are plugins. Mean reversion may be registered as one
plugin, but no strategy family is built into or selected by this engine.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from math import isfinite, sqrt
from statistics import fmean, stdev
from typing import Any, Protocol, runtime_checkable

from protocols import (
    BacktestRequest,
    BacktestResult,
    BacktestStatus,
)


ENGINE_NAME = "fractional_ai_workforce_backtest_engine"
ENGINE_VERSION = "0.3.0"
DEFAULT_AVAILABLE_FIELDS = (
    "symbol",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
)


class BacktestEngineError(Exception):
    """Base error normalized into a structured BacktestResult."""


class BacktestConfigurationError(BacktestEngineError):
    """The request or engine configuration cannot be executed safely."""


class BacktestDataError(BacktestEngineError):
    """Resolved data is absent, inconsistent, or not point-in-time safe."""


class BacktestExecutionError(BacktestEngineError):
    """A registered deterministic strategy or simulation failed."""


@dataclass(frozen=True, slots=True)
class PriceBar:
    """One validated market observation supplied by the Data Service adapter."""

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
        if (
            self.timestamp.tzinfo is None
            or self.timestamp.utcoffset() is None
        ):
            raise ValueError("PriceBar.timestamp must be timezone-aware.")
        prices = {
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
        }
        for name, value in prices.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(float(value))
                or value <= 0
            ):
                raise ValueError(f"PriceBar.{name} must be finite and positive.")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("PriceBar.low is inconsistent with OHLC values.")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("PriceBar.high is inconsistent with OHLC values.")
        if self.volume is not None and (
            isinstance(self.volume, bool)
            or not isinstance(self.volume, (int, float))
            or not isfinite(float(self.volume))
            or self.volume < 0
        ):
            raise ValueError("PriceBar.volume must be finite and non-negative.")


@dataclass(frozen=True, slots=True)
class ResolvedBacktestData:
    """Point-in-time bars resolved from the request's immutable references."""

    data_references: tuple[str, ...]
    bars: tuple[PriceBar, ...]
    point_in_time_verified: bool
    available_fields: tuple[str, ...] = DEFAULT_AVAILABLE_FIELDS
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.data_references:
            raise ValueError("ResolvedBacktestData requires data references.")
        if not self.bars:
            raise ValueError("ResolvedBacktestData requires at least one bar.")
        seen: set[tuple[str, datetime]] = set()
        for bar in self.bars:
            key = (bar.symbol, bar.timestamp)
            if key in seen:
                raise ValueError(
                    f"Duplicate bar for {bar.symbol} at {bar.timestamp.isoformat()}."
                )
            seen.add(key)


@dataclass(frozen=True, slots=True)
class StrategyEvaluationContext:
    """Point-in-time context passed to one deterministic strategy session."""

    timestamp: datetime
    current_bars: Mapping[str, PriceBar]
    history: Mapping[str, tuple[PriceBar, ...]]
    positions: Mapping[str, float]
    cash: float
    equity: float
    parameters: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Transaction:
    symbol: str
    signal_timestamp: datetime
    execution_timestamp: datetime
    side: str
    quantity: float
    reference_price: float
    execution_price: float
    notional: float
    commission: float
    slippage_cost: float


@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp: datetime
    value: float


@dataclass(frozen=True, slots=True)
class BacktestArtifacts:
    """Detailed deterministic output available to an optional artifact sink."""

    equity_curve: tuple[EquityPoint, ...]
    transactions: tuple[Transaction, ...]
    executor_id: str
    applied_assumptions: Mapping[str, Any]
    data_references: tuple[str, ...]


@runtime_checkable
class BacktestDataResolver(Protocol):
    """Resolve Data Service references without hard-coded files or providers."""

    async def resolve(self, request: BacktestRequest) -> ResolvedBacktestData:
        """Return validated bars corresponding to request.data_references."""


@runtime_checkable
class StrategySession(Protocol):
    """One isolated, deterministic strategy instance for a single request."""

    def target_weights(
        self,
        context: StrategyEvaluationContext,
    ) -> Mapping[str, float] | None:
        """Return desired portfolio weights, or None to keep current positions."""


@runtime_checkable
class StrategyExecutor(Protocol):
    """Factory for deterministic, audited strategy sessions."""

    executor_id: str

    def create_session(self, request: BacktestRequest) -> StrategySession:
        """Create request-local state so concurrent runs cannot interfere."""


@runtime_checkable
class BacktestArtifactSink(Protocol):
    """Persist detailed output without coupling the engine to storage."""

    async def save(
        self,
        request: BacktestRequest,
        artifacts: BacktestArtifacts,
    ) -> Sequence[str]:
        """Return immutable artifact references."""


@runtime_checkable
class BacktestEngine(Protocol):
    """Execute every trader candidate under common coded assumptions."""

    async def run(self, request: BacktestRequest) -> BacktestResult:
        """Return reproducible metrics; an LLM may not manufacture them."""


@dataclass(frozen=True, slots=True)
class FunctionalStrategyExecutor:
    """Small adapter for registering a strategy-session factory."""

    executor_id: str
    session_factory: Callable[[BacktestRequest], StrategySession]

    def __post_init__(self) -> None:
        if not self.executor_id.strip():
            raise ValueError("executor_id must be non-empty.")

    def create_session(self, request: BacktestRequest) -> StrategySession:
        return self.session_factory(request)


@dataclass(frozen=True, slots=True)
class ExecutionAssumptions:
    """Common simulation assumptions, explicit in every result."""

    initial_capital: float = 100_000.0
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    fill_price_field: str = "open"
    signal_delay_bars: int = 1
    liquidate_at_end: bool = True
    allow_short: bool = False
    max_gross_leverage: float = 1.0
    annualization_factor: int = 252
    annual_risk_free_rate: float = 0.0

    @classmethod
    def from_request(cls, request: BacktestRequest) -> "ExecutionAssumptions":
        defaults = cls()
        raw = request.plan.transaction_cost_assumptions
        constraints = request.mandate_constraints
        frequency = request.plan.frequency.casefold().replace("-", "_")
        default_annualization = {
            "daily": 252,
            "1d": 252,
            "weekly": 52,
            "1w": 52,
            "monthly": 12,
            "1m": 12,
        }.get(frequency, 252)

        assumptions = cls(
            initial_capital=_finite_number(
                raw.get("initial_capital", defaults.initial_capital),
                "initial_capital",
                minimum=0.0,
                strictly_greater=True,
            ),
            commission_bps=_finite_number(
                raw.get(
                    "commission_bps",
                    raw.get(
                        "transaction_cost_bps",
                        defaults.commission_bps,
                    ),
                ),
                "commission_bps",
                minimum=0.0,
            ),
            slippage_bps=_finite_number(
                raw.get("slippage_bps", defaults.slippage_bps),
                "slippage_bps",
                minimum=0.0,
            ),
            fill_price_field=str(
                raw.get("fill_price_field", defaults.fill_price_field)
            ).casefold(),
            signal_delay_bars=_positive_integer(
                raw.get("signal_delay_bars", defaults.signal_delay_bars),
                "signal_delay_bars",
            ),
            liquidate_at_end=_boolean(
                raw.get("liquidate_at_end", defaults.liquidate_at_end),
                "liquidate_at_end",
            ),
            allow_short=_boolean(
                constraints.get(
                    "allow_short",
                    raw.get("allow_short", defaults.allow_short),
                ),
                "allow_short",
            ),
            max_gross_leverage=_finite_number(
                constraints.get(
                    "max_gross_leverage",
                    raw.get(
                        "max_gross_leverage",
                        defaults.max_gross_leverage,
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
            annual_risk_free_rate=_finite_number(
                raw.get(
                    "annual_risk_free_rate",
                    defaults.annual_risk_free_rate,
                ),
                "annual_risk_free_rate",
            ),
        )
        if assumptions.fill_price_field not in {"open", "close"}:
            raise BacktestConfigurationError(
                "fill_price_field must be 'open' or 'close'."
            )
        if assumptions.signal_delay_bars < 1:
            raise BacktestConfigurationError(
                "signal_delay_bars must be at least 1 to prevent same-bar "
                "look-ahead execution."
            )
        return assumptions


class DeterministicBacktestEngine:
    """Shared engine with injected data, strategy, and artifact adapters."""

    def __init__(
        self,
        *,
        data_resolver: BacktestDataResolver,
        strategy_executors: Iterable[StrategyExecutor],
        artifact_sink: BacktestArtifactSink | None = None,
        engine_name: str = ENGINE_NAME,
        engine_version: str = ENGINE_VERSION,
    ) -> None:
        if not engine_name.strip() or not engine_version.strip():
            raise ValueError("engine_name and engine_version must be non-empty.")
        registry: dict[str, StrategyExecutor] = {}
        for executor in strategy_executors:
            executor_id = executor.executor_id.strip()
            if not executor_id:
                raise ValueError("Strategy executor IDs must be non-empty.")
            if executor_id in registry:
                raise ValueError(
                    f"Duplicate strategy executor ID: {executor_id}."
                )
            registry[executor_id] = executor
        self._data_resolver = data_resolver
        self._strategy_executors = registry
        self._artifact_sink = artifact_sink
        self._engine_name = engine_name.strip()
        self._engine_version = engine_version.strip()

    @property
    def registered_executor_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._strategy_executors))

    async def run(self, request: BacktestRequest) -> BacktestResult:
        warnings: list[str] = []
        try:
            self._validate_request(request)
            executor_id = self._executor_id(request)
            executor = self._strategy_executors.get(executor_id)
            if executor is None:
                raise BacktestConfigurationError(
                    f"Strategy executor '{executor_id}' is not registered. "
                    "Available executors: "
                    + (
                        ", ".join(self.registered_executor_ids)
                        if self._strategy_executors
                        else "none"
                    )
                    + "."
                )

            assumptions = ExecutionAssumptions.from_request(request)
            resolved = await self._data_resolver.resolve(request)
            bars, data_warnings = self._prepare_data(request, resolved)
            warnings.extend(data_warnings)
            session = executor.create_session(request)
            simulation = self._simulate(
                request=request,
                bars=bars,
                session=session,
                assumptions=assumptions,
            )
            warnings.extend(simulation.warnings)

            metrics = _compute_metrics(
                simulation.equity_curve,
                simulation.transactions,
                assumptions,
            )
            out_of_sample_metrics, evaluation_warnings = (
                self._out_of_sample_metrics(
                    request=request,
                    simulation=simulation,
                    assumptions=assumptions,
                )
            )
            warnings.extend(evaluation_warnings)
            benchmark_metrics, benchmark_warnings = self._benchmark_metrics(
                request=request,
                bars=bars,
                assumptions=assumptions,
            )
            warnings.extend(benchmark_warnings)
            warnings.extend(
                self._unsupported_metric_warnings(request, metrics)
            )

            artifact_references: tuple[str, ...] = ()
            if self._artifact_sink is not None:
                artifacts = BacktestArtifacts(
                    equity_curve=simulation.equity_curve,
                    transactions=simulation.transactions,
                    executor_id=executor_id,
                    applied_assumptions=asdict(assumptions),
                    data_references=resolved.data_references,
                )
                try:
                    artifact_references = tuple(
                        await self._artifact_sink.save(request, artifacts)
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    warnings.append(
                        "Artifact persistence failed without invalidating "
                        f"computed metrics: {type(exc).__name__}: {exc}"
                    )

            return BacktestResult(
                result_id=f"{request.request_id}.result",
                request_id=request.request_id,
                candidate_id=request.candidate.candidate_id,
                status=BacktestStatus.SUCCEEDED,
                engine_name=self._engine_name,
                engine_version=self._engine_version,
                metrics=metrics,
                out_of_sample_metrics=out_of_sample_metrics,
                benchmark_metrics=benchmark_metrics,
                warnings=tuple(_deduplicate(warnings)),
                artifact_references=artifact_references,
                additional_fields={
                    "executor_id": executor_id,
                    "applied_assumptions": asdict(assumptions),
                    "data_references": resolved.data_references,
                    "bar_count": len(bars),
                    "symbols": tuple(sorted({bar.symbol for bar in bars})),
                    "transaction_count": len(simulation.transactions),
                },
            )
        except asyncio.CancelledError:
            raise
        except BacktestDataError as exc:
            return self._failure_result(
                request,
                BacktestStatus.INSUFFICIENT_DATA,
                str(exc),
                warnings,
            )
        except Exception as exc:
            return self._failure_result(
                request,
                BacktestStatus.FAILED,
                f"{type(exc).__name__}: {exc}",
                warnings,
            )

    def _failure_result(
        self,
        request: BacktestRequest,
        status: BacktestStatus,
        reason: str,
        warnings: Sequence[str],
    ) -> BacktestResult:
        candidate_id = getattr(
            getattr(request, "candidate", None),
            "candidate_id",
            "unknown_candidate",
        )
        request_id = getattr(request, "request_id", "unknown_request")
        return BacktestResult(
            result_id=f"{request_id}.result",
            request_id=request_id,
            candidate_id=candidate_id,
            status=status,
            engine_name=self._engine_name,
            engine_version=self._engine_version,
            warnings=tuple(_deduplicate(warnings)),
            failure_reason=reason or type(reason).__name__,
        )

    @staticmethod
    def _validate_request(request: BacktestRequest) -> None:
        if not isinstance(request, BacktestRequest):
            raise BacktestConfigurationError(
                "DeterministicBacktestEngine requires a BacktestRequest."
            )
        if not request.request_id.strip():
            raise BacktestConfigurationError(
                "BacktestRequest.request_id must be non-empty."
            )
        if not request.candidate.candidate_id.strip():
            raise BacktestConfigurationError(
                "CandidateRuleSpecification.candidate_id must be non-empty."
            )
        if request.plan.requested_start_date and request.plan.requested_end_date:
            if (
                request.plan.requested_start_date
                > request.plan.requested_end_date
            ):
                raise BacktestConfigurationError(
                    "requested_start_date must not exceed requested_end_date."
                )
        if (
            request.plan.requested_end_date
            and request.plan.requested_end_date > request.as_of_date
        ):
            raise BacktestConfigurationError(
                "Backtest end date cannot exceed the request as-of date."
            )
        if not request.data_references:
            raise BacktestConfigurationError(
                "BacktestRequest.data_references must not be empty."
            )

    @staticmethod
    def _executor_id(request: BacktestRequest) -> str:
        return request.executor_id.strip()

    @staticmethod
    def _prepare_data(
        request: BacktestRequest,
        resolved: ResolvedBacktestData,
    ) -> tuple[tuple[PriceBar, ...], tuple[str, ...]]:
        if not isinstance(resolved, ResolvedBacktestData):
            raise BacktestDataError(
                "Data resolver returned an invalid result type."
            )
        if not resolved.point_in_time_verified:
            raise BacktestDataError(
                "Resolved data is not verified as point-in-time."
            )
        missing_references = sorted(
            set(request.data_references) - set(resolved.data_references)
        )
        if missing_references:
            raise BacktestDataError(
                "Resolved data omitted request references: "
                + ", ".join(missing_references)
            )
        available = {field.casefold() for field in resolved.available_fields}
        missing_fields = sorted(
            field_name
            for field_name in request.candidate.required_data_fields
            if field_name.casefold() not in available
        )
        if missing_fields:
            raise BacktestDataError(
                "Required fields are unavailable: " + ", ".join(missing_fields)
            )

        start = request.plan.requested_start_date
        end = request.plan.requested_end_date or request.as_of_date
        bars = tuple(
            sorted(
                (
                    bar
                    for bar in resolved.bars
                    if bar.timestamp.date() <= request.as_of_date
                    and (start is None or bar.timestamp.date() >= start)
                    and bar.timestamp.date() <= end
                ),
                key=lambda item: (item.timestamp, item.symbol),
            )
        )
        if not bars:
            raise BacktestDataError(
                "No bars remain after applying the requested date boundaries."
            )
        timeline = {bar.timestamp for bar in bars}
        if len(timeline) < 2:
            raise BacktestDataError(
                "At least two distinct timestamps are required."
            )
        return bars, resolved.warnings

    def _simulate(
        self,
        *,
        request: BacktestRequest,
        bars: tuple[PriceBar, ...],
        session: StrategySession,
        assumptions: ExecutionAssumptions,
    ) -> "_SimulationResult":
        bars_by_timestamp: dict[datetime, dict[str, PriceBar]] = defaultdict(dict)
        for bar in bars:
            bars_by_timestamp[bar.timestamp][bar.symbol] = bar
        timeline = sorted(bars_by_timestamp)

        histories: dict[str, list[PriceBar]] = defaultdict(list)
        latest_bars: dict[str, PriceBar] = {}
        positions: dict[str, float] = {}
        cash = assumptions.initial_capital
        transactions: list[Transaction] = []
        equity_curve: list[EquityPoint] = []
        warnings: list[str] = []
        pending: dict[int, list[tuple[datetime, Mapping[str, float]]]] = (
            defaultdict(list)
        )
        known_symbols = {bar.symbol for bar in bars}

        for index, timestamp in enumerate(timeline):
            current_bars = bars_by_timestamp[timestamp]

            for signal_timestamp, target in pending.pop(index, ()):
                cash = self._rebalance(
                    target_weights=target,
                    signal_timestamp=signal_timestamp,
                    execution_timestamp=timestamp,
                    current_bars=current_bars,
                    latest_bars=latest_bars,
                    positions=positions,
                    cash=cash,
                    assumptions=assumptions,
                    transactions=transactions,
                    warnings=warnings,
                )

            latest_bars.update(current_bars)
            for symbol, bar in current_bars.items():
                histories[symbol].append(bar)

            equity = _portfolio_value(cash, positions, latest_bars, "close")
            context = StrategyEvaluationContext(
                timestamp=timestamp,
                current_bars=dict(current_bars),
                history={
                    symbol: tuple(history)
                    for symbol, history in histories.items()
                },
                positions=dict(positions),
                cash=cash,
                equity=equity,
                parameters=request.candidate.parameters,
            )
            try:
                target = session.target_weights(context)
            except Exception as exc:
                raise BacktestExecutionError(
                    "Strategy executor failed at "
                    f"{timestamp.isoformat()}: {type(exc).__name__}: {exc}"
                ) from exc

            if target is not None:
                normalized = self._validate_target_weights(
                    target,
                    known_symbols,
                    assumptions,
                )
                execution_index = index + assumptions.signal_delay_bars
                if execution_index < len(timeline):
                    pending[execution_index].append((timestamp, normalized))
                elif self._target_requires_rebalance(
                    target_weights=normalized,
                    positions=positions,
                    cash=cash,
                    latest_bars=latest_bars,
                    price_field="close",
                ):
                    warnings.append(
                        "A final strategy signal could not execute because its "
                        "configured delay extended beyond available data."
                    )

            equity_curve.append(EquityPoint(timestamp=timestamp, value=equity))

        if assumptions.liquidate_at_end and positions:
            final_timestamp = timeline[-1]
            liquidation_bars = {
                symbol: latest_bars[symbol] for symbol in positions
            }
            cash = self._rebalance(
                target_weights={},
                signal_timestamp=final_timestamp,
                execution_timestamp=final_timestamp,
                current_bars=liquidation_bars,
                latest_bars=latest_bars,
                positions=positions,
                cash=cash,
                assumptions=ExecutionAssumptions(
                    **{
                        **asdict(assumptions),
                        "fill_price_field": "close",
                    }
                ),
                transactions=transactions,
                warnings=warnings,
            )
            equity_curve[-1] = EquityPoint(
                timestamp=final_timestamp,
                value=_portfolio_value(cash, positions, latest_bars, "close"),
            )

        if not equity_curve:
            raise BacktestDataError("Simulation produced no equity observations.")
        return _SimulationResult(
            equity_curve=tuple(equity_curve),
            transactions=tuple(transactions),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _target_requires_rebalance(
        *,
        target_weights: Mapping[str, float],
        positions: Mapping[str, float],
        cash: float,
        latest_bars: Mapping[str, PriceBar],
        price_field: str,
        tolerance: float = 1e-4,
    ) -> bool:
        equity = _portfolio_value(
            cash,
            positions,
            latest_bars,
            price_field,
        )
        if equity <= 0:
            return True
        symbols = set(target_weights) | set(positions)
        for symbol in symbols:
            bar = latest_bars.get(symbol)
            if bar is None:
                return True
            current_weight = (
                positions.get(symbol, 0.0)
                * float(getattr(bar, price_field))
                / equity
            )
            if (
                abs(current_weight - target_weights.get(symbol, 0.0))
                > tolerance
            ):
                return True
        return False

    @staticmethod
    def _validate_target_weights(
        target: Mapping[str, float],
        known_symbols: set[str],
        assumptions: ExecutionAssumptions,
    ) -> dict[str, float]:
        if not isinstance(target, Mapping):
            raise BacktestExecutionError(
                "Strategy target_weights must return a mapping or None."
            )
        normalized: dict[str, float] = {}
        for raw_symbol, raw_weight in target.items():
            symbol = str(raw_symbol).strip()
            if symbol not in known_symbols:
                raise BacktestExecutionError(
                    f"Strategy targeted unknown symbol '{symbol}'."
                )
            weight = _finite_number(raw_weight, f"weight[{symbol}]")
            if not assumptions.allow_short and weight < 0:
                raise BacktestExecutionError(
                    f"Negative weight for {symbol} violates long-only execution."
                )
            normalized[symbol] = weight
        gross = sum(abs(weight) for weight in normalized.values())
        if gross > assumptions.max_gross_leverage + 1e-9:
            raise BacktestExecutionError(
                f"Target gross leverage {gross:.6f} exceeds "
                f"{assumptions.max_gross_leverage:.6f}."
            )
        return normalized

    @staticmethod
    def _rebalance(
        *,
        target_weights: Mapping[str, float],
        signal_timestamp: datetime,
        execution_timestamp: datetime,
        current_bars: Mapping[str, PriceBar],
        latest_bars: Mapping[str, PriceBar],
        positions: dict[str, float],
        cash: float,
        assumptions: ExecutionAssumptions,
        transactions: list[Transaction],
        warnings: list[str],
    ) -> float:
        fill_field = assumptions.fill_price_field
        equity = _portfolio_value(
            cash,
            positions,
            {**latest_bars, **current_bars},
            fill_field,
        )
        if equity <= 0:
            raise BacktestExecutionError(
                "Portfolio equity must remain positive before rebalancing."
            )

        desired_shares: dict[str, float] = {}
        for symbol in set(positions) | set(target_weights):
            bar = current_bars.get(symbol)
            current_quantity = positions.get(symbol, 0.0)
            weight = target_weights.get(symbol, 0.0)
            if bar is None:
                if abs(weight) > 1e-12 or abs(current_quantity) > 1e-12:
                    warnings.append(
                        f"Rebalance for {symbol} was skipped at "
                        f"{execution_timestamp.isoformat()} because no "
                        "execution bar was available; the existing position "
                        "was preserved."
                    )
                continue
            reference_price = float(getattr(bar, fill_field))
            desired_shares[symbol] = weight * equity / reference_price

        orders: list[tuple[str, float]] = []
        for symbol, desired in desired_shares.items():
            delta = desired - positions.get(symbol, 0.0)
            if abs(delta) > 1e-12:
                orders.append((symbol, delta))
        orders.sort(key=lambda item: item[1])

        commission_rate = assumptions.commission_bps / 10_000.0
        slippage_rate = assumptions.slippage_bps / 10_000.0
        for symbol, requested_delta in orders:
            bar = current_bars[symbol]
            reference_price = float(getattr(bar, fill_field))
            delta = requested_delta
            if delta > 0 and not assumptions.allow_short:
                per_share_cost = reference_price * (
                    1.0 + slippage_rate + commission_rate
                )
                affordable = max(0.0, cash) / per_share_cost
                if delta > affordable:
                    delta = affordable
                    warnings.append(
                        f"Buy for {symbol} was cash-capped after costs."
                    )
            if abs(delta) <= 1e-12:
                continue

            side = "buy" if delta > 0 else "sell"
            execution_price = reference_price * (
                1.0 + slippage_rate if delta > 0 else 1.0 - slippage_rate
            )
            quantity = abs(delta)
            reference_notional = quantity * reference_price
            commission = reference_notional * commission_rate
            slippage_cost = quantity * abs(execution_price - reference_price)
            cash -= delta * execution_price
            cash -= commission
            positions[symbol] = positions.get(symbol, 0.0) + delta
            if abs(positions[symbol]) <= 1e-12:
                positions.pop(symbol, None)
            transactions.append(
                Transaction(
                    symbol=symbol,
                    signal_timestamp=signal_timestamp,
                    execution_timestamp=execution_timestamp,
                    side=side,
                    quantity=quantity,
                    reference_price=reference_price,
                    execution_price=execution_price,
                    notional=reference_notional,
                    commission=commission,
                    slippage_cost=slippage_cost,
                )
            )
        return cash

    @staticmethod
    def _out_of_sample_metrics(
        *,
        request: BacktestRequest,
        simulation: "_SimulationResult",
        assumptions: ExecutionAssumptions,
    ) -> tuple[
        dict[str, float | int | None],
        tuple[str, ...],
    ]:
        split = request.plan.validation_split
        if split is None:
            if request.plan.held_out_evaluation_required:
                raise BacktestConfigurationError(
                    "held_out_evaluation_required is true, but the finalized "
                    "plan contains no validation_split."
                )
            return {}, ()
        test_start = split.test_start_date
        test_end = split.test_end_date
        points = tuple(
            point
            for point in simulation.equity_curve
            if test_start <= point.timestamp.date() <= test_end
        )
        if len(points) < 2:
            return (
                {},
                (
                    "The configured validation window contained fewer than "
                    "two equity observations; in-sample metrics remain valid "
                    "but out-of-sample metrics were not computed.",
                ),
            )
        trades = tuple(
            trade
            for trade in simulation.transactions
            if test_start <= trade.execution_timestamp.date() <= test_end
        )
        return _compute_metrics(points, trades, assumptions), ()

    @staticmethod
    def _benchmark_metrics(
        *,
        request: BacktestRequest,
        bars: tuple[PriceBar, ...],
        assumptions: ExecutionAssumptions,
    ) -> tuple[
        dict[str, float | int | None],
        tuple[str, ...],
    ]:
        benchmark = request.plan.benchmark
        if not benchmark:
            return {}, ()
        benchmark_bars = tuple(
            sorted(
                (bar for bar in bars if bar.symbol == benchmark),
                key=lambda item: item.timestamp,
            )
        )
        if len(benchmark_bars) < 2:
            return (
                {},
                (
                    f"Benchmark '{benchmark}' could not be computed because "
                    "fewer than two benchmark bars were resolved.",
                ),
            )
        first_close = benchmark_bars[0].close
        points = tuple(
            EquityPoint(
                timestamp=bar.timestamp,
                value=assumptions.initial_capital * bar.close / first_close,
            )
            for bar in benchmark_bars
        )
        return _compute_metrics(points, (), assumptions), ()

    @staticmethod
    def _unsupported_metric_warnings(
        request: BacktestRequest,
        metrics: Mapping[str, float | int | None],
    ) -> tuple[str, ...]:
        unsupported = sorted(
            set(request.plan.requested_metrics) - set(metrics)
        )
        if not unsupported:
            return ()
        return (
            "Unsupported requested metrics were not computed: "
            + ", ".join(unsupported),
        )


@dataclass(frozen=True, slots=True)
class _SimulationResult:
    equity_curve: tuple[EquityPoint, ...]
    transactions: tuple[Transaction, ...]
    warnings: tuple[str, ...]


def _portfolio_value(
    cash: float,
    positions: Mapping[str, float],
    bars: Mapping[str, PriceBar],
    price_field: str,
) -> float:
    value = cash
    for symbol, quantity in positions.items():
        bar = bars.get(symbol)
        if bar is None:
            raise BacktestDataError(
                f"No valuation price is available for {symbol}."
            )
        value += quantity * float(getattr(bar, price_field))
    if not isfinite(value):
        raise BacktestExecutionError("Portfolio value became non-finite.")
    return value


def _compute_metrics(
    equity_curve: Sequence[EquityPoint],
    transactions: Sequence[Transaction],
    assumptions: ExecutionAssumptions,
) -> dict[str, float | int | None]:
    values = [point.value for point in equity_curve]
    if len(values) < 2 or values[0] <= 0:
        raise BacktestDataError(
            "At least two positive-baseline equity points are required."
        )
    returns = [
        values[index] / values[index - 1] - 1.0
        for index in range(1, len(values))
        if values[index - 1] != 0
    ]
    total_return = values[-1] / values[0] - 1.0
    running_peak = values[0]
    max_drawdown = 0.0
    for value in values:
        running_peak = max(running_peak, value)
        drawdown = value / running_peak - 1.0
        max_drawdown = min(max_drawdown, drawdown)

    periods = len(values) - 1
    annualized_return = (
        (values[-1] / values[0])
        ** (assumptions.annualization_factor / periods)
        - 1.0
        if values[-1] > 0
        else -1.0
    )
    annualized_volatility: float | None = None
    sharpe_ratio: float | None = None
    if len(returns) >= 2:
        period_stdev = stdev(returns)
        annualized_volatility = period_stdev * sqrt(
            assumptions.annualization_factor
        )
        if period_stdev > 0:
            period_risk_free = (
                assumptions.annual_risk_free_rate
                / assumptions.annualization_factor
            )
            sharpe_ratio = (
                (fmean(returns) - period_risk_free)
                / period_stdev
                * sqrt(assumptions.annualization_factor)
            )

    transaction_costs = sum(
        trade.commission + trade.slippage_cost for trade in transactions
    )
    turnover = (
        sum(trade.notional for trade in transactions)
        / assumptions.initial_capital
    )
    return {
        "initial_equity": round(values[0], 8),
        "final_equity": round(values[-1], 8),
        "total_return": round(total_return, 12),
        "annualized_return": round(annualized_return, 12),
        "max_drawdown": round(max_drawdown, 12),
        "annualized_volatility": (
            round(annualized_volatility, 12)
            if annualized_volatility is not None
            else None
        ),
        "sharpe_ratio": (
            round(sharpe_ratio, 12)
            if sharpe_ratio is not None
            else None
        ),
        "transaction_count": len(transactions),
        "transaction_costs": round(transaction_costs, 8),
        "turnover": round(turnover, 12),
    }


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
        raise BacktestConfigurationError(f"{name} must be a finite number.")
    number = float(value)
    if minimum is not None and (
        number <= minimum if strictly_greater else number < minimum
    ):
        comparator = "greater than" if strictly_greater else "at least"
        raise BacktestConfigurationError(
            f"{name} must be {comparator} {minimum}."
        )
    return number


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BacktestConfigurationError(
            f"{name} must be a positive integer."
        )
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise BacktestConfigurationError(f"{name} must be a boolean.")
    return value


def _deduplicate(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
