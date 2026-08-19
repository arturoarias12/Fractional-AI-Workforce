# Methodology: Technical Trader Agent

*Paper section — The Fractional AI Workforce | Prepared by Arturo Arias*

## 1. Investment Thesis and System Role

The Technical Trader is one of three independent specialist traders in the Fractional AI Workforce, alongside Fundamental and Quant. It converts a normalized Portfolio Manager mandate and point-in-time exchange-traded fund (ETF) price data into one auditable, executable multi-ETF strategy package. Its thesis is that price structure, trend, momentum, and market participation can identify repeatable tactical opportunities when the evidence is defined before evaluation, evaluated at a scale appropriate to the mandate, and translated into deterministic entry and exit rules after costs.

The design deliberately separates judgment from calculation. A large language model plans the research, compares eligible technical setups, forms one portfolio, challenges its initial proposal, and explains the deterministic result. Ordinary Python computes all indicators, validates every evidence reference, executes each trading rule, applies costs and constraints, and calculates performance. The model cannot invent prices, indicator values, backtest returns, or exceptions to the mandate.

The Technical Trader does not approve its own recommendation, combine it with another trader's output, or make the final investment decision. It returns the same typed TraderStrategyPackage used by the other trader branches for collective Risk and Reporting review. The Portfolio Manager may then accept, reject, compare, or request another research round. This common boundary prevents Technical-specific orchestration and permits the three trader branches to execute in parallel.

## 2. Architecture, Inputs, and Data Boundary

Four replaceable interfaces isolate the agent from shared infrastructure: a structured-output ModelClient, a point-in-time DataService, a deterministic BacktestEngine, and an injected ValidationSplitPolicy that supplies the shared evaluation dates. The LangGraph adapter exposes the Technical Trader as a single node that reads pm_mandate and writes technical_trader_package. Its internal planning, analysis, review, validation, evaluation, and interpretation stages therefore remain encapsulated within the trader branch.

The mandate defines the objective, investment horizon, permitted asset universe, prohibited assets, risk tolerance, leverage and short-selling constraints, liquidity requirements, rebalancing preference, and as-of date. The model may interpret those instructions through a Technical lens, but it cannot broaden the universe or weaken structured limits. The same normalized mandate can be consumed independently by Technical, Fundamental, and Quant.

The agent requests daily point-in-time market data through the shared Data Service. Symbol identity, timezone-aware timestamp, open, high, low, and close form the mandatory analytical core. Volume, trading-session flags, ETF lifecycle data, liquidity metadata, and adjustment metadata are requested when available. A missing optional field disables only the dependent strategy family: for example, incomplete volume prevents a volume-confirmed breakout but does not invalidate support, resistance, pattern, or moving-average evidence.

Each series is validated before analysis. Timestamps must be unique, strictly increasing, timezone-aware, and no later than the permitted as-of boundary. OHLC values must be finite, positive, and internally consistent; supplied volume must be non-negative. Immutable data references, coverage, provenance, unavailable fields, and limitations are retained in the final package. The shared Data Service and evaluation policy remain authoritative for the market calendar, price adjustments, missing-bar treatment, and survivorship policy.

## 3. Controlled LLM Reasoning

A normal research round makes four structured LLM calls. Every response must satisfy a typed Pydantic contract before it can affect deterministic execution.

### Research planning

The first call translates the mandate into a data and research plan without selecting an ETF or strategy. Code normalizes the request so that daily symbol, timestamp, open, high, low, and close data remain mandatory and strategy-specific enhancements remain optional.

### Candidate construction

After deterministic analysis of the complete permitted universe, the second call receives a bounded shortlist of eligible technical opportunities. By default, the top 20 unique ETFs are exposed for comparative reasoning while the complete universe report remains attached for audit. The model creates one multi-ETF portfolio and aims for ten unique holdings, but may select fewer when frozen training evidence does not support a positive technical hypothesis for ten. Such a hypothesis is a model-authored interpretation of submitted evidence, not a calibrated expected return or guarantee.

For each sleeve, the model chooses one eligible ETF, one registered strategy family, and the exact evidence identifiers required by that family. It may explain the setup and select only the bounded buffers allowed by the executor contract. It may not reproduce high-precision indicator values, transcribe support prices, estimate a neckline, select the held-out period, or manufacture performance.

### Independent technical review

The third call challenges the whole proposed portfolio using the same frozen training report. It reviews contradictory signals, staleness, fragile structures, whipsaw risk, false breakouts, repeated exposure to similar technical conditions, and avoidable concentration. It may replace sleeves or reduce portfolio size, but it cannot use held-out results, fundamental information, macroeconomic forecasts, or quantitative factor claims. An invalid review is recorded as a non-fatal failure and the already validated initial proposal is retained; an invalid initial proposal fails closed.

