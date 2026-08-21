# The Fractional AI Workforce

**Managing a Team of AI Research Specialists on Measured Performance**

Arturo Arias, Aditi Bagwe, Yiran Li, Yutong Liu, Shaurya Manhas, Emma Peng, Wanyi Zheng

## Abstract

Discussions of AI agents typically ask whether a single agent can complete a task. This project asks a different question: once a human delegates work to a team of AI specialists instead of one, how do they decide who to trust, who to let go, and who to try differently — the way a manager runs a small team of people, on measured performance rather than impression? We answer this inside a concrete, testable setting: a solo Portfolio Manager who hires five specialist agents — three independent traders (Technical, Fundamental, Quant), a Risk/Skeptic agent, and a Reporting agent — to propose, backtest, and critique trading strategies across a fixed 120-ETF universe, with every number a human acts on computed from an immutable event ledger rather than any agent's self-report. The system was verified end-to-end, not merely demoed: a real four-round production run drove real Fundamental, Quant, Risk, Reporting, and Memory components against live data, and by round 4 the same unmodified 13-point Risk checklist vetoed both surviving candidates on its validation-touch budget check — a genuine, mechanically-produced veto rather than a scripted outcome. Hire, bench, and pivot decisions were confirmed to carry real effects into subsequent rounds. We report these results, including a losing backtest, an unresolved data-provenance regression, and a crashed agent, as readily as the favorable ones. The contribution is a management mechanism, not a trading signal: this work demonstrates that a human can staff and evaluate a team of AI research agents on real, replayed performance data, not a claim that any strategy here is ready for live capital.

---

## 1. Introduction & System Architecture



### 1. The Idea, in Plain Terms

Most discussions of "AI agents" focus on whether an agent can complete a task. This project asks a different question: once you have a team of AI agents instead of one, how does a human actually manage them — decide who to trust, who to let go, and who to try differently — the way a manager runs a small team of people? The Fractional AI Workforce answers that question inside a concrete, testable setting: a solo investment researcher who "hires" a small staff of AI specialists to research trading strategies. The specific setting (finance) is a vehicle; the actual contribution is a management pattern — a dashboard and a set of productivity metrics that turn "which AI agent should I keep using" into a data-driven decision instead of a guess.

### 2. The System in One Paragraph

The Fractional AI Workforce is a Virtual Office in which a human Portfolio Manager (PM) delegates to five hireable specialist agents — three independent traders (Technical, Fundamental, Quant), a Risk/Skeptic agent, and a Reporting agent — that together propose, backtest, and critique trading strategies across a fixed 120-ETF universe. A real-time dashboard tracks each agent's real, measured productivity (cost, latency, success rate, veto rate), and that data — not subjective judgment — is the input to the PM's hire/fire/pivot decisions. That loop now runs for real, end to end: a human decision pauses and resumes the actual system, staffing changes have a real effect on the next round, and the data behind every metric is replayed from an event ledger rather than any agent's self-report.

### 3. The Architecture Decision: The Independent Trader Architecture

Two architectures were evaluated for how Technical, Fundamental, and Quant should relate to each other: the Independent Trader Architecture (adopted), where each trader owns the full propose-through-backtest pipeline for its own analytical lens, and a combined-strategy alternative, where three analysts feed a single combiner before backtesting. The independent design was chosen for three reasons: it keeps the hireable roster at exactly 5 agents, as the project brief requires; it makes every result attributable to a single agent, which the hire/fire/pivot thesis depends on; and the alternative's synthesis step — mechanically combining a technical, a fundamental, and a statistical signal into one rule — was a genuinely unsolved design problem the timeline could not safely absorb. One idea from that alternative was kept: the Data service pushes an initial point-in-time package to all three traders as soon as the PM sets the mandate, rather than each trader starting from nothing.

### 4. The Five Hireable Agents

| Agent | Lens / Job | Owner | Status |
| --- | --- | --- | --- |
| Technical Trader | Charts, volume, indicators (RSI, MACD, moving averages) | Arturo | Real when configured (OpenAI/Anthropic/Gemini adapters built); falls back to a labeled stub without credentials. Live-key smoke test completed — see the Technical Trader methodology section for the verified result. |
| Fundamental Trader | Fund-level fundamentals via ISSUER_SCALE_TIER heuristic (category-benchmark deviation) | Aditi | Built, tested, verified end-to-end |
| Quant Trader | Statistical anomalies — cross-asset mean-reversion pairs | Shaurya | Built, verified end-to-end |
| Risk / Skeptic Agent | 13-point cherry-picking checklist (CP-1–CP-13); can veto any candidate | Yutong | Built, verified against real candidates and a real 4-round run |
| Reporting Agent | Assembles the strategy memo from whatever survives Risk | Emma | Built, verified against real Risk output |

*Data service and the deterministic backtest engine are shared infrastructure — tools every trader calls — not hireable agents, which keeps the roster at 5 per the project brief.*

### 5. The Research Loop

PM → Data (initial push) → {Technical, Fundamental, Quant} in parallel → Risk → Reporting → PM decision (durable interrupt) → Memory → next round.

The PM sets the mandate — not just as-of date and universe, but risk profile, investment horizon, rebalancing preference, risk limits, and leverage/short constraints, all of which now have a real, documented effect on what each trader proposes (see §6). The Data service immediately pushes an initial data package to all three traders. Each trader independently proposes a rule using its own lens and tests it via the shared backtest engine. Risk reviews all three results together against its 13-point checklist and can veto any of them. Reporting writes up whatever survives. The PM's decision — Select, Reject, or Request Another Round — is a real pause-and-resume of the running system, not a script: the graph genuinely halts and waits for that decision, and Hire/Bench/Pivot choices made at that point carry into the next round. The outcome is written to a persistent Memory store that survives between rounds, closing the loop.

### 6. What Was Actually Fixed, Not Just Planned

A round of dashboard testing surfaced three real gaps between what the system was supposed to do and what it actually did. All three were found, fixed, and verified against the real system, not just described:

| Gap found | Fix |
| --- | --- |
| Only as-of date, universe, and prohibited assets affected trader behavior; every other mandate field was accepted and displayed but ignored. | Built a shared, documented resolver (`mandate_directives.py`) used by both deterministic traders: `risk_profile` tunes entry conviction, `rebalancing_preference` tunes exit patience, `investment_horizon` sets the lookback window, `risk_limits.max_drawdown` is a real post-backtest screen, leverage/short constraints are validated (not ignored), and `market_context`/`pm_notes`/`prior_round_lessons` exclude specific tickers via a stated keyword scan. |
| Hire/Bench worked, but "Pivot" was cosmetic — it mapped to the same status as Hire and only wrote a UI log line. | Pivot now tags a real, agent-scoped exclusion that rides into the next round's mandate, genuinely changing which candidate that specific agent proposes next. Verified end-to-end: pivoting an agent changes its output; other agents are unaffected. |
| Non-time productivity metrics (success rate, retries, failures) stayed N/A even after the evaluation harness was built. | Found the actual cause: the dashboard had a second, separate, incomplete metrics calculation that hardcoded `success_rate` to "N/A" unconditionally. Replaced it with the real, tested `evaluation.harness` module — one source of truth instead of two disagreeing ones. |

### 7. Verification Discipline

- 111 automated tests pass on `main` as of this writing (up from 91 at the time the mandate-directive fix first landed, as more agent and integration work merged in), including 20 covering the mandate-directive resolver and two full end-to-end proofs that a Pivot action and a risk-profile change each genuinely alter what a trader proposes — not just that the underlying resolver returns the right value in isolation.
- A representative live run drove the real system through four consecutive rounds (23 operational events), and the Risk agent's deterministic checklist correctly vetoed both surviving candidates at round 4 on CP-11 (the validation-touch budget) — a genuine veto produced by real code reviewing real results, not a scripted demo outcome.
- The dashboard was verified to launch cleanly from a completely fresh install, following its own README's setup instructions exactly, before any documentation claims were made about it.
- Every fix in §6 was verified against the real, shared 120-ETF dataset through the actual compiled production graph — not a mock — and confirmed that both real traders still pass Risk's unmodified checklist afterward.

### 8. Known Limitations (honest, not hidden)

- Technical Trader's live model call has been smoke-tested with real credentials against a real OpenAI model — see its methodology section's verified result (43.44% vs. a 39.57% executable benchmark over a 504-session held-out window). That result came from a controlled, Technical-only harness, not the full five-agent production graph; a separate integration run confirmed the same runtime completes correctly inside the compiled production graph alongside Fundamental and Quant Trader, but that run did not independently re-verify the backtest performance figures above.
- Five of the Risk agent's 13 checks (CP-1, CP-2, CP-4, CP-10, CP-12) require a round-audit and round-history reader that doesn't exist yet; they currently return a flag requiring human review rather than a computed verdict, and are honest about that rather than defaulting to pass.
- A data-provenance regression was found and documented, not silently patched: the shared data source's point-in-time verification was relaxed at some point, and no current check catches that specific class of regression. This is flagged as a genuine open question for the team, not resolved unilaterally.
- API cost is measured end-to-end in the metrics pipeline but has no live runtime source wired in yet, so it currently reports N/A rather than a number — stated as an absence, not printed as zero.
- The `risk_limits.max_drawdown` screen checks only the single top-ranked candidate per trader per round; a lower-ranked, compliant alternative is not automatically retried the same round.
- Memory and paused-round state persist to local files, not a shared or hosted store — correct for a single-machine demo, not yet a multi-user system.

