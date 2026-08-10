"""Deterministic mapping from PM horizon language to Technical policy."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from math import ceil, sqrt
from typing import Any, Literal, Mapping

from protocols import PMMandate

from .executors import (
    HORIZON_ADAPTIVE_TREND_EXECUTOR_ID,
    INVERSE_PATTERN_EXECUTOR_ID,
    ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID,
    ROLLING_SUPPORT_REACTION_EXECUTOR_ID,
    ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID,
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
    review_interval_bars: int
    rolling_level_lookback_bars: int
    rolling_pivot_window: int
    rolling_merge_tolerance_percent: float
    rolling_min_touches: int
    volatility_lookback_bars: int
    profit_target_sigma_multiple: float
    stop_loss_sigma_multiple: float
    family_preference_weights: tuple[tuple[str, float], ...]
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
        value["family_preference_weights"] = dict(
            self.family_preference_weights
        )
        return value

    def family_weight(self, executor_id: str) -> float:
        return dict(self.family_preference_weights).get(executor_id, 0.0)

    @property
    def family_order(self) -> tuple[str, ...]:
        return tuple(
            executor_id
            for executor_id, _weight in sorted(
                self.family_preference_weights,
                key=lambda item: (-item[1], item[0]),
            )
        )


@dataclass(frozen=True, slots=True)
class HorizonEvaluationWindow:
    """Auditable date-span check for a horizon-sized primary evaluation."""

    expected_trading_days: int
    test_start_date: date
    test_end_date: date
    inclusive_calendar_days: int
    maximum_plausible_calendar_days: int

    def as_mapping(self) -> dict[str, Any]:
        return {
            "policy": "mandate_horizon_primary_window",
            "expected_trading_days": self.expected_trading_days,
            "test_start_date": self.test_start_date.isoformat(),
            "test_end_date": self.test_end_date.isoformat(),
            "inclusive_calendar_days": self.inclusive_calendar_days,
            "maximum_plausible_calendar_days": (
                self.maximum_plausible_calendar_days
            ),
            "exact_trading_bar_count_owned_by_shared_policy": True,
        }


def validate_horizon_evaluation_window(
    mandate: PMMandate,
    *,
    test_start_date: date,
    test_end_date: date,
) -> HorizonEvaluationWindow:
    """Reject a primary holdout grossly shorter or longer than the horizon.

    Exact exchange-session counting belongs to the injected shared evaluation
    policy because the Technical Trader does not own a market calendar. This
    boundary check still prevents, for example, evaluating a two-year mandate
    over one month or six years. The isolated harness verifies the exact bar
    count against its frozen fixture calendar.
    """

    if test_start_date > test_end_date:
        raise ValueError("test_start_date must not exceed test_end_date")
    profile = resolve_technical_horizon(mandate)
    expected = profile.horizon_trading_days
    inclusive_days = (test_end_date - test_start_date).days + 1
    approximate_calendar_days = ceil(expected * 7 / 5)
    tolerance_days = max(14, ceil(approximate_calendar_days * 0.15))
    maximum_calendar_days = approximate_calendar_days + tolerance_days
    if inclusive_days < expected or inclusive_days > maximum_calendar_days:
        raise ValueError(
            "The shared validation split is not compatible with the PM "
            f"horizon: expected exactly {expected} trading sessions, but "
            f"{test_start_date.isoformat()} through "
            f"{test_end_date.isoformat()} spans {inclusive_days} calendar "
            "days. The shared policy must resolve an exact horizon-sized "
            "market-session window."
        )
    return HorizonEvaluationWindow(
        expected_trading_days=expected,
        test_start_date=test_start_date,
        test_end_date=test_end_date,
        inclusive_calendar_days=inclusive_days,
        maximum_plausible_calendar_days=maximum_calendar_days,
    )


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
    return parsed


def _mandate_horizon_days(mandate: PMMandate) -> int:
    """Return the balanced operating horizon used by compatibility callers."""

    return _parsed_mandate_horizon_days(mandate) or 63


def _maximum_holding_days(mandate: PMMandate, horizon_days: int) -> int:
    configured = _days_from_mapping(mandate.risk_limits)
    return min(configured or horizon_days, horizon_days)


def resolve_technical_horizon(
    mandate: PMMandate,
) -> TechnicalHorizonProfile:
    """Resolve an auditable Technical horizon without consulting market data."""

    parsed_horizon_days = _parsed_mandate_horizon_days(mandate)
    used_conservative_default = parsed_horizon_days is None
    horizon_days = parsed_horizon_days or 63
    maximum_holding = _maximum_holding_days(mandate, horizon_days)
    resolution_fields = {
        "resolution_source": (
            "conservative_default"
            if used_conservative_default
            else "pm_mandate"
        ),
        "resolution_note": (
            "PM investment_horizon was absent or unparseable; Technical "
            "policy applied a balanced 63-trading-day operating horizon, "
            "multi-scale trend evidence, and explicit uncertainty disclosure."
            if used_conservative_default
            else None
        ),
    }
    def policy_fields(
        *,
        review_interval_bars: int,
        rolling_level_lookback_bars: int,
        rolling_pivot_window: int,
        volatility_lookback_bars: int,
        profit_target_sigma_multiple: float,
        stop_loss_sigma_multiple: float,
        family_weights: tuple[tuple[str, float], ...],
    ) -> dict[str, Any]:
        return {
            "review_interval_bars": review_interval_bars,
            "rolling_level_lookback_bars": rolling_level_lookback_bars,
            "rolling_pivot_window": rolling_pivot_window,
            "rolling_merge_tolerance_percent": 0.01,
            "rolling_min_touches": 2,
            "volatility_lookback_bars": volatility_lookback_bars,
            "profit_target_sigma_multiple": profit_target_sigma_multiple,
            "stop_loss_sigma_multiple": stop_loss_sigma_multiple,
            "family_preference_weights": family_weights,
        }

    if used_conservative_default:
        return TechnicalHorizonProfile(
            label="unspecified_balanced",
            horizon_trading_days=horizon_days,
            maximum_holding_bars=maximum_holding,
            moving_average_windows=((5, 20), (20, 50), (50, 200)),
            maximum_recent_cross_age_bars=63,
            maximum_level_distance_percent=8.0,
            **policy_fields(
                review_interval_bars=5,
                rolling_level_lookback_bars=252,
                rolling_pivot_window=3,
                volatility_lookback_bars=30,
                profit_target_sigma_multiple=1.75,
                stop_loss_sigma_multiple=1.25,
                family_weights=(
                    (HORIZON_ADAPTIVE_TREND_EXECUTOR_ID, 1.0),
                    (ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID, 0.9),
                    (ROLLING_SUPPORT_REACTION_EXECUTOR_ID, 0.85),
                    (ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID, 0.8),
                    (INVERSE_PATTERN_EXECUTOR_ID, 0.7),
                ),
            ),
            **resolution_fields,
        )
    if horizon_days <= 5:
        return TechnicalHorizonProfile(
            label="very_short_term",
            horizon_trading_days=horizon_days,
            maximum_holding_bars=maximum_holding,
            moving_average_windows=((3, 10), (5, 20)),
            maximum_recent_cross_age_bars=max(5, horizon_days * 2),
            maximum_level_distance_percent=3.0,
            **policy_fields(
                review_interval_bars=1,
                rolling_level_lookback_bars=63,
                rolling_pivot_window=2,
                volatility_lookback_bars=10,
                profit_target_sigma_multiple=1.25,
                stop_loss_sigma_multiple=1.0,
                family_weights=(
                    (ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID, 1.0),
                    (ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID, 0.95),
                    (ROLLING_SUPPORT_REACTION_EXECUTOR_ID, 0.9),
                    (HORIZON_ADAPTIVE_TREND_EXECUTOR_ID, 0.75),
                    (INVERSE_PATTERN_EXECUTOR_ID, 0.65),
                ),
            ),
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
            **policy_fields(
                review_interval_bars=1,
                rolling_level_lookback_bars=126,
                rolling_pivot_window=2,
                volatility_lookback_bars=20,
                profit_target_sigma_multiple=1.5,
                stop_loss_sigma_multiple=1.0,
                family_weights=(
                    (ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID, 1.0),
                    (ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID, 0.95),
                    (HORIZON_ADAPTIVE_TREND_EXECUTOR_ID, 0.9),
                    (ROLLING_SUPPORT_REACTION_EXECUTOR_ID, 0.85),
                    (INVERSE_PATTERN_EXECUTOR_ID, 0.7),
                ),
            ),
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
            **policy_fields(
                review_interval_bars=5,
                rolling_level_lookback_bars=252,
                rolling_pivot_window=3,
                volatility_lookback_bars=30,
                profit_target_sigma_multiple=1.75,
                stop_loss_sigma_multiple=1.25,
                family_weights=(
                    (HORIZON_ADAPTIVE_TREND_EXECUTOR_ID, 1.0),
                    (ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID, 0.95),
                    (ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID, 0.85),
                    (ROLLING_SUPPORT_REACTION_EXECUTOR_ID, 0.8),
                    (INVERSE_PATTERN_EXECUTOR_ID, 0.7),
                ),
            ),
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
            **policy_fields(
                review_interval_bars=10,
                rolling_level_lookback_bars=378,
                rolling_pivot_window=4,
                volatility_lookback_bars=42,
                profit_target_sigma_multiple=2.0,
                stop_loss_sigma_multiple=1.5,
                family_weights=(
                    (HORIZON_ADAPTIVE_TREND_EXECUTOR_ID, 1.0),
                    (ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID, 0.9),
                    (ROLLING_SUPPORT_REACTION_EXECUTOR_ID, 0.75),
                    (ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID, 0.7),
                    (INVERSE_PATTERN_EXECUTOR_ID, 0.65),
                ),
            ),
            **resolution_fields,
        )
    return TechnicalHorizonProfile(
        label="long_term",
        horizon_trading_days=horizon_days,
        maximum_holding_bars=maximum_holding,
        moving_average_windows=((50, 100), (50, 200)),
        maximum_recent_cross_age_bars=max(63, horizon_days),
        maximum_level_distance_percent=20.0,
        **policy_fields(
            review_interval_bars=21,
            rolling_level_lookback_bars=min(
                756, max(504, horizon_days)
            ),
            rolling_pivot_window=5,
            volatility_lookback_bars=63,
            profit_target_sigma_multiple=2.0,
            stop_loss_sigma_multiple=1.75,
            family_weights=(
                (HORIZON_ADAPTIVE_TREND_EXECUTOR_ID, 1.0),
                (ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID, 0.85),
                (ROLLING_SUPPORT_REACTION_EXECUTOR_ID, 0.65),
                (ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID, 0.6),
                (INVERSE_PATTERN_EXECUTOR_ID, 0.55),
            ),
        ),
        **resolution_fields,
    )


def _bounded(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _recency_score(age_calendar_days: int, horizon_bars: int) -> float:
    allowed_calendar_days = max(7.0, horizon_bars * 7.0 / 5.0)
    return _bounded(1.0 - max(age_calendar_days, 0) / allowed_calendar_days)


def _horizon_adjusted_score(
    base_score: float,
    *,
    executor_id: str,
    profile: TechnicalHorizonProfile,
) -> tuple[float, float]:
    """Blend evidence quality with an ex-ante horizon/family preference."""

    family_fit = _bounded(profile.family_weight(executor_id))
    return _bounded(0.80 * base_score + 0.20 * family_fit), family_fit


def _family_balanced_order(
    opportunities: list[TechnicalOpportunity],
    profile: TechnicalHorizonProfile,
) -> list[TechnicalOpportunity]:
    """Expose strong candidates from every applicable Technical family.

    This affects only evidence presentation order. It does not require the LLM
    to select a family or lower the evidence threshold.
    """

    queues: dict[str, list[TechnicalOpportunity]] = {}
    for opportunity in opportunities:
        queues.setdefault(opportunity.executor_id, []).append(opportunity)
    for queue in queues.values():
        queue.sort(
            key=lambda item: (
                -item.score,
                item.symbol,
                item.opportunity_id,
            )
        )
    family_order = [
        family for family in profile.family_order if queues.get(family)
    ]
    family_order.extend(
        family
        for family in sorted(queues)
        if family not in family_order
    )
    ordered: list[TechnicalOpportunity] = []
    while any(queues.get(family) for family in family_order):
        for family in family_order:
            queue = queues.get(family, [])
            if queue:
                ordered.append(queue.pop(0))
    return ordered


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
                ROLLING_SUPPORT_REACTION_EXECUTOR_ID,
                "rolling support reaction",
            ),
            (
                PriceLevelKind.RESISTANCE,
                ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID,
                "rolling resistance breakout",
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
            adjusted_score, family_fit = _horizon_adjusted_score(
                score,
                executor_id=executor_id,
                profile=profile,
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
                    score=adjusted_score,
                    score_components={
                        **components,
                        "horizon_family_fit": family_fit,
                    },
                    horizon_trading_days=profile.horizon_trading_days,
                    rationale=(
                        f"Deterministic {label} opportunity within the "
                        "mandate-specific actionability distance. The cited "
                        "training level establishes family eligibility; "
                        "execution recalculates reliable levels from past "
                        "bars at the code-owned review cadence."
                    ),
                )
            )

        for observation in asset.available_moving_averages():
            windows = (observation.fast_window, observation.slow_window)
            if windows not in allowed_windows:
                continue
            if observation.relationship is not MovingAverageRelationship.BULLISH:
                continue
            recency = (
                _bounded(
                    1.0
                    - observation.bars_since_latest_cross
                    / profile.maximum_recent_cross_age_bars
                )
                if (
                    observation.latest_cross_direction
                    is MovingAverageCrossDirection.BULLISH
                    and observation.bars_since_latest_cross is not None
                )
                else 0.5
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
            base_score = (
                0.35 * recency
                + 0.35 * strength
                + 0.30 * daily_movement_capacity
            )
            adjusted_score, family_fit = _horizon_adjusted_score(
                base_score,
                executor_id=HORIZON_ADAPTIVE_TREND_EXECUTOR_ID,
                profile=profile,
            )
            opportunities.append(
                TechnicalOpportunity(
                    opportunity_id=(
                        f"{report.report_id}.horizon-{profile.horizon_trading_days}."
                        f"{asset.symbol}.{HORIZON_ADAPTIVE_TREND_EXECUTOR_ID}."
                        f"{observation.fast_window}-{observation.slow_window}"
                    ),
                    rank=1,
                    symbol=asset.symbol,
                    executor_id=HORIZON_ADAPTIVE_TREND_EXECUTOR_ID,
                    evidence_ids=[observation.moving_average_id],
                    score=adjusted_score,
                    score_components={
                        "bullish_trend_recency_or_continuity": recency,
                        "volatility_scaled_trend_strength": strength,
                        "capped_daily_movement_capacity": (
                            daily_movement_capacity
                        ),
                        "horizon_family_fit": family_fit,
                    },
                    horizon_trading_days=profile.horizon_trading_days,
                    rationale=(
                        "Currently bullish moving-average relationship at a "
                        "mandate-compatible lookback pair. Execution "
                        "recalculates both averages from past bars and can "
                        "enter a prevailing qualified trend at each review."
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
                base_score = 0.70 * recency + 0.30 * daily_movement_capacity
                adjusted_score, family_fit = _horizon_adjusted_score(
                    base_score,
                    executor_id=INVERSE_PATTERN_EXECUTOR_ID,
                    profile=profile,
                )
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
                        score=adjusted_score,
                        score_components={
                            "confirmation_recency": recency,
                            "capped_daily_movement_capacity": (
                                daily_movement_capacity
                            ),
                            "horizon_family_fit": family_fit,
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
            base_score = 0.70 * resistance_score + 0.30 * relative_volume
            adjusted_score, family_fit = _horizon_adjusted_score(
                base_score,
                executor_id=ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID,
                profile=profile,
            )
            opportunities.append(
                TechnicalOpportunity(
                    opportunity_id=(
                        f"{report.report_id}.horizon-{profile.horizon_trading_days}."
                        f"{asset.symbol}.{ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID}"
                    ),
                    rank=1,
                    symbol=asset.symbol,
                    executor_id=ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID,
                    evidence_ids=[level.level_id, volume.volume_id],
                    score=adjusted_score,
                    score_components={
                        **{
                            f"resistance_{key}": value
                            for key, value in resistance_components.items()
                        },
                        "relative_volume": relative_volume,
                        "horizon_family_fit": family_fit,
                    },
                    horizon_trading_days=profile.horizon_trading_days,
                    rationale=(
                        "Nearby resistance with contemporaneous relative-"
                        "volume evidence. Execution refreshes the resistance "
                        "from past bars at the code-owned review cadence."
                    ),
                )
            )

    opportunities = _family_balanced_order(opportunities, profile)
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
        review_interval_bars=profile.review_interval_bars,
        rolling_level_lookback_bars=profile.rolling_level_lookback_bars,
        rolling_pivot_window=profile.rolling_pivot_window,
        rolling_merge_tolerance_percent=(
            profile.rolling_merge_tolerance_percent
        ),
        rolling_min_touches=profile.rolling_min_touches,
        volatility_lookback_bars=profile.volatility_lookback_bars,
        profit_target_sigma_multiple=(
            profile.profit_target_sigma_multiple
        ),
        stop_loss_sigma_multiple=profile.stop_loss_sigma_multiple,
        family_preference_weights=dict(profile.family_preference_weights),
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
    "HorizonEvaluationWindow",
    "TechnicalHorizonProfile",
    "resolve_technical_horizon",
    "screen_horizon_opportunities",
    "validate_horizon_evaluation_window",
]
