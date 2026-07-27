"""Deterministic technical-analysis inputs and outputs.

These models form the boundary between the shared point-in-time Data Service
and tools local to the Technical Trader. They deliberately contain no
data-provider-specific types.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr


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


class AssetTechnicalAnalysis(ContractModel):
    artifact_id: NonEmptyStr
    symbol: NonEmptyStr
    last_bar_timestamp: datetime
    last_close: float = Field(gt=0)
    support_resistance_levels: list[SupportResistanceLevel] = Field(
        default_factory=list
    )
    chart_patterns: list[ChartPatternObservation] = Field(default_factory=list)


class TechnicalAnalysisReport(ContractModel):
    """Code-computed evidence supplied to the Technical Trader's LLM."""

    report_id: NonEmptyStr
    generated_by: Literal["deterministic_technical_analysis_toolkit"]
    toolkit_version: NonEmptyStr
    as_of_date: date
    assets: list[AssetTechnicalAnalysis] = Field(min_length=1)
    warnings: list[NonEmptyStr] = Field(default_factory=list)

    def level_ids(self) -> set[str]:
        return {
            level.level_id
            for asset in self.assets
            for level in asset.support_resistance_levels
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
        }
