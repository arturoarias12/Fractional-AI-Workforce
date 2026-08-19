"""Deterministic, code-authored backtest interpretation.

Same boundary rule as Quant Trader's ``interpretation.py``: "only code
returns performance results" says nothing about interpretation, which is
normally expected to be LLM-authored. This module is a conservative
stand-in that turns ``BacktestResult`` metrics into the same structured
shape a model would produce, using fixed templates instead of a model
call. Swap ``build_interpretation`` for a model-backed version once a
``model_client`` boundary is wired into this trader.
"""

from __future__ import annotations

from protocols import (
    BacktestResult,
    BacktestStatus,
    ConfidenceAssessment,
    ConfidenceLevel,
    MetricInterpretation,
)
from tools import BACKTEST_METRIC_DEFINITIONS

from .rule_generator import ProposedCategoryDeviation

MIN_TRUSTED_TRADES = 15


def _metric_interpretations(result: BacktestResult) -> list[MetricInterpretation]:
    interpretations: list[MetricInterpretation] = []
    for name, value in result.metrics.items():
        description = BACKTEST_METRIC_DEFINITIONS.get(name, {}).get(
            "description", "See BACKTEST_METRIC_DEFINITIONS for this metric."
        )
        interpretations.append(MetricInterpretation(
            metric_name=name,
            interpretation=f"{description} Training-window value: {value}.",
            result_section="train_period",
        ))
    for name, value in result.out_of_sample_metrics.items():
        description = BACKTEST_METRIC_DEFINITIONS.get(name, {}).get(
            "description", "See BACKTEST_METRIC_DEFINITIONS for this metric."
        )
        interpretations.append(MetricInterpretation(
            metric_name=name,
            interpretation=f"{description} Held-out test-window value: {value}.",
            result_section="test_period",
        ))
    return interpretations


def build_interpretation(proposal: ProposedCategoryDeviation, result: BacktestResult):
    """Build a ``BacktestInterpretationDraft`` from a settled ``BacktestResult``."""
    from protocols import BacktestInterpretationDraft  # local import avoids a cycle

    train_return = result.metrics.get("total_return")
    test_return = result.out_of_sample_metrics.get("total_return")
    trade_count = result.metrics.get("transaction_count")

    summary = (
        f"Category-benchmark deviation on {proposal.ticker} (\"{proposal.category}\" "
        f"category) versus its major-tier peer benchmark "
        f"({', '.join(proposal.benchmark_tickers)}). Training-window total "
        f"return: {train_return}. Held-out test-window total return: {test_return}."
    )

    out_of_sample_assessment = (
        "Held-out metrics are reported separately from training metrics above "
        "and were computed on a window the candidate's parameters were never "
        "tuned against."
        if result.out_of_sample_metrics
        else "No held-out metrics were returned by the engine for this run."
    )

    overfitting_risks = [
        (
            f"This candidate was selected from a scan of every boutique-tier "
            f"ticker across all populated categories in the permitted "
            "universe; a single strong-looking category deviation among many "
            "tested is exactly the kind of result that needs Risk's scrutiny "
            "for selection bias / cherry-picking, independent of how the "
            "backtest itself performed."
        ),
        (
            "The ISSUER_SCALE_TIER split (major vs. boutique fund family) is "
            "a heuristic substitute for fund-level fundamentals (expense "
            "ratio, dividend yield, NAV premium/discount) that are not "
            "populated in ETF_info.xlsx for this universe - see "
            "docs/fundamental_trader.md. Risk should weigh this candidate "
            "knowing the underlying signal is a liquidity/issuer-scale proxy, "
            "not a direct fundamental valuation gap."
        ),
    ]
    if isinstance(trade_count, (int, float)) and trade_count < MIN_TRUSTED_TRADES:
        overfitting_risks.append(
            f"Only {trade_count:g} trades were simulated - too few to draw a "
            "confident conclusion from either period's win rate or return."
        )

    confidence_level = ConfidenceLevel.MEDIUM
    uncertainty_drivers = [
        "Interpretation is template-generated, not model-authored; treat "
        "language here as a structured summary of the metrics, not analysis.",
        "Category benchmark is an equal-weight average of major-tier peers "
        "in the same category, not a licensed index - see implementation_notes.",
    ]
    if isinstance(trade_count, (int, float)) and trade_count < MIN_TRUSTED_TRADES:
        confidence_level = ConfidenceLevel.LOW
        uncertainty_drivers.append("Trade count is below the trusted-sample threshold.")

    return BacktestInterpretationDraft(
        summary=summary,
        metric_interpretations=_metric_interpretations(result),
        out_of_sample_assessment=out_of_sample_assessment,
        strengths=(
            [
                f"Category-grounded selection: {proposal.rationale}",
            ]
            if result.status is BacktestStatus.SUCCEEDED
            else []
        ),
        weaknesses=list(result.warnings),
        overfitting_risks=overfitting_risks,
        limitations=[
            "No transaction-cost stress testing beyond the engine's configured "
            "commission/slippage assumptions.",
            "Fund-level fundamentals (expense ratio, dividend yield, NAV "
            "premium/discount) are unavailable in the current data fixture; "
            "category + issuer-scale tier is used as a proxy signal instead.",
        ],
        mandate_alignment=[
            "Long-only, single-ticker exposure; no leverage or short selling used.",
        ],
        open_questions=[
            "Should Fundamental Trader propose more than one candidate per "
            "round so Risk can compare survivors instead of reviewing a "
            "single ticker?",
            "Would a licensed category benchmark (vs. an equal-weight "
            "major-tier average computed in-house) change which deviations "
            "look significant?",
        ],
        confidence=ConfidenceAssessment(
            level=confidence_level,
            rationale=(
                f"Backtest status was {result.status.value}; metrics were "
                "computed by the deterministic engine, not estimated."
            ),
            uncertainty_drivers=uncertainty_drivers,
        ),
    )


__all__ = ["build_interpretation"]
