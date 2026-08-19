# Methodology: Quant Trader Agent

*Paper section — The Fractional AI Workforce | Prepared by Shaurya*

## 1. Investment Thesis

Quant Trader is one of three independent specialist traders in the system, each proposing and testing a strategy through its own analytical lens — Technical (price action), Fundamental (fund-level characteristics), and Quant (statistics and cross-asset anomalies). Quant Trader's thesis does not rest on any single instrument's own history; it looks across pairs of ETFs for a real, persistent statistical relationship — high return correlation — and tests whether the price *spread* between the two, once it drifts unusually far from its own historical average, tends to snap back. A relationship that is both strongly correlated and genuinely mean-reverting is treated as a tradeable anomaly; correlation without measurable reversion is treated as coincidence, not a signal.

## 2. Statistical Discovery Methodology

Given a training-window price panel, discovery runs two independent, vectorized screens (pandas/numpy) over every candidate pair in the permitted universe — a full 120-ticker scan (~7,000 pairs) completes in well under a second:

- **Correlation screen.** Daily simple returns are computed for every ticker, and the pairwise Pearson correlation matrix is computed across the full panel at once. A pair is retained only if it has at least 750 trading days (~3 years) of overlapping history and a correlation at or above 0.70.
- **Mean-reversion (half-life) screen.** For each correlated pair, an AR(1) model is fit to the price ratio (spread) between the two tickers: `spread_change[t] = a + b × spread[t−1]`. A negative `b` indicates the spread tends to snap back toward its average rather than drift; the corresponding half-life, `−ln(2) / ln(1 + b)`, estimates how many trading days that snap-back typically takes. Pairs with no mean reversion, an undefined half-life, or a half-life exceeding 90 days are discarded as not tradeable within a practical horizon.

Correlation is treated as necessary but not sufficient by design: two assets can move together without their price ratio ever reliably reverting to a stable level, so every pair is required to clear both screens independently before it is considered a candidate.

Surviving candidates are ranked by a combined score, `correlation × 1 / (1 + half_life / 30)`, which rewards both a strong relationship and a fast reversion — a pair that reverts in two weeks offers materially more tradeable opportunities within a fixed window than one that takes three months, even at similar correlation. The top-ranked pair is the one submitted to the backtest engine, always accompanied by the underlying evidence (correlation, half-life, shared trading-day count, composite score) and a plain-language rationale so Risk and Reporting can evaluate the statistical basis rather than trust a bare assertion.

## 3. The Strategy: Cross-Asset Spread Mean Reversion

The winning pair is translated into a rule bound to one registered, deterministic executor (`quant_trader.cross_asset_spread_mean_reversion.v1`) with parameters `ticker_a`, `ticker_b`, `lookback_days`, `entry_zscore`, and `exit_zscore`. At each bar, the executor computes the rolling z-score of the `ticker_a / ticker_b` price ratio over the trailing `lookback_days` window, using only history already revealed to it at that point in time (point-in-time by construction, not by discipline). The position enters (target weight 100% `ticker_a`) once the z-score falls to or below `−entry_zscore` (default −1.5), and exits fully to cash once the z-score recovers to `−exit_zscore` (default −0.25); in between, the executor signals "hold whatever position is already open," giving the rule hysteresis so it does not flicker in and out on single-day noise. The strategy is long-only and single-position — no leverage, no shorting.

## 4. Pipeline and the Propose/Compute Boundary

Consistent with the project's core design rule — an LLM (or in this case, a statistics routine) never computes its own backtest performance — Quant Trader's `run()` method only proposes; a shared, deterministic backtest engine computes every reported number. The pipeline for one research round is:

1. **Fetch.** Request point-in-time daily OHLC data for the permitted universe from the injected Data service — the same shared boundary every trader depends on, not a Quant-Trader-specific integration.
2. **Resolve the train/test split before proposing anything.** The code-owned validation split is resolved immediately after the fetch and before any statistics run. The training panel handed to discovery is sliced to bars strictly before the resolved test-start date; discovery itself has no knowledge of any test window and cannot access it even by mistake. (An earlier standalone prototype of this logic scanned full history including the eventual test window to pick a pair — a genuine look-ahead bug that this design fixes structurally, not by convention.)
3. **Discover.** Scan every pair in the training-window panel as in §2.
4. **Package.** The strongest candidate becomes a fully specified rule (entry/exit logic, parameters, and the evidence that produced it) bound to the registered executor from §3.
5. **Evaluate.** The candidate is sent to the shared backtest engine unchanged; the agent has no ability to alter or interpret the resulting numbers before they are reported. The backtest plan also declares a same-terms benchmark — a buy-and-hold position in the pair's second leg — computed by the same engine, under the same assumptions, in the same run, so Risk has a real baseline to compare against rather than an assumption-free or self-selected one.
6. **Interpret.** A template-generated (not model-authored) interpretation turns the settled result into a structured summary for the Risk agent to review, explicitly flagging the selection-bias risk described in §6.

