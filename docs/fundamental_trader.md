# Fundamental Trader

Status: prototype (built Workstream #2, offline end-to-end verified)

Owner: Aditi

Package: `src/agents/fundamental_trader/`

## What it does

Fundamental Trader is one of the three independent trader branches described
in `docs/architecture.md`. Its lens is "fund-level fundamentals" - reading
what an ETF *is*, not how its price has been moving (Technical) or how it
correlates statistically with other assets (Quant).

Like the other traders, it never computes its own performance numbers. It
proposes a candidate rule and hands it to the shared, deterministic
`tools.backtest_engine`; only that engine's simulation is allowed to report
metrics.

## The data gap, and the heuristic built to work around it

The original design called for classic ETF fundamentals: expense ratio,
dividend yield, NAV premium/discount, sector/factor exposure. `ETF_info.xlsx`
was inspected directly (not assumed from the spec) and does **not** populate
`marketCap`, `sector`, or `industry` for any of the 120 finalized tickers.
Only `category` (44 distinct values) and `fundFamily` (27 distinct values)
are populated for effectively the whole universe.

**ISSUER_SCALE_TIER** is the heuristic built on top of that: `fundFamily` is
bucketed into `"major"` (large, broadly-distributed issuers - iShares,
Vanguard, State Street, Invesco, Schwab, Fidelity, JPMorgan, First Trust,
WisdomTree) versus `"boutique"` (everything else present in the fixture -
ARK, Global X, ProShares, VanEck, and 15 others). Against the real 120-ticker
universe this splits 82 major / 38 boutique.

This is a **liquidity/issuer-scale proxy**, not a direct fundamental
valuation signal, and every candidate this trader proposes says so explicitly
in `implementation_notes` and in the Risk-facing `overfitting_risks` - see
`interpretation.py`. Risk should weigh results from this trader knowing that.

## The strategy: category-benchmark deviation

Two ETFs in the same `category` (e.g. "Technology", "Natural Resources")
track similar underlying exposure by construction. If a boutique-tier
ETF's return drifts unusually far from the equal-weight return of its
category's major-tier peers, that gap is more likely a liquidity/technical
artifact than a fundamentally justified difference - nothing in the category
definition explains why two funds tracking the same space should diverge for
long. The trader proposes betting on that gap closing.

## Pipeline

`FundamentalTraderAgent.run(TraderTask) -> TraderStrategyPackage` does, in order:

1. **Fetch.** Requests point-in-time `PRICE_VOLUME` **and** `ETF_METADATA`
   for the mandate's permitted asset universe from the injected
   `DataService`, in a single call.
2. **Resolve the split before proposing anything.** Same anti-look-ahead
   discipline as Quant Trader: the `ValidationSplitPolicy` runs immediately
   after the fetch, and discovery only ever sees bars strictly before
   `test_start_date`.
3. **Discover.** `rule_generator.py` groups the universe by `category`, builds
   an equal-weight major-tier benchmark per category, and scans every
   boutique-tier ticker in that category for a significant z-score deviation
   from that benchmark, ranked by `|z-score| x correlation`.
4. **Package.** The strongest candidate becomes a `CandidateRuleSpecification`
   bound to `fundamental_trader.category_benchmark_deviation.v1`, with the
   deviation/correlation evidence attached as `specialty_evidence`.
5. **Evaluate.** The candidate is sent to the shared `BacktestEngine`
   unchanged; Fundamental Trader has no opinion on the resulting numbers.
6. **Interpret.** `interpretation.py` turns the settled `BacktestResult` into
   a `BacktestInterpretationDraft` - template-generated, not model-authored,
   same boundary as Quant Trader (see Known limitations).

Any stage that fails (no data, no candidate found, a prohibited asset, an
engine error) returns a settled, non-eligible `TraderStrategyPackage` with a
`TraderFailure` explaining why, rather than raising.

## The strategy executor

`strategy.py` registers one `StrategyExecutor` (`CATEGORY_DEVIATION_EXECUTOR_ID`)
with the shared backtest engine. Given a candidate's `parameters` (`ticker`,
`category`, `lookback_days`, `entry_zscore`, `exit_zscore`,
`benchmark_tickers`), `CategoryDeviationSession.target_weights`:

