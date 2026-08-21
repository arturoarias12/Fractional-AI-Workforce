# Methodology: Data & Universe Selection

*Paper section — The Fractional AI Workforce | Prepared by Yiran*

## 1. Purpose

This section defines the investable universe and the market data used by all trader agents. Strategy discovery may differ by lens, but the universe, data source, and evaluation window are shared so Quant, Technical, and Fundamental results remain comparable.

## 2. Universe Ownership

The human Portfolio Manager sets the universe in the mandate. `permitted_asset_universe` is the candidate list; `prohibited_assets` are excluded. Traders do not expand the universe after seeing results. The shared DataService only fetches tickers supplied in the request.

## 3. Eligible Assets

The working universe is U.S.-listed ETFs named in the mandate (the Quant demo uses a 120-ticker ETF list). A name that is both permitted and prohibited is rejected. Agents may use a subset of the permitted list; they may not add names outside it.

## 4. Data Source and Fields

All agents obtain prices through the shared DataService, not through private APIs. The current provider is yfinance. We request daily OHLCV (open, high, low, close; volume optional). The same PriceBar objects are used for research fetch and backtest resolution.

## 5. As-of Discipline

Every request has an `as_of_date`. End dates are clipped to that date. If no start date is given, history defaults to about ten years before the end date. Bars after `as_of_date` are dropped.

## 6. Train / Test Split

A code-owned validation split is applied before strategy discovery. Training uses only bars strictly before `test_start_date`. Held-out metrics are computed on `[test_start_date, test_end_date]`, with `test_end_date` ≤ `as_of_date`. The split is not chosen by the LLM.

## 7. Use by Agents

Quant scans permitted names for cross-asset pairs using training-window closes. Technical requires daily OHLC for the same permitted names. Backtests resolve only symbols named in the candidate (for example `ticker_a` / `ticker_b` or `symbol`).

## 8. Missing Prices

If no current bar exists on an execution date, the engine skips that fill. It does not trade at a stale last close. Incomplete symbols are reported in the data response rather than silently filled.

## 9. Known Limitations and Assumptions

yfinance is unofficial and auto-adjusted, so it is not true point-in-time restated data. Survivorship and corporate-action revision risk are not controlled. This is a research prototype, not a licensed production feed.