### 9. Where This Leaves the Project

The engine of the system — the mechanism the entire hire/fire/pivot thesis depends on — is proven to work end-to-end, with real agents, real Risk review, real Reporting output, real Memory, and real staffing effects. Every agent has a completed methodology section. What remains is concentrated in a small number of well-understood, individually owned items (§8), plus assembling the individual methodology sections into one coherent final paper — which has not yet started, despite every section it depends on now existing. For a reader evaluating this as a portfolio artifact, the distinction that matters is between a demo that merely runs and a system whose behavior, including its failure modes, has been independently verified — this project has consistently aimed for the latter, including when that meant reporting a losing backtest or an unresolved regression rather than a cleaner story.


Several concrete gaps were found this way beyond the three above — from the same-terms-benchmark defect Fundamental and Quant Trader hit independently (see their respective sections) to the point-in-time data check that was quietly relaxed on Technical Trader's data boundary (see the Risk Agent section) — each disclosed in the section of the agent that owns it, in keeping with the project's standard of reporting a gap rather than papering over it, rather than repeated here.


## 2. Methodology

### 2.1 Data & Universe Selection

*Prepared by Yiran*



### 1. Purpose

This section defines the investable universe and the market data used by all trader agents. Strategy discovery may differ by lens, but the universe, data source, and evaluation window are shared so Quant, Technical, and Fundamental results remain comparable.

### 2. Universe Ownership

The human Portfolio Manager sets the universe in the mandate. `permitted_asset_universe` is the candidate list; `prohibited_assets` are excluded. Traders do not expand the universe after seeing results. The shared DataService only fetches tickers supplied in the request.

### 3. Eligible Assets

The working universe is U.S.-listed ETFs named in the mandate (the Quant demo uses a 120-ticker ETF list). A name that is both permitted and prohibited is rejected. Agents may use a subset of the permitted list; they may not add names outside it.

### 4. Data Source and Fields

All agents obtain prices through the shared DataService, not through private APIs. The current provider is yfinance. We request daily OHLCV (open, high, low, close; volume optional). The same PriceBar objects are used for research fetch and backtest resolution.

### 5. As-of Discipline

Every request has an `as_of_date`. End dates are clipped to that date. If no start date is given, history defaults to about ten years before the end date. Bars after `as_of_date` are dropped.

### 6. Train / Test Split

A code-owned validation split is applied before strategy discovery. Training uses only bars strictly before `test_start_date`. Held-out metrics are computed on `[test_start_date, test_end_date]`, with `test_end_date` ≤ `as_of_date`. The split is not chosen by the LLM.

### 7. Use by Agents

Quant scans permitted names for cross-asset pairs using training-window closes. Technical requires daily OHLC for the same permitted names. Backtests resolve only symbols named in the candidate (for example `ticker_a` / `ticker_b` or `symbol`).

### 8. Missing Prices

If no current bar exists on an execution date, the engine skips that fill. It does not trade at a stale last close. Incomplete symbols are reported in the data response rather than silently filled.

### 9. Known Limitations and Assumptions

yfinance is unofficial and auto-adjusted, so it is not true point-in-time restated data. Survivorship and corporate-action revision risk are not controlled. This is a research prototype, not a licensed production feed.


### 2.2 Technical Trader

*Prepared by Arturo*



### 1. Investment Thesis and System Role

The Technical Trader is one of three independent specialist traders in the Fractional AI Workforce, alongside Fundamental and Quant. It converts a normalized Portfolio Manager mandate and point-in-time exchange-traded fund (ETF) price data into one auditable, executable multi-ETF strategy package. Its thesis is that price structure, trend, momentum, and market participation can identify repeatable tactical opportunities when the evidence is defined before evaluation, evaluated at a scale appropriate to the mandate, and translated into deterministic entry and exit rules after costs.

The design deliberately separates judgment from calculation. A large language model plans the research, compares eligible technical setups, forms one portfolio, challenges its initial proposal, and explains the deterministic result. Ordinary Python computes all indicators, validates every evidence reference, executes each trading rule, applies costs and constraints, and calculates performance. The model cannot invent prices, indicator values, backtest returns, or exceptions to the mandate.

The Technical Trader does not approve its own recommendation, combine it with another trader's output, or make the final investment decision. It returns the same typed TraderStrategyPackage used by the other trader branches for collective Risk and Reporting review. The Portfolio Manager may then accept, reject, compare, or request another research round. This common boundary prevents Technical-specific orchestration and permits the three trader branches to execute in parallel.

### 2. Architecture, Inputs, and Data Boundary

Four replaceable interfaces isolate the agent from shared infrastructure: a structured-output ModelClient, a point-in-time DataService, a deterministic BacktestEngine, and an injected ValidationSplitPolicy that supplies the shared evaluation dates. The LangGraph adapter exposes the Technical Trader as a single node that reads pm_mandate and writes technical_trader_package. Its internal planning, analysis, review, validation, evaluation, and interpretation stages therefore remain encapsulated within the trader branch.

The mandate defines the objective, investment horizon, permitted asset universe, prohibited assets, risk tolerance, leverage and short-selling constraints, liquidity requirements, rebalancing preference, and as-of date. The model may interpret those instructions through a Technical lens, but it cannot broaden the universe or weaken structured limits. The same normalized mandate can be consumed independently by Technical, Fundamental, and Quant.

The agent requests daily point-in-time market data through the shared Data Service. Symbol identity, timezone-aware timestamp, open, high, low, and close form the mandatory analytical core. Volume, trading-session flags, ETF lifecycle data, liquidity metadata, and adjustment metadata are requested when available. A missing optional field disables only the dependent strategy family: for example, incomplete volume prevents a volume-confirmed breakout but does not invalidate support, resistance, pattern, or moving-average evidence.

Each series is validated before analysis. Timestamps must be unique, strictly increasing, timezone-aware, and no later than the permitted as-of boundary. OHLC values must be finite, positive, and internally consistent; supplied volume must be non-negative. Immutable data references, coverage, provenance, unavailable fields, and limitations are retained in the final package. The shared Data Service and evaluation policy remain authoritative for the market calendar, price adjustments, missing-bar treatment, and survivorship policy.

### 3. Controlled LLM Reasoning

A normal research round makes four structured LLM calls. Every response must satisfy a typed Pydantic contract before it can affect deterministic execution.

#### Research planning

The first call translates the mandate into a data and research plan without selecting an ETF or strategy. Code normalizes the request so that daily symbol, timestamp, open, high, low, and close data remain mandatory and strategy-specific enhancements remain optional.

#### Candidate construction

After deterministic analysis of the permitted assets with sufficient pre-evaluation history and complete benchmark-calendar coverage, the second call receives a bounded shortlist of eligible technical opportunities. By default, the top 20 unique ETFs are exposed for comparative reasoning while the complete eligible-universe report remains attached for audit. The model creates one multi-ETF portfolio and aims for ten unique holdings, but may select fewer when frozen training evidence does not support a positive technical hypothesis for ten. Such a hypothesis is a model-authored interpretation of submitted evidence, not a calibrated expected return or guarantee.

For each sleeve, the model chooses one prompt-local opportunity reference and explains why the setup fits the mandate. Deterministic code atomically expands that reference into the eligible ETF, registered strategy family, complete canonical evidence set, opportunity metadata, and bounded executor parameters before the unchanged shared proposal contract is validated. This makes an invalid symbol/strategy/evidence recombination unrepresentable and prevents prompt-local aliases from entering the final package. The model may not reproduce high-precision indicator values, transcribe support prices, estimate a neckline, select the held-out period, or manufacture performance.

#### Independent technical review

The third call challenges the whole proposed portfolio using the same frozen training report. It reviews contradictory signals, staleness, fragile structures, whipsaw risk, false breakouts, repeated exposure to similar technical conditions, and avoidable concentration. It may replace sleeves or reduce portfolio size, but it cannot use held-out results, fundamental information, macroeconomic forecasts, or quantitative factor claims. An invalid review is recorded as a non-fatal failure and the already validated initial proposal is retained; an invalid initial proposal fails closed.

#### Backtest interpretation

The fourth call interprets only the metrics, warnings, constraints, and benchmark comparison returned by deterministic code. It may explain strengths, weaknesses, uncertainty, and mandate alignment, but it cannot recalculate metrics, approve the candidate, override a deterministic fallback, or claim that historical performance will persist.

Interchangeable asynchronous OpenAI and Anthropic adapters implement the same structured-output contract. Provider and model choice are deployment configuration rather than agent logic. Both paths revalidate output locally, normalize provider request and token telemetry, reject incomplete or truncated output, and use the same bounded execution policy. API credentials are read only during explicit runtime composition and are not stored in prompts, packages, or source files.

### 4. Deterministic Technical-Analysis Toolkit

