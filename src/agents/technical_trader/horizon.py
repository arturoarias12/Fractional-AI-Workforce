"""Deterministic mapping from PM horizon language to Technical policy."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from math import sqrt
from typing import Any, Literal, Mapping

from protocols import PMMandate

from .executors import (
    INVERSE_PATTERN_EXECUTOR_ID,
    MOVING_AVERAGE_TREND_EXECUTOR_ID,
    RESISTANCE_BREAKOUT_EXECUTOR_ID,
    SUPPORT_REACTION_EXECUTOR_ID,
    VOLUME_BREAKOUT_EXECUTOR_ID,
)
from .models.technical_analysis import (
    ChartPatternStatus,
    ChartPatternType,
    MovingAverageConfig,
    MovingAverageCrossDirection,
    MovingAverageRelationship,
    PriceLevelKind,
    TechnicalAnalysisReport,
    TechnicalHorizonContext,
    TechnicalOpportunity,
)


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
}


@dataclass(frozen=True, slots=True)
class TechnicalHorizonProfile:
    label: str
    horizon_trading_days: int
    maximum_holding_bars: int
    moving_average_windows: tuple[tuple[int, int], ...]
    maximum_recent_cross_age_bars: int
    maximum_level_distance_percent: float
    minimum_training_observations: int = 252
    resolution_source: Literal[
        "pm_mandate", "conservative_default"
    ] = "pm_mandate"
    resolution_note: str | None = None

    def as_prompt_mapping(self) -> dict[str, Any]:
        value = asdict(self)
        value["moving_average_windows"] = [
            {"fast_window": fast, "slow_window": slow}
            for fast, slow in self.moving_average_windows
        ]
        return value


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer() and value > 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _days_from_mapping(value: Mapping[str, Any]) -> int | None:
    for key in (
        "trading_days",
        "horizon_trading_days",
        "days",
        "maximum_holding_period_trading_days",
        "maximum_holding_bars",
    ):
        parsed = _positive_integer(value.get(key))
        if parsed is not None:
            return parsed
    for key, multiplier in (("weeks", 5), ("months", 21), ("years", 252)):
        parsed = _positive_integer(value.get(key))
        if parsed is not None:
            return parsed * multiplier
    count = next(
        (
            parsed
            for key in ("value", "count", "length")
            if (parsed := _positive_integer(value.get(key))) is not None
        ),
        None,
    )
    unit = str(value.get("unit", value.get("units", ""))).casefold().strip()
    if count is not None and unit:
        multiplier = {
            "bar": 1,
            "bars": 1,
            "trading day": 1,
            "trading days": 1,
            "day": 1,
            "days": 1,
            "week": 5,
            "weeks": 5,
            "month": 21,
            "months": 21,
            "year": 252,
            "years": 252,
        }.get(unit)
        if multiplier is not None:
            return count * multiplier
    description = value.get("description")
    return _days_from_text(str(description)) if description else None


def _days_from_text(value: str) -> int | None:
    text = value.casefold().replace("-", " ")
    number_pattern = r"(\d+|" + "|".join(_NUMBER_WORDS) + r")"
    match = re.search(
        number_pattern
        + r"\s*(trading\s+)?(day|days|week|weeks|month|months|year|years)\b",
        text,
    )
    if match:
        raw_number = match.group(1)
        count = (
            int(raw_number)
            if raw_number.isdigit()
            else _NUMBER_WORDS[raw_number]
        )
        unit = match.group(3)
        multiplier = {
            "day": 1,
            "days": 1,
            "week": 5,
            "weeks": 5,
            "month": 21,
            "months": 21,
            "year": 252,
            "years": 252,
        }[unit]
        return count * multiplier
    if "short term" in text or "tactical" in text:
        return 20
    if "medium term" in text:
        return 63
    if "long term" in text:
        return 252
    return None


def _parsed_mandate_horizon_days(mandate: PMMandate) -> int | None:
    value = mandate.investment_horizon
    if isinstance(value, Mapping):
        parsed = _days_from_mapping(value)
    elif isinstance(value, str):
        parsed = _days_from_text(value)
    else:
        parsed = None
    return min(parsed, 1_260) if parsed is not None else None


def _mandate_horizon_days(mandate: PMMandate) -> int:
    """Return a conservative usable horizon for compatibility callers."""

    return _parsed_mandate_horizon_days(mandate) or 5


def _maximum_holding_days(mandate: PMMandate, horizon_days: int) -> int:
    configured = _days_from_mapping(mandate.risk_limits)
    return min(configured or horizon_days, horizon_days)


def resolve_technical_horizon(
    mandate: PMMandate,
) -> TechnicalHorizonProfile:
    """Resolve an auditable Technical horizon without consulting market data."""

    parsed_horizon_days = _parsed_mandate_horizon_days(mandate)
    used_conservative_default = parsed_horizon_days is None
    horizon_days = parsed_horizon_days or 5
    maximum_holding = _maximum_holding_days(mandate, horizon_days)
    resolution_fields = {
        "resolution_source": (
            "conservative_default"
            if used_conservative_default
            else "pm_mandate"
        ),
        "resolution_note": (
            "PM investment_horizon was absent or unparseable; Technical "
            "policy applied a conservative five-trading-day default."
            if used_conservative_default
            else None
        ),
    }
    if horizon_days <= 5:
        return TechnicalHorizonProfile(
            label="very_short_term",
            horizon_trading_days=horizon_days,
            maximum_holding_bars=maximum_holding,
            moving_average_windows=((3, 10), (5, 20)),
            maximum_recent_cross_age_bars=max(5, horizon_days * 2),
            maximum_level_distance_percent=3.0,
            **resolution_fields,
        )
    if horizon_days <= 20:
        return TechnicalHorizonProfile(
            label="short_term",
            horizon_trading_days=horizon_days,
            maximum_holding_bars=maximum_holding,
            moving_average_windows=((5, 20), (10, 30)),
            maximum_recent_cross_age_bars=max(10, horizon_days * 2),
            maximum_level_distance_percent=5.0,
            **resolution_fields,
        )
    if horizon_days <= 63:
        return TechnicalHorizonProfile(
            label="intermediate",
            horizon_trading_days=horizon_days,
            maximum_holding_bars=maximum_holding,
            moving_average_windows=((10, 30), (20, 50)),
            maximum_recent_cross_age_bars=max(20, horizon_days),
            maximum_level_distance_percent=8.0,
            **resolution_fields,
        )
    if horizon_days <= 126:
        return TechnicalHorizonProfile(
            label="medium_term",
            horizon_trading_days=horizon_days,
            maximum_holding_bars=maximum_holding,
            moving_average_windows=((20, 50), (50, 100)),
            maximum_recent_cross_age_bars=max(40, horizon_days),
            maximum_level_distance_percent=12.0,
            **resolution_fields,
        )
    return TechnicalHorizonProfile(
        label="long_term",
        horizon_trading_days=horizon_days,
        maximum_holding_bars=maximum_holding,
        moving_average_windows=((50, 100), (50, 200)),
        maximum_recent_cross_age_bars=max(63, horizon_days),
        maximum_level_distance_percent=20.0,
        **resolution_fields,
    )


def _bounded(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _recency_score(age_calendar_days: int, horizon_bars: int) -> float:
    allowed_calendar_days = max(7.0, horizon_bars * 7.0 / 5.0)
    return _bounded(1.0 - max(age_calendar_days, 0) / allowed_calendar_days)


def screen_horizon_opportunities(
    report: TechnicalAnalysisReport,
    profile: TechnicalHorizonProfile,
) -> TechnicalAnalysisReport:
    """Rank ex-ante opportunities using only the frozen Technical report."""

    reliable_level_ids = report.reliable_level_ids()
    opportunities: list[TechnicalOpportunity] = []
    allowed_windows = set(profile.moving_average_windows)
    for asset in report.assets:
        if int(asset.observation_count or 0) < profile.minimum_training_observations:
            continue
        daily_movement_capacity = _bounded(
            float(asset.daily_return_volatility or 0.0) * 100.0
        )
        nearby_levels = [
            level
            for level in asset.support_resistance_levels
            if level.level_id in reliable_level_ids
            and abs(level.distance_from_last_close_percent)
            <= profile.maximum_level_distance_percent
        ]

        def level_score(level: Any) -> tuple[float, dict[str, float]]:
            proximity = _bounded(
                1.0
                - abs(level.distance_from_last_close_percent)
                / profile.maximum_level_distance_percent
            )
            touches = _bounded(float(level.touches) / 5.0)
            age_days = (
                asset.last_bar_timestamp.date()
                - level.last_touched_at.date()
            ).days
            recency = _recency_score(
                age_days,
                max(profile.horizon_trading_days * 4, 20),
            )
            components = {
                "proximity": proximity,
                "repeated_touch_quality": touches,
                "recency": recency,
                "capped_daily_movement_capacity": daily_movement_capacity,
            }
            return (
                0.30 * proximity
                + 0.20 * touches
                + 0.15 * recency
                + 0.35 * daily_movement_capacity,
                components,
            )

        for kind, executor_id, label in (
            (
                PriceLevelKind.SUPPORT,
                SUPPORT_REACTION_EXECUTOR_ID,
                "support reaction",
            ),
            (
                PriceLevelKind.RESISTANCE,
                RESISTANCE_BREAKOUT_EXECUTOR_ID,
                "resistance breakout",
            ),
        ):
            candidates = [level for level in nearby_levels if level.kind is kind]
            if not candidates:
                continue
            scored = [(*level_score(level), level) for level in candidates]
            score, components, level = max(
                scored,
                key=lambda item: (
                    item[0],
                    item[2].touches,
                    -abs(item[2].distance_from_last_close_percent),
                    item[2].level_id,
                ),
            )
            opportunities.append(
                TechnicalOpportunity(
                    opportunity_id=(
                        f"{report.report_id}.horizon-{profile.horizon_trading_days}."
                        f"{asset.symbol}.{executor_id}"
                    ),
                    rank=1,
                    symbol=asset.symbol,
                    executor_id=executor_id,
                    evidence_ids=[level.level_id],
                    score=score,
                    score_components=components,
                    horizon_trading_days=profile.horizon_trading_days,
                    rationale=(
                        f"Deterministic {label} opportunity within the "
                        "mandate-specific actionability distance."
                    ),
                )
            )

        for observation in asset.available_moving_averages():
            windows = (observation.fast_window, observation.slow_window)
            if windows not in allowed_windows:
                continue
            if (
                observation.relationship is not MovingAverageRelationship.BULLISH
                or observation.latest_cross_direction
                is not MovingAverageCrossDirection.BULLISH
                or observation.bars_since_latest_cross is None
                or observation.bars_since_latest_cross
                > profile.maximum_recent_cross_age_bars
            ):
                continue
            recency = _bounded(
                1.0
                - observation.bars_since_latest_cross
                / profile.maximum_recent_cross_age_bars
            )
            daily_volatility_percent = max(
                float(asset.daily_return_volatility or 0.0) * 100.0,
                1e-9,
            )
            horizon_move = daily_volatility_percent * sqrt(
                profile.horizon_trading_days
            )
            strength = _bounded(
                max(observation.spread_percent, 0.0) / horizon_move
            )
            opportunities.append(
                TechnicalOpportunity(
                    opportunity_id=(
                        f"{report.report_id}.horizon-{profile.horizon_trading_days}."
                        f"{asset.symbol}.{MOVING_AVERAGE_TREND_EXECUTOR_ID}."
                        f"{observation.fast_window}-{observation.slow_window}"
                    ),
                    rank=1,
                    symbol=asset.symbol,
                    executor_id=MOVING_AVERAGE_TREND_EXECUTOR_ID,
                    evidence_ids=[observation.moving_average_id],
                    score=(
                        0.45 * recency
                        + 0.25 * strength
                        + 0.30 * daily_movement_capacity
                    ),
                    score_components={
                        "recent_bullish_crossover": recency,
                        "volatility_scaled_trend_strength": strength,
                        "capped_daily_movement_capacity": (
                            daily_movement_capacity
                        ),
                    },
                    horizon_trading_days=profile.horizon_trading_days,
                    rationale=(
                        "Currently bullish moving-average relationship with a "
                        "recent bullish crossover at a mandate-compatible "
                        "lookback pair."
                    ),
                )
            )

        confirmed_inverse = [
            pattern
            for pattern in asset.chart_patterns
            if pattern.pattern_type
            is ChartPatternType.INVERSE_HEAD_AND_SHOULDERS
            and pattern.status is ChartPatternStatus.CONFIRMED
            and pattern.confirmation_timestamp is not None
        ]
        if confirmed_inverse:
            pattern = max(
                confirmed_inverse,
                key=lambda item: (
                    item.confirmation_timestamp.timestamp()
                    if item.confirmation_timestamp is not None
                    else 0.0
                ),
            )
            confirmation_timestamp = pattern.confirmation_timestamp
            if confirmation_timestamp is None:
                raise RuntimeError(
                    "Confirmed-pattern filtering lost its timestamp invariant."
                )
            age_days = (
                asset.last_bar_timestamp.date()
                - confirmation_timestamp.date()
            ).days
            recency = _recency_score(
                age_days,
                profile.maximum_recent_cross_age_bars,
            )
            if recency > 0:
                opportunities.append(
                    TechnicalOpportunity(
                        opportunity_id=(
                            f"{report.report_id}.horizon-"
                            f"{profile.horizon_trading_days}.{asset.symbol}."
                            f"{INVERSE_PATTERN_EXECUTOR_ID}"
                        ),
                        rank=1,
                        symbol=asset.symbol,
                        executor_id=INVERSE_PATTERN_EXECUTOR_ID,
                        evidence_ids=[pattern.pattern_id],
                        score=(
                            0.70 * recency
                            + 0.30 * daily_movement_capacity
                        ),
                        score_components={
                            "confirmation_recency": recency,
                            "capped_daily_movement_capacity": (
                                daily_movement_capacity
                            ),
                        },
                        horizon_trading_days=profile.horizon_trading_days,
                        rationale=(
                            "Recently confirmed inverse-head-and-shoulders "
                            "breakout aligned with the mandate horizon."
                        ),
                    )
                )

        volume = asset.volume_observation
        resistances = [
            level
            for level in nearby_levels
            if level.kind is PriceLevelKind.RESISTANCE
        ]
        if volume is not None and resistances:
            scored_resistances = [
                (*level_score(level), level) for level in resistances
            ]
            resistance_score, resistance_components, level = max(
                scored_resistances,
                key=lambda item: (item[0], item[2].level_id),
            )
            relative_volume = _bounded(volume.relative_volume / 2.0)
            opportunities.append(
                TechnicalOpportunity(
                    opportunity_id=(
                        f"{report.report_id}.horizon-{profile.horizon_trading_days}."
                        f"{asset.symbol}.{VOLUME_BREAKOUT_EXECUTOR_ID}"
                    ),
                    rank=1,
                    symbol=asset.symbol,
                    executor_id=VOLUME_BREAKOUT_EXECUTOR_ID,
                    evidence_ids=[level.level_id, volume.volume_id],
                    score=0.70 * resistance_score + 0.30 * relative_volume,
                    score_components={
                        **{
                            f"resistance_{key}": value
                            for key, value in resistance_components.items()
                        },
                        "relative_volume": relative_volume,
                    },
                    horizon_trading_days=profile.horizon_trading_days,
                    rationale=(
                        "Nearby resistance with contemporaneous relative-"
                        "volume evidence."
                    ),
                )
            )

    opportunities.sort(
        key=lambda item: (
            -item.score,
            item.symbol,
            item.executor_id,
            item.opportunity_id,
        )
    )
    ranked = [
        opportunity.model_copy(update={"rank": rank})
        for rank, opportunity in enumerate(opportunities, start=1)
    ]
    context = TechnicalHorizonContext(
        label=profile.label,
        horizon_trading_days=profile.horizon_trading_days,
        maximum_holding_bars=profile.maximum_holding_bars,
        moving_average_windows=[
            MovingAverageConfig(fast_window=fast, slow_window=slow)
            for fast, slow in profile.moving_average_windows
        ],
        maximum_recent_cross_age_bars=profile.maximum_recent_cross_age_bars,
        maximum_level_distance_percent=(
            profile.maximum_level_distance_percent
        ),
        minimum_training_observations=profile.minimum_training_observations,
        resolution_source=profile.resolution_source,
        resolution_note=profile.resolution_note,
    )
    warnings = list(report.warnings)
    if profile.resolution_note and profile.resolution_note not in warnings:
        warnings.append(profile.resolution_note)
    return report.model_copy(
        update={
            "horizon_context": context,
            "horizon_opportunities": ranked,
            "warnings": warnings,
        }
    )


__all__ = [
    "TechnicalHorizonProfile",
    "resolve_technical_horizon",
    "screen_horizon_opportunities",
]