### Backtest interpretation

The fourth call interprets only the metrics, warnings, constraints, and benchmark comparison returned by deterministic code. It may explain strengths, weaknesses, uncertainty, and mandate alignment, but it cannot recalculate metrics, approve the candidate, override a deterministic fallback, or claim that historical performance will persist.

Interchangeable asynchronous OpenAI and Anthropic adapters implement the same structured-output contract. Provider and model choice are deployment configuration rather than agent logic. Both paths revalidate output locally, normalize provider request and token telemetry, reject incomplete or truncated output, and use the same bounded execution policy. API credentials are read only during explicit runtime composition and are not stored in prompts, packages, or source files.

## 4. Deterministic Technical-Analysis Toolkit

### Support and resistance

Support and resistance are derived from clustered local pivots. Code identifies strict pivot lows and highs with a symmetric window, sorts their prices, clusters nearby pivots within a percentage tolerance, rejects clusters with insufficient touches, and averages the surviving prices. Defaults use two bars on each side, a 1% merge tolerance, at least two touches, and no more than eight levels of each type. Every level records type, price, touch count, source pivots, first and last touch times, distance from the latest close, and a stable evidence identifier. If no repeated-touch level survives, the observed range boundary is retained with used_range_fallback=true for description only; it cannot satisfy a reliable-level rule.

### Head-and-shoulders structures

Normal and inverse head-and-shoulders observations are geometric pivot structures. The normal form requires a central high above two sufficiently similar shoulder highs, minimum pivot separation, a bounded total span, and a neckline constructed from intervening lows; confirmation requires a later close below that neckline. The inverse form applies the corresponding conditions to three lows and requires a later close above the neckline. Defaults use 4% shoulder similarity, 3% head prominence, at least two bars between pivots, and a maximum span of 126 bars. Forming and confirmed labels describe observed geometry, not predictions. Only a confirmed inverse formation is eligible for the current long-only executor.

### Moving averages and relative volume

Python computes simple moving-average evidence at 3/10, 5/20, 10/30, 20/50, 50/100, and 50/200 bars. Each observation includes the averages, percentage spread, bullish, bearish, or neutral relationship, latest crossover direction and time, and bars since the crossover. A neutral band prevents small numerical differences from becoming false signals. When complete volume is present, relative volume compares the latest observation with the preceding 20-bar mean and records the ratio and contemporaneous return. Missing or non-positive comparison data produces a warning and no volume observation; the model cannot impute it.

## 5. Horizon-Adaptive Policy and Opportunity Screen

The PM's investment horizon determines the analytical scale, review cadence, rolling-level lookback, position holding cap, volatility lookback, risk scaling, pattern recency, and eligible moving-average windows. Structured trading-day values and natural-language day, week, month, and year expressions are accepted. An absent or unparseable horizon uses a disclosed balanced profile of 63 trading days rather than allowing the model to invent one.

| PM horizon | Moving-average pairs | Review cadence | Level lookback | Maximum level distance |
|---|---|---:|---:|---:|
| 1–5 days | 3/10 and 5/20 | 1 bar | 63 bars | 3% |
| 6–20 days | 5/20 and 10/30 | 1 bar | 126 bars | 5% |
| 21–63 days | 10/30 and 20/50 | 5 bars | 252 bars | 8% |
| 64–126 days | 20/50 and 50/100 | 10 bars | 378 bars | 12% |
| 127+ days | 50/100 and 50/200 | 21 bars | 504–756 bars | 20% |

The maximum position holding period is the shorter of the PM horizon and any stricter risk limit. A tighter cap changes duration without silently rewriting the longer-term evidence profile. At least 252 training observations are required before an asset enters the opportunity screen. Family-specific opportunities are created using only evidence frozen at the training cutoff.

The reproducible opportunity score combines applicable level proximity, repeated-touch quality, recency, trend strength, relative volume, bounded movement capacity, and horizon-family fit. The screen balances the shortlist across available families rather than presenting only one signal type. This score prioritizes submitted evidence; it is neither an optimized backtest statistic nor a forecast.

## 6. Strategy Construction and Evidence Enforcement

The package-level executor, technical.multi_asset_portfolio.v1, coordinates one to ten independently stateful long-only ETF sleeves within one candidate artifact. Current model-selectable families are:

- Rolling support reaction.
- Rolling resistance breakout.
- Horizon-adaptive moving-average trend.
- Rolling volume-confirmed resistance breakout.
- Confirmed inverse-head-and-shoulders breakout.

Bearish head-and-shoulders remains analytical evidence but is not an executable long-only sleeve. Every selected sleeve must exactly match one code-ranked opportunity by symbol, executor family, and complete evidence-ID set. Deterministic validation rejects unsubmitted symbols, missing or extra IDs, evidence belonging to another ETF, fallback or wrong-side levels, incompatible moving-average windows, forming patterns represented as confirmed, and executors that cannot implement the stated rule.