#### Support and resistance

Support and resistance are derived from clustered local pivots. Code identifies strict pivot lows and highs with a symmetric window, sorts their prices, clusters nearby pivots within a percentage tolerance, rejects clusters with insufficient touches, and averages the surviving prices. Defaults use two bars on each side, a 1% merge tolerance, at least two touches, and no more than eight levels of each type. Every level records type, price, touch count, source pivots, first and last touch times, distance from the latest close, and a stable evidence identifier. If no repeated-touch level survives, the observed range boundary is retained with used_range_fallback=true for description only; it cannot satisfy a reliable-level rule.

#### Head-and-shoulders structures

Normal and inverse head-and-shoulders observations are geometric pivot structures. The normal form requires a central high above two sufficiently similar shoulder highs, minimum pivot separation, a bounded total span, and a neckline constructed from intervening lows; confirmation requires a later close below that neckline. The inverse form applies the corresponding conditions to three lows and requires a later close above the neckline. Defaults use 4% shoulder similarity, 3% head prominence, at least two bars between pivots, and a maximum span of 126 bars. Forming and confirmed labels describe observed geometry, not predictions. Only a confirmed inverse formation is eligible for the current long-only executor.

#### Moving averages and relative volume

Python computes simple moving-average evidence at 3/10, 5/20, 10/30, 20/50, 50/100, and 50/200 bars. Each observation includes the averages, percentage spread, bullish, bearish, or neutral relationship, latest crossover direction and time, and bars since the crossover. A neutral band prevents small numerical differences from becoming false signals. When complete volume is present, relative volume compares the latest observation with the preceding 20-bar mean and records the ratio and contemporaneous return. Missing or non-positive comparison data produces a warning and no volume observation; the model cannot impute it.

### 5. Horizon-Adaptive Policy and Opportunity Screen

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

### 6. Strategy Construction and Evidence Enforcement

The package-level executor, technical.multi_asset_portfolio.v1, coordinates one to ten independently stateful long-only ETF sleeves within one candidate artifact. Current model-selectable families are:

- Rolling support reaction.
- Rolling resistance breakout.
- Horizon-adaptive moving-average trend.
- Rolling volume-confirmed resistance breakout.
- Confirmed inverse-head-and-shoulders breakout.

Bearish head-and-shoulders remains analytical evidence but is not an executable long-only sleeve. Every selected sleeve must exactly match one code-ranked opportunity by symbol, executor family, and complete evidence-ID set. Deterministic validation rejects unsubmitted symbols, missing or extra IDs, evidence belonging to another ETF, fallback or wrong-side levels, incompatible moving-average windows, forming patterns represented as confirmed, and executors that cannot implement the stated rule.

After validation, code binds evidence-derived values such as moving-average windows, pattern neckline, level eligibility, volume lookback, rolling review settings, holding limits, and volatility-scaled risk parameters. The model chooses among supported opportunities without being trusted to copy precise numerical inputs. The portfolio is equal-weighted within its gross target. Sleeves enter, exit, and re-enter independently, and capital assigned to inactive sleeves remains in cash. Each state change returns the full active target mapping so active sleeves can be restored to equal targets; this deliberate drift correction can increase turnover.

### 7. Point-in-Time Execution and Backtesting

Portfolio membership and strategy-family selection are frozen before held-out evaluation. During the backtest, rolling executors recompute levels, moving averages, volume relationships, and volatility using only bars completed by the current signal timestamp. A pattern neckline remains fixed because it represents the specifically cited training-period formation. Orders fill only after the configured signal delay, preventing a signal from using the same bar's future execution price.

The shared Backtest Engine is the only component allowed to calculate returns. It receives the finalized rule and registered executor, immutable data references, mandate constraints, evaluation window, frequency, benchmark identity, execution assumptions, transaction costs, and requested metrics. It returns immutable status, metrics, warnings, constraint violations, artifact references, and a run-ledger entry.

The isolated validation configuration used daily bars, one-bar-delayed next-open execution, 1 basis point of commission, 2 basis points of slippage, long-only exposure, maximum gross leverage of 1.0, initial capital of $100,000, and deterministic end-of-test liquidation. Requested metrics were total and annualized return, maximum drawdown, annualized volatility, Sharpe ratio, transaction count, transaction costs, and turnover.

### 8. Horizon-Matched Evaluation and Benchmark Gate

The primary held-out window matches the PM's requested investment horizon: approximately 21 trading sessions for one month and 504 sessions for two years. The injected shared policy selects the exact market dates. The Technical Trader checks that the supplied span is plausible for the mandate, while the policy and Data Service remain responsible for the precise exchange calendar. Training evidence ends before the held-out window begins, and no model prompt receives held-out prices or results before membership is finalized.

Each completed run evaluates two executable candidates: the reviewed Technical portfolio and a buy-and-hold benchmark. Both use the identical finalized plan, including dates, frequency, costs, signal delay, fill-price field, liquidation rule, constraints, data references, and execution context. A convenience benchmark series may remain in the engine ledger for audit, but it is not used for selection if its timing differs from an executable strategy.

The prototype gate compares held-out total return. Strict Technical outperformance retains the multi-ETF strategy; equality or underperformance selects the already evaluated benchmark. The model cannot author or override this decision, and the rejected Technical request, result, and ledger remain attached. Because the same held-out period both evaluates and selects the final artifact, this is a transparent prototype policy rather than independent confirmation. The package records selection_uses_evaluation_window=true and independent_post_selection_test_required=true. Future governance may instead return the Technical proposal with a warning, permit abstention, or leave cross-strategy selection entirely to the Portfolio Manager.

### 9. Output, Auditability, Integration, and Resilience

The final TraderStrategyPackage contains workflow, task, attempt, trader, package, and candidate identities; the normalized mandate reference; requested and used data with provenance and limitations; the complete deterministic Technical report; the selected rule, registered executor, parameters, and evidence mappings; the finalized backtest request, result, and ledger; the constrained LLM interpretation; mandate assessment; non-fatal diagnostics; resolved horizon and evaluation semantics; initial and reviewed membership; the Technical-versus-benchmark comparison; and Risk-review eligibility.

Only a complete, successfully analyzed, backtested, and interpreted package is eligible for Risk review. A stage failure settles as a structured partial or failed package instead of raising an unhandled exception through the full multi-agent workflow. Operational diagnostics are isolated from model-authored strategy text so an exception message cannot trigger analytical guardrails. The Technical branch therefore preserves partial evidence and failure details without invalidating unrelated branches.

Each model adapter returns normalized usage telemetry, including the agent, operation, workflow, task, call, attempt, provider request ID, latency, token usage, model identity, status, and provider-reported cost when available. An injected metrics sink can retain those records. The current production graph does not yet bridge the Technical Trader's per-call usage into the shared operational-event ledger or apply centrally maintained model prices, so dashboard API cost may remain unavailable. The complete Technical Trader deadline is 600 seconds. Model, data, specialist, and backtest operations remain separately bounded, and runtime composition validates that retry and timeout budgets fit within the surrounding deadline. Provider choice remains a configuration change, while the LangGraph node and downstream package contract remain stable.

### 10. Prototype Verification and Representative Result

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

Separately, the same Technical runtime completed inside the repository's compiled production LangGraph alongside the current Fundamental and Quant Traders. All three trader packages reached Risk review, Reporting completed, and the graph paused at the durable human Portfolio Manager decision as designed. This integration result verifies the shared package and workflow boundaries; it does not replace the controlled Technical-only result above or constitute additional evidence of investment performance.

### 11. Risk Interpretation, Limitations, and Appropriate Claims

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

### 12. Recommended Evaluation Extensions

The next methodological extension should be rolling horizon-matched evaluation. For a 504-session mandate, the system should repeatedly freeze evidence at time T, construct a new portfolio, evaluate T through T+504, and advance the origin by a fixed interval such as 63 sessions. The full distribution should report median excess return, benchmark hit rate, worst window, dispersion, drawdown, turnover, and costs. Selecting only the best window would reintroduce data snooping.

After rolling evaluation, a final period should remain untouched by evidence selection, prompt refinement, parameter changes, and benchmark gating. The already selected configuration should be executed on that period once. Rolling windows test regime robustness and portfolio-selection stability, while the untouched final period tests post-selection generalization; neither substitutes for the other.

Further shared evaluation should add per-sleeve attribution, liquidity and capacity diagnostics, sensitivity tests for review cadence and risk parameters, and comparison of Technical, Fundamental, and Quant packages under common mandates. These additions belong to the shared evaluation and Risk framework and do not require changing the Technical Trader's input or output contract.

### 13. Conclusion

The Technical Trader establishes a clear division of labor between LLM reasoning and deterministic finance code. The model supplies comparative technical judgment; typed contracts and ordinary Python enforce evidence, execution, constraints, costs, metrics, and auditability. Horizon-adaptive screening allows the same agent boundary to serve short and long mandates, while point-in-time evaluation and executable benchmark comparison make the resulting claims inspectable.

