"""Dev-only ``ValidationSplitPolicy`` used by the local demo only.

The real fixed train/test boundary is a shared, code-owned decision meant
to be identical across Technical, Fundamental, and Quant (see
``docs/implementation_boundaries.md``). This percentile-based policy is a
convenience for running Quant Trader standalone before that shared policy
exists - it should be replaced, not extended, once one is injected.
"""

from __future__ import annotations

from protocols import BacktestPlanDraft, DataResponse, TraderTask, ValidationSplit

from ..data_adapter import extract_price_panel


class PercentileValidationSplitPolicy:
    """Holds out the most recent ``1 - train_fraction`` of available history."""

    def __init__(self, train_fraction: float = 0.8) -> None:
        if not 0 < train_fraction < 1:
            raise ValueError("train_fraction must be between 0 and 1, exclusive.")
        self._train_fraction = train_fraction

    def resolve(
        self, *, task: TraderTask, plan: BacktestPlanDraft, data_response: DataResponse,
    ) -> ValidationSplit:
        panel = extract_price_panel(data_response)
        all_dates = sorted({
            bar.timestamp.date() for bars in panel.values() for bar in bars
        })
        if not all_dates:
            raise ValueError("Cannot resolve a validation split with no bars.")

        split_index = int(len(all_dates) * self._train_fraction)
        split_index = min(max(split_index, 1), len(all_dates) - 1)
        return ValidationSplit(
            test_start_date=all_dates[split_index],
            test_end_date=all_dates[-1],
        )


__all__ = ["PercentileValidationSplitPolicy"]
