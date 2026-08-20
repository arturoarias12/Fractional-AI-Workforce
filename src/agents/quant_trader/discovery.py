"""Statistical pair discovery - Quant Trader's "propose" stage.

This module never touches the Backtest Engine and never invents a
performance number. Its only job is: given point-in-time bars, find pairs
of instruments that (a) genuinely move together and (b) have a spread that
historically snaps back toward its own average, then package the strongest
of those into strategy_parameters ready for the registered deterministic
executor in :mod:`agents.quant_trader.strategy`.

Look-ahead discipline
----------------------
Callers must pass only bars from the *training* portion of history (i.e.
strictly before the resolved ``ValidationSplit.test_start_date``). This
module does not know about the held-out window and will happily use
whatever bars it is given - the caller (``QuantTraderAgent``) is
responsible for slicing the panel correctly before calling
:func:`propose_pairs`. Scanning the held-out window to pick a strategy
would make the later out-of-sample test meaningless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from tools import PriceBar

DEFAULT_ENTRY_ZSCORE = 1.5
DEFAULT_EXIT_ZSCORE = 0.25
MIN_HISTORY_DAYS = 250       # ~1 trading year of overlap before a correlation is trusted
MIN_CORRELATION = 0.70       # how related two instruments must be to consider as a pair
MAX_HALF_LIFE_DAYS = 90      # a spread slower than this to revert isn't worth trading
MIN_LOOKBACK_DAYS = 10
MAX_LOOKBACK_DAYS = 60

PricePanel = Mapping[str, Sequence[PriceBar]]


@dataclass(frozen=True, slots=True)
class PairEvidence:
    """The statistical case for one candidate pair."""

    ticker_a: str
    ticker_b: str
    correlation: float
    half_life_days: float
    shared_trading_days: int
    score: float


@dataclass(frozen=True, slots=True)
class ProposedPair:
    """A concrete, testable cross-asset mean-reversion candidate."""

    ticker_a: str
    ticker_b: str
    lookback_days: int
    entry_zscore: float
    exit_zscore: float
    evidence: PairEvidence
    rationale: str

    def as_strategy_parameters(self) -> dict[str, Any]:
        """Parameters for the registered ``StrategyExecutor``."""
        return {
            "ticker_a": self.ticker_a,
            "ticker_b": self.ticker_b,
            "lookback_days": self.lookback_days,
            "entry_zscore": self.entry_zscore,
            "exit_zscore": self.exit_zscore,
        }


def _panel_to_wide_closes(panel: PricePanel) -> pd.DataFrame:
    """Build one DataFrame: rows = dates, columns = symbols, values = close."""
    series = {}
    for symbol, bars in panel.items():
        if not bars:
            continue
        ordered = sorted(bars, key=lambda bar: bar.timestamp)
        index = [bar.timestamp.date() for bar in ordered]
        values = [bar.close for bar in ordered]
        series[symbol] = pd.Series(values, index=index)
    if not series:
        return pd.DataFrame()
    return pd.concat(series, axis=1).sort_index()


def find_correlated_pairs(
    wide_closes: pd.DataFrame,
    *,
    min_correlation: float = MIN_CORRELATION,
    min_history_days: int = MIN_HISTORY_DAYS,
) -> list[dict[str, Any]]:
    """Every pair of columns whose daily returns move together closely.

    Uses matrix math so a full ~100-symbol universe (thousands of pairs)
    scans in well under a second.
    """
    if wide_closes.shape[1] < 2:
        return []

    returns = wide_closes.pct_change(fill_method=None)
    is_valid = returns.notna().to_numpy().astype(np.int32)
    overlap_counts = is_valid.T @ is_valid
    corr_matrix = returns.corr(min_periods=min_history_days).to_numpy()

    symbols = list(returns.columns)
    pairs: list[dict[str, Any]] = []
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            corr = corr_matrix[i, j]
            if np.isnan(corr):
                continue
            if overlap_counts[i, j] >= min_history_days and corr >= min_correlation:
                pairs.append({
                    "ticker_a": symbols[i],
                    "ticker_b": symbols[j],
                    "correlation": round(float(corr), 4),
                    "shared_trading_days": int(overlap_counts[i, j]),
                })
    return pairs


def estimate_half_life(
    wide_closes: pd.DataFrame,
    ticker_a: str,
    ticker_b: str,
    *,
    min_history_days: int = MIN_HISTORY_DAYS,
    max_half_life_days: float = MAX_HALF_LIFE_DAYS,
) -> float | None:
    """Fit spread_change[t] = a + b * spread[t-1] (a simple AR(1) fit).

    A negative ``b`` means the price ratio between the two symbols tends to
    snap back toward its average; the half-life is how many trading days
    that snap-back typically takes. Returns ``None`` if the pair does not
    mean-revert or lacks enough overlapping history.
    """
    pair_prices = wide_closes[[ticker_a, ticker_b]].dropna()
    if len(pair_prices) < min_history_days:
        return None

    spread = pair_prices[ticker_a] / pair_prices[ticker_b]
    lagged = spread.shift(1)
    change = spread - lagged
    valid = lagged.notna() & change.notna()
    lagged, change = lagged[valid], change[valid]

    variance = lagged.var()
    if not variance:
        return None
    b = float(np.cov(lagged, change)[0, 1] / variance)
    if b >= 0:
        return None  # drifts rather than reverting

    half_life_days = -np.log(2) / np.log(1 + b)
    if half_life_days <= 0 or half_life_days > max_half_life_days:
        return None
    return round(float(half_life_days), 2)


def propose_pairs(
    panel: PricePanel,
    *,
    permitted_symbols: Sequence[str] | None = None,
    excluded_tickers: frozenset[str] | Sequence[str] = frozenset(),
    top_n: int = 3,
    min_correlation: float = MIN_CORRELATION,
    min_history_days: int = MIN_HISTORY_DAYS,
    max_half_life_days: float = MAX_HALF_LIFE_DAYS,
    entry_zscore: float = DEFAULT_ENTRY_ZSCORE,
    exit_zscore: float = DEFAULT_EXIT_ZSCORE,
    preferred_lookback_days: int | None = None,
) -> list[ProposedPair]:
    """Scan the training-window panel and return up to ``top_n`` candidates.

    Ranking rewards both a strong relationship and a fast snap-back: a
    pair that reverts in two weeks gives far more tradeable opportunities
    over a fixed evaluation window than one that takes three months.

    ``excluded_tickers`` drops any pair involving one of these symbols
    (e.g. from a PM's Pivot action or mandate directive - see
    mandate_directives.py), without touching the permitted universe
    itself. ``preferred_lookback_days``, if given, overrides the
    half-life-derived lookback rather than deriving it from the pair's
    measured mean-reversion speed.
    """
    wide_closes = _panel_to_wide_closes(panel)
    if permitted_symbols:
        allowed = set(permitted_symbols)
        wide_closes = wide_closes[[c for c in wide_closes.columns if c in allowed]]
    excluded = {t.upper() for t in excluded_tickers}
    if excluded:
        wide_closes = wide_closes[[c for c in wide_closes.columns if c.upper() not in excluded]]

    candidates: list[PairEvidence] = []
    for pair in find_correlated_pairs(
        wide_closes,
        min_correlation=min_correlation,
        min_history_days=min_history_days,
    ):
        half_life = estimate_half_life(
            wide_closes,
            pair["ticker_a"],
            pair["ticker_b"],
            min_history_days=min_history_days,
            max_half_life_days=max_half_life_days,
        )
        if half_life is None:
            continue
        score = pair["correlation"] * (1.0 / (1.0 + half_life / 30.0))
        candidates.append(PairEvidence(
            ticker_a=pair["ticker_a"],
            ticker_b=pair["ticker_b"],
            correlation=pair["correlation"],
            half_life_days=half_life,
            shared_trading_days=pair["shared_trading_days"],
            score=round(score, 4),
        ))

    candidates.sort(key=lambda c: c.score, reverse=True)

    proposals: list[ProposedPair] = []
    for evidence in candidates[:top_n]:
        lookback_days = (
            preferred_lookback_days
            if preferred_lookback_days is not None
            else int(min(
                max(round(evidence.half_life_days * 2), MIN_LOOKBACK_DAYS),
                MAX_LOOKBACK_DAYS,
            ))
        )
        rationale = (
            f"{evidence.ticker_a} and {evidence.ticker_b} moved together closely "
            f"during the training window (correlation {evidence.correlation} over "
            f"{evidence.shared_trading_days} shared trading days), and their price "
            f"spread snapped back toward its average in about "
            f"{evidence.half_life_days} trading days. That combination - a real "
            f"relationship plus a measurable pull back to normal - is what makes "
            f"this a testable mean-reversion anomaly. Trade the spread: buy "
            f"{evidence.ticker_a} when it is cheap versus {evidence.ticker_b} by "
            f"{entry_zscore} standard deviations, exit as the gap closes back to "
            f"{exit_zscore} standard deviations."
        )
        proposals.append(ProposedPair(
            ticker_a=evidence.ticker_a,
            ticker_b=evidence.ticker_b,
            lookback_days=lookback_days,
            entry_zscore=entry_zscore,
            exit_zscore=exit_zscore,
            evidence=evidence,
            rationale=rationale,
        ))
    return proposals