- computes the rolling spread between the ticker's own return and the
  equal-weight return of its `benchmark_tickers`, over the trailing
  `lookback_days` window, using only bars the engine has already revealed
  (`context.history`, point-in-time by construction);
- enters (target weight `{ticker: 1.0}`) once the spread z-score falls to or
  below `-entry_zscore`;
- exits (target weight `{}`, fully to cash) once it recovers to or above
  `-exit_zscore`;
- otherwise returns `None` ("keep the current position") for hysteresis.

No leverage, no shorting, one position at a time.

## A resolver gap found during integration testing

The shared `services.data_service.YFinanceBacktestDataResolver` only looks
for a fixed set of single-ticker parameter keys (`ticker_a`, `ticker_b`,
`symbol`, `ticker`). Fundamental Trader's candidates also carry a
`benchmark_tickers` list, which that resolver does not know to look for - it
would silently backtest against only the main ticker's bars, and the
category-deviation session would never see its benchmark peers' history.

`examples/backtest_resolver.py` (`FundamentalBacktestDataResolver`) is a
Fundamental-Trader-owned wrapper that also resolves every symbol in
`benchmark_tickers`. **Flagged for Workstream #3 integration**: the cleaner
long-term fix is for the shared resolver to grow a general "extra symbol
keys" hook so every trader doesn't need its own variant - raise with Yiran
before wiring the production graph.

## Running it locally

```bash
pip install -e ".[fundamental-demo]"
# copy ETF_info.xlsx to the repo root first (gitignored, supplied per developer)
python scripts/run_fundamental_trader_standalone.py
# or: python -m agents.fundamental_trader.examples.run_demo
```

This wires the real `FundamentalTraderAgent` and the real, shared
`DeterministicBacktestEngine` to `FundamentalMetadataDataService`
(`examples/static_data_service.py` - PRICE_VOLUME delegated to the shared
`YFinanceDataService`, ETF_METADATA read from the local `ETF_info.xlsx`
fixture) and `FundamentalBacktestDataResolver`. Expected output includes the
discovered ticker, its category/benchmark evidence, the executor's
parameters, and both training-window and held-out test-window metrics from
the real backtest engine.

**Verified offline** (no network access) against the real 120-ticker
`ETF_historical_prices.xlsx` / `ETF_info.xlsx` fixtures during development:
discovery completed in under a second and returned five plausible candidates
(e.g. `LIT` vs. its "Natural Resources" major-tier peers, `FINX` vs.
"Technology"); a full `agent.run()` pass through the real
`DeterministicBacktestEngine` produced a settled, eligible package with real
(in this case, negative) out-of-sample metrics - i.e. the pipeline reports
losing results honestly rather than only ever finding winners.

## Tests

`tests/fundamental_trader/test_fundamental_trader_agent.py` uses small,
synthetic, hand-built fixtures (not the real 31MB price file) so CI stays
fast and hermetic:

- `classify_issuer_tier` splits major/boutique correctly.
- `propose_category_deviations` finds a planted divergence.
- A full `agent.run()` against a fake `DataService` + real
  `DeterministicBacktestEngine` produces an eligible, complete package, and
  its interpretation always surfaces the ISSUER_SCALE_TIER limitation.
- A full `agent.run()` against an empty `DataService` settles a `failed`
  package rather than raising.

## Known limitations

- **ISSUER_SCALE_TIER is a heuristic, not licensed data.** The major/boutique
  split (9 issuers, chosen for AUM/shelf-space breadth) has not been
  confirmed with the team - see `rule_generator.MAJOR_TIER_ISSUERS`.
- **The category benchmark is computed in-house**, not a licensed index - an
  equal-weight average of whichever major-tier peers happen to share a
  category in this fixture.
- **Interpretation is template-generated**, not model-authored, same as
  Quant Trader - see `interpretation.py`.
- **No transaction-cost stress testing** beyond the engine's configured
  commission/slippage assumptions.
- **Single-candidate proposal per round** - Risk currently reviews one
  ticker per round from this trader, not several ranked candidates.