Its main contribution is not a promise that technical analysis will always outperform. It is a reproducible method for converting an LLM's technical reasoning into a bounded, testable, and reviewable multi-ETF strategy artifact without delegating arithmetic or historical performance claims to the model. The package is modular, provider-selectable, LangGraph-compatible, resilient to partial failure, and ready for collective Risk review within the full Fractional AI Workforce.


### 2.3 Fundamental Trader

*Prepared by Aditi*



### 1. Investment Thesis

The Fundamental Trader agent is one of three independent specialist traders in the system, each proposing and testing a strategy through its own analytical lens — Technical (price action), Quant (statistical anomalies), and Fundamental (fund-level characteristics). Fundamental Trader's thesis is that two ETFs classified under the same category track substantially similar underlying exposure by construction; if a smaller-issuer ETF's return diverges unusually far from the return of its category's large-issuer peers, that divergence is more likely a liquidity or technical artifact than a fundamentally justified difference, since nothing in a shared category definition explains why two funds tracking comparable exposure should diverge for long. The strategy tests whether that gap tends to close.

### 2. Adapting the Signal to the Available Data

The original design for this agent called for classic ETF fundamentals — expense ratio, dividend yield, NAV premium/discount, and sector or factor exposure. Direct inspection of the team's `ETF_info.xlsx` source data (not an assumption carried over from the original proposal) found that `marketCap`, `sector`, and `industry` are null or empty for all 120 tickers in the finalized universe. Only two fields are populated for effectively the entire universe: `category` (44 distinct values) and `fundFamily` (27 distinct values).

In place of the unavailable fields, this agent introduces an **ISSUER_SCALE_TIER** heuristic: `fundFamily` is bucketed into a "major" tier (nine large, broadly-distributed asset managers — iShares, Vanguard, State Street, Invesco, Schwab, Fidelity, JPMorgan, First Trust, and WisdomTree) versus a "boutique" tier (the remaining 18 issuers present in the fixture, including ARK, Global X, ProShares, and VanEck). Against the real 120-ticker universe, this splits 82 major-tier and 38 boutique-tier tickers.

*This substitution is treated as a limitation, not a hidden assumption: ISSUER_SCALE_TIER is a liquidity and issuer-scale proxy, not a direct fundamental valuation signal, and every candidate this agent proposes states that explicitly in the evidence passed to the Risk agent (see §6).*

### 3. The Strategy: Category-Benchmark Deviation

For each category with at least two major-tier constituents, the agent constructs an equal-weight "category benchmark" from those major-tier tickers' daily returns. For every boutique-tier ticker in that category, it computes the rolling z-score of the spread between that ticker's own return and the category benchmark's return, over a trailing lookback window (20, 40, or 90 trading days, selected per candidate). Candidates are ranked by |z-score| × historical correlation to the benchmark, favoring tickers that normally track their peers closely but have recently diverged sharply — the strongest evidence of a temporary dislocation rather than a structural difference.

The resulting rule is long-only and single-position: enter the boutique-tier ticker when its spread z-score falls to or below −entry_zscore (default −1.5); exit to cash once it recovers to −exit_zscore (default −0.25). No leverage or shorting is used.

### 4. Pipeline and the Propose/Compute Boundary

Consistent with the project's core design rule — an LLM never computes its own backtest performance — this agent's `run()` method only proposes; a shared, deterministic backtest engine computes every reported number. The pipeline for one research round is:

1. **Fetch.** Request point-in-time price data and ETF category/fund-family metadata for the permitted universe from the injected Data service, delivered as a single package as soon as the PM sets the mandate.
2. **Resolve the train/test split before proposing anything.** Discovery only ever sees bars strictly before the held-out test window — the anti-look-ahead guarantee.
3. **Discover.** Scan every boutique-tier ticker in every populated category for a significant deviation from its major-tier benchmark, ranked as in §3.
4. **Package.** The strongest candidate becomes a fully specified rule (entry/exit logic, parameters, and the evidence that produced it) bound to a registered, deterministic executor.
5. **Evaluate.** The candidate is sent to the shared backtest engine unchanged; the agent has no ability to alter or interpret the resulting numbers before they are reported.
6. **Interpret.** A template-generated (not model-authored) interpretation turns the settled result into a structured summary — metrics, strengths, weaknesses, overfitting risks, and limitations — for the Risk agent to review.

### 5. Verification and Representative Result

The full pipeline was run end-to-end — offline, against the real 120-ticker dataset — through the actual shared, deterministic backtest engine, not a mock. A representative run selected AWAY (a boutique-tier "Consumer Cyclical" ETF) against a benchmark of its major-tier category peers (PEJ, XLY):

| Metric | Training window | Held-out test window |
|---|---|---|
| Total return | −7.40% | −14.96% |
| Annualized return | −0.28% | −3.51% |
| Sharpe ratio | −0.03 | −0.31 |
| Max drawdown | −22.27% | −20.11% |
| Transactions | 182 | 128 |

This result is reported here deliberately because it is a losing one, not a cherry-picked winner: the strategy underperformed on both the training and held-out windows. This is treated as evidence the pipeline is reporting honestly, in line with the project's central design principle that agent output must be evaluated by real, unfavorable results as readily as favorable ones — not selectively surfaced only when it looks good.

### 6. Risk Analysis and Interpretation

Every candidate this agent proposes is passed to the Risk agent with two limitations stated explicitly, not left implicit:

- **Selection-bias exposure.** The reported candidate is the strongest of a scan across every boutique-tier ticker in every populated category — a single strong-looking deviation found this way is exactly the kind of result that needs independent scrutiny for cherry-picking, regardless of how the backtest itself performs.
- **Proxy-signal exposure.** ISSUER_SCALE_TIER substitutes for fund-level fundamentals that are not available in the source data; Risk is told explicitly that the underlying signal is a liquidity/issuer-scale proxy, not a direct valuation gap, so it can weigh the candidate accordingly.

In full-loop integration testing, this agent's candidates were reviewed against the Risk agent's real 13-point checklist (CP-1 through CP-13). One genuine defect was found and fixed in the process: the backtest plan initially did not declare a same-terms benchmark, which caused Risk's CP-6 check to correctly veto every candidate. After declaring a buy-and-hold benchmark on the traded ticker, candidates from this agent received a real approve verdict from the unmodified Risk checklist — confirming the interaction between this agent's output and Risk's review logic, not merely this agent in isolation.

### 7. Known Limitations and Assumptions

- ISSUER_SCALE_TIER is a heuristic (nine issuers selected for AUM/shelf-space breadth), not a licensed or team-confirmed classification.
- The category benchmark is computed in-house as an equal-weight average of major-tier peers sharing a category in this fixture, not a licensed index.
- Interpretation of backtest results is template-generated, not model-authored — a conservative stand-in pending a model-backed version.
- No transaction-cost stress testing beyond the shared engine's configured commission/slippage assumptions.
- The agent proposes a single top-ranked candidate per round; Risk currently reviews one Fundamental Trader ticker per round, not several ranked alternatives.


### 2.4 Quant Trader

*Prepared by Shaurya*



### 1. Investment Thesis

Quant Trader is one of three independent specialist traders in the system, each proposing and testing a strategy through its own analytical lens — Technical (price action), Fundamental (fund-level characteristics), and Quant (statistics and cross-asset anomalies). Quant Trader's thesis does not rest on any single instrument's own history; it looks across pairs of ETFs for a real, persistent statistical relationship — high return correlation — and tests whether the price *spread* between the two, once it drifts unusually far from its own historical average, tends to snap back. A relationship that is both strongly correlated and genuinely mean-reverting is treated as a tradeable anomaly; correlation without measurable reversion is treated as coincidence, not a signal.

### 2. Statistical Discovery Methodology

Given a training-window price panel, discovery runs two independent, vectorized screens (pandas/numpy) over every candidate pair in the permitted universe — a full 120-ticker scan (~7,000 pairs) completes in well under a second:

- **Correlation screen.** Daily simple returns are computed for every ticker, and the pairwise Pearson correlation matrix is computed across the full panel at once. A pair is retained only if it has at least 750 trading days (~3 years) of overlapping history and a correlation at or above 0.70.
- **Mean-reversion (half-life) screen.** For each correlated pair, an AR(1) model is fit to the price ratio (spread) between the two tickers: `spread_change[t] = a + b × spread[t−1]`. A negative `b` indicates the spread tends to snap back toward its average rather than drift; the corresponding half-life, `−ln(2) / ln(1 + b)`, estimates how many trading days that snap-back typically takes. Pairs with no mean reversion, an undefined half-life, or a half-life exceeding 90 days are discarded as not tradeable within a practical horizon.

Correlation is treated as necessary but not sufficient by design: two assets can move together without their price ratio ever reliably reverting to a stable level, so every pair is required to clear both screens independently before it is considered a candidate.

Surviving candidates are ranked by a combined score, `correlation × 1 / (1 + half_life / 30)`, which rewards both a strong relationship and a fast reversion — a pair that reverts in two weeks offers materially more tradeable opportunities within a fixed window than one that takes three months, even at similar correlation. The top-ranked pair is the one submitted to the backtest engine, always accompanied by the underlying evidence (correlation, half-life, shared trading-day count, composite score) and a plain-language rationale so Risk and Reporting can evaluate the statistical basis rather than trust a bare assertion.

