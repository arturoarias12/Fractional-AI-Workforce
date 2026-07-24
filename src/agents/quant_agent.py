"""
Quant Research Agent (backtest driver)
========================================
Workstream #2 - Core Agent Build. Owner: Shaurya.

What this does, in plain terms:
  1. The Theory agent hands us a "strategy_spec" - a simple mean-reversion
     rule (buy after a drop, sell after a recovery).
  2. This agent does NOT ask an LLM to guess what would have happened.
     It runs the rule against real historical prices, day by day.
  3. It reports back a "backtest_result" - the same shape defined in the
     Agent Card spec from Workstream #1 - with train and test period
     results kept separate (out-of-sample validation).

Data source: the static ETF_historical_prices.xlsx file (120 ETFs,
1996-2026, columns: date, ticker, open, high, low, close).
"""

import pandas as pd

DATA_FILE = "ETF_historical_prices.xlsx"


# ---------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------

def load_prices(ticker, data_file=DATA_FILE):
    """Load one ticker's daily closing prices, sorted by date."""
    df = pd.read_excel(data_file)
    df = df[df["ticker"] == ticker].sort_values("date").reset_index(drop=True)
    if df.empty:
        raise ValueError(f"No data found for ticker '{ticker}'")
    return df[["date", "close"]]


# ---------------------------------------------------------------------
# 2. Run the mean-reversion rule over one period and simulate trades
# ---------------------------------------------------------------------

def run_mean_reversion(prices, lookback_days, entry_drop_pct, exit_recovery_pct,
                        start_date=None, end_date=None):
    """
    Simple mean-reversion backtest:
      - Look at the % price change over the last `lookback_days`.
      - If it dropped by at least `entry_drop_pct`, buy.
      - While holding, sell as soon as price recovers by `exit_recovery_pct`
        from the entry price.
      - Only one position open at a time (no pyramiding).

    Returns a dict of trades and a day-by-day equity curve.
    """
    df = prices.copy()
    if start_date is not None:
        df = df[df["date"] >= start_date]
    if end_date is not None:
        df = df[df["date"] <= end_date]
    df = df.reset_index(drop=True)

    df["pct_change_over_lookback"] = df["close"].pct_change(lookback_days)

    cash = 100.0          # start with $100, track it as an index
    position_shares = 0.0
    entry_price = None
    trades = []
    equity_curve = []

    for i, row in df.iterrows():
        price = row["close"]

        if position_shares == 0.0:
            # Not holding - check if today's the day to buy in.
            drop = row["pct_change_over_lookback"]
            if pd.notna(drop) and drop <= -entry_drop_pct:
                position_shares = cash / price
                entry_price = price
                cash = 0.0
                trades.append({"action": "buy", "date": str(row["date"].date()), "price": price})
        else:
            # Holding - check if price has recovered enough to sell.
            recovery = (price - entry_price) / entry_price
            if recovery >= exit_recovery_pct:
                cash = position_shares * price
                trades.append({"action": "sell", "date": str(row["date"].date()), "price": price})
                position_shares = 0.0
                entry_price = None

        # Mark portfolio value to market every day (cash or shares held).
        value_today = cash if position_shares == 0.0 else position_shares * price
        equity_curve.append(value_today)

    # Close out any open position at the last available price so the
    # backtest doesn't end holding an unrealized position.
    if position_shares > 0.0:
        final_price = df.iloc[-1]["close"]
        cash = position_shares * final_price
        trades.append({"action": "sell (period end)", "date": str(df.iloc[-1]["date"].date()), "price": final_price})
        equity_curve[-1] = cash

    return {"trades": trades, "equity_curve": equity_curve, "dates": df["date"].tolist()}


# ---------------------------------------------------------------------
# 3. Turn the trade log / equity curve into simple performance metrics
# ---------------------------------------------------------------------

def compute_metrics(result):
    equity = pd.Series(result["equity_curve"])
    if equity.empty or equity.iloc[0] == 0:
        return {"total_return_pct": 0.0, "max_drawdown_pct": 0.0, "num_trades": 0, "win_rate_pct": 0.0}

    total_return_pct = (equity.iloc[-1] / equity.iloc[0] - 1) * 100

    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    max_drawdown_pct = drawdown.min() * 100

    # Pair up buy/sell trades to compute a simple win rate.
    buys = [t for t in result["trades"] if t["action"] == "buy"]
    sells = [t for t in result["trades"] if t["action"].startswith("sell")]
    wins = sum(1 for b, s in zip(buys, sells) if s["price"] > b["price"])
    num_round_trips = min(len(buys), len(sells))
    win_rate_pct = (wins / num_round_trips * 100) if num_round_trips > 0 else 0.0

    return {
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "num_trades": num_round_trips,
        "win_rate_pct": round(win_rate_pct, 2),
    }


# ---------------------------------------------------------------------
# 4. The agent's one public skill: run_backtest(strategy_spec)
# ---------------------------------------------------------------------

class QuantResearchAgent:
    """Matches the Agent Card skill: run_backtest(strategy_spec) -> backtest_result."""

    def __init__(self, data_file=DATA_FILE):
        self.data_file = data_file

    def run_backtest(self, strategy_spec):
        """
        strategy_spec example:
        {
            "ticker": "QQQ",
            "lookback_days": 5,
            "entry_drop_pct": 0.05,
            "exit_recovery_pct": 0.05,
            "train_start": "2010-01-01", "train_end": "2019-12-31",
            "test_start": "2020-01-01", "test_end": "2026-06-29",
        }
        """
        prices = load_prices(strategy_spec["ticker"], self.data_file)

        train = run_mean_reversion(
            prices,
            strategy_spec["lookback_days"],
            strategy_spec["entry_drop_pct"],
            strategy_spec["exit_recovery_pct"],
            start_date=strategy_spec["train_start"],
            end_date=strategy_spec["train_end"],
        )
        test = run_mean_reversion(
            prices,
            strategy_spec["lookback_days"],
            strategy_spec["entry_drop_pct"],
            strategy_spec["exit_recovery_pct"],
            start_date=strategy_spec["test_start"],
            end_date=strategy_spec["test_end"],
        )

        # backtest_result, shaped to match the Agent Card output_schema
        # (train vs. test kept separate - this is the anti-self-deception
        # check the Risk agent will look at next).
        return {
            "ticker": strategy_spec["ticker"],
            "strategy": "mean_reversion",
            "train_period": {"start": strategy_spec["train_start"], "end": strategy_spec["train_end"], "metrics": compute_metrics(train)},
            "test_period": {"start": strategy_spec["test_start"], "end": strategy_spec["test_end"], "metrics": compute_metrics(test)},
        }


# ---------------------------------------------------------------------
# 5. Example run
# ---------------------------------------------------------------------

if __name__ == "__main__":
    agent = QuantResearchAgent()

    strategy_spec = {
        "ticker": "QQQ",
        "lookback_days": 5,           # look at the 5-day price change
        "entry_drop_pct": 0.05,       # buy after a 5% drop over 5 days
        "exit_recovery_pct": 0.05,    # sell after a 5% bounce from entry
        "train_start": "2010-01-01",
        "train_end": "2019-12-31",
        "test_start": "2020-01-01",
        "test_end": "2026-06-29",
    }

    backtest_result = agent.run_backtest(strategy_spec)

    print(f"\nMean-reversion backtest: {backtest_result['ticker']}\n")
    for period_name in ["train_period", "test_period"]:
        p = backtest_result[period_name]
        print(f"{period_name}  ({p['start']} to {p['end']})")
        for k, v in p["metrics"].items():
            print(f"  {k}: {v}")
        print()
