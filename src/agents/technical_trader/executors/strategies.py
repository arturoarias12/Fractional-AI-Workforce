"""Deterministic strategy executors owned by the Technical Trader."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

from protocols import BacktestRequest

if TYPE_CHECKING:
    from tools import StrategyEvaluationContext

from .catalog import (
    BENCHMARK_FALLBACK_EXECUTOR_ID,
    HEAD_PATTERN_EXECUTOR_ID,
    HORIZON_ADAPTIVE_TREND_EXECUTOR_ID,
    INVERSE_PATTERN_EXECUTOR_ID,
    MOVING_AVERAGE_TREND_EXECUTOR_ID,
    MULTI_ASSET_PORTFOLIO_EXECUTOR_ID,
    RESISTANCE_BREAKOUT_EXECUTOR_ID,
    ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID,
    ROLLING_SUPPORT_REACTION_EXECUTOR_ID,
    ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID,
    SUPPORT_REACTION_EXECUTOR_ID,
    TARGET_PORTFOLIO_ASSET_COUNT,
    VOLUME_BREAKOUT_EXECUTOR_ID,
)
from .common import (
    ExecutionSettings,
    RiskManagedParameters,
    VolatilityManagedSession,
    number,
    positive_integer,
    symbol as parsed_symbol,
)


@dataclass(frozen=True, slots=True)
class LevelParameters:
    risk: RiskManagedParameters
    anchor_level: float
    entry_buffer_percent: float
    support_entry_floor_buffer_percent: float
    technical_invalidation_buffer_percent: float

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any],
        *,
        support: bool,
    ) -> "LevelParameters":
        return cls(
            risk=RiskManagedParameters.from_mapping(values),
            anchor_level=number(values, "anchor_level", minimum=1e-12),
            entry_buffer_percent=number(
                values,
                "entry_buffer_percent",
                minimum=0.0,
                maximum=0.25,
            ),
            support_entry_floor_buffer_percent=(
                number(
                    values,
                    "support_entry_floor_buffer_percent",
                    minimum=0.0,
                    maximum=0.25,
                )
                if support
                else 0.0
            ),
            technical_invalidation_buffer_percent=number(
                values,
                "technical_invalidation_buffer_percent",
                minimum=0.0,
                maximum=0.25,
            ),
        )


class LevelSession(VolatilityManagedSession):
    def __init__(
        self,
        parameters: LevelParameters,
        settings: ExecutionSettings,
        *,
        support: bool,
    ) -> None:
        super().__init__(parameters.risk, settings)
        self.parameters = parameters
        self.support = support
        self.entry_armed = True

    def target_weights(
        self,
        context: StrategyEvaluationContext,
    ) -> Mapping[str, float] | None:
        bar = context.current_bars.get(self.risk.symbol)
        if bar is None:
            return None
        history = context.history.get(self.risk.symbol, ())
        invested = self.observe_position(bar, context.positions)
        close = float(bar.close)
        anchor = self.parameters.anchor_level

        if self.support:
            entry_ceiling = anchor * (
                1.0 + self.parameters.entry_buffer_percent
            )
            entry_floor = anchor * (
                1.0
                - self.parameters.support_entry_floor_buffer_percent
            )
            invalidation = anchor * (
                1.0
                - self.parameters.technical_invalidation_buffer_percent
            )
            in_entry_zone = entry_floor <= close <= entry_ceiling
            if invested:
                return (
                    {}
                    if self.exit_required(
                        close=close,
                        technical_invalidation=invalidation,
                    )
                    else None
                )
            if not self.entry_armed:
                if not in_entry_zone:
                    self.entry_armed = True
                return None
            if in_entry_zone:
                target = self.prepare_entry(history)
                if target is not None:
                    self.entry_armed = False
                return target
            return None

        breakout = anchor * (1.0 + self.parameters.entry_buffer_percent)
        invalidation = anchor * (
            1.0 - self.parameters.technical_invalidation_buffer_percent
        )
        if invested:
            return (
                {}
                if self.exit_required(
                    close=close,
                    technical_invalidation=invalidation,
                )
                else None
            )
        if not self.entry_armed:
            if close < breakout:
                self.entry_armed = True
            return None
        previous_close = history[-2].close if len(history) >= 2 else None
        if previous_close is not None and previous_close < breakout <= close:
            target = self.prepare_entry(history)
            if target is not None:
                self.entry_armed = False
            return target
        return None


class SupportReactionExecutor:
    executor_id = SUPPORT_REACTION_EXECUTOR_ID

    def create_session(self, request: BacktestRequest) -> LevelSession:
        return LevelSession(
            LevelParameters.from_mapping(
                request.candidate.parameters,
                support=True,
            ),
            ExecutionSettings.from_request(request),
            support=True,
        )


class ResistanceBreakoutExecutor:
    executor_id = RESISTANCE_BREAKOUT_EXECUTOR_ID

    def create_session(self, request: BacktestRequest) -> LevelSession:
        return LevelSession(
            LevelParameters.from_mapping(
                request.candidate.parameters,
                support=False,
            ),
            ExecutionSettings.from_request(request),
            support=False,
        )


@dataclass(frozen=True, slots=True)
class MovingAverageParameters:
    risk: RiskManagedParameters
    fast_window: int
    slow_window: int

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any],
    ) -> "MovingAverageParameters":
        fast_window = positive_integer(
            values, "fast_window", minimum=2, maximum=252
        )
        slow_window = positive_integer(
            values, "slow_window", minimum=3, maximum=504
        )
        if fast_window >= slow_window:
            raise ValueError("fast_window must be below slow_window.")
        return cls(
            risk=RiskManagedParameters.from_mapping(values),
            fast_window=fast_window,
            slow_window=slow_window,
        )


class MovingAverageTrendSession(VolatilityManagedSession):
    def __init__(
        self,
        parameters: MovingAverageParameters,
        settings: ExecutionSettings,
    ) -> None:
        super().__init__(parameters.risk, settings)
        self.parameters = parameters

    def _averages(self, history: Any, *, previous: bool) -> tuple[float, float] | None:
        bars = history[:-1] if previous else history
        if len(bars) < self.parameters.slow_window:
            return None
        closes = [float(bar.close) for bar in bars]
        fast = sum(closes[-self.parameters.fast_window :]) / (
            self.parameters.fast_window
        )
        slow = sum(closes[-self.parameters.slow_window :]) / (
            self.parameters.slow_window
        )
        return fast, slow

    def target_weights(
        self,
        context: StrategyEvaluationContext,
    ) -> Mapping[str, float] | None:
        bar = context.current_bars.get(self.risk.symbol)
        if bar is None:
            return None
        history = context.history.get(self.risk.symbol, ())
        current = self._averages(history, previous=False)
        if current is None:
            return None
        invested = self.observe_position(bar, context.positions)
        fast, slow = current
        close = float(bar.close)
        if invested:
            if fast <= slow or self.exit_required(
                close=close,
                technical_invalidation=slow,
            ):
                return {}
            return None
        previous = self._averages(history, previous=True)
        if previous is None:
            return None
        previous_fast, previous_slow = previous
        if previous_fast <= previous_slow and fast > slow:
            return self.prepare_entry(history)
        return None


class MovingAverageTrendExecutor:
    executor_id = MOVING_AVERAGE_TREND_EXECUTOR_ID

    def create_session(self, request: BacktestRequest) -> MovingAverageTrendSession:
        return MovingAverageTrendSession(
            MovingAverageParameters.from_mapping(request.candidate.parameters),
            ExecutionSettings.from_request(request),
        )


@dataclass(frozen=True, slots=True)
class HorizonAdaptiveTrendParameters:
    moving_average: MovingAverageParameters
    review_interval_bars: int

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any],
    ) -> "HorizonAdaptiveTrendParameters":
        return cls(
            moving_average=MovingAverageParameters.from_mapping(values),
            review_interval_bars=positive_integer(
                values,
                "review_interval_bars",
                maximum=252,
            ),
        )


class HorizonAdaptiveTrendSession(MovingAverageTrendSession):
    """Recalculate trend state from past bars at the horizon cadence."""

    def __init__(
        self,
        parameters: HorizonAdaptiveTrendParameters,
        settings: ExecutionSettings,
    ) -> None:
        super().__init__(parameters.moving_average, settings)
        self.adaptive_parameters = parameters
        self._last_review_history_count: int | None = None

    def _review_due(self, history_count: int) -> bool:
        previous = self._last_review_history_count
        if previous is None:
            self._last_review_history_count = history_count
            return True
        if history_count - previous < self.adaptive_parameters.review_interval_bars:
            return False
        self._last_review_history_count = history_count
        return True

    def target_weights(
        self,
        context: StrategyEvaluationContext,
    ) -> Mapping[str, float] | None:
        bar = context.current_bars.get(self.risk.symbol)
        if bar is None:
            return None
        history = context.history.get(self.risk.symbol, ())
        current = self._averages(history, previous=False)
        if current is None:
            return None
        invested = self.observe_position(bar, context.positions)
        fast, slow = current
        close = float(bar.close)
        if invested:
            if fast <= slow or close <= slow or self.exit_required(
                close=close,
                technical_invalidation=slow,
            ):
                return {}
            return None
        if not self._review_due(len(history)):
            return None
        if fast > slow and close > slow:
            return self.prepare_entry(history)
        return None


class HorizonAdaptiveTrendExecutor:
    executor_id = HORIZON_ADAPTIVE_TREND_EXECUTOR_ID

    def create_session(
        self,
        request: BacktestRequest,
    ) -> HorizonAdaptiveTrendSession:
        return HorizonAdaptiveTrendSession(
            HorizonAdaptiveTrendParameters.from_mapping(
                request.candidate.parameters
            ),
            ExecutionSettings.from_request(request),
        )


@dataclass(frozen=True, slots=True)
class RollingLevelParameters:
    risk: RiskManagedParameters
    review_interval_bars: int
    rolling_level_lookback_bars: int
    pivot_window: int
    merge_tolerance_percent: float
    min_touches: int
    maximum_level_distance_percent: float
    entry_buffer_percent: float
    support_entry_floor_buffer_percent: float
    technical_invalidation_buffer_percent: float
    volume_lookback_bars: int | None = None
    minimum_relative_volume: float | None = None

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any],
        *,
        support: bool,
        require_volume: bool = False,
    ) -> "RollingLevelParameters":
        return cls(
            risk=RiskManagedParameters.from_mapping(values),
            review_interval_bars=positive_integer(
                values, "review_interval_bars", maximum=252
            ),
            rolling_level_lookback_bars=positive_integer(
                values,
                "rolling_level_lookback_bars",
                minimum=20,
                maximum=1_260,
            ),
            pivot_window=positive_integer(
                values, "pivot_window", maximum=25
            ),
            merge_tolerance_percent=number(
                values,
                "merge_tolerance_percent",
                minimum=0.000001,
                maximum=0.10,
            ),
            min_touches=positive_integer(
                values, "min_touches", minimum=2, maximum=20
            ),
            maximum_level_distance_percent=number(
                values,
                "maximum_level_distance_percent",
                minimum=0.01,
                maximum=100.0,
            ),
            entry_buffer_percent=number(
                values,
                "entry_buffer_percent",
                minimum=0.0,
                maximum=0.25,
            ),
            support_entry_floor_buffer_percent=(
                number(
                    values,
                    "support_entry_floor_buffer_percent",
                    minimum=0.0,
                    maximum=0.25,
                )
                if support
                else 0.0
            ),
            technical_invalidation_buffer_percent=number(
                values,
                "technical_invalidation_buffer_percent",
                minimum=0.0,
                maximum=0.25,
            ),
            volume_lookback_bars=(
                positive_integer(
                    values,
                    "volume_lookback_bars",
                    minimum=2,
                    maximum=252,
                )
                if require_volume
                else None
            ),
            minimum_relative_volume=(
                number(
                    values,
                    "minimum_relative_volume",
                    minimum=1.0,
                    maximum=10.0,
                )
                if require_volume
                else None
            ),
        )


def _rolling_structural_level(
    history: Any,
    *,
    support: bool,
    reference_close: float,
    lookback_bars: int,
    pivot_window: int,
    merge_tolerance_percent: float,
    min_touches: int,
) -> float | None:
    """Return the nearest repeated pivot cluster using past bars only."""

    completed = tuple(history[:-1])[-lookback_bars:]
    if len(completed) < 2 * pivot_window + 1:
        return None
    pivots: list[float] = []
    for index in range(pivot_window, len(completed) - pivot_window):
        bar = completed[index]
        neighbours = (
            completed[index - pivot_window : index]
            + completed[index + 1 : index + pivot_window + 1]
        )
        if support:
            value = float(bar.low)
            if value <= min(float(item.low) for item in neighbours):
                pivots.append(value)
        else:
            value = float(bar.high)
            if value >= max(float(item.high) for item in neighbours):
                pivots.append(value)
    if not pivots:
        return None
    clusters: list[list[float]] = []
    for value in sorted(pivots):
        if not clusters:
            clusters.append([value])
            continue
        center = sum(clusters[-1]) / len(clusters[-1])
        if abs(value - center) / center <= merge_tolerance_percent:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    levels = [
        sum(cluster) / len(cluster)
        for cluster in clusters
        if len(cluster) >= min_touches
    ]
    if support:
        eligible = [level for level in levels if level <= reference_close]
        return max(eligible) if eligible else None
    crossed = [level for level in levels if level <= reference_close]
    if crossed:
        return max(crossed)
    eligible = [level for level in levels if level > reference_close]
    return min(eligible) if eligible else None


class RollingLevelSession(VolatilityManagedSession):
    """Recalculate a structural level without reading future bars."""

    def __init__(
        self,
        parameters: RollingLevelParameters,
        settings: ExecutionSettings,
        *,
        support: bool,
        require_volume: bool = False,
    ) -> None:
        super().__init__(parameters.risk, settings)
        self.parameters = parameters
        self.support = support
        self.require_volume = require_volume
        self._last_review_history_count: int | None = None
        self._active_anchor: float | None = None

    def _review_due(self, history_count: int) -> bool:
        previous = self._last_review_history_count
        if previous is None:
            self._last_review_history_count = history_count
            return True
        if history_count - previous < self.parameters.review_interval_bars:
            return False
        self._last_review_history_count = history_count
        return True

    def _volume_confirmed(self, history: Any, bar: Any) -> bool:
        if not self.require_volume:
            return True
        lookback = self.parameters.volume_lookback_bars
        minimum = self.parameters.minimum_relative_volume
        if lookback is None or minimum is None or len(history) < lookback + 1:
            return False
        if bar.volume is None:
            return False
        raw = [item.volume for item in history[-(lookback + 1) : -1]]
        if any(value is None for value in raw):
            return False
        values = [float(value) for value in raw if value is not None]
        average = sum(values) / len(values)
        return average > 0 and float(bar.volume) / average >= minimum

    def target_weights(
        self,
        context: StrategyEvaluationContext,
    ) -> Mapping[str, float] | None:
        bar = context.current_bars.get(self.risk.symbol)
        if bar is None:
            return None
        history = context.history.get(self.risk.symbol, ())
        invested = self.observe_position(bar, context.positions)
        close = float(bar.close)
        if invested:
            anchor = self._active_anchor
            if anchor is None:
                raise RuntimeError("Rolling level position has no active anchor.")
            invalidation = anchor * (
                1.0 - self.parameters.technical_invalidation_buffer_percent
            )
            if self.exit_required(
                close=close,
                technical_invalidation=invalidation,
            ):
                return {}
            return None
        if not self._review_due(len(history)):
            return None
        anchor = _rolling_structural_level(
            history,
            support=self.support,
            reference_close=close,
            lookback_bars=self.parameters.rolling_level_lookback_bars,
            pivot_window=self.parameters.pivot_window,
            merge_tolerance_percent=(
                self.parameters.merge_tolerance_percent
            ),
            min_touches=self.parameters.min_touches,
        )
        if anchor is None:
            return None
        distance_percent = abs(close / anchor - 1.0) * 100.0
        if distance_percent > self.parameters.maximum_level_distance_percent:
            return None
        if self.support:
            ceiling = anchor * (1.0 + self.parameters.entry_buffer_percent)
            floor = anchor * (
                1.0 - self.parameters.support_entry_floor_buffer_percent
            )
            qualifies = floor <= close <= ceiling
        else:
            trigger = anchor * (1.0 + self.parameters.entry_buffer_percent)
            qualifies = close >= trigger and self._volume_confirmed(history, bar)
        if not qualifies:
            return None
        target = self.prepare_entry(history)
        if target is not None:
            self._active_anchor = anchor
        return target


class RollingSupportReactionExecutor:
    executor_id = ROLLING_SUPPORT_REACTION_EXECUTOR_ID

    def create_session(self, request: BacktestRequest) -> RollingLevelSession:
        return RollingLevelSession(
            RollingLevelParameters.from_mapping(
                request.candidate.parameters,
                support=True,
            ),
            ExecutionSettings.from_request(request),
            support=True,
        )


class RollingResistanceBreakoutExecutor:
    executor_id = ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID

    def create_session(self, request: BacktestRequest) -> RollingLevelSession:
        return RollingLevelSession(
            RollingLevelParameters.from_mapping(
                request.candidate.parameters,
                support=False,
            ),
            ExecutionSettings.from_request(request),
            support=False,
        )


class RollingVolumeConfirmedBreakoutExecutor:
    executor_id = ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID

    def create_session(self, request: BacktestRequest) -> RollingLevelSession:
        return RollingLevelSession(
            RollingLevelParameters.from_mapping(
                request.candidate.parameters,
                support=False,
                require_volume=True,
            ),
            ExecutionSettings.from_request(request),
            support=False,
            require_volume=True,
        )


@dataclass(frozen=True, slots=True)
class VolumeBreakoutParameters:
    level: LevelParameters
    volume_lookback_bars: int
    minimum_relative_volume: float

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any],
    ) -> "VolumeBreakoutParameters":
        return cls(
            level=LevelParameters.from_mapping(values, support=False),
            volume_lookback_bars=positive_integer(
                values,
                "volume_lookback_bars",
                minimum=2,
                maximum=252,
            ),
            minimum_relative_volume=number(
                values,
                "minimum_relative_volume",
                minimum=1.0,
                maximum=10.0,
            ),
        )


class VolumeBreakoutSession(VolatilityManagedSession):
    def __init__(
        self,
        parameters: VolumeBreakoutParameters,
        settings: ExecutionSettings,
    ) -> None:
        super().__init__(parameters.level.risk, settings)
        self.parameters = parameters
        self.entry_armed = True

    def target_weights(
        self,
        context: StrategyEvaluationContext,
    ) -> Mapping[str, float] | None:
        bar = context.current_bars.get(self.risk.symbol)
        if bar is None:
            return None
        history = context.history.get(self.risk.symbol, ())
        invested = self.observe_position(bar, context.positions)
        level = self.parameters.level
        close = float(bar.close)
        breakout = level.anchor_level * (1.0 + level.entry_buffer_percent)
        invalidation = level.anchor_level * (
            1.0 - level.technical_invalidation_buffer_percent
        )
        if invested:
            return (
                {}
                if self.exit_required(
                    close=close,
                    technical_invalidation=invalidation,
                )
                else None
            )
        if not self.entry_armed:
            if close < breakout:
                self.entry_armed = True
            return None
        lookback = self.parameters.volume_lookback_bars
        if len(history) < lookback + 1 or bar.volume is None:
            return None
        raw_prior_volumes = [
            prior.volume for prior in history[-(lookback + 1) : -1]
        ]
        if any(volume is None for volume in raw_prior_volumes):
            return None
        prior_volumes = [
            float(volume)
            for volume in raw_prior_volumes
            if volume is not None
        ]
        average_volume = sum(prior_volumes) / lookback
        if average_volume <= 0:
            return None
        relative_volume = float(bar.volume) / average_volume
        previous_close = history[-2].close
        if (
            previous_close < breakout <= close
            and relative_volume >= self.parameters.minimum_relative_volume
        ):
            target = self.prepare_entry(history)
            if target is not None:
                self.entry_armed = False
            return target
        return None


class VolumeConfirmedBreakoutExecutor:
    executor_id = VOLUME_BREAKOUT_EXECUTOR_ID

    def create_session(self, request: BacktestRequest) -> VolumeBreakoutSession:
        return VolumeBreakoutSession(
            VolumeBreakoutParameters.from_mapping(request.candidate.parameters),
            ExecutionSettings.from_request(request),
        )


@dataclass(frozen=True, slots=True)
class PatternParameters:
    risk: RiskManagedParameters
    neckline_price: float
    breakout_buffer_percent: float
    technical_invalidation_buffer_percent: float

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "PatternParameters":
        return cls(
            risk=RiskManagedParameters.from_mapping(values),
            neckline_price=number(values, "neckline_price", minimum=1e-12),
            breakout_buffer_percent=number(
                values,
                "breakout_buffer_percent",
                minimum=0.0,
                maximum=0.25,
            ),
            technical_invalidation_buffer_percent=number(
                values,
                "technical_invalidation_buffer_percent",
                minimum=0.0,
                maximum=0.25,
            ),
        )


class PatternBreakSession(VolatilityManagedSession):
    def __init__(
        self,
        parameters: PatternParameters,
        settings: ExecutionSettings,
        *,
        direction: int,
    ) -> None:
        super().__init__(parameters.risk, settings, direction=direction)
        self.parameters = parameters
        self.entry_armed = True

    def target_weights(
        self,
        context: StrategyEvaluationContext,
    ) -> Mapping[str, float] | None:
        bar = context.current_bars.get(self.risk.symbol)
        if bar is None:
            return None
        history = context.history.get(self.risk.symbol, ())
        invested = self.observe_position(bar, context.positions)
        close = float(bar.close)
        neckline = self.parameters.neckline_price
        buffer = self.parameters.breakout_buffer_percent
        invalidation_buffer = (
            self.parameters.technical_invalidation_buffer_percent
        )
        if self.direction > 0:
            trigger = neckline * (1.0 + buffer)
            invalidation = neckline * (1.0 - invalidation_buffer)
        else:
            trigger = neckline * (1.0 - buffer)
            invalidation = neckline * (1.0 + invalidation_buffer)

        if invested:
            return (
                {}
                if self.exit_required(
                    close=close,
                    technical_invalidation=invalidation,
                )
                else None
            )
        if not self.entry_armed:
            if (self.direction > 0 and close < trigger) or (
                self.direction < 0 and close > trigger
            ):
                self.entry_armed = True
            return None
        if len(history) < 2:
            return None
        previous_close = float(history[-2].close)
        crossed = (
            previous_close < trigger <= close
            if self.direction > 0
            else previous_close > trigger >= close
        )
        if crossed:
            target = self.prepare_entry(history)
            if target is not None:
                self.entry_armed = False
            return target
        return None


class InverseHeadShouldersBreakoutExecutor:
    executor_id = INVERSE_PATTERN_EXECUTOR_ID

    def create_session(self, request: BacktestRequest) -> PatternBreakSession:
        return PatternBreakSession(
            PatternParameters.from_mapping(request.candidate.parameters),
            ExecutionSettings.from_request(request),
            direction=1,
        )


class HeadShouldersBreakdownExecutor:
    executor_id = HEAD_PATTERN_EXECUTOR_ID

    def create_session(self, request: BacktestRequest) -> PatternBreakSession:
        return PatternBreakSession(
            PatternParameters.from_mapping(request.candidate.parameters),
            ExecutionSettings.from_request(request),
            direction=-1,
        )


support_reaction_executor = SupportReactionExecutor()
resistance_breakout_executor = ResistanceBreakoutExecutor()
moving_average_trend_executor = MovingAverageTrendExecutor()
horizon_adaptive_trend_executor = HorizonAdaptiveTrendExecutor()
rolling_support_reaction_executor = RollingSupportReactionExecutor()
rolling_resistance_breakout_executor = RollingResistanceBreakoutExecutor()
rolling_volume_confirmed_breakout_executor = (
    RollingVolumeConfirmedBreakoutExecutor()
)
volume_confirmed_breakout_executor = VolumeConfirmedBreakoutExecutor()
inverse_head_shoulders_breakout_executor = InverseHeadShouldersBreakoutExecutor()
head_shoulders_breakdown_executor = HeadShouldersBreakdownExecutor()

TECHNICAL_SLEEVE_EXECUTORS = (
    rolling_support_reaction_executor,
    rolling_resistance_breakout_executor,
    horizon_adaptive_trend_executor,
    rolling_volume_confirmed_breakout_executor,
    support_reaction_executor,
    resistance_breakout_executor,
    moving_average_trend_executor,
    volume_confirmed_breakout_executor,
    inverse_head_shoulders_breakout_executor,
)

_SLEEVE_EXECUTOR_BY_ID = {
    executor.executor_id: executor for executor in TECHNICAL_SLEEVE_EXECUTORS
}

_FAMILY_PARAMETERS: dict[str, frozenset[str]] = {
    ROLLING_SUPPORT_REACTION_EXECUTOR_ID: frozenset(
        {
            "review_interval_bars",
            "rolling_level_lookback_bars",
            "pivot_window",
            "merge_tolerance_percent",
            "min_touches",
            "maximum_level_distance_percent",
            "entry_buffer_percent",
            "support_entry_floor_buffer_percent",
            "technical_invalidation_buffer_percent",
        }
    ),
    ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID: frozenset(
        {
            "review_interval_bars",
            "rolling_level_lookback_bars",
            "pivot_window",
            "merge_tolerance_percent",
            "min_touches",
            "maximum_level_distance_percent",
            "entry_buffer_percent",
            "technical_invalidation_buffer_percent",
        }
    ),
    HORIZON_ADAPTIVE_TREND_EXECUTOR_ID: frozenset(
        {"fast_window", "slow_window", "review_interval_bars"}
    ),
    ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID: frozenset(
        {
            "review_interval_bars",
            "rolling_level_lookback_bars",
            "pivot_window",
            "merge_tolerance_percent",
            "min_touches",
            "maximum_level_distance_percent",
            "entry_buffer_percent",
            "technical_invalidation_buffer_percent",
            "volume_lookback_bars",
            "minimum_relative_volume",
        }
    ),
    SUPPORT_REACTION_EXECUTOR_ID: frozenset(
        {
            "anchor_level",
            "entry_buffer_percent",
            "support_entry_floor_buffer_percent",
            "technical_invalidation_buffer_percent",
        }
    ),
    RESISTANCE_BREAKOUT_EXECUTOR_ID: frozenset(
        {
            "anchor_level",
            "entry_buffer_percent",
            "technical_invalidation_buffer_percent",
        }
    ),
    MOVING_AVERAGE_TREND_EXECUTOR_ID: frozenset(
        {"fast_window", "slow_window"}
    ),
    VOLUME_BREAKOUT_EXECUTOR_ID: frozenset(
        {
            "anchor_level",
            "entry_buffer_percent",
            "technical_invalidation_buffer_percent",
            "volume_lookback_bars",
            "minimum_relative_volume",
        }
    ),
    INVERSE_PATTERN_EXECUTOR_ID: frozenset(
        {
            "neckline_price",
            "breakout_buffer_percent",
            "technical_invalidation_buffer_percent",
        }
    ),
}

_COMMON_RISK_PARAMETERS = frozenset(
    {
        "max_holding_bars",
        "volatility_lookback_bars",
        "profit_target_sigma_multiple",
        "stop_loss_sigma_multiple",
    }
)


@dataclass(frozen=True, slots=True)
class TechnicalPortfolioSleeve:
    symbol: str
    executor_id: str
    evidence_ids: tuple[str, ...]
    opportunity_id: str
    opportunity_rank: int
    opportunity_score: float
    expected_return_rationale: str
    family_parameters: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TechnicalPortfolioParameters:
    target_asset_count: int
    selected_asset_count: int
    portfolio_target_gross_weight: float
    common_risk_parameters: Mapping[str, Any]
    sleeves: tuple[TechnicalPortfolioSleeve, ...]

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any],
    ) -> "TechnicalPortfolioParameters":
        target_count = positive_integer(
            values,
            "target_asset_count",
            maximum=TARGET_PORTFOLIO_ASSET_COUNT,
        )
        if target_count != TARGET_PORTFOLIO_ASSET_COUNT:
            raise ValueError(
                f"target_asset_count must equal "
                f"{TARGET_PORTFOLIO_ASSET_COUNT}."
            )
        selected_count = positive_integer(
            values,
            "selected_asset_count",
            maximum=TARGET_PORTFOLIO_ASSET_COUNT,
        )
        allocation = str(values.get("allocation_method", "")).strip()
        if allocation != "equal_weight":
            raise ValueError("allocation_method must be 'equal_weight'.")
        threshold = str(values.get("selection_threshold", "")).strip()
        if threshold != "positive_expected_return_from_training_evidence":
            raise ValueError(
                "selection_threshold must be "
                "'positive_expected_return_from_training_evidence'."
            )
        omission = str(values.get("omission_rationale", "")).strip()
        if selected_count < target_count and not omission:
            raise ValueError(
                "omission_rationale is required when fewer than 10 ETFs "
                "are selected."
            )
        common = values.get("common_risk_parameters")
        if not isinstance(common, Mapping):
            raise ValueError("common_risk_parameters must be a mapping.")
        common_keys = {str(key) for key in common}
        if common_keys != _COMMON_RISK_PARAMETERS:
            raise ValueError(
                "common_risk_parameters must contain exactly: "
                + ", ".join(sorted(_COMMON_RISK_PARAMETERS))
                + "."
            )
        raw_sleeves = values.get("sleeves")
        if not isinstance(raw_sleeves, list):
            raise ValueError("sleeves must be a list.")
        if len(raw_sleeves) != selected_count:
            raise ValueError(
                "selected_asset_count must equal the number of sleeves."
            )

        sleeves: list[TechnicalPortfolioSleeve] = []
        seen_symbols: set[str] = set()
        seen_evidence_ids: set[str] = set()
        for index, raw_sleeve in enumerate(raw_sleeves, start=1):
            if not isinstance(raw_sleeve, Mapping):
                raise ValueError(f"sleeves[{index}] must be a mapping.")
            sleeve_symbol = str(raw_sleeve.get("symbol", "")).strip()
            if not sleeve_symbol:
                raise ValueError(f"sleeves[{index}].symbol must be non-empty.")
            if sleeve_symbol in seen_symbols:
                raise ValueError(
                    f"Duplicate portfolio sleeve symbol '{sleeve_symbol}'."
                )
            seen_symbols.add(sleeve_symbol)
            executor_id = str(raw_sleeve.get("executor_id", "")).strip()
            expected_parameters = _FAMILY_PARAMETERS.get(executor_id)
            if expected_parameters is None:
                raise ValueError(
                    f"sleeves[{index}] selected unsupported long-only "
                    f"executor '{executor_id}'."
                )
            raw_evidence = raw_sleeve.get("evidence_ids")
            if not isinstance(raw_evidence, list) or not raw_evidence:
                raise ValueError(
                    f"sleeves[{index}].evidence_ids must be a non-empty list."
                )
            evidence_ids = tuple(
                str(item).strip() for item in raw_evidence if str(item).strip()
            )
            if len(evidence_ids) != len(raw_evidence) or len(
                evidence_ids
            ) != len(set(evidence_ids)):
                raise ValueError(
                    f"sleeves[{index}].evidence_ids must be unique and "
                    "non-empty."
                )
            reused_evidence = set(evidence_ids).intersection(
                seen_evidence_ids
            )
            if reused_evidence:
                raise ValueError(
                    "Evidence IDs cannot be reused across ETF sleeves: "
                    + ", ".join(sorted(reused_evidence))
                )
            seen_evidence_ids.update(evidence_ids)
            rationale = str(
                raw_sleeve.get("expected_return_rationale", "")
            ).strip()
            if not rationale:
                raise ValueError(
                    f"sleeves[{index}].expected_return_rationale is required."
                )
            opportunity_id = str(
                raw_sleeve.get("opportunity_id", "")
            ).strip()
            if not opportunity_id:
                raise ValueError(
                    f"sleeves[{index}].opportunity_id must be code-bound."
                )
            opportunity_rank = positive_integer(
                raw_sleeve,
                "opportunity_rank",
                maximum=100_000,
            )
            opportunity_score = number(
                raw_sleeve,
                "opportunity_score",
                minimum=0.0,
                maximum=1.0,
            )
            family_parameters = raw_sleeve.get("parameters")
            if not isinstance(family_parameters, Mapping):
                raise ValueError(f"sleeves[{index}].parameters must be a mapping.")
            family_keys = {str(key) for key in family_parameters}
            if family_keys != expected_parameters:
                raise ValueError(
                    f"sleeves[{index}].parameters must contain exactly: "
                    + ", ".join(sorted(expected_parameters))
                    + "."
                )
            sleeves.append(
                TechnicalPortfolioSleeve(
                    symbol=sleeve_symbol,
                    executor_id=executor_id,
                    evidence_ids=evidence_ids,
                    opportunity_id=opportunity_id,
                    opportunity_rank=opportunity_rank,
                    opportunity_score=opportunity_score,
                    expected_return_rationale=rationale,
                    family_parameters=dict(family_parameters),
                )
            )

        return cls(
            target_asset_count=target_count,
            selected_asset_count=selected_count,
            portfolio_target_gross_weight=number(
                values,
                "portfolio_target_gross_weight",
                minimum=0.01,
                maximum=1.0,
            ),
            common_risk_parameters=dict(common),
            sleeves=tuple(sleeves),
        )


class MultiAssetPortfolioSession:
    """Combine independently stateful ETF sleeves into one target mapping."""

    def __init__(
        self,
        request: BacktestRequest,
        parameters: TechnicalPortfolioParameters,
    ) -> None:
        sleeve_weight = (
            parameters.portfolio_target_gross_weight
            / parameters.selected_asset_count
        )
        sessions: list[tuple[str, Any]] = []
        for sleeve in parameters.sleeves:
            missing_usage = set(sleeve.evidence_ids) - set(
                request.candidate.specialty_evidence_usage
            )
            if missing_usage:
                raise ValueError(
                    "Portfolio sleeve evidence is missing candidate usage "
                    "mappings: " + ", ".join(sorted(missing_usage))
                )
            merged_parameters = {
                **parameters.common_risk_parameters,
                **sleeve.family_parameters,
                "symbol": sleeve.symbol,
                "target_weight": sleeve_weight,
            }
            child_candidate = request.candidate.model_copy(
                update={
                    "executor_id": sleeve.executor_id,
                    "parameters": merged_parameters,
                    "specialty_evidence_ids": list(sleeve.evidence_ids),
                    "specialty_evidence_usage": {
                        evidence_id: request.candidate.specialty_evidence_usage[
                            evidence_id
                        ]
                        for evidence_id in sleeve.evidence_ids
                    },
                }
            )
            child_request = request.model_copy(
                update={"candidate": child_candidate}
            )
            child_executor = _SLEEVE_EXECUTOR_BY_ID[sleeve.executor_id]
            sessions.append(
                (sleeve.symbol, child_executor.create_session(child_request))
            )
        self._sessions = tuple(sessions)
        self._desired_weights: dict[str, float] = {}

    def target_weights(
        self,
        context: StrategyEvaluationContext,
    ) -> Mapping[str, float] | None:
        changed = False
        for sleeve_symbol, session in self._sessions:
            sleeve_target = session.target_weights(context)
            if sleeve_target is None:
                continue
            unexpected = set(sleeve_target) - {sleeve_symbol}
            if unexpected:
                raise RuntimeError(
                    "Technical sleeve targeted an unexpected symbol: "
                    + ", ".join(sorted(unexpected))
                )
            changed = True
            weight = float(sleeve_target.get(sleeve_symbol, 0.0))
            if abs(weight) <= 1e-12:
                self._desired_weights.pop(sleeve_symbol, None)
            else:
                self._desired_weights[sleeve_symbol] = weight
        return dict(self._desired_weights) if changed else None


class MultiAssetTechnicalPortfolioExecutor:
    executor_id = MULTI_ASSET_PORTFOLIO_EXECUTOR_ID

    def create_session(self, request: BacktestRequest) -> MultiAssetPortfolioSession:
        parameters = TechnicalPortfolioParameters.from_mapping(
            request.candidate.parameters
        )
        return MultiAssetPortfolioSession(request, parameters)


multi_asset_technical_portfolio_executor = MultiAssetTechnicalPortfolioExecutor()


@dataclass(frozen=True, slots=True)
class BenchmarkFallbackParameters:
    symbol: str
    target_weight: float

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any],
    ) -> "BenchmarkFallbackParameters":
        return cls(
            symbol=parsed_symbol(values),
            target_weight=number(
                values,
                "target_weight",
                minimum=0.000001,
                maximum=1.0,
            ),
        )


class BenchmarkFallbackSession:
    """Submit one benchmark target and hold until engine liquidation."""

    def __init__(self, parameters: BenchmarkFallbackParameters) -> None:
        self.parameters = parameters
        self._target_submitted = False

    def target_weights(
        self,
        context: StrategyEvaluationContext,
    ) -> Mapping[str, float] | None:
        if self._target_submitted:
            return None
        if self.parameters.symbol not in context.current_bars:
            return None
        self._target_submitted = True
        return {
            self.parameters.symbol: self.parameters.target_weight,
        }


class BenchmarkFallbackExecutor:
    executor_id = BENCHMARK_FALLBACK_EXECUTOR_ID

    def create_session(
        self,
        request: BacktestRequest,
    ) -> BenchmarkFallbackSession:
        return BenchmarkFallbackSession(
            BenchmarkFallbackParameters.from_mapping(
                request.candidate.parameters
            )
        )


benchmark_fallback_executor = BenchmarkFallbackExecutor()

LONG_ONLY_TECHNICAL_EXECUTORS = (
    multi_asset_technical_portfolio_executor,
    benchmark_fallback_executor,
)

TECHNICAL_STRATEGY_EXECUTORS = (
    multi_asset_technical_portfolio_executor,
    benchmark_fallback_executor,
)


__all__ = [
    "BenchmarkFallbackExecutor",
    "BenchmarkFallbackParameters",
    "BenchmarkFallbackSession",
    "HeadShouldersBreakdownExecutor",
    "HorizonAdaptiveTrendExecutor",
    "HorizonAdaptiveTrendParameters",
    "HorizonAdaptiveTrendSession",
    "InverseHeadShouldersBreakoutExecutor",
    "LONG_ONLY_TECHNICAL_EXECUTORS",
    "LevelParameters",
    "LevelSession",
    "MovingAverageParameters",
    "MovingAverageTrendExecutor",
    "MovingAverageTrendSession",
    "MultiAssetPortfolioSession",
    "MultiAssetTechnicalPortfolioExecutor",
    "PatternBreakSession",
    "PatternParameters",
    "ResistanceBreakoutExecutor",
    "RollingLevelParameters",
    "RollingLevelSession",
    "RollingResistanceBreakoutExecutor",
    "RollingSupportReactionExecutor",
    "RollingVolumeConfirmedBreakoutExecutor",
    "SupportReactionExecutor",
    "TECHNICAL_STRATEGY_EXECUTORS",
    "TECHNICAL_SLEEVE_EXECUTORS",
    "TechnicalPortfolioParameters",
    "TechnicalPortfolioSleeve",
    "VolumeBreakoutParameters",
    "VolumeBreakoutSession",
    "VolumeConfirmedBreakoutExecutor",
    "benchmark_fallback_executor",
    "head_shoulders_breakdown_executor",
    "horizon_adaptive_trend_executor",
    "inverse_head_shoulders_breakout_executor",
    "moving_average_trend_executor",
    "multi_asset_technical_portfolio_executor",
    "resistance_breakout_executor",
    "rolling_resistance_breakout_executor",
    "rolling_support_reaction_executor",
    "rolling_volume_confirmed_breakout_executor",
    "support_reaction_executor",
    "volume_confirmed_breakout_executor",
]