### 3. The Strategy: Cross-Asset Spread Mean Reversion

The winning pair is translated into a rule bound to one registered, deterministic executor (`quant_trader.cross_asset_spread_mean_reversion.v1`) with parameters `ticker_a`, `ticker_b`, `lookback_days`, `entry_zscore`, and `exit_zscore`. At each bar, the executor computes the rolling z-score of the `ticker_a / ticker_b` price ratio over the trailing `lookback_days` window, using only history already revealed to it at that point in time (point-in-time by construction, not by discipline). The position enters (target weight 100% `ticker_a`) once the z-score falls to or below `−entry_zscore` (default −1.5), and exits fully to cash once the z-score recovers to `−exit_zscore` (default −0.25); in between, the executor signals "hold whatever position is already open," giving the rule hysteresis so it does not flicker in and out on single-day noise. The strategy is long-only and single-position — no leverage, no shorting.

### 4. Pipeline and the Propose/Compute Boundary

Consistent with the project's core design rule — an LLM (or in this case, a statistics routine) never computes its own backtest performance — Quant Trader's `run()` method only proposes; a shared, deterministic backtest engine computes every reported number. The pipeline for one research round is:

1. **Fetch.** Request point-in-time daily OHLC data for the permitted universe from the injected Data service — the same shared boundary every trader depends on, not a Quant-Trader-specific integration.
2. **Resolve the train/test split before proposing anything.** The code-owned validation split is resolved immediately after the fetch and before any statistics run. The training panel handed to discovery is sliced to bars strictly before the resolved test-start date; discovery itself has no knowledge of any test window and cannot access it even by mistake. (An earlier standalone prototype of this logic scanned full history including the eventual test window to pick a pair — a genuine look-ahead bug that this design fixes structurally, not by convention.)
3. **Discover.** Scan every pair in the training-window panel as in §2.
4. **Package.** The strongest candidate becomes a fully specified rule (entry/exit logic, parameters, and the evidence that produced it) bound to the registered executor from §3.
5. **Evaluate.** The candidate is sent to the shared backtest engine unchanged; the agent has no ability to alter or interpret the resulting numbers before they are reported. The backtest plan also declares a same-terms benchmark — a buy-and-hold position in the pair's second leg — computed by the same engine, under the same assumptions, in the same run, so Risk has a real baseline to compare against rather than an assumption-free or self-selected one.
6. **Interpret.** A template-generated (not model-authored) interpretation turns the settled result into a structured summary for the Risk agent to review, explicitly flagging the selection-bias risk described in §6.

### 5. Verification and Representative Result

The full pipeline was run end-to-end against live data — real yfinance daily prices, through the actual shared, deterministic backtest engine, not a mock. A representative run over a 15-ticker candidate universe selected the EWA/EWC pair (correlation 0.846 over 2,009 shared trading days, ~56-trading-day half-life):

| Metric | Training window | Held-out test window |
|---|---|---|
| Total return | 27.26% | 22.65% |
| Annualized return | 2.45% | 10.79% |
| Sharpe ratio | 0.235 | 0.714 |
| Max drawdown | −33.41% | −17.95% |
| Transactions | 84 | 18 |

This result is reported here because the held-out test window held up *better* than the training window on every risk-adjusted measure (higher Sharpe, shallower drawdown, far fewer trades), which is a meaningfully different pattern from simple in-sample outperformance — consistent with a genuine mean-reversion relationship rather than a fit that only worked on the data used to find it. As with the rest of this project's reporting standard, this number is not treated as proof the strategy "works"; §6 and §7 describe why it still requires scrutiny.

### 6. Risk Analysis and Interpretation

Every candidate this agent proposes is passed to the Risk agent with the selection-bias risk stated explicitly, not left implicit: the reported candidate is the strongest of a scan across every pair in the permitted universe, and a single strong-looking result found this way is exactly the kind of process that can manufacture a good-looking outcome by chance, regardless of how the backtest itself performs.

In full-loop integration testing, this agent's candidates were reviewed against the Risk agent's real 13-point checklist (CP-1 through CP-13), in a two-trader round alongside Technical Trader. One genuine defect was found and fixed in the process: the backtest plan initially did not declare a same-terms benchmark, which caused Risk's CP-6 check to correctly veto every candidate ("No same-terms baseline: the plan lacks a benchmark or the engine produced no benchmark metrics"). After declaring a buy-and-hold benchmark on the pair's second leg, an unmodified Risk checklist run against a real candidate returned:

- **Approve**, with six checks passing cleanly (CP-3 backtest completeness, CP-5 canonical metrics present, CP-6 same-terms benchmark, CP-9 evidence traceability, CP-11 validation-touch budget, CP-12 no prior vetoes).
- Three checks (CP-1, CP-2, CP-4) returned `flag, requires human review` rather than a manufactured pass, since no round-audit-ledger service exists yet in this environment — an honest "cannot verify" rather than a false positive.
- One round-level check (CP-7, multiple-comparison disclosure) flagged that only one candidate reached Risk that round, reminding Reporting to disclose that rather than present a lone result as if it had no competing alternatives.

