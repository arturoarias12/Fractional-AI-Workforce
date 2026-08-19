# Methodology: Fundamental Trader Agent

*Paper section — The Fractional AI Workforce | Prepared by Aditi*

## 1. Investment Thesis

The Fundamental Trader agent is one of three independent specialist traders in the system, each proposing and testing a strategy through its own analytical lens — Technical (price action), Quant (statistical anomalies), and Fundamental (fund-level characteristics). Fundamental Trader's thesis is that two ETFs classified under the same category track substantially similar underlying exposure by construction; if a smaller-issuer ETF's return diverges unusually far from the return of its category's large-issuer peers, that divergence is more likely a liquidity or technical artifact than a fundamentally justified difference, since nothing in a shared category definition explains why two funds tracking comparable exposure should diverge for long. The strategy tests whether that gap tends to close.

## 2. Adapting the Signal to the Available Data

The original design for this agent called for classic ETF fundamentals — expense ratio, dividend yield, NAV premium/discount, and sector or factor exposure. Direct inspection of the team's `ETF_info.xlsx` source data (not an assumption carried over from the original proposal) found that `marketCap`, `sector`, and `industry` are null or empty for all 120 tickers in the finalized universe. Only two fields are populated for effectively the entire universe: `category` (44 distinct values) and `fundFamily` (27 distinct values).

In place of the unavailable fields, this agent introduces an **ISSUER_SCALE_TIER** heuristic: `fundFamily` is bucketed into a "major" tier (nine large, broadly-distributed asset managers — iShares, Vanguard, State Street, Invesco, Schwab, Fidelity, JPMorgan, First Trust, and WisdomTree) versus a "boutique" tier (the remaining 18 issuers present in the fixture, including ARK, Global X, ProShares, and VanEck). Against the real 120-ticker universe, this splits 82 major-tier and 38 boutique-tier tickers.

*This substitution is treated as a limitation, not a hidden assumption: ISSUER_SCALE_TIER is a liquidity and issuer-scale proxy, not a direct fundamental valuation signal, and every candidate this agent proposes states that explicitly in the evidence passed to the Risk agent (see §6).*

## 3. The Strategy: Category-Benchmark Deviation

For each category with at least two major-tier constituents, the agent constructs an equal-weight "category benchmark" from those major-tier tickers' daily returns. For every boutique-tier ticker in that category, it computes the rolling z-score of the spread between that ticker's own return and the category benchmark's return, over a trailing lookback window (20, 40, or 90 trading days, selected per candidate). Candidates are ranked by |z-score| × historical correlation to the benchmark, favoring tickers that normally track their peers closely but have recently diverged sharply — the strongest evidence of a temporary dislocation rather than a structural difference.

The resulting rule is long-only and single-position: enter the boutique-tier ticker when its spread z-score falls to or below −entry_zscore (default −1.5); exit to cash once it recovers to −exit_zscore (default −0.25). No leverage or shorting is used.

## 4. Pipeline and the Propose/Compute Boundary

Consistent with the project's core design rule — an LLM never computes its own backtest performance — this agent's `run()` method only proposes; a shared, deterministic backtest engine computes every reported number. The pipeline for one research round is:

1. **Fetch.** Request point-in-time price data and ETF category/fund-family metadata for the permitted universe from the injected Data service, delivered as a single package as soon as the PM sets the mandate.
2. **Resolve the train/test split before proposing anything.** Discovery only ever sees bars strictly before the held-out test window — the anti-look-ahead guarantee.
3. **Discover.** Scan every boutique-tier ticker in every populated category for a significant deviation from its major-tier benchmark, ranked as in §3.
4. **Package.** The strongest candidate becomes a fully specified rule (entry/exit logic, parameters, and the evidence that produced it) bound to a registered, deterministic executor.
5. **Evaluate.** The candidate is sent to the shared backtest engine unchanged; the agent has no ability to alter or interpret the resulting numbers before they are reported.
6. **Interpret.** A template-generated (not model-authored) interpretation turns the settled result into a structured summary — metrics, strengths, weaknesses, overfitting risks, and limitations — for the Risk agent to review.

## 5. Verification and Representative Result

The full pipeline was run end-to-end — offline, against the real 120-ticker dataset — through the actual shared, deterministic backtest engine, not a mock. A representative run selected AWAY (a boutique-tier "Consumer Cyclical" ETF) against a benchmark of its major-tier category peers (PEJ, XLY):

| Metric | Training window | Held-out test window |
|---|---|---|
| Total return | −7.40% | −14.96% |
| Annualized return | −0.28% | −3.51% |
| Sharpe ratio | −0.03 | −0.31 |
| Max drawdown | −22.27% | −20.11% |
| Transactions | 182 | 128 |

This result is reported here deliberately because it is a losing one, not a cherry-picked winner: the strategy underperformed on both the training and held-out windows. This is treated as evidence the pipeline is reporting honestly, in line with the project's central design principle that agent output must be evaluated by real, unfavorable results as readily as favorable ones — not selectively surfaced only when it looks good.

## 6. Risk Analysis and Interpretation

Every candidate this agent proposes is passed to the Risk agent with two limitations stated explicitly, not left implicit:

- **Selection-bias exposure.** The reported candidate is the strongest of a scan across every boutique-tier ticker in every populated category — a single strong-looking deviation found this way is exactly the kind of result that needs independent scrutiny for cherry-picking, regardless of how the backtest itself performs.
- **Proxy-signal exposure.** ISSUER_SCALE_TIER substitutes for fund-level fundamentals that are not available in the source data; Risk is told explicitly that the underlying signal is a liquidity/issuer-scale proxy, not a direct valuation gap, so it can weigh the candidate accordingly.

In full-loop integration testing, this agent's candidates were reviewed against the Risk agent's real 13-point checklist (CP-1 through CP-13). One genuine defect was found and fixed in the process: the backtest plan initially did not declare a same-terms benchmark, which caused Risk's CP-6 check to correctly veto every candidate. After declaring a buy-and-hold benchmark on the traded ticker, candidates from this agent received a real approve verdict from the unmodified Risk checklist — confirming the interaction between this agent's output and Risk's review logic, not merely this agent in isolation.

## 7. Known Limitations and Assumptions

- ISSUER_SCALE_TIER is a heuristic (nine issuers selected for AUM/shelf-space breadth), not a licensed or team-confirmed classification.
- The category benchmark is computed in-house as an equal-weight average of major-tier peers sharing a category in this fixture, not a licensed index.
- Interpretation of backtest results is template-generated, not model-authored — a conservative stand-in pending a model-backed version.
- No transaction-cost stress testing beyond the shared engine's configured commission/slippage assumptions.
- The agent proposes a single top-ranked candidate per round; Risk currently reviews one Fundamental Trader ticker per round, not several ranked alternatives.
