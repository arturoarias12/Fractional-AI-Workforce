"""Horizon-matched validation policy for the full research-loop demo.

The graph owner can replace this policy during production composition. This
implementation deterministically selects the final exact number of available
market sessions implied by the PM mandate. It never lets an agent or an LLM
choose evaluation dates.
"""

from __future__ import annotations

from protocols import BacktestPlanDraft, DataResponse, TraderTask, ValidationSplit

from agents.technical_trader.horizon import resolve_technical_horizon
from agents.technical_trader.tools import (
    ArtifactPayloadTechnicalInputAdapter,
    TechnicalAnalysisInputAdapter,
)


DEFAULT_MINIMUM_TRAINING_SESSIONS = 252


class HorizonMatchedValidationSplitPolicy:
    """Select an exact trailing, mandate-horizon evaluation window."""

    def __init__(
        self,
        *,
        minimum_training_sessions: int = DEFAULT_MINIMUM_TRAINING_SESSIONS,
        input_adapter: TechnicalAnalysisInputAdapter | None = None,
    ) -> None:
        if (
            isinstance(minimum_training_sessions, bool)
            or minimum_training_sessions < 1
        ):
            raise ValueError("minimum_training_sessions must be positive.")
        self._minimum_training_sessions = minimum_training_sessions
        self._input_adapter = (
            input_adapter
            if input_adapter is not None
            else ArtifactPayloadTechnicalInputAdapter()
        )

    def resolve(
        self,
        *,
        task: TraderTask,
        plan: BacktestPlanDraft,
        data_response: DataResponse,
    ) -> ValidationSplit:
        series = self._input_adapter.extract(data_response)
        as_of_date = task.mandate.as_of_date
        benchmark = (plan.benchmark or "").strip().upper()
        calendar_series = next(
            (
                price_series
                for price_series in series
                if benchmark
                and str(getattr(price_series, "symbol", "")).strip().upper()
                == benchmark
            ),
            None,
        )
        dated_series = (
            (calendar_series,)
            if calendar_series is not None
            else series
        )
        all_dates = sorted(
            {
                bar.timestamp.date()
                for price_series in dated_series
                for bar in price_series.bars
                if bar.timestamp.date() <= as_of_date
            }
        )
        horizon_sessions = resolve_technical_horizon(
            task.mandate
        ).horizon_trading_days
        required_dates = self._minimum_training_sessions + horizon_sessions
        if len(all_dates) < required_dates:
            raise ValueError(
                "The horizon-matched validation policy requires at least "
                f"{required_dates} distinct market sessions: "
                f"{self._minimum_training_sessions} for Technical discovery "
                f"and {horizon_sessions} for evaluation; only "
                f"{len(all_dates)} are available through "
                f"{as_of_date.isoformat()}."
            )
        evaluation_dates = all_dates[-horizon_sessions:]
        return ValidationSplit(
            test_start_date=evaluation_dates[0],
            test_end_date=evaluation_dates[-1],
        )


__all__ = [
    "DEFAULT_MINIMUM_TRAINING_SESSIONS",
    "HorizonMatchedValidationSplitPolicy",
]
