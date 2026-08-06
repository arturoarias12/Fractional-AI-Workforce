"""Deterministic technical-analysis inputs and outputs.

These models form the boundary between the shared point-in-time Data Service
and tools local to the Technical Trader. They deliberately contain no
data-provider-specific types.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from protocols import ContractModel, NonEmptyStr


class PriceBar(ContractModel):
    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float | None = Field(default=None, ge=0)

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Price-bar timestamps must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_ohlc(self) -> "PriceBar":
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("high must be greater than or equal to OHLC values.")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("low must be less than or equal to OHLC values.")
        return self


class PriceSeries(ContractModel):
    """One adjusted or unadjusted OHLCV series supplied by a data adapter."""

    artifact_id: NonEmptyStr
    symbol: NonEmptyStr
    as_of_date: date
    frequency: NonEmptyStr
    adjustment: NonEmptyStr | None = None
    bars: list[PriceBar] = Field(min_length=5)

    @model_validator(mode="after")
    def validate_chronology(self) -> "PriceSeries":
        timestamps = [bar.timestamp for bar in self.bars]
        if timestamps != sorted(timestamps) or len(timestamps) != len(
            set(timestamps)
        ):
            raise ValueError(
                "Price bars must be strictly increasing with no duplicate timestamps."
            )
        if timestamps[-1].date() > self.as_of_date:
            raise ValueError("Price series contains a bar after as_of_date.")
        return self


class PivotKind(StrEnum):
    HIGH = "high"
    LOW = "low"


class PriceLevelKind(StrEnum):
    SUPPORT = "support"
    RESISTANCE = "resistance"


class SupportResistanceConfig(ContractModel):
    pivot_window: int = Field(default=2, ge=1, le=25)
    merge_tolerance_percent: float = Field(default=0.01, gt=0, le=0.10)
    min_touches: int = Field(default=2, ge=1, le=20)
    max_levels_per_kind: int = Field(default=8, ge=1, le=50)


class SupportResistanceLevel(ContractModel):
    level_id: NonEmptyStr
    kind: PriceLevelKind
    price: float = Field(gt=0)
    touches: int = Field(ge=1)
    first_touched_at: datetime
    last_touched_at: datetime
    source_pivots: list[PivotKind] = Field(min_length=1)
    distance_from_last_close_percent: float
    used_range_fallback: bool = False


class ChartPatternType(StrEnum):
    HEAD_AND_SHOULDERS = "head_and_shoulders"
    INVERSE_HEAD_AND_SHOULDERS = "inverse_head_and_shoulders"


class ChartPatternStatus(StrEnum):
    FORMING = "forming"
    CONFIRMED = "confirmed"


class ChartPatternConfig(ContractModel):
    pivot_window: int = Field(default=2, ge=1, le=25)
    shoulder_tolerance_percent: float = Field(default=0.04, gt=0, le=0.20)
    head_prominence_percent: float = Field(default=0.03, gt=0, le=0.50)
    min_separation_bars: int = Field(default=2, ge=1, le=50)
    max_pattern_span_bars: int = Field(default=126, ge=5, le=756)
    max_patterns_per_series: int = Field(default=5, ge=1, le=25)


class PatternPoint(ContractModel):
    label: Literal["left_shoulder", "head", "right_shoulder"]
    bar_index: int = Field(ge=0)
    timestamp: datetime
    price: float = Field(gt=0)


class ChartPatternObservation(ContractModel):
    """A deterministic geometric observation, not a trading recommendation."""

    pattern_id: NonEmptyStr
    pattern_type: ChartPatternType
    status: ChartPatternStatus
    points: list[PatternPoint] = Field(min_length=3, max_length=3)
    neckline_price: float = Field(gt=0)
    confirmation_timestamp: datetime | None = None
    notes: list[NonEmptyStr] = Field(default_factory=list)


class MovingAverageRelationship(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class MovingAverageCrossDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class MovingAverageConfig(ContractModel):
    fast_window: int = Field(default=20, ge=2, le=252)
    slow_window: int = Field(default=50, ge=3, le=504)
    neutral_band_percent: float = Field(default=0.001, ge=0, le=0.05)

    @model_validator(mode="after")
    def require_ordered_windows(self) -> "MovingAverageConfig":
        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be below slow_window.")
        return self


class MovingAverageObservation(ContractModel):
    moving_average_id: NonEmptyStr
    fast_window: int = Field(ge=2)
    slow_window: int = Field(ge=3)
    fast_average: float = Field(gt=0)
    slow_average: float = Field(gt=0)
    spread_percent: float
    relationship: MovingAverageRelationship
    latest_cross_direction: MovingAverageCrossDirection | None = None
    latest_cross_timestamp: datetime | None = None
    bars_since_latest_cross: int | None = Field(default=None, ge=0)


class VolumeAnalysisConfig(ContractModel):
    lookback_window: int = Field(default=20, ge=2, le=252)


class VolumeObservation(ContractModel):
    volume_id: NonEmptyStr
    lookback_window: int = Field(ge=2)
    latest_volume: float = Field(ge=0)
    average_prior_volume: float = Field(gt=0)
    relative_volume: float = Field(ge=0)
    available_observations: int = Field(ge=1)
    latest_close_return_percent: float


class TechnicalHorizonContext(ContractModel):
    label: NonEmptyStr
    horizon_trading_days: int = Field(ge=1, le=1260)
    maximum_holding_bars: int = Field(ge=1, le=1260)
    moving_average_windows: list[MovingAverageConfig] = Field(min_length=1)
    maximum_recent_cross_age_bars: int = Field(ge=1)
    maximum_level_distance_percent: float = Field(gt=0)
    minimum_training_observations: int = Field(ge=5)
    resolution_source: Literal["pm_mandate", "conservative_default"] = (
        "pm_mandate"
    )
    resolution_note: NonEmptyStr | None = None


class TechnicalOpportunity(ContractModel):
    opportunity_id: NonEmptyStr
    rank: int = Field(ge=1)
    symbol: NonEmptyStr
    executor_id: NonEmptyStr
    evidence_ids: list[NonEmptyStr] = Field(min_length=1)
    score: float = Field(ge=0, le=1)
    score_components: dict[str, float] = Field(default_factory=dict)
    horizon_trading_days: int = Field(ge=1)
    rationale: NonEmptyStr
    additional_fields: dict[str, Any] = Field(default_factory=dict)


class AssetTechnicalAnalysis(ContractModel):
    artifact_id: NonEmptyStr
    symbol: NonEmptyStr
    first_bar_timestamp: datetime | None = None
    last_bar_timestamp: datetime
    observation_count: int | None = Field(default=None, ge=5)
    last_close: float = Field(gt=0)
    daily_return_volatility: float | None = Field(default=None, ge=0)
    annualized_volatility: float | None = Field(default=None, ge=0)
    support_resistance_levels: list[SupportResistanceLevel] = Field(
        default_factory=list
    )
    chart_patterns: list[ChartPatternObservation] = Field(default_factory=list)
    moving_averages: list[MovingAverageObservation] = Field(
        default_factory=list
    )
    moving_average: MovingAverageObservation | None = None
    volume_observation: VolumeObservation | None = None

    @model_validator(mode="after")
    def synchronize_moving_average_compatibility(
        self,
    ) -> "AssetTechnicalAnalysis":
        observations = list(self.moving_averages)
        if self.moving_average is not None and all(
            item.moving_average_id != self.moving_average.moving_average_id
            for item in observations
        ):
            observations.append(self.moving_average)
        observations.sort(key=lambda item: (item.slow_window, item.fast_window))
        legacy = self.moving_average
        if legacy is None and observations:
            legacy = next(
                (
                    item
                    for item in observations
                    if (item.fast_window, item.slow_window) == (20, 50)
                ),
                observations[0],
            )
        object.__setattr__(self, "moving_averages", observations)
        object.__setattr__(self, "moving_average", legacy)
        return self

    def available_moving_averages(self) -> tuple[MovingAverageObservation, ...]:
        return tuple(self.moving_averages)


class TechnicalAnalysisReport(ContractModel):
    """Code-computed evidence supplied to the Technical Trader's LLM."""

    report_id: NonEmptyStr
    generated_by: Literal["deterministic_technical_analysis_toolkit"]
    toolkit_version: NonEmptyStr
    as_of_date: date
    assets: list[AssetTechnicalAnalysis] = Field(min_length=1)
    horizon_context: TechnicalHorizonContext | None = None
    horizon_opportunities: list[TechnicalOpportunity] = Field(
        default_factory=list
    )
    warnings: list[NonEmptyStr] = Field(default_factory=list)

    def level_ids(self) -> set[str]:
        return {
            level.level_id
            for asset in self.assets
            for level in asset.support_resistance_levels
        }

    def reliable_level_ids(self) -> set[str]:
        """Return structural levels that retain their current semantic side."""

        return {
            level.level_id
            for asset in self.assets
            for level in asset.support_resistance_levels
            if not level.used_range_fallback
            and (
                (
                    level.kind is PriceLevelKind.SUPPORT
                    and level.price <= asset.last_close
                )
                or (
                    level.kind is PriceLevelKind.RESISTANCE
                    and level.price >= asset.last_close
                )
            )
        }

    def evidence_ids(self) -> set[str]:
        return {
            self.report_id,
            *self.level_ids(),
            *(
                pattern.pattern_id
                for asset in self.assets
                for pattern in asset.chart_patterns
            ),
            *(
                observation.moving_average_id
                for asset in self.assets
                for observation in asset.available_moving_averages()
            ),
            *(
                asset.volume_observation.volume_id
                for asset in self.assets
                if asset.volume_observation is not None
            ),
        }

    def pattern_ids(self) -> set[str]:
        return {
            pattern.pattern_id
            for asset in self.assets
            for pattern in asset.chart_patterns
        }

    def moving_average_ids(self) -> set[str]:
        return {
            observation.moving_average_id
            for asset in self.assets
            for observation in asset.available_moving_averages()
        }

    def volume_ids(self) -> set[str]:
        return {
            asset.volume_observation.volume_id
            for asset in self.assets
            if asset.volume_observation is not None
        }
