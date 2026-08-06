"""Deterministic support/resistance and chart-pattern calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import sqrt
from typing import Protocol, Sequence, runtime_checkable

from ..models.technical_analysis import (
    AssetTechnicalAnalysis,
    ChartPatternConfig,
    ChartPatternObservation,
    ChartPatternStatus,
    ChartPatternType,
    MovingAverageConfig,
    MovingAverageCrossDirection,
    MovingAverageObservation,
    MovingAverageRelationship,
    PatternPoint,
    PivotKind,
    PriceBar,
    PriceLevelKind,
    PriceSeries,
    SupportResistanceConfig,
    SupportResistanceLevel,
    TechnicalAnalysisReport,
    VolumeAnalysisConfig,
    VolumeObservation,
)


@runtime_checkable
class TechnicalAnalysisToolkit(Protocol):
    """Owned deterministic-tool interface, replaceable without changing the agent."""

    def analyze(
        self,
        *,
        series: Sequence[PriceSeries],
        as_of_date: date,
        report_id: str,
    ) -> TechnicalAnalysisReport:
        """Compute Technical Trader evidence without using an LLM."""
        ...


@dataclass(frozen=True, slots=True)
class _Pivot:
    index: int
    timestamp: datetime
    price: float
    kind: PivotKind


class DeterministicTechnicalAnalysisToolkit:
    """Calculate reproducible geometric observations from validated OHLCV bars.

    The calculations identify historical structures only. They do not predict
    returns, approve a strategy, or replace deterministic backtesting and Risk
    review.
    """

    version = "0.4.0"

    def __init__(
        self,
        *,
        support_resistance: SupportResistanceConfig | None = None,
        chart_patterns: ChartPatternConfig | None = None,
        moving_average: MovingAverageConfig | None = None,
        moving_averages: Sequence[MovingAverageConfig] | None = None,
        volume_analysis: VolumeAnalysisConfig | None = None,
    ) -> None:
        if moving_average is not None and moving_averages is not None:
            raise ValueError(
                "Provide moving_average or moving_averages, not both."
            )
        self._support_resistance = (
            support_resistance or SupportResistanceConfig()
        )
        self._chart_patterns = chart_patterns or ChartPatternConfig()
        configured_moving_averages = (
            tuple(moving_averages)
            if moving_averages is not None
            else (
                (moving_average,)
                if moving_average is not None
                else (
                    MovingAverageConfig(fast_window=3, slow_window=10),
                    MovingAverageConfig(fast_window=5, slow_window=20),
                    MovingAverageConfig(fast_window=10, slow_window=30),
                    MovingAverageConfig(fast_window=20, slow_window=50),
                    MovingAverageConfig(fast_window=50, slow_window=100),
                    MovingAverageConfig(fast_window=50, slow_window=200),
                )
            )
        )
        if not configured_moving_averages:
            raise ValueError("At least one moving-average configuration is required.")
        moving_average_keys = [
            (item.fast_window, item.slow_window)
            for item in configured_moving_averages
        ]
        if len(moving_average_keys) != len(set(moving_average_keys)):
            raise ValueError("Moving-average configurations must be unique.")
        self._moving_averages = configured_moving_averages
        self._volume_analysis = volume_analysis or VolumeAnalysisConfig()

    def analyze(
        self,
        *,
        series: Sequence[PriceSeries],
        as_of_date: date,
        report_id: str,
    ) -> TechnicalAnalysisReport:
        if not series:
            raise ValueError("At least one price series is required.")

        assets: list[AssetTechnicalAnalysis] = []
        warnings: list[str] = []
        for price_series in series:
            if price_series.as_of_date > as_of_date:
                raise ValueError(
                    f"{price_series.symbol} series exceeds report as_of_date."
                )
            levels, level_warnings = self._support_and_resistance(price_series)
            patterns = self._head_and_shoulders(price_series)
            moving_averages, moving_average_warnings = self._moving_averages_for(
                price_series
            )
            volume_observation, volume_warning = self._volume_observation(
                price_series
            )
            daily_volatility = self._daily_return_volatility(
                price_series.bars
            )
            warnings.extend(level_warnings)
            warnings.extend(moving_average_warnings)
            if volume_warning is not None:
                warnings.append(volume_warning)
            assets.append(
                AssetTechnicalAnalysis(
                    artifact_id=price_series.artifact_id,
                    symbol=price_series.symbol,
                    first_bar_timestamp=price_series.bars[0].timestamp,
                    last_bar_timestamp=price_series.bars[-1].timestamp,
                    observation_count=len(price_series.bars),
                    last_close=price_series.bars[-1].close,
                    daily_return_volatility=daily_volatility,
                    annualized_volatility=daily_volatility * sqrt(252.0),
                    support_resistance_levels=levels,
                    chart_patterns=patterns,
                    moving_averages=moving_averages,
                    volume_observation=volume_observation,
                )
            )

        return TechnicalAnalysisReport(
            report_id=report_id,
            generated_by="deterministic_technical_analysis_toolkit",
            toolkit_version=self.version,
            as_of_date=as_of_date,
            assets=assets,
            warnings=warnings,
        )

    @staticmethod
    def _daily_return_volatility(bars: list[PriceBar]) -> float:
        """Return sample volatility of point-in-time close-to-close returns."""

        returns = [
            current.close / previous.close - 1.0
            for previous, current in zip(bars, bars[1:], strict=False)
        ]
        if len(returns) < 2:
            return 0.0
        mean_return = sum(returns) / len(returns)
        variance = sum(
            (period_return - mean_return) ** 2
            for period_return in returns
        ) / (len(returns) - 1)
        return sqrt(max(variance, 0.0))

    def _moving_averages_for(
        self,
        series: PriceSeries,
    ) -> tuple[list[MovingAverageObservation], list[str]]:
        observations: list[MovingAverageObservation] = []
        warnings: list[str] = []
        for config in self._moving_averages:
            observation = self._moving_average_observation(series, config)
            if observation is None:
                warnings.append(
                    f"{series.symbol}: moving-average evidence "
                    f"{config.fast_window}/{config.slow_window} requires at "
                    f"least {config.slow_window} bars."
                )
            else:
                observations.append(observation)
        return observations, warnings

    def _moving_average_observation(
        self,
        series: PriceSeries,
        config: MovingAverageConfig,
    ) -> MovingAverageObservation | None:
        bars = series.bars
        if len(bars) < config.slow_window:
            return None

        closes = [bar.close for bar in bars]

        def average(end_index: int, window: int) -> float:
            values = closes[end_index - window + 1 : end_index + 1]
            return sum(values) / window

        latest_index = len(bars) - 1
        fast_average = average(latest_index, config.fast_window)
        slow_average = average(latest_index, config.slow_window)
        spread = (fast_average - slow_average) / slow_average
        if abs(spread) <= config.neutral_band_percent:
            relationship = MovingAverageRelationship.NEUTRAL
        elif spread > 0:
            relationship = MovingAverageRelationship.BULLISH
        else:
            relationship = MovingAverageRelationship.BEARISH

        latest_cross_direction: MovingAverageCrossDirection | None = None
        latest_cross_timestamp: datetime | None = None
        latest_cross_index: int | None = None
        previous_difference: float | None = None
        for index in range(config.slow_window - 1, len(bars)):
            difference = (
                average(index, config.fast_window)
                - average(index, config.slow_window)
            )
            if previous_difference is not None:
                if previous_difference <= 0 < difference:
                    latest_cross_direction = MovingAverageCrossDirection.BULLISH
                    latest_cross_timestamp = bars[index].timestamp
                    latest_cross_index = index
                elif previous_difference >= 0 > difference:
                    latest_cross_direction = MovingAverageCrossDirection.BEARISH
                    latest_cross_timestamp = bars[index].timestamp
                    latest_cross_index = index
            previous_difference = difference

        evidence_key = self._evidence_key(
            symbol=series.symbol,
            artifact_id=series.artifact_id,
        )
        return MovingAverageObservation(
            moving_average_id=(
                f"{evidence_key}.moving-average."
                f"{config.fast_window}-{config.slow_window}"
            ),
            fast_window=config.fast_window,
            slow_window=config.slow_window,
            fast_average=fast_average,
            slow_average=slow_average,
            spread_percent=spread * 100.0,
            relationship=relationship,
            latest_cross_direction=latest_cross_direction,
            latest_cross_timestamp=latest_cross_timestamp,
            bars_since_latest_cross=(
                latest_index - latest_cross_index
                if latest_cross_index is not None
                else None
            ),
        )

    def _volume_observation(
        self,
        series: PriceSeries,
    ) -> tuple[VolumeObservation | None, str | None]:
        config = self._volume_analysis
        bars = series.bars
        if len(bars) < config.lookback_window + 1:
            return None, (
                f"{series.symbol}: volume evidence requires at least "
                f"{config.lookback_window + 1} bars."
            )
        latest_volume = bars[-1].volume
        prior_volumes = [
            bar.volume
            for bar in bars[-(config.lookback_window + 1) : -1]
            if bar.volume is not None
        ]
        if latest_volume is None or len(prior_volumes) < config.lookback_window:
            return None, (
                f"{series.symbol}: complete volume evidence was unavailable "
                f"for the latest bar and prior {config.lookback_window} bars."
            )
        average_prior_volume = sum(prior_volumes) / len(prior_volumes)
        if average_prior_volume <= 0:
            return None, (
                f"{series.symbol}: prior average volume was not positive."
            )
        evidence_key = self._evidence_key(
            symbol=series.symbol,
            artifact_id=series.artifact_id,
        )
        latest_return = bars[-1].close / bars[-2].close - 1.0
        return (
            VolumeObservation(
                volume_id=(
                    f"{evidence_key}.volume.{config.lookback_window}"
                ),
                lookback_window=config.lookback_window,
                latest_volume=latest_volume,
                average_prior_volume=average_prior_volume,
                relative_volume=latest_volume / average_prior_volume,
                available_observations=len(prior_volumes) + 1,
                latest_close_return_percent=latest_return * 100.0,
            ),
            None,
        )

    def _support_and_resistance(
        self,
        series: PriceSeries,
    ) -> tuple[list[SupportResistanceLevel], list[str]]:
        pivots = self._local_pivots(
            series.bars,
            window=self._support_resistance.pivot_window,
        )
        lows = [pivot for pivot in pivots if pivot.kind is PivotKind.LOW]
        highs = [pivot for pivot in pivots if pivot.kind is PivotKind.HIGH]
        warnings: list[str] = []

        low_clusters = self._clusters(lows)
        high_clusters = self._clusters(highs)
        low_clusters = [
            cluster
            for cluster in low_clusters
            if len(cluster) >= self._support_resistance.min_touches
        ]
        high_clusters = [
            cluster
            for cluster in high_clusters
            if len(cluster) >= self._support_resistance.min_touches
        ]

        fallback_support = False
        fallback_resistance = False
        if not low_clusters:
            minimum = min(
                enumerate(series.bars),
                key=lambda item: (item[1].low, item[0]),
            )
            low_clusters = [
                [
                    _Pivot(
                        index=minimum[0],
                        timestamp=minimum[1].timestamp,
                        price=minimum[1].low,
                        kind=PivotKind.LOW,
                    )
                ]
            ]
            fallback_support = True
            warnings.append(
                f"{series.symbol}: support used the observed range low because "
                "no low-pivot cluster met min_touches."
            )

        if not high_clusters:
            maximum = max(
                enumerate(series.bars),
                key=lambda item: (item[1].high, -item[0]),
            )
            high_clusters = [
                [
                    _Pivot(
                        index=maximum[0],
                        timestamp=maximum[1].timestamp,
                        price=maximum[1].high,
                        kind=PivotKind.HIGH,
                    )
                ]
            ]
            fallback_resistance = True
            warnings.append(
                f"{series.symbol}: resistance used the observed range high "
                "because no high-pivot cluster met min_touches."
            )

        last_close = series.bars[-1].close
        levels: list[SupportResistanceLevel] = []
        levels.extend(
            self._levels_from_clusters(
                symbol=series.symbol,
                artifact_id=series.artifact_id,
                kind=PriceLevelKind.SUPPORT,
                clusters=low_clusters,
                last_close=last_close,
                used_range_fallback=fallback_support,
            )
        )
        levels.extend(
            self._levels_from_clusters(
                symbol=series.symbol,
                artifact_id=series.artifact_id,
                kind=PriceLevelKind.RESISTANCE,
                clusters=high_clusters,
                last_close=last_close,
                used_range_fallback=fallback_resistance,
            )
        )
        return levels, warnings

    def _clusters(self, pivots: list[_Pivot]) -> list[list[_Pivot]]:
        clusters: list[list[_Pivot]] = []
        for pivot in sorted(pivots, key=lambda item: (item.price, item.index)):
            if not clusters:
                clusters.append([pivot])
                continue
            current = clusters[-1]
            center = sum(item.price for item in current) / len(current)
            if (
                abs(pivot.price - center) / center
                <= self._support_resistance.merge_tolerance_percent
            ):
                current.append(pivot)
            else:
                clusters.append([pivot])
        return clusters

    def _levels_from_clusters(
        self,
        *,
        symbol: str,
        artifact_id: str,
        kind: PriceLevelKind,
        clusters: list[list[_Pivot]],
        last_close: float,
        used_range_fallback: bool,
    ) -> list[SupportResistanceLevel]:
        prepared: list[tuple[float, list[_Pivot]]] = [
            (
                sum(pivot.price for pivot in cluster) / len(cluster),
                sorted(cluster, key=lambda pivot: pivot.index),
            )
            for cluster in clusters
        ]
        prepared.sort(key=lambda item: abs(item[0] - last_close))
        prepared = prepared[: self._support_resistance.max_levels_per_kind]
        evidence_key = self._evidence_key(
            symbol=symbol,
            artifact_id=artifact_id,
        )

        levels: list[SupportResistanceLevel] = []
        for position, (price, cluster) in enumerate(prepared, start=1):
            levels.append(
                SupportResistanceLevel(
                    level_id=f"{evidence_key}.{kind.value}.{position}",
                    kind=kind,
                    price=price,
                    touches=len(cluster),
                    first_touched_at=cluster[0].timestamp,
                    last_touched_at=cluster[-1].timestamp,
                    source_pivots=sorted(
                        {pivot.kind for pivot in cluster},
                        key=lambda pivot_kind: pivot_kind.value,
                    ),
                    distance_from_last_close_percent=(
                        (price - last_close) / last_close * 100
                    ),
                    used_range_fallback=used_range_fallback,
                )
            )
        return levels

    def _head_and_shoulders(
        self,
        series: PriceSeries,
    ) -> list[ChartPatternObservation]:
        pivots = self._local_pivots(
            series.bars,
            window=self._chart_patterns.pivot_window,
        )
        observations = [
            *self._pattern_direction(
                series=series,
                pivots=[
                    pivot for pivot in pivots if pivot.kind is PivotKind.HIGH
                ],
                pattern_type=ChartPatternType.HEAD_AND_SHOULDERS,
            ),
            *self._pattern_direction(
                series=series,
                pivots=[
                    pivot for pivot in pivots if pivot.kind is PivotKind.LOW
                ],
                pattern_type=ChartPatternType.INVERSE_HEAD_AND_SHOULDERS,
            ),
        ]
        observations.sort(
            key=lambda observation: observation.points[-1].bar_index,
            reverse=True,
        )
        return observations[: self._chart_patterns.max_patterns_per_series]

    def _pattern_direction(
        self,
        *,
        series: PriceSeries,
        pivots: list[_Pivot],
        pattern_type: ChartPatternType,
    ) -> list[ChartPatternObservation]:
        observations: list[ChartPatternObservation] = []
        for offset in range(len(pivots) - 2):
            left, head, right = pivots[offset : offset + 3]
            if not self._valid_pattern_geometry(
                left=left,
                head=head,
                right=right,
                inverse=(
                    pattern_type
                    is ChartPatternType.INVERSE_HEAD_AND_SHOULDERS
                ),
            ):
                continue

            neckline = self._neckline(
                bars=series.bars,
                left=left,
                head=head,
                right=right,
                inverse=(
                    pattern_type
                    is ChartPatternType.INVERSE_HEAD_AND_SHOULDERS
                ),
            )
            confirmation = self._confirmation_timestamp(
                bars=series.bars,
                after_index=right.index,
                neckline=neckline,
                inverse=(
                    pattern_type
                    is ChartPatternType.INVERSE_HEAD_AND_SHOULDERS
                ),
            )
            evidence_key = self._evidence_key(
                symbol=series.symbol,
                artifact_id=series.artifact_id,
            )
            pattern_number = len(observations) + 1
            observations.append(
                ChartPatternObservation(
                    pattern_id=(
                        f"{evidence_key}.{pattern_type.value}.{pattern_number}"
                    ),
                    pattern_type=pattern_type,
                    status=(
                        ChartPatternStatus.CONFIRMED
                        if confirmation is not None
                        else ChartPatternStatus.FORMING
                    ),
                    points=[
                        PatternPoint(
                            label="left_shoulder",
                            bar_index=left.index,
                            timestamp=left.timestamp,
                            price=left.price,
                        ),
                        PatternPoint(
                            label="head",
                            bar_index=head.index,
                            timestamp=head.timestamp,
                            price=head.price,
                        ),
                        PatternPoint(
                            label="right_shoulder",
                            bar_index=right.index,
                            timestamp=right.timestamp,
                            price=right.price,
                        ),
                    ],
                    neckline_price=neckline,
                    confirmation_timestamp=confirmation,
                    notes=[
                        "Heuristic geometric observation; backtesting and Risk "
                        "review remain required."
                    ],
                )
            )
        return observations

    @staticmethod
    def _evidence_key(*, symbol: str, artifact_id: str) -> str:
        def normalize(value: str, fallback: str) -> str:
            return "".join(
                character.lower() if character.isalnum() else "-"
                for character in value
            ).strip("-") or fallback

        return (
            f"{normalize(symbol, 'asset')}."
            f"{normalize(artifact_id, 'artifact')}"
        )

    def _valid_pattern_geometry(
        self,
        *,
        left: _Pivot,
        head: _Pivot,
        right: _Pivot,
        inverse: bool,
    ) -> bool:
        left_gap = head.index - left.index
        right_gap = right.index - head.index
        if min(left_gap, right_gap) < self._chart_patterns.min_separation_bars:
            return False
        if right.index - left.index > self._chart_patterns.max_pattern_span_bars:
            return False

        shoulder_average = (left.price + right.price) / 2
        shoulder_difference = abs(left.price - right.price) / shoulder_average
        if (
            shoulder_difference
            > self._chart_patterns.shoulder_tolerance_percent
        ):
            return False

        prominence = self._chart_patterns.head_prominence_percent
        if inverse:
            return head.price < min(left.price, right.price) * (1 - prominence)
        return head.price > max(left.price, right.price) * (1 + prominence)

    @staticmethod
    def _neckline(
        *,
        bars: list[PriceBar],
        left: _Pivot,
        head: _Pivot,
        right: _Pivot,
        inverse: bool,
    ) -> float:
        left_segment = bars[left.index : head.index + 1]
        right_segment = bars[head.index : right.index + 1]
        if inverse:
            left_turn = max(bar.high for bar in left_segment)
            right_turn = max(bar.high for bar in right_segment)
        else:
            left_turn = min(bar.low for bar in left_segment)
            right_turn = min(bar.low for bar in right_segment)
        return (left_turn + right_turn) / 2

    @staticmethod
    def _confirmation_timestamp(
        *,
        bars: list[PriceBar],
        after_index: int,
        neckline: float,
        inverse: bool,
    ) -> datetime | None:
        for bar in bars[after_index + 1 :]:
            crossed = bar.close > neckline if inverse else bar.close < neckline
            if crossed:
                return bar.timestamp
        return None

    @staticmethod
    def _local_pivots(
        bars: list[PriceBar],
        *,
        window: int,
    ) -> list[_Pivot]:
        pivots: list[_Pivot] = []
        if len(bars) < window * 2 + 1:
            return pivots

        for index in range(window, len(bars) - window):
            bar = bars[index]
            neighbors = [
                *bars[index - window : index],
                *bars[index + 1 : index + window + 1],
            ]
            if all(bar.high > neighbor.high for neighbor in neighbors):
                pivots.append(
                    _Pivot(
                        index=index,
                        timestamp=bar.timestamp,
                        price=bar.high,
                        kind=PivotKind.HIGH,
                    )
                )
            if all(bar.low < neighbor.low for neighbor in neighbors):
                pivots.append(
                    _Pivot(
                        index=index,
                        timestamp=bar.timestamp,
                        price=bar.low,
                        kind=PivotKind.LOW,
                    )
                )
        pivots.sort(key=lambda pivot: (pivot.index, pivot.kind.value))
        return pivots