This confirms the interaction between this agent's output and Risk's real review logic end to end, not merely this agent in isolation. (Note: Fundamental Trader independently hit the identical CP-6 defect and fix during the same integration work — see `docs/fundamental_trader.md` — which is a second, independent confirmation that the benchmark requirement is a real, systemic Risk gate and not specific to one trader's design.)

### 7. Known Limitations and Assumptions

- **Selection-bias risk is real, not hypothetical.** Scanning hundreds of pairs and keeping the best-scoring one is exactly the kind of process that can manufacture a good-looking result by chance; this is surfaced explicitly in every interpretation rather than hidden, but it is not eliminated by the current design.
- **Single candidate per round.** Discovery can rank several qualifying pairs, but only the top-ranked candidate is currently backtested and submitted; presenting the top 2–3 would let Risk compare survivors rather than judge one pair in isolation.
- **Universe size affects results directly.** A small permitted universe can leave only one pair clearing both statistical thresholds in a given round, which limits how much genuine cross-sectional comparison Risk's multiple-comparison checks can perform.
- **Interpretation is template-generated, not model-authored** — a conservative stand-in pending a model-backed version, matching the other traders' current state.
- **No transaction-cost stress testing** beyond the shared engine's configured commission/slippage assumptions.
- **Data is not point-in-time verified in the strict sense.** yfinance prices are auto-adjusted for splits and dividends rather than reconstructed as-of a specific historical date, which the Data service's own provenance metadata discloses on every response.


### 2.5 Risk Agent

*Prepared by Yutong*



### 1. Role in the System

The three preceding sections describe agents that *propose*. This section describes the two mechanisms that decide whether a proposal should be believed and whether the agent that made it is worth keeping: the **Risk agent**, which reviews every candidate against a 13-point cherry-picking checklist, and the **evaluation harness**, which turns a finished run into per-agent productivity metrics.

The system's premise is that a human Portfolio Manager manages AI specialists the way a manager runs a small team, on measured performance rather than impression. That premise has one structural requirement: the numbers the PM acts on must not be authored by the thing being judged. So a strategy's verdict is computed from engine-produced evidence rather than the trader's memo — traders' claims are hypotheses, the backtest engine's run ledger is ground truth — and an agent's score is replayed from an immutable event ledger rather than any agent's self-report.

Risk is also the only node with the visibility the job requires. The three traders are competing lenses on the same validation window and the PM can request further rounds, so selection bias has three places to hide: **within one trader** (many variants run, only the winner reported), **across the three traders** ("best of three lenses" presented as one hypothesis, when three shots at the same window inflate expected performance), and **across rounds** ("request another round" repeated until something passes). The second and third are invisible to any single trader.

### 2. The Checklist: CP-1 … CP-13

Each check returns **PASS**, **FLAG** (approval still permitted, but the flag must appear verbatim in the Reporting memo), or **VETO** (candidate rejected, with the check ID as a machine-readable veto reason code).

| Check | Scope | Deterministic basis | Status |
| --- | --- | --- | --- |
| CP-1 report-everything-tried | candidate | ledger run count vs. declared count | needs audit reader |
| CP-2 best-of-N disclosure | candidate | undeclared sweep → veto; large declared sweep → flag | needs audit reader |
| CP-3 full-period metrics | candidate | backtest succeeded, split applied, out-of-sample metrics present | runs |
| CP-4 no post-hoc universe trimming | candidate | resolved symbols, first run vs. last run | needs audit reader |
| CP-5 full canonical metric set | candidate | every required metric present and non-null | runs |
| CP-6 same-terms baseline | candidate | benchmark computed by the same engine run | runs |
| CP-7 multiple-comparison disclosure | round | candidate count vs. declared hypothesis count; always a flag | runs |
| CP-8 lens duplication | round | identical executor with identical parameters (proxy) | runs, as a proxy |
| CP-9 no borrowed evidence | candidate | result, request and trader identity; cited foreign run IDs | runs |
| CP-10 nothing is deleted | round | every prior round present in history | needs history reader |
| CP-11 validation-touch budget | candidate | round number vs. budget; approval past it needs stability evidence | runs |
| CP-12 no cosmetic resurrection | candidate | match against prior vetoed strategies without declared lineage | needs history reader |
| CP-13 test-set lock | candidate | resolved data end and split end vs. the mandate as-of date | runs |

Eight checks run today from evidence already embedded in the candidate package. Five require two small adapters that dereference the round-audit and round-history references the workflow state already carries but which nothing currently resolves; their absence is disclosed rather than concealed (§3, §7).

### 3. Two Stages, in This Order

**Deterministic gate.** Every mechanically checkable item is computed in ordinary Python from the run-ledger entry embedded in each result, from request counts, and from package identity fields. No model call is involved. This mirrors the propose/compute boundary the traders observe: the reviewer no more computes its verdict by language model than a trader computes its own Sharpe ratio.

**Bounded model judgment.** An optional model client then reviews what code cannot judge — sweep severity, semantic similarity between lenses, how to read stability evidence, whether a resubmission genuinely addressed its original veto — grounded in the deterministic results it is shown. Its authority is deliberately asymmetric: it may *escalate* severity (PASS → FLAG → VETO) with justification and evidence IDs, an escalation at equal or lower severity than the computed verdict is discarded, and a model failure degrades the review to deterministic-only rather than aborting the round. The model can never downgrade a computed result.

**Unverifiable is not a pass.** Where evidence cannot be reached — the two missing readers being the common case — the check returns FLAG with requires_human_review set and a summary naming what could not be verified. A manufactured PASS would be the most damaging failure available to this component, because it would make an absent check indistinguishable from a satisfied one.

A candidate is vetoed if any of its checks vetoed; otherwise it is approved carrying its flags, and the response exposes every flag the Reporting memo must reproduce. A round-level veto must block progression, enforced by a contract validator rather than by convention. Dropping a flag downstream would be cherry-picking the critique rather than the result. Every threshold the checklist draft left open — the round budget (3), the sweep-disclosure flag threshold (20), the lens-overlap cutoff (0.7), and the canonical metric set — lives in a single policy object, so a team ruling is a one-line change.

### 4. The Evaluation Harness

The Risk agent grades strategies. The harness grades **agents**, which is what the hire/fire/pivot controls act on. Each node wrapper in the production graph already knew everything an event needs — which agent ran, at which stage, when it started and ended, whether it settled or failed — and was discarding all but the lifecycle summary. Emission now attaches an operational event at each wrapper's exit path, and the harness replays that ledger into a per-agent record: tasks observed and completed, failures, retries, latency, model calls, tokens, API cost, and candidates reviewed versus approved. Risk's verdicts are collected first, so traders are scored against the reviewer's record rather than their own.

**Measured or N/A, never defaulted.** No metric defaults to zero. An agent that made no model calls has an *unknown* cost, not a cost of nothing, and the difference matters when the number sits under a fire button. A benched agent has no success rate — not 0%. A trader that crashed has no risk-approval rate: its failed package still carries a candidate ID, but Risk never reviewed it, so counting it as a rejected proposal would score a crash as a research-quality failure and penalise the agent twice for one incident. The same discipline was applied to the dashboard, where demo and live modes render through identical widgets: each site that displays productivity figures now states their provenance, and demo mode says plainly that nothing on screen was measured.

**The open ruling: what "Success %" means.** The term has two defensible readings. *Execution* — the share of tasks that finished without erroring — is literal, cheap and un-gameable, and nearly useless for firing, because a trader that reliably produces worthless strategies scores 100%. *Risk approval* — the share of proposals that survived review — is genuinely informative about research quality, and it makes the skeptic the scorekeeper for everyone it judges: once a trader is measured on its approval rate, the way to score well is to propose things Risk waves through, which points Goodhart's law at the mechanism this project is built around. The choice is a team ruling and is deliberately still open, so the harness computes **both, always**, and reports them under separate names; the selector only decides which one fills the single slot the dashboard renders. No view can silently imply the question has been settled.

### 5. Verification and Representative Result

The run below was executed end-to-end on 19 August 2026 through the compiled production workflow with real Fundamental Trader, Quant Trader, Risk agent, Reporting agent and Memory store, against the real 120-ticker ETF fixture and the shared deterministic backtest engine — not mocks. The Technical Trader ran in its stubbed form because no model provider was configured in this environment; it settles as a failed package and is therefore excluded from Risk review, which is itself one of the behaviours under test. Risk ran deterministic-only, so every verdict reported here was computed by code.

In round 1 both candidates that reached review were approved, each carrying three flags naming exactly what could not be verified, with the round-level multiple-comparison disclosure recording that two hypotheses competed and one package was excluded. Driving the same workflow through three further "request another round" decisions produced a 23-event ledger over four rounds, and at round 4 the deterministic gate vetoed **both** surviving candidates on CP-11 — *"Round 4 exceeds the 3-round validation-touch budget and the candidate carries no parameter-stability evidence"* — leaving nothing selectable.

| Agent | Success (risk) | Execution | Risk approval | Time | Failed | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| fundamental_trader_agent | 75% | 100% | 75% | 2.43s | 0 | N/A |
| quant_trader_agent | 75% | 100% | 75% | 4.67s | 0 | N/A |
| reporting_agent | N/A | 100% | N/A | 1ms | 0 | N/A |
| risk_agent | N/A | 100% | N/A | 1ms | 0 | N/A |
| technical_trader_agent | N/A | 0% | N/A | 0ms | 4 | N/A |

Four details in that table are the point of the section. Both traders executed flawlessly in all four rounds while three of their four proposals survived review, so the two readings of Success % diverge on the same run — under the execution reading, an agent whose fourth-round work was rejected outright looks perfect. The crashed Technical Trader reads 0% on execution and N/A on risk approval, a crash rather than a rejected proposal. Risk and Reporting read N/A on approval because they submit no candidates, rather than 0%, which would read as a failing grade. And cost reads N/A throughout because no model call reported usage — a missing measurement, stated as such rather than printed as $0.00.

The loop was stopped here by the accumulated cost of re-touching the validation window, not by anything wrong with the fourth round's strategies. Benching the Risk agent produces the complementary behaviour: the graph records a review failure requiring PM action, Reporting never runs, and no candidate becomes selectable — so firing the skeptic escalates to the human instead of silently approving.

### 6. Risk Analysis and Interpretation

The honest limitation of this design is structural rather than numerical. Every other agent is checked by something outside itself — traders by Risk, arithmetic by the shared engine, data by provenance records. The Risk agent is checked by nothing, because it *is* the checking code, and the harness has the same property one level up.

The project has already produced one instance of this failure mode. The shared data service back-adjusts prices and therefore honestly declares that its data is not point-in-time verified. In the same change that introduced it, the Technical Trader's data check — which had rejected unverified data — was relaxed to require only that provenance *exists*, and the flag was dropped from the backtest data contract. A source failed a look-ahead guard and the guard moved. Nothing in the checklist catches this: CP-13 verifies that resolved data and the validation split respect the as-of boundary, which they do, and no check consults the point-in-time flag at all.

This is not offered as a defect to be quietly patched before submission. It is the precise self-deception the project exists to detect, committed by the project, and it is a real research gap: there is no mechanism for reviewing changes to the reviewer. Two defensible resolutions exist — restore the strict check and accept that the live data source cannot be used for graded runs, or keep it relaxed and add an explicit disclosure that propagates through Risk into the PM memo. What is not defensible is letting it be settled by silence. The second-order risk is the one in §4: if risk approval becomes the number under the fire button, traders are optimised toward whatever Risk approves and the adversary becomes a target. The current answer is to refuse to pick one number, publish both, and force the choice to be made explicitly.

### 7. Known Limitations and Assumptions

- **Five of thirteen checks do not run.** CP-1, CP-2, CP-4, CP-10 and CP-12 degrade to *flag, requires human review* until the round-audit and round-history readers are supplied. The system therefore cannot yet mechanically detect a hidden sweep in a live run.

- **No trader produces the disclosure fields.** Declared run count, stability evidence and parent strategy ID have no producer, so CP-1, CP-2 and CP-7 see no declared trial counts, CP-11 can only hard-veto past the round budget rather than assess perturbation results, and CP-12 has no lineage to inspect.

- **CP-8 is a proxy.** It detects an identical executor with identical parameters, not the intended trade-day overlap; two lenses converging on economically similar but structurally different rules would pass.

- **No check verifies point-in-time data** (§6).

- **API cost is unmeasured end to end.** Provider telemetry is converted into ledger events and unit-tested against the Technical Trader's real metrics type, but no runtime construction site supplies the sink yet, so every verified run reports cost as N/A. The metric is honest about its own absence; it is still absent.

- **Policy thresholds are proposals, not rulings.** The 3-round budget, the 20-variant flag threshold and the 70% overlap cutoff are the checklist draft's suggested values and have not been ratified by the team or confirmed with the professor.

- **The model-judgment stage is unexercised in the verified runs**, which used a deterministic-only reviewer; escalation logic has not been run against a live provider inside the full loop.


### 2.6 Reporting Agent & Memory Store

*Prepared by Emma*



### 1. Role in the System

The Reporting Agent is the last node before the human Portfolio Manager's decision. Unlike the three traders, it proposes nothing, and unlike Risk, it judges nothing: its job is to assemble whatever survived Risk review into a comparison the PM can actually read, and to say so honestly when a candidate was vetoed rather than quietly omit it. The agent consumes the round's `RiskReviewResponse` together with the surviving `TraderStrategyPackage` objects and produces a `ReportingOutput` carrying a structured, deterministic cross-lens comparison and, optionally, a natural-language memo.

Consistent with the project's central design rule — that the numbers a human acts on must not be authored by the thing being judged — the Reporting Agent is explicitly instructed never to select a winner or make the final portfolio decision. That choice is reserved for the PM. The agent's own system prompt enforces this as a hard rule, not a convention left to the model's discretion.

### 2. Pipeline and the Propose/Compute Boundary

The same propose/compute boundary described in the Fundamental Trader section governs Reporting: the structured comparison is always computed deterministically, and only the memo's narrative text is optionally produced by a model, constrained to interpret that data rather than introduce anything new.

The pipeline for one round is:

- **Collect.** Take the surviving candidates named on the `RiskReviewResponse` — candidates Risk vetoed do not reach this stage.
- **Compare.** Build a per-candidate record (hypothesis, metrics, interpretation, strengths/weaknesses, risk verdict, risk critiques, reporting flags) plus the round-level collective critiques and required disclosures Risk attached.
- **Interpret (optional).** If a `ModelClient` is configured, generate a narrative strategy memo from the comparison; if not, the round proceeds with the structured comparison only — never a hard failure.
- **Construct.** Assemble the `ReportingOutput` the PM and the dashboard consume: output and request identifiers, the surviving-candidate list, the comparison, and the memo reference if one was generated.

The model boundary uses the same provider-neutral `ModelClient` protocol shared with Risk's optional judgment stage and the Technical Trader's structured calls. A `GeminiModelClient` adapter was implemented and verified end-to-end against the live provider (§4); the agent remains fully functional with `model_client` left unset, in which case the PM still receives the full comparison, just without narrative memo text.

### 3. Memo Generation and Prompt Design

The system prompt given to the model enforces four rules directly:

- Summarize and compare the surviving candidates.
- Clearly report material Risk flags and critiques.
- Do not invent evidence, metrics, or conclusions.
- Do not select a winner or make the final portfolio decision.

Two further rules were added after inspecting the first real, provider-generated memo rather than assumed in advance: the initial output was one dense, unbroken paragraph, and it restated exact metrics that the comparison table already displayed. The prompt was revised to require a short paragraph per candidate, separated by line breaks, followed by a separate paragraph for risk disclosures; and to explicitly instruct the model to interpret the numbers rather than restate them, since the exact figures are already rendered in a separate table. Both changes were verified by regenerating the memo and inspecting the result, not assumed to have worked.

### 4. Verification and Representative Result

| Check | Result | Basis |
| --- | --- | --- |
| Reporting Agent unit tests | 3 / 3 pass | Cross-lens comparison, output identifiers, and surviving-candidate propagation, run against a real `RiskReviewResponse`. |
| Memory Store unit tests | 5 / 5 pass | Empty-context bootstrap, record()/load_context() round-trip, multi-round aggregation, per-workflow isolation, and state surviving a fresh instance pointed at the same directory (simulating a process restart). |
| Manual end-to-end chain | Verified | Technical/Fundamental/Quant candidates (shared risk_fixtures builders) → real `RiskAgentImpl` → `ReportingAgentImpl`, reproduced on demand. |
| Live production run | 100% execution | Four-round run, 19 Aug 2026 (see the Risk & Evaluation methodology section): Reporting completed every round it was reached; N/A on risk-approval since Reporting reviews no candidates itself. |
| Local live pilot (dashboard) | Verified | `GeminiModelClient` wired into the Reporting node produced a real, provider-generated narrative memo for the round's approved Fundamental and Quant candidates, correctly grounded in Risk's verdicts and flags. |

A representative memo, generated against a real round with one Technical candidate excluded (no model provider configured for Technical Trader in that environment) and Fundamental and Quant candidates approved by Risk, correctly separated each candidate into its own paragraph, avoided restating the table's exact figures, surfaced Risk's audit-ledger and multiple-comparison disclosures in a dedicated closing paragraph, and — as instructed — did not select a winner between the two approved candidates.

### 5. Risk Analysis and Interpretation

Because the memo's narrative half is optionally model-authored, the primary risk is invented content — a model asserting a conclusion the underlying data does not support. This is mitigated three ways: the system prompt explicitly forbids inventing evidence, metrics, or conclusions; the structured comparison is always computed deterministically regardless of whether a memo is generated, so a PM's access to the actual numbers never depends on the narrative; and a missing or failed model client degrades the round to structured-comparison-only rather than blocking it, mirroring the same fail-open-on-narrative, fail-closed-on-data discipline Risk applies to its own optional model-judgment stage.

A second, more honest risk is that the formatting rules in §3 were arrived at by inspecting a handful of real generations and revising the prompt accordingly, not by evaluating a held-out set of rounds or multiple providers. The rules work for the cases observed; whether they generalize to less typical rounds — many more surviving candidates, a candidate with unusually long critiques — has not yet been tested.

### 6. Known Limitations and Assumptions

- `combination_logic_implemented` is currently always false: the agent does not synthesize a single recommended combination across surviving candidates. This is a deliberate consequence of §1, not an unfinished feature — that judgment is reserved for the PM.
- Only the Gemini adapter has been smoke-tested against a live provider for this agent. Unlike Technical Trader, OpenAI and Anthropic adapters for Reporting have not yet been verified end to end.
- Prompt formatting rules (§3) were tuned empirically over a small number of manual inspections, not validated against a systematic evaluation set.
- Reporting's field access is coupled to the exact shape of `RiskReviewResponse` and `TraderStrategyPackage`; a contract change on Risk's side that is not mirrored here would fail at the type boundary rather than silently — consistent with the project's fail-closed convention, but noted here as a coupling worth dedicated test coverage.
- The dashboard integration in §4 currently renders the structured comparison directly when no memo was generated, which is correct behavior, not an error — documented here because it can otherwise look like a missing feature.

### 7. The Memory Store

Memory is shared infrastructure rather than a hireable agent — the same category as the Data service and the deterministic backtest engine. It is documented here, alongside Reporting, because both were built by the same owner and neither appears in another section.

The `MemoryStore` protocol defines two operations: `record(MemoryRecord)`, which persists a round's results, critiques, and PM decision, and `load_context(workflow_id)`, which returns the accumulated `MemoryContext` — prior result references, prior critiques, prior PM decisions, and distilled lessons — for the next round. A single workflow can span multiple rounds whenever the PM requests another round, so `load_context` must fold together every prior round's record, not only the most recent one.

The current, live implementation is `FileBackedMemoryStore`: it persists every record to a JSON file per `workflow_id` on disk, rather than holding state only in the running process. This was a deliberate correction, not the original design — an earlier `InMemoryMemoryStore` (an in-process dictionary keyed by workflow ID) was the first implementation, and it satisfies the same `MemoryStore` protocol correctly on its own. It became a real bug once the live dashboard began launching each research round as a fresh subprocess: a purely in-process store loses everything the instant that process exits, so a PM's second "Request Another Round" would have started from a blank Memory rather than the prior round's actual lessons. `FileBackedMemoryStore` was built to close that gap, and both implementations now exist in the codebase — `InMemoryMemoryStore` remains valid for single-process use (e.g. the original multi-round test script), while `FileBackedMemoryStore` is what the live, subprocess-per-round dashboard pilot actually uses today, since only the file-backed version survives a round's subprocess exiting.

Both implementations satisfy the identical protocol, so nothing calling `load_context`/`record` needed to change when the live pilot switched from one to the other — the substitution is exactly what the protocol boundary was designed to allow.

Nine tests verify the two implementations together: the four shared behavioral properties (empty context before any round is recorded; `record()` returns the persisted record's identifier; `load_context()` aggregates results, critiques, PM decisions, and lessons across multiple recorded rounds, not just the latest; two different workflows never leak state into each other) are each verified against both `InMemoryMemoryStore` and `FileBackedMemoryStore`, plus one test specific to the file-backed store: state genuinely survives a fresh store instance being constructed against the same directory, directly simulating the subprocess-restart scenario that motivated building it.

**Known limitation:** `FileBackedMemoryStore` persists to a single machine's local filesystem — correct for the current single-machine demo, not yet a shared, multi-user, or hosted store.


## 3. Results, Risk Analysis & Interpretation



### 1. What This Section Is, and Isn't

Each agent's own methodology section reports its results in isolation: Fundamental Trader's category-benchmark deviation, Quant Trader's cross-asset pair, Risk's checklist and the evaluation harness's productivity metrics. This section does not repeat those results — it asks what they mean together, as evidence about the system as a whole rather than about any one strategy. The central claim of this project was never that a specific rule beats the market. It is that a human can manage a team of AI research agents on measured performance, the way a manager runs a small team of people, rather than on impression. The results below are read against that claim, not against whether any individual backtest made money.

### 2. What the Individual Results Actually Show

Fundamental Trader and Quant Trader produced genuinely different outcomes, and that difference is itself informative. Fundamental Trader's representative candidate — AWAY against its major-tier "Consumer Cyclical" peers (PEJ, XLY) — lost money on both the training window (−7.40% total return) and the held-out test window (−14.96%), with Sharpe ratios of −0.03 and −0.31 respectively. Quant Trader's representative candidate — the EWA/EWC pair, selected from a 15-ticker universe on 0.846 correlation and a roughly 56-trading-day half-life — made money on both windows, and held up *better* out of sample than in sample (Sharpe 0.235 training vs. 0.714 test; max drawdown improving from −33.41% to −17.95%; transaction count falling from 84 to 18 as the position was held rather than churned).

Read individually, one of these looks like a failed strategy and the other looks like a working one. Read together, they are the same kind of evidence: two independent, honestly-reported outcomes from two different analytical lenses applied to the same underlying discipline (a declared rule, a fixed train/test split, a deterministic engine that computed every number). Neither result was selected because it was favorable — Fundamental Trader's loss is reported in its own methodology section for the same reason Quant Trader's gain is: both are what the pipeline actually produced, without editing after the fact.

### 3. The System-Level Result That Matters More Than Either Backtest

The most informative result in this project is not a return figure. It is what happened when the same workflow was driven through four consecutive research rounds on 19 August 2026: real Fundamental Trader, real Quant Trader, real Risk agent, real Reporting agent, and a real Memory store, against the real 120-ticker fixture, producing a 23-event operational ledger. Round 1 approved two candidates, each carrying three explicit flags naming exactly what could not yet be verified. By round 4, the same deterministic Risk checklist — unmodified, running the same code as round 1 — vetoed *both* surviving candidates on CP-11, the validation-touch budget: *"Round 4 exceeds the 3-round validation-touch budget and the candidate carries no parameter-stability evidence."*

This is the demonstration the project's hire/fire/pivot thesis actually depends on. The system did not simply keep producing approvable results round after round; it detected, mechanically and without human prompting, that continuing to re-touch the same validation window past a stated budget had become a research-integrity problem, and it stopped the process rather than let a fourth round manufacture a result. A dashboard that only ever shows green checkmarks would not have demonstrated anything about self-deception; a dashboard that shows real work getting vetoed by its own rules is closer to the actual point of the project than any single winning backtest could be.

### 4. Interpreting the Productivity Metrics

The same four-round run produced per-agent productivity data that is worth reading carefully rather than at face value, because two of its numbers are genuinely counter-intuitive by design, not by accident:

- **Both traders executed flawlessly across all four rounds (100% execution), while roughly a quarter of their combined proposals were rejected by Risk (75% risk-approval rate each).** These two readings of "success" diverge on the same underlying data, and that divergence is itself a finding: a metric that only measured whether an agent's code ran without crashing would have called every round a full success, including the round where both proposals were correctly vetoed. This is precisely why the evaluation harness reports both readings under separate names rather than collapsing them into one number — collapsing them would let the dashboard imply a question ("what does success mean for a research agent?") that the team has not actually settled.
- **Technical Trader's crash reads as 0% execution and N/A on risk approval, not a rejected proposal.** This distinction matters for what a PM would actually do with the number: a trader whose code fails is a different problem, needing a different fix, than a trader whose ideas are consistently rejected. Scoring a crash as a rejected proposal would penalize the same incident twice and point a human toward the wrong fix.
- **Cost reads N/A throughout the run**, because no model call in that particular run reported provider usage (Fundamental and Quant Trader are both deterministic; Technical Trader's proposal never got far enough to report cost). This is stated as an absent measurement, not printed as $0.00 — a genuinely different claim, since a fire decision made on a fabricated zero would be a worse failure than one made on an honest "unknown."

### 5. Risk Analysis: Where the Design Is Genuinely Exposed

Two risks are worth stating plainly, because they are structural rather than incidental, and because a paper that only reports risks in individual agents' sections while treating the system itself as risk-free would be repeating the exact failure mode this project is built to catch.

**The checker has no checker.** Every trader's output is reviewed by Risk; Risk's own logic is reviewed by nothing but its own code, and the evaluation harness has the same property one level up. This is not a hypothetical concern: a real instance of it has already occurred in this project. The shared data service back-adjusts prices and honestly declares its data as not point-in-time verified — but in the same change that introduced that declaration, Technical Trader's own look-ahead guard, which had previously rejected unverified data outright, was relaxed to require only that provenance metadata *exist*. A safeguard failed a check, and the check was loosened rather than the underlying issue fixed, and nothing in the current 13-point checklist catches that specific class of regression, because no check consults the point-in-time flag at all. This is documented here deliberately, not patched quietly before submission, because silently fixing it would itself be an instance of the self-deception the project exists to detect. It remains an open decision for the team: either restore the stricter check and accept that the current data source cannot be used for graded runs, or keep the relaxed check with an explicit disclosure that propagates through Risk into the PM's memo.

**Whichever "success" definition gets chosen becomes a target.** If risk-approval rate becomes the number a PM fires agents on, the fastest way for a trader to score well stops being "find a genuinely good strategy" and starts being "propose things Risk tends to wave through" — a textbook instance of Goodhart's law aimed directly at the mechanism this entire project is organized around. The current, deliberate answer is not to pick a winner between execution and risk-approval, but to compute and publish both under clearly separate names, so that a PM's staffing decision is visibly a choice about what to value, not a number the system has quietly decided for them.

### 6. Interpretation: What the Results Support and What They Don't

The results support a narrow, specific claim: a small set of independently-owned agents can propose real trading rules, have those rules evaluated by a reviewer that computes its verdicts from ledger data rather than the traders' own claims, and have a human's staffing decisions carried mechanically into what those agents do next — and this loop can run for multiple rounds, on real data, producing outcomes (including outright vetoes) that were not scripted in advance. That is what was verified, repeatedly, against the real system rather than a simulated one.

The results do not support a claim that any strategy here is investable, or that the Risk checklist is complete, or that the productivity metrics are free of their own blind spots. Eight of Risk's thirteen checks run on live evidence today; five require infrastructure (a round-audit reader, a round-history reader) that does not exist yet, and those five are honest about returning "cannot verify" rather than manufacturing a pass. The project's own standard — state what was actually tested, report unfavorable results as readily as favorable ones, and disclose a gap rather than paper over it — is the standard this section has tried to hold itself to as well.

### 7. Known Limitations and Assumptions

- Both representative backtests (§2) are single candidates from a single run each, not a distribution over many independent draws; neither result should be read as characterizing the strategy family's typical performance.
- The four-round run in §3 and §4 excluded Technical Trader (no model provider configured in that environment), so the productivity comparison in §4 covers four of the five hireable agents, not all five.
- The point-in-time data regression described in §5 is unresolved as of this writing; any results computed after a fix is applied may differ from those reported here, and that is expected, not a contradiction of this section.
- "Success %" is reported using both the execution and risk-approval definitions throughout this project's evaluation output; this section does not select one as canonical, consistent with the evaluation harness's own design choice not to settle that question implicitly.

## 4. Conclusion

This project set out to answer a management question, not a trading question: once a human delegates research to a team of AI specialists instead of one, how do they decide who to trust, who to let go, and who to try differently — on data, rather than on impression? The Fractional AI Workforce answers that question inside a concrete, testable setting, and the evidence that matters most is not any single backtest, but what happened when the system ran the same workflow for real across four consecutive rounds: two candidates were approved in round 1, each carrying explicit flags naming exactly what could not yet be verified, and by round 4 the same unmodified Risk checklist vetoed both surviving candidates on CP-11, the validation-touch budget — a genuine, mechanically-produced veto, not a scripted outcome. Hire, bench, and pivot decisions carried real effects into the next round; the evaluation harness replayed per-agent productivity from an operational event ledger rather than any agent's self-report; and the two agents that could crash, get vetoed, or succeed did all three, honestly reported under separate metric names rather than collapsed into one comforting number.

That is a narrow, specific claim, and it is worth stating what it does not cover. Eight of Risk's thirteen checks run on live evidence today; five require a round-audit and round-history reader that does not yet exist, and are honest about returning "cannot verify" rather than manufacturing a pass. The point-in-time data regression described in the Risk Agent section remains an open, undecided question for the team rather than a quietly patched one. Technical Trader's live model call was smoke-tested with real credentials, closing what had been the project's one remaining technical unknown at the time of the Architecture Overview section above. None of this is hidden in an appendix; each limitation is disclosed in the section of the agent that owns it, in keeping with the project's own standard — report unfavorable results as readily as favorable ones, and disclose a gap rather than paper over it.

The result is not a claim that any strategy here is investable, or that a solo researcher should trade on these signals. It is evidence that the underlying mechanism — measured, per-agent performance driving real staffing decisions, verified against a system's actual behavior rather than its demo — works, including when that meant reporting a losing backtest, an unresolved regression, or a crashed agent rather than a cleaner story.