After validation, code binds evidence-derived values such as moving-average windows, pattern neckline, level eligibility, volume lookback, rolling review settings, holding limits, and volatility-scaled risk parameters. The model chooses among supported opportunities without being trusted to copy precise numerical inputs. The portfolio is equal-weighted within its gross target. Sleeves enter, exit, and re-enter independently, and capital assigned to inactive sleeves remains in cash. Each state change returns the full active target mapping so active sleeves can be restored to equal targets; this deliberate drift correction can increase turnover.

## 7. Point-in-Time Execution and Backtesting

Portfolio membership and strategy-family selection are frozen before held-out evaluation. During the backtest, rolling executors recompute levels, moving averages, volume relationships, and volatility using only bars completed by the current signal timestamp. A pattern neckline remains fixed because it represents the specifically cited training-period formation. Orders fill only after the configured signal delay, preventing a signal from using the same bar's future execution price.

The shared Backtest Engine is the only component allowed to calculate returns. It receives the finalized rule and registered executor, immutable data references, mandate constraints, evaluation window, frequency, benchmark identity, execution assumptions, transaction costs, and requested metrics. It returns immutable status, metrics, warnings, constraint violations, artifact references, and a run-ledger entry.

The isolated validation configuration used daily bars, one-bar-delayed next-open execution, 1 basis point of commission, 2 basis points of slippage, long-only exposure, maximum gross leverage of 1.0, initial capital of $100,000, and deterministic end-of-test liquidation. Requested metrics were total and annualized return, maximum drawdown, annualized volatility, Sharpe ratio, transaction count, transaction costs, and turnover.

## 8. Horizon-Matched Evaluation and Benchmark Gate

The primary held-out window matches the PM's requested investment horizon: approximately 21 trading sessions for one month and 504 sessions for two years. The injected shared policy selects the exact market dates. The Technical Trader checks that the supplied span is plausible for the mandate, while the policy and Data Service remain responsible for the precise exchange calendar. Training evidence ends before the held-out window begins, and no model prompt receives held-out prices or results before membership is finalized.

Each completed run evaluates two executable candidates: the reviewed Technical portfolio and a buy-and-hold benchmark. Both use the identical finalized plan, including dates, frequency, costs, signal delay, fill-price field, liquidation rule, constraints, data references, and execution context. A convenience benchmark series may remain in the engine ledger for audit, but it is not used for selection if its timing differs from an executable strategy.

The prototype gate compares held-out total return. Strict Technical outperformance retains the multi-ETF strategy; equality or underperformance selects the already evaluated benchmark. The model cannot author or override this decision, and the rejected Technical request, result, and ledger remain attached. Because the same held-out period both evaluates and selects the final artifact, this is a transparent prototype policy rather than independent confirmation. The package records selection_uses_evaluation_window=true and independent_post_selection_test_required=true. Future governance may instead return the Technical proposal with a warning, permit abstention, or leave cross-strategy selection entirely to the Portfolio Manager.

## 9. Output, Auditability, Integration, and Resilience

The final TraderStrategyPackage contains workflow, task, attempt, trader, package, and candidate identities; the normalized mandate reference; requested and used data with provenance and limitations; the complete deterministic Technical report; the selected rule, registered executor, parameters, and evidence mappings; the finalized backtest request, result, and ledger; the constrained LLM interpretation; mandate assessment; non-fatal diagnostics; resolved horizon and evaluation semantics; initial and reviewed membership; the Technical-versus-benchmark comparison; and Risk-review eligibility.

Only a complete, successfully analyzed, backtested, and interpreted package is eligible for Risk review. A stage failure settles as a structured partial or failed package instead of raising an unhandled exception through the full multi-agent workflow. Operational diagnostics are isolated from model-authored strategy text so an exception message cannot trigger analytical guardrails. The Technical branch therefore preserves partial evidence and failure details without invalidating unrelated branches.

Model-call telemetry records the agent, operation, workflow, task, call, attempt, provider request ID, latency, token usage, model identity, status, and provider-reported cost when available. The complete Technical Trader deadline is 400 seconds. Model, data, specialist, and backtest operations remain separately bounded, and runtime composition validates that retry and timeout budgets fit within the surrounding deadline. Provider choice remains a configuration change, while the LangGraph node and downstream package contract remain stable.

## 10. Prototype Verification and Representative Result

The complete Technical pipeline was validated locally without invoking the other agents or the production LangGraph. The controlled harness analyzed the full 120-ETF fixture universe with a real OpenAI model. Technical evidence was frozen through June 24, 2024, and the reviewed portfolio and executable IVV benchmark were evaluated over the same 504 subsequent trading sessions from June 25, 2024 through June 29, 2026. All four model stages, both deterministic backtests, evidence validation, and package construction completed without model failure, engine warning, constraint violation, or benchmark fallback.

