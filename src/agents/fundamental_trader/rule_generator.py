"""Fund-level fundamental discovery - Fundamental Trader's "propose" stage.

The strategy this module proposes: **category-benchmark deviation**. Two
ETFs in the same Morningstar-style ``category`` (e.g. "Technology",
"Energy Limited Partnership") are, by construction, tracking similar
underlying exposure. If one of them - specifically, one issued by a
smaller/boutique fund family - drifts unusually far from the return of its
category's major-issuer peers, that gap is more likely a liquidity/technical
artifact than a fundamentally justified difference, since nothing in the ETF
category definition explains why two funds tracking the same space should
diverge for long. This module proposes betting on that gap closing.

Why category + issuer tier, and not classic fundamentals
----------------------------------------------------------
The original design called for expense ratio, dividend yield, and NAV
premium/discount as fundamental signals. ``ETF_info.xlsx`` was inspected
directly (not assumed from the spec) and does not populate those fields,
nor ``marketCap``/``sector``/``industry``, for any of the 120 tickers. Only
``category`` and ``fundFamily`` are populated for effectively the whole
universe. ``ISSUER_SCALE_TIER`` is a heuristic built on top of
``fundFamily``: it buckets issuers into "major" (large, broadly-distributed
asset managers) versus "boutique" (smaller/specialist issuers), used as a
proxy for the liquidity and tracking-quality differences that would
otherwise come from balance-sheet data this fixture does not have. This
substitution is a limitation, documented here and carried into every
candidate's ``implementation_notes`` and the Risk-facing interpretation.

Look-ahead discipline
----------------------
Callers must pass only bars from the *training* portion of history (i.e.
strictly before the resolved ``ValidationSplit.test_start_date``), exactly
as Quant Trader's ``discovery.py`` requires of its caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from tools import PriceBar

from .data_adapter import ETFFundamentals, FundamentalPanel, PricePanel

DEFAULT_ENTRY_ZSCORE = 1.5
DEFAULT_EXIT_ZSCORE = 0.25
MIN_HISTORY_DAYS = 250        # ~1 trading year before a category benchmark is trusted
MIN_BENCHMARK_PEERS = 2       # major-tier peers required to form a category benchmark
MIN_LOOKBACK_DAYS = 20
MAX_LOOKBACK_DAYS = 90

# Large, broadly-distributed ETF issuers used as the "major" tier of the
# ISSUER_SCALE_TIER heuristic. Chosen for AUM/shelf-space breadth among the
# 27 distinct fundFamily values actually present in ETF_info.xlsx (verified
# by inspection). Everything else present in the fixture is "boutique".
# Team should revisit this list before treating it as final - see
# docs/fundamental_trader.md.
MAJOR_TIER_ISSUERS: frozenset[str] = frozenset({
    "iShares",
    "Vanguard",
    "State Street Investment Management",
    "Invesco",
    "Schwab ETFs",
    "Fidelity Investments",
    "JPMorgan",
    "First Trust",
    "WisdomTree",
})


def classify_issuer_tier(fund_family: str) -> str:
    """Return ``"major"`` or ``"boutique"`` for a ``fundFamily`` value."""
    return "major" if fund_family in MAJOR_TIER_ISSUERS else "boutique"


@dataclass(frozen=True, slots=True)
class CategoryDeviationEvidence:
    """The fundamental case for one candidate ticker."""

    ticker: str
    category: str
    fund_family: str
    benchmark_tickers: tuple[str, ...]  # major-tier peers used for the benchmark
    correlation: float
    current_zscore: float
    shared_trading_days: int
    score: float


@dataclass(frozen=True, slots=True)
class ProposedCategoryDeviation:
    """A concrete, testable category-benchmark-deviation candidate."""

    ticker: str
    category: str
    lookback_days: int
    entry_zscore: float
    exit_zscore: float
    benchmark_tickers: tuple[str, ...]
    evidence: CategoryDeviationEvidence
    rationale: str

    def as_strategy_parameters(self) -> dict[str, Any]:
        """Parameters for the registered ``StrategyExecutor``."""
        return {
            "ticker": self.ticker,
            "category": self.category,
            "lookback_days": self.lookback_days,
            "entry_zscore": self.entry_zscore,
            "exit_zscore": self.exit_zscore,
            "benchmark_tickers": list(self.benchmark_tickers),
        }


def _panel_to_wide_closes(panel: PricePanel) -> pd.DataFrame:
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


def _category_groups(
    fundamentals: FundamentalPanel, permitted_symbols: Sequence[str] | None,
) -> dict[str, list[ETFFundamentals]]:
    allowed = set(permitted_symbols) if permitted_symbols else None
    groups: dict[str, list[ETFFundamentals]] = {}
    for ticker, info in fundamentals.items():
        if allowed is not None and ticker not in allowed:
            continue
        groups.setdefault(info.category, []).append(info)
    return groups


def propose_category_deviations(
    price_panel: PricePanel,
    fundamental_panel: FundamentalPanel,
    *,
    permitted_symbols: Sequence[str] | None = None,
    excluded_tickers: frozenset[str] | Sequence[str] = frozenset(),
    top_n: int = 3,
    entry_zscore: float = DEFAULT_ENTRY_ZSCORE,
    exit_zscore: float = DEFAULT_EXIT_ZSCORE,
    preferred_lookback_days: int | None = None,
) -> list[ProposedCategoryDeviation]:
    """Rank boutique-tier tickers by how far they've drifted from their
    category's major-tier benchmark, and return the strongest candidates.

    ``excluded_tickers`` removes specific boutique-tier tickers from
    consideration this round (e.g. from a PM's Pivot action or mandate
    directive - see mandate_directives.py) without touching the permitted
    universe itself. ``preferred_lookback_days``, if given, tries only that
    window instead of scanning all three defaults.
    """
    closes = _panel_to_wide_closes(price_panel)
    if closes.empty:
        return []
    returns = closes.pct_change(fill_method=None).dropna(how="all")
    excluded = {t.upper() for t in excluded_tickers}
    lookback_candidates = (
        (preferred_lookback_days,)
        if preferred_lookback_days is not None
        else (MIN_LOOKBACK_DAYS, 40, MAX_LOOKBACK_DAYS)
    )

    groups = _category_groups(fundamental_panel, permitted_symbols)
    proposals: list[ProposedCategoryDeviation] = []

    for category, members in groups.items():
        major = [m for m in members if m.issuer_tier == "major" and m.ticker in returns.columns]
        boutique = [
            m for m in members
            if m.issuer_tier == "boutique" and m.ticker in returns.columns
            and m.ticker.upper() not in excluded
        ]
        if len(major) < MIN_BENCHMARK_PEERS or not boutique:
            continue

        benchmark_tickers = tuple(sorted(m.ticker for m in major))
        benchmark_returns = returns[list(benchmark_tickers)].mean(axis=1, skipna=True)

        for info in boutique:
            ticker_returns = returns[info.ticker].dropna()
            aligned = pd.concat(
                {"ticker": ticker_returns, "benchmark": benchmark_returns}, axis=1,
            ).dropna()
            if len(aligned) < MIN_HISTORY_DAYS:
                continue

            spread = aligned["ticker"] - aligned["benchmark"]
            for lookback_days in lookback_candidates:
                if len(spread) <= lookback_days:
                    continue
                window = spread.iloc[-lookback_days:]
                std = window.std(ddof=0)
                if std == 0 or np.isnan(std):
                    continue
                mean = window.mean()
                current_zscore = (spread.iloc[-1] - mean) / std
                correlation = float(aligned["ticker"].corr(aligned["benchmark"]))
                score = abs(current_zscore) * max(correlation, 0.0)

                evidence = CategoryDeviationEvidence(
                    ticker=info.ticker,
                    category=category,
                    fund_family=info.fund_family,
                    benchmark_tickers=benchmark_tickers,
                    correlation=correlation,
                    current_zscore=float(current_zscore),
                    shared_trading_days=len(aligned),
                    score=float(score),
                )
                rationale = (
                    f"{info.ticker} ({info.fund_family}, boutique tier) has "
                    f"diverged {current_zscore:+.2f} std from its \"{category}\" "
                    f"category benchmark ({', '.join(benchmark_tickers)}, major "
                    f"tier) over the trailing {lookback_days} trading days, "
                    f"with {correlation:.2f} return correlation to that "
                    "benchmark historically."
                )
                proposals.append(ProposedCategoryDeviation(
                    ticker=info.ticker,
                    category=category,
                    lookback_days=lookback_days,
                    entry_zscore=entry_zscore,
                    exit_zscore=exit_zscore,
                    benchmark_tickers=benchmark_tickers,
                    evidence=evidence,
                    rationale=rationale,
                ))
                break  # one lookback per ticker is enough; keep the discovery cheap

    proposals.sort(key=lambda p: p.evidence.score, reverse=True)
    return proposals[:top_n]


__all__ = [
    "MAJOR_TIER_ISSUERS",
    "CategoryDeviationEvidence",
    "ProposedCategoryDeviation",
    "classify_issuer_tier",
    "propose_category_deviations",
]
