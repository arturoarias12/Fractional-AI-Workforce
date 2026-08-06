"""Stable Technical Trader executor identities and LLM-facing contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SUPPORT_REACTION_EXECUTOR_ID = "technical.support_reaction.v1"
RESISTANCE_BREAKOUT_EXECUTOR_ID = "technical.resistance_breakout.v1"
MOVING_AVERAGE_TREND_EXECUTOR_ID = "technical.moving_average_trend.v1"
VOLUME_BREAKOUT_EXECUTOR_ID = "technical.volume_confirmed_breakout.v1"
INVERSE_PATTERN_EXECUTOR_ID = (
    "technical.inverse_head_shoulders_breakout.v1"
)
HEAD_PATTERN_EXECUTOR_ID = "technical.head_shoulders_breakdown.v1"
MULTI_ASSET_PORTFOLIO_EXECUTOR_ID = "technical.multi_asset_portfolio.v1"
BENCHMARK_FALLBACK_EXECUTOR_ID = (
    "technical.benchmark_buy_and_hold_fallback.v1"
)
TARGET_PORTFOLIO_ASSET_COUNT = 10

EvidenceKind = Literal[
    "support",
    "resistance",
    "moving_average",
    "volume",
    "inverse_head_and_shoulders",
    "head_and_shoulders",
    "per_sleeve_family_evidence",
    "technical_report",
]


@dataclass(frozen=True, slots=True)
class TechnicalExecutorSpec:
    executor_id: str
    strategy_family: str
    description: str
    evidence_requirements: tuple[EvidenceKind, ...]
    parameters: tuple[str, ...]
    supports_short: bool = False


_RISK_PARAMETERS = (
    "symbol",
    "target_weight",
    "max_holding_bars",
    "volatility_lookback_bars",
    "profit_target_sigma_multiple",
    "stop_loss_sigma_multiple",
)

TECHNICAL_EXECUTOR_SPECS: tuple[TechnicalExecutorSpec, ...] = (
    TechnicalExecutorSpec(
        executor_id=BENCHMARK_FALLBACK_EXECUTOR_ID,
        strategy_family="benchmark_buy_and_hold_fallback",
        description=(
            "Code-owned long-only fallback that tracks the requested "
            "benchmark when the Technical portfolio does not strictly beat "
            "it under the configured benchmark-selection policy."
        ),
        evidence_requirements=("technical_report",),
        parameters=("symbol", "target_weight"),
    ),
    TechnicalExecutorSpec(
        executor_id=MULTI_ASSET_PORTFOLIO_EXECUTOR_ID,
        strategy_family="multi_asset_technical_portfolio",
        description=(
            "One long-only portfolio candidate containing up to 10 uniquely "
            "identified ETF sleeves. Each sleeve uses one deterministic "
            "Technical family and its own cited training evidence; code binds "
            "evidence-derived numeric parameters from those IDs."
        ),
        evidence_requirements=("per_sleeve_family_evidence",),
        parameters=(
            "target_asset_count",
            "selected_asset_count",
            "portfolio_target_gross_weight",
            "allocation_method",
            "selection_threshold",
            "omission_rationale",
            "common_risk_parameters",
            "sleeves",
        ),
    ),
    TechnicalExecutorSpec(
        executor_id=SUPPORT_REACTION_EXECUTOR_ID,
        strategy_family="support_reaction",
        description=(
            "Long-only reaction inside a reliable support zone with separate "
            "entry-floor and technical-invalidation buffers."
        ),
        evidence_requirements=("support",),
        parameters=(
            *_RISK_PARAMETERS,
            "anchor_level",
            "entry_buffer_percent",
            "support_entry_floor_buffer_percent",
            "technical_invalidation_buffer_percent",
        ),
    ),
    TechnicalExecutorSpec(
        executor_id=RESISTANCE_BREAKOUT_EXECUTOR_ID,
        strategy_family="resistance_breakout",
        description=(
            "Long-only crossing from below a reliable resistance threshold, "
            "with re-arming only after price returns below the threshold."
        ),
        evidence_requirements=("resistance",),
        parameters=(
            *_RISK_PARAMETERS,
            "anchor_level",
            "entry_buffer_percent",
            "technical_invalidation_buffer_percent",
        ),
    ),
    TechnicalExecutorSpec(
        executor_id=MOVING_AVERAGE_TREND_EXECUTOR_ID,
        strategy_family="moving_average_trend",
        description=(
            "Long-only fast/slow simple-moving-average bullish crossover with "
            "a bearish crossover or slow-average loss as technical exit."
        ),
        evidence_requirements=("moving_average",),
        parameters=(*_RISK_PARAMETERS, "fast_window", "slow_window"),
    ),
    TechnicalExecutorSpec(
        executor_id=VOLUME_BREAKOUT_EXECUTOR_ID,
        strategy_family="volume_confirmed_breakout",
        description=(
            "Long-only resistance crossing that additionally requires current "
            "volume to exceed a multiple of prior average volume."
        ),
        evidence_requirements=("resistance", "volume"),
        parameters=(
            *_RISK_PARAMETERS,
            "anchor_level",
            "entry_buffer_percent",
            "technical_invalidation_buffer_percent",
            "volume_lookback_bars",
            "minimum_relative_volume",
        ),
    ),
    TechnicalExecutorSpec(
        executor_id=INVERSE_PATTERN_EXECUTOR_ID,
        strategy_family="inverse_head_and_shoulders_breakout",
        description=(
            "Long-only crossing above the neckline of a supplied confirmed "
            "inverse-head-and-shoulders observation."
        ),
        evidence_requirements=("inverse_head_and_shoulders",),
        parameters=(
            *_RISK_PARAMETERS,
            "neckline_price",
            "breakout_buffer_percent",
            "technical_invalidation_buffer_percent",
        ),
    ),
    TechnicalExecutorSpec(
        executor_id=HEAD_PATTERN_EXECUTOR_ID,
        strategy_family="head_and_shoulders_breakdown",
        description=(
            "Short crossing below the neckline of a supplied confirmed "
            "head-and-shoulders observation; usable only when the mandate and "
            "Backtest Plan explicitly permit shorting."
        ),
        evidence_requirements=("head_and_shoulders",),
        parameters=(
            *_RISK_PARAMETERS,
            "neckline_price",
            "breakout_buffer_percent",
            "technical_invalidation_buffer_percent",
        ),
        supports_short=True,
    ),
)

TECHNICAL_EXECUTOR_SPEC_BY_ID = {
    spec.executor_id: spec for spec in TECHNICAL_EXECUTOR_SPECS
}


def render_executor_catalog(executor_ids: tuple[str, ...]) -> str:
    """Render known executor contracts and preserve unknown injected IDs."""

    sections: list[str] = []
    for executor_id in executor_ids:
        spec = TECHNICAL_EXECUTOR_SPEC_BY_ID.get(executor_id)
        if spec is None:
            sections.append(f"- {executor_id}: externally supplied executor.")
            continue
        sections.append(
            "\n".join(
                [
                    f"- {spec.executor_id} ({spec.strategy_family})",
                    f"  Behavior: {spec.description}",
                    "  Required evidence: "
                    + ", ".join(spec.evidence_requirements),
                    "  Required parameters: " + ", ".join(spec.parameters),
                ]
            )
        )
    return "\n".join(sections)


__all__ = [
    "BENCHMARK_FALLBACK_EXECUTOR_ID",
    "HEAD_PATTERN_EXECUTOR_ID",
    "INVERSE_PATTERN_EXECUTOR_ID",
    "MOVING_AVERAGE_TREND_EXECUTOR_ID",
    "MULTI_ASSET_PORTFOLIO_EXECUTOR_ID",
    "RESISTANCE_BREAKOUT_EXECUTOR_ID",
    "SUPPORT_REACTION_EXECUTOR_ID",
    "TECHNICAL_EXECUTOR_SPECS",
    "TECHNICAL_EXECUTOR_SPEC_BY_ID",
    "TechnicalExecutorSpec",
    "TARGET_PORTFOLIO_ASSET_COUNT",
    "VOLUME_BREAKOUT_EXECUTOR_ID",
    "render_executor_catalog",
]
