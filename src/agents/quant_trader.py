"""
Quant Trader agent - the "propose" half
==========================================
Workstream #2: Build Quant Trader agent. Owner: Shaurya.

This is deliberately split from the backtest engine:
  - the ENGINE = the deterministic part that EVALUATES a rule once you
    hand it one (being refactored separately to match the latest
    architecture).
  - quant_trader.py (this file) = the part that DECIDES which rule to
    try in the first place. This is Quant Trader's actual judgment: look
    at the data, find a statistically interesting relationship, and
    propose a specific, testable rule from it. No LLM guessing at
    numbers here either - this is math (correlation + mean-reversion
    speed), same "don't hallucinate the result" principle as the engine.

What "propose a strategy" means concretely for Quant Trader (per the
flowchart's "statistics and cross-asset anomalies" lens):
  1. Scan all ETF pairs for ones that move together (high correlation)
     - a real relationship is more likely to keep holding than a
     coincidence.
  2. For the pairs that qualify, check whether their price spread
     actually tends to snap back toward its average (mean-reverts) and
     how fast (the "half-life"). A spread that doesn't mean-revert isn't
     a tradeable anomaly, no matter how correlated the two ETFs are.
  3. Turn the strongest candidates into concrete strategy_spec dicts -
     the shape the engine expects - with a plain-English rationale
     attached for the Risk agent and Reporting agent to read.

IMPORTANT - no peeking:
  Every step above looks ONLY at the training period. If we scanned the
  full history to pick pairs, we'd be choosing strategies using data
  from the test window, and the "out-of-sample" test would be a lie -
  the exact look-ahead bias the Risk agent is meant to catch. The test
  period is never touched during proposal, only during evaluation.

Data source: still the static ETF_historical_prices.xlsx file.
"""

import numpy as np
import pandas as pd

DATA_FILE = "ETF_historical_prices.xlsx"

DEFAULT_ENTRY_ZSCORE = 1.5
DEFAULT_EXIT_ZSCORE = 0.25
MIN_HISTORY_DAYS = 750      # ~3 years of shared history before we trust a correlation
MIN_CORRELATION = 0.70      # how "related" two ETFs must be to consider them a pair
MAX_HALF_LIFE_DAYS = 90     # a spread slower than this to revert isn't worth trading


def load_all_prices(data_file=DATA_FILE):
    """Load the price file once. Returns {ticker: DataFrame[date, close]}."""
    df = pd.read_excel(data_file)
    return {
        ticker: group[["date", "close"]].sort_values("date").reset_index(drop=True)
        for ticker, group in df.groupby("ticker")
    }