| Metric | Technical portfolio | Executable IVV benchmark |
|---|---:|---:|
| Total return | 43.44% | 39.57% |
| Annualized return | 19.81% | 18.18% |
| Sharpe ratio | 1.69 | 1.09 |
| Maximum drawdown | -11.29% | -18.75% |
| Annualized volatility | 11.07% | 16.56% |
| Transactions | 195 | 2 |
| Transaction costs | $209.17 | $71.88 |

The Technical portfolio exceeded the executable benchmark by 3.87 percentage points in this one held-out path while exhibiting lower drawdown and volatility. The run completed in approximately 114 seconds and used 191,263 provider-reported tokens across four calls: 179,878 input tokens and 11,385 output tokens. The provider did not return a monetary cost. This result verifies the pipeline, point-in-time boundary, evidence enforcement, and like-for-like execution. It does not establish persistent alpha or forecast future performance.

## 11. Risk Interpretation, Limitations, and Appropriate Claims

Every complete package is handed to Risk with the technical report, rule, evidence mappings, data provenance, mandate assessment, backtest ledger, warnings, and model telemetry. Exact evidence enforcement prevents the model from introducing an unsubmitted ETF, unsupported strategy, fallback level, incompatible indicator window, or fabricated observation. Risk still must judge whether the Technical package is acceptable beside the independently generated Fundamental and Quant packages.

- Support, resistance, pattern, and opportunity-score definitions are configurable heuristics rather than universally accepted market truths or calibrated expected-return models.
- One horizon-length evaluation cannot separate strategy skill from regime luck, and daily observations and repeated positions are not statistically independent.
- Portfolio membership is fixed at the training cutoff. Rolling rules adapt using past bars, but the agent does not replace ETFs during the same package run.
- The benchmark gate reuses the reported held-out period and therefore introduces selection bias; an untouched post-selection period remains necessary.
- The local fixture lacks complete volume, liquidity, lifecycle, and capacity metadata, limiting volume-confirmed strategies and market-impact analysis.
- Per-sleeve return, cost, and turnover attribution are not yet included in the shared result, so portfolio-level metrics do not identify each sleeve's contribution.
- Results depend on shared universe construction, calendar, adjustment, missing-bar, survivorship, execution, and cost policies that must remain common across traders and benchmarks.
- The Technical Trader does not learn automatically across tests. Memory may supply controlled context, but deterministic parameters are not fitted with machine learning.
- OpenAI and Anthropic support is implemented, but each chosen production model still requires a credentialed acceptance test for structured-output compatibility, latency, token use, and cost.

The appropriate prototype claim is therefore limited but meaningful: the Technical Trader can construct, execute, and fairly compare an auditable, horizon-aware technical strategy package. A successful historical path is evidence of engineering validity, not proof of generalizable alpha or suitability for live capital.

## 12. Recommended Evaluation Extensions

The next methodological extension should be rolling horizon-matched evaluation. For a 504-session mandate, the system should repeatedly freeze evidence at time T, construct a new portfolio, evaluate T through T+504, and advance the origin by a fixed interval such as 63 sessions. The full distribution should report median excess return, benchmark hit rate, worst window, dispersion, drawdown, turnover, and costs. Selecting only the best window would reintroduce data snooping.

After rolling evaluation, a final period should remain untouched by evidence selection, prompt refinement, parameter changes, and benchmark gating. The already selected configuration should be executed on that period once. Rolling windows test regime robustness and portfolio-selection stability, while the untouched final period tests post-selection generalization; neither substitutes for the other.

Further shared evaluation should add per-sleeve attribution, liquidity and capacity diagnostics, sensitivity tests for review cadence and risk parameters, and comparison of Technical, Fundamental, and Quant packages under common mandates. These additions belong to the shared evaluation and Risk framework and do not require changing the Technical Trader's input or output contract.

## 13. Conclusion

The Technical Trader establishes a clear division of labor between LLM reasoning and deterministic finance code. The model supplies comparative technical judgment; typed contracts and ordinary Python enforce evidence, execution, constraints, costs, metrics, and auditability. Horizon-adaptive screening allows the same agent boundary to serve short and long mandates, while point-in-time evaluation and executable benchmark comparison make the resulting claims inspectable.

Its main contribution is not a promise that technical analysis will always outperform. It is a reproducible method for converting an LLM's technical reasoning into a bounded, testable, and reviewable multi-ETF strategy artifact without delegating arithmetic or historical performance claims to the model. The package is modular, provider-selectable, LangGraph-compatible, resilient to partial failure, and ready for collective Risk review within the full Fractional AI Workforce.
