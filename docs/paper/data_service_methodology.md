## Methodology: data & universe selection

**Purpose**

This section defines the investable universe and the market data used by all trader agents. Strategy discovery may differ by lens, but the universe, data source, and evaluation window are shared so Quant, Technical, and Fundamental results remain comparable.

**Universe ownership**

The human Portfolio Manager sets the universe in the mandate. permitted\_asset\_universe is the candidate list; prohibited\_assets are excluded. Traders do not expand the universe after seeing results. The shared DataService only fetches tickers supplied in the request.

**Eligible assets**

The working universe is U.S.-listed ETFs named in the mandate (the Quant demo uses a 120-ticker ETF list). A name that is both permitted and prohibited is rejected. Agents may use a subset of the permitted list; they may not add names outside it.

**Data source and fields**

All agents obtain prices through the shared DataService, not through private APIs. The current provider is yfinance. We request daily OHLCV (open, high, low, close; volume optional). The same PriceBar objects are used for research fetch and backtest resolution.

**As-of discipline**

Every request has an as\_of\_date. End dates are clipped to that date. If no start date is given, history defaults to about ten years before the end date. Bars after as\_of\_date are dropped.

**Train / test split**

A code-owned validation split is applied before strategy discovery. Training uses only bars strictly before test\_start\_date. Held-out metrics are computed on \[test\_start\_date, test\_end\_date\], with test\_end\_date ≤ as\_of\_date. The split is not chosen by the LLM.

**Use by agents**

Quant scans permitted names for cross-asset pairs using training-window closes. Technical requires daily OHLC for the same permitted names. Backtests resolve only symbols named in the candidate (for example ticker\_a / ticker\_b or symbol).

**Missing prices**

If no current bar exists on an execution date, the engine skips that fill. It does not trade at a stale last close. Incomplete symbols are reported in the data response rather than silently filled.

**Limitations**

yfinance is unofficial and auto-adjusted, so it is not true point-in-time restated data. Survivorship and corporate-action revision risk are not controlled. This is a research prototype, not a licensed production feed.  