class QuantTrader:
    """Quant Trader's skill: propose_strategies() -> a ranked list of strategy_spec proposals."""

    def __init__(self, data_file=DATA_FILE, prices_by_ticker=None):
        self.prices_by_ticker = prices_by_ticker or load_all_prices(data_file)
        self.wide_prices = self._build_wide_prices()

    def _build_wide_prices(self):
        """One DataFrame: rows = dates, columns = tickers, values = close price."""
        frames = [
            df.set_index("date")["close"].rename(ticker)
            for ticker, df in self.prices_by_ticker.items()
        ]
        return pd.concat(frames, axis=1).sort_index()

    def _train_window(self, train_start, train_end):
        """Slice the price panel down to the training period only (no peeking)."""
        window = self.wide_prices
        if train_start is not None:
            window = window[window.index >= pd.Timestamp(train_start)]
        if train_end is not None:
            window = window[window.index <= pd.Timestamp(train_end)]
        return window

    # -------------------------------------------------------------
    # Step 1: find pairs that move together (training period only)
    # -------------------------------------------------------------

    def find_correlated_pairs(self, train_prices, min_correlation=MIN_CORRELATION):
        """
        Correlate daily returns across every ticker at once, then keep
        only pairs with enough overlapping history AND a strong enough
        correlation. Uses matrix math so the full 120-ticker scan
        (~7,000 pairs) takes well under a second.
        """
        returns = train_prices.pct_change(fill_method=None)

        is_valid = returns.notna().to_numpy().astype(np.int32)
        overlap_counts = is_valid.T @ is_valid            # shared trading days per pair
        corr_matrix = returns.corr(min_periods=MIN_HISTORY_DAYS).to_numpy()

        tickers = list(returns.columns)
        pairs = []
        for i in range(len(tickers)):
            for j in range(i + 1, len(tickers)):
                corr = corr_matrix[i, j]
                if np.isnan(corr):
                    continue
                if overlap_counts[i, j] >= MIN_HISTORY_DAYS and corr >= min_correlation:
                    pairs.append({
                        "ticker_a": tickers[i],
                        "ticker_b": tickers[j],
                        "correlation": round(float(corr), 3),
                        "shared_days": int(overlap_counts[i, j]),
                    })
        return pairs

    # -------------------------------------------------------------
    # Step 2: does the pair's spread actually mean-revert, and how fast?
    # -------------------------------------------------------------

    def estimate_half_life(self, train_prices, ticker_a, ticker_b):
        """
        Fits spread_change[t] = a + b * spread[t-1] on the price ratio
        between the two tickers (a simple AR(1) fit). A negative `b`
        means the spread tends to snap back toward its average; the
        half-life is how many days that snap-back typically takes.

        Returns None if the pair doesn't mean-revert (b >= 0), reverts
        too slowly to trade, or lacks enough overlapping data.
        """
        pair_prices = train_prices[[ticker_a, ticker_b]].dropna()
        if len(pair_prices) < MIN_HISTORY_DAYS:
            return None

        spread = pair_prices[ticker_a] / pair_prices[ticker_b]
        lagged = spread.shift(1)
        change = spread - lagged
        valid = lagged.notna() & change.notna()
        lagged, change = lagged[valid], change[valid]

        variance = lagged.var()
        if variance == 0:
            return None
        b = float(np.cov(lagged, change)[0, 1] / variance)

        if b >= 0:
            return None  # spread drifts rather than reverting - not tradeable this way

        half_life_days = -np.log(2) / np.log(1 + b)
        if half_life_days <= 0 or half_life_days > MAX_HALF_LIFE_DAYS:
            return None
        return round(float(half_life_days), 1)

    # -------------------------------------------------------------
    # Step 3: turn the best candidates into concrete, testable proposals
    # -------------------------------------------------------------

    def propose_strategies(self, top_n=5,
                            train_start="2010-01-01", train_end="2019-12-31",
                            test_start="2020-01-01", test_end="2026-06-29"):
        """
        Returns up to `top_n` strategy_spec dicts, ready to hand to the
        backtest engine. Ranked by a combined score that rewards a strong
        relationship AND a fast snap-back, since a pair that reverts in
        two weeks gives far more tradeable opportunities than one that
        takes three months.

        Only training-period data is used to pick and rank these.
        """
        train_prices = self._train_window(train_start, train_end)

        candidates = []
        for pair in self.find_correlated_pairs(train_prices):
            half_life = self.estimate_half_life(train_prices, pair["ticker_a"], pair["ticker_b"])
            if half_life is None:
                continue
            # Score: correlation strength, discounted the slower the spread reverts.
            score = pair["correlation"] * (1.0 / (1.0 + half_life / 30.0))
            candidates.append({**pair, "half_life_days": half_life, "score": round(score, 4)})

        candidates.sort(key=lambda c: c["score"], reverse=True)

        proposals = []
        for c in candidates[:top_n]:
            # Lookback for the rolling z-score: about two half-lives of
            # history, bounded to a sane range.
            lookback_days = int(min(max(round(c["half_life_days"] * 2), 10), 60))

            proposals.append({
                "ticker_a": c["ticker_a"],
                "ticker_b": c["ticker_b"],
                "lookback_days": lookback_days,
                "entry_zscore": DEFAULT_ENTRY_ZSCORE,
                "exit_zscore": DEFAULT_EXIT_ZSCORE,
                "train_start": train_start, "train_end": train_end,
                "test_start": test_start, "test_end": test_end,
                "proposed_by": "quant_trader",
                "evidence": {
                    "correlation": c["correlation"],
                    "half_life_days": c["half_life_days"],
                    "shared_days": c["shared_days"],
                    "score": c["score"],
                },
                "rationale": (
                    f"{c['ticker_a']} and {c['ticker_b']} moved together closely during the "
                    f"training period (correlation {c['correlation']} over {c['shared_days']} "
                    f"shared trading days), and their price spread snapped back toward its "
                    f"average in about {c['half_life_days']} trading days. That combination - "
                    f"a real relationship plus a measurable pull back to normal - is what makes "
                    f"this a testable mean-reversion anomaly rather than a coincidence. Trade "
                    f"the spread: buy {c['ticker_a']} when it looks cheap versus {c['ticker_b']} "
                    f"by {DEFAULT_ENTRY_ZSCORE} standard deviations, exit as the gap closes."
                ),
            })
        return proposals


# =======================================================================
# Example run
# =======================================================================

if __name__ == "__main__":
    trader = QuantTrader()

    print("Scanning the universe for statistically interesting pairs (training period only)...\n")
    proposals = trader.propose_strategies(top_n=5)

    print(f"Quant Trader proposes {len(proposals)} candidate strategies:\n")
    for i, p in enumerate(proposals, 1):
        ev = p["evidence"]
        print(f"{i}. {p['ticker_a']} / {p['ticker_b']}")
        print(f"   rule: {p['lookback_days']}-day rolling spread, enter at "
              f"-{p['entry_zscore']} z, exit at -{p['exit_zscore']} z")
        print(f"   evidence: correlation {ev['correlation']}, "
              f"half-life {ev['half_life_days']}d, {ev['shared_days']} shared days")
        print(f"   {p['rationale']}")
        print()

    print("Each proposal above is a strategy_spec ready to hand to the backtest engine "
          "for evaluation, then on to the Risk agent for review.")