## 5. Verification and Representative Result

The full pipeline was run end-to-end against live data — real yfinance daily prices, through the actual shared, deterministic backtest engine, not a mock. A representative run over a 15-ticker candidate universe selected the EWA/EWC pair (correlation 0.846 over 2,009 shared trading days, ~56-trading-day half-life):

| Metric | Training window | Held-out test window |
|---|---|---|
| Total return | 27.26% | 22.65% |
| Annualized return | 2.45% | 10.79% |
| Sharpe ratio | 0.235 | 0.714 |
| Max drawdown | −33.41% | −17.95% |
| Transactions | 84 | 18 |

This result is reported here because the held-out test window held up *better* than the training window on every risk-adjusted measure (higher Sharpe, shallower drawdown, far fewer trades), which is a meaningfully different pattern from simple in-sample outperformance — consistent with a genuine mean-reversion relationship rather than a fit that only worked on the data used to find it. As with the rest of this project's reporting standard, this number is not treated as proof the strategy "works"; §6 and §7 describe why it still requires scrutiny.

## 6. Risk Analysis and Interpretation

Every candidate this agent proposes is passed to the Risk agent with the selection-bias risk stated explicitly, not left implicit: the reported candidate is the strongest of a scan across every pair in the permitted universe, and a single strong-looking result found this way is exactly the kind of process that can manufacture a good-looking outcome by chance, regardless of how the backtest itself performs.

In full-loop integration testing, this agent's candidates were reviewed against the Risk agent's real 13-point checklist (CP-1 through CP-13), in a two-trader round alongside Technical Trader. One genuine defect was found and fixed in the process: the backtest plan initially did not declare a same-terms benchmark, which caused Risk's CP-6 check to correctly veto every candidate ("No same-terms baseline: the plan lacks a benchmark or the engine produced no benchmark metrics"). After declaring a buy-and-hold benchmark on the pair's second leg, an unmodified Risk checklist run against a real candidate returned:

- **Approve**, with six checks passing cleanly (CP-3 backtest completeness, CP-5 canonical metrics present, CP-6 same-terms benchmark, CP-9 evidence traceability, CP-11 validation-touch budget, CP-12 no prior vetoes).
- Three checks (CP-1, CP-2, CP-4) returned `flag, requires human review` rather than a manufactured pass, since no round-audit-ledger service exists yet in this environment — an honest "cannot verify" rather than a false positive.
- One round-level check (CP-7, multiple-comparison disclosure) flagged that only one candidate reached Risk that round, reminding Reporting to disclose that rather than present a lone result as if it had no competing alternatives.

This confirms the interaction between this agent's output and Risk's real review logic end to end, not merely this agent in isolation. (Note: Fundamental Trader independently hit the identical CP-6 defect and fix during the same integration work — see `docs/fundamental_trader.md` — which is a second, independent confirmation that the benchmark requirement is a real, systemic Risk gate and not specific to one trader's design.)

## 7. Known Limitations and Assumptions

- **Selection-bias risk is real, not hypothetical.** Scanning hundreds of pairs and keeping the best-scoring one is exactly the kind of process that can manufacture a good-looking result by chance; this is surfaced explicitly in every interpretation rather than hidden, but it is not eliminated by the current design.
- **Single candidate per round.** Discovery can rank several qualifying pairs, but only the top-ranked candidate is currently backtested and submitted; presenting the top 2–3 would let Risk compare survivors rather than judge one pair in isolation.
- **Universe size affects results directly.** A small permitted universe can leave only one pair clearing both statistical thresholds in a given round, which limits how much genuine cross-sectional comparison Risk's multiple-comparison checks can perform.
- **Interpretation is template-generated, not model-authored** — a conservative stand-in pending a model-backed version, matching the other traders' current state.
- **No transaction-cost stress testing** beyond the shared engine's configured commission/slippage assumptions.
- **Data is not point-in-time verified in the strict sense.** yfinance prices are auto-adjusted for splits and dividends rather than reconstructed as-of a specific historical date, which the Data service's own provenance metadata discloses on every response.
