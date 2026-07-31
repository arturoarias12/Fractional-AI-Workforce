"""Deterministic, code-authored backtest interpretation.

The project's boundary rule is "only code returns performance results" -
it says nothing about interpretation, which is normally expected to be
LLM-authored (see ``protocols.trader.BacktestInterpretationDraft`` and
``CandidateRuleDraft`` being "LLM-authored"). This module is a conservative
stand-in: it turns ``BacktestResult`` metrics into the same structured
shape a model would produce, using fixed templates instead of a model
call. Swap ``build_interpretation`` for a model-backed version once a
``model_client`` boundary is wired into this trader - the rest of the
agent does not need to change.
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

from .discovery import ProposedPair

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


def build_interpretation(proposal: ProposedPair, result: BacktestResult):
    """Build a ``BacktestInterpretationDraft`` from a settled ``BacktestResult``."""
    from protocols import BacktestInterpretationDraft  # local import avoids a cycle

    train_return = result.metrics.get("total_return")
    test_return = result.out_of_sample_metrics.get("total_return")
    trade_count = result.metrics.get("transaction_count")

    summary = (
        f"Cross-asset spread mean reversion on {proposal.ticker_a}/"
        f"{proposal.ticker_b}. Training-window total return: {train_return}. "
        f"Held-out test-window total return: {test_return}."
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
            f"This candidate was selected from a scan of {proposal.evidence.score:g}"
            " score-ranked pairs across the permitted universe; a single "
            "strong-looking pair among many tested is exactly the kind of "
            "result that needs Risk's scrutiny for selection bias / "
            "cherry-picking, independent of how the backtest itself performed."
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
    ]
    if isinstance(trade_count, (int, float)) and trade_count < MIN_TRUSTED_TRADES:
        confidence_level = ConfidenceLevel.LOW
        uncertainty_drivers.append("Trade count is below the trusted-sample threshold.")

    return BacktestInterpretationDraft(
        summary=summary,
        metric_interpretations=_metric_interpretations(result),
        out_of_sample_assessment=out_of_sample_assessment,
        strengths=(
            [f"Statistically grounded pair selection: {proposal.rationale}"]
            if result.status is BacktestStatus.SUCCEEDED
            else []
        ),
        weaknesses=list(result.warnings),
        overfitting_risks=overfitting_risks,
        limitations=[
            "No transaction-cost stress testing beyond the engine's configured "
            "commission/slippage assumptions.",
            "Single benchmark-free pair strategy; no comparison against "
            "alternative pairs' out-of-sample performance yet.",
        ],
        mandate_alignment=[
            "Long-only, single-pair exposure; no leverage or short selling used.",
        ],
        open_questions=[
            "Should Quant Trader propose more than one candidate per round so "
            "Risk can compare survivors instead of reviewing a single pair?",
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
