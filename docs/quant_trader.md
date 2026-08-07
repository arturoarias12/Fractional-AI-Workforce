# Quant Trader

Status: prototype (moved from placeholder in `docs/architecture.md`)

Owner: Shaurya

Package: `src/agents/quant_trader/`

## What it does

Quant Trader is one of the three independent trader branches described in
`docs/architecture.md`. Its lens is "statistics and cross-asset anomalies":
instead of reading one instrument's own price/volume history (Technical) or
its fundamentals (Fundamental), it looks for pairs of ETFs whose prices move
together and whose spread has historically snapped back toward its own
average - a cross-asset mean-reversion trade.

Like the other traders, it never computes its own performance numbers. It
proposes a candidate rule and hands it to the shared, deterministic
`tools.backtest_engine`; only that engine's simulation is allowed to report
metrics.

## Pipeline

`QuantTraderAgent.run(TraderTask) -> TraderStrategyPackage` does, in order:

1. **Fetch.** Requests point-in-time `PRICE_VOLUME` data for the mandate's
   permitted asset universe from the injected `DataService`.
2. **Resolve the split before proposing anything.** Calls the injected
   `ValidationSplitPolicy` immediately after the fetch, *before* running any
   statistics. This is deliberate: the split marks a `test_start_date`, and
   discovery is only ever given bars strictly before that date.
3. **Discover.** `discovery.py` scans every pair in the training-window panel
   for (a) return correlation above a threshold and (b) a price ratio whose
   AR(1) fit implies genuine mean reversion, then ranks survivors by a score
   that rewards both a strong relationship and a fast snap-back (a pair that
   reverts in two weeks is more useful than one that takes three months).
4. **Package.** The strongest candidate becomes a `CandidateRuleSpecification`
   bound to the registered executor
   `quant_trader.cross_asset_spread_mean_reversion.v1`, with the correlation/
   half-life evidence attached as `specialty_evidence` for Risk and Reporting
   to read.
5. **Evaluate.** The candidate is sent to the shared `BacktestEngine`
   unchanged; Quant Trader has no opinion on the resulting numbers.
6. **Interpret.** `interpretation.py` turns the settled `BacktestResult` into
   a `BacktestInterpretationDraft` - currently template-generated, not
   model-authored (see Known limitations).

Any stage that fails (no data, no candidate found, a prohibited asset, an
engine error) returns a settled, non-eligible `TraderStrategyPackage` with a
`TraderFailure` explaining why, rather than raising. This matches the
project's join semantics: one trader's failure must not erase another
trader's candidate.

## Why the point-in-time discipline matters here specifically

An earlier standalone version of this logic scanned a strategy's *entire*
available history - including what later became the held-out test window -
to decide which pair to trade. That is a real look-ahead bug: it means the
"out-of-sample" test isn't testing anything held out at all, since the
pair was chosen partly because it already looked good on that window.

The fix embedded in this package is structural, not a discipline someone has
to remember: `agent.py` resolves the `ValidationSplit` first and slices the
panel to `timestamp.date() < split.test_start_date` before calling
`discovery.propose_pairs`. Discovery itself has no knowledge of any test
window and cannot accidentally use one.

## The strategy executor

`strategy.py` registers one `StrategyExecutor`
(`CROSS_ASSET_SPREAD_EXECUTOR_ID`) with the shared backtest engine. Given a
candidate's `parameters` (`ticker_a`, `ticker_b`, `lookback_days`,
`entry_zscore`, `exit_zscore`), its `PairSpreadSession.target_weights`:

- computes the rolling `ticker_a / ticker_b` price-ratio z-score over the
  trailing `lookback_days` window using only bars the engine has already
  revealed to it (`context.history`, which is point-in-time by construction);
- enters (target weight `{ticker_a: 1.0}`) once the z-score falls to or below
  `-entry_zscore`;
- exits (target weight `{}`, fully to cash) once the z-score recovers to or
  above `-exit_zscore`;
- otherwise returns `None`, meaning "keep whatever position you already
  have" - this is what gives the rule hysteresis so it doesn't flicker in
  and out on small daily noise.

No leverage, no shorting, one position at a time.

## Running it locally

Quant Trader now calls the real, shared `DataService` -
`services.data_service.YFinanceDataService` / `YFinanceBacktestDataResolver`
(built on Yiran's workstream) - the same boundary the other trader agents
use. `agent.py` was never coupled to any particular implementation (it only
depends on the `DataService` Protocol), so this was purely a wiring change in
`examples/run_demo.py`, which now imports directly from `services` instead of
from a Quant-Trader-only adapter.

```bash
pip install -e ".[quant-demo]"
python -m agents.quant_trader.examples.run_demo
```

Expected output includes the discovered pair, its correlation/half-life
evidence, the executor's parameters, and both the training-window and
held-out test-window metrics reported by the real backtest engine.

**Old process, kept as a fallback.** Before the shared DataService existed,
this package carried its own dev-only stand-ins in
`examples/static_data_service.py` so the real `QuantTraderAgent` and the real
`DeterministicBacktestEngine` could still be run and demonstrated end to end.
All of them are kept, commented out, satisfying the exact same Protocols, in
the order they were actually tried during development:

0. **`YFinanceDataService` / `YFinanceDataResolver` (dev-only)** - the
   Quant-Trader-only adapter this package used to run live before the shared
   `services.data_service` landed. Functionally identical to
   `services.data_service.YFinanceDataService` / `YFinanceBacktestDataResolver`.
1. **`FMPDataService` / `FMPDataResolver`** - Financial Modeling Prep's REST
   API. Its `historical-price-eod/full` endpoint turned out to require a
   paid plan. Needs an `FMP_API_KEY` environment variable if uncommented.
2. **`StooqDataService` / `StooqDataResolver`** - Stooq's free CSV endpoint
   (`stooq.com/q/d/l`). Widely documented online as working, but returns a
   404 in practice for direct programmatic access.
3. **`AlphaVantageDataService` / `AlphaVantageDataResolver`** - has a real
   free tier and worked, but that tier only returns the last ~100 trading
   days per symbol (`outputsize=full`, needed for real history, is
   premium-only). This project's `discovery.py` needs at least
   `MIN_HISTORY_DAYS` (750) days of shared history to trust a correlation
   or fit a mean-reversion half-life, so 100 days isn't usable here - kept
   in case a paid plan becomes available, or for a different use case that
   doesn't need deep history. Needs an `ALPHA_VANTAGE_API_KEY` environment
   variable if uncommented.
4. **`StaticExcelDataService` / `StaticExcelDataResolver`** - the original
   implementation, reads `ETF_historical_prices.xlsx` directly with no
   network calls at all. Useful for running fully offline.

To fall back: uncomment the desired class(es) in `static_data_service.py`,
then uncomment the matching import and swap the `data_service`/
`backtest_engine` construction in `run_demo.py`'s `main()` (the commented
block is right there, directly under the primary path). If the shared
DataService is ever unavailable, the static xlsx fallback is the most
reliable option since it has no external dependency at all.

## Known limitations / open questions

- **Interpretation is template-generated, not model-authored.**
  `interpretation.py` says so explicitly in its own `ConfidenceAssessment.
  uncertainty_drivers`. A `model_client` boundary (mirroring Technical
  Trader's) can replace `build_interpretation` later without touching
  `agent.py`'s control flow.
- **Single candidate per round.** `propose_pairs` can rank several
  candidates, but `agent.py` currently only backtests the top-ranked one.
  Submitting the top 2-3 would let Risk compare survivors instead of judging
  one pair in isolation - flagged as an `open_question` inside every
  interpretation this package produces.
- **Selection-bias risk is real, not hypothetical.** Scanning hundreds of
  pairs and keeping the best-scoring one is exactly the kind of process that
  can manufacture a good-looking result by chance. `interpretation.py`
  surfaces this directly in `overfitting_risks` so Risk is never handed a
  candidate without that caveat attached.
- **No transaction-cost stress testing** beyond whatever
  `ExecutionAssumptions` the engine is configured with by default.
- **Data adapter seam: now verified against the real DataService.**
  `data_adapter.extract_price_panel` supports `DataArtifact.analysis_payload`
  as either a `{symbol: bars}` mapping or a flat bar sequence tagged with the
  artifact's `asset_scope`. `services.data_service.YFinanceDataService`
  returns the `{symbol: bars}` mapping form, so no change was needed here -
  confirmed with a mocked end-to-end run through the real `DataService` and
  the real `DeterministicBacktestEngine`.

## Files

| File | Role |
|---|---|
| `agent.py` | `QuantTraderAgent`; orchestrates fetch -> split -> discover -> package -> backtest -> interpret. |
| `discovery.py` | Correlation + AR(1) half-life pair scan; pure statistics, no I/O. |
| `strategy.py` | The registered `StrategyExecutor` the shared backtest engine actually runs. |
| `interpretation.py` | Deterministic, template-based `BacktestInterpretationDraft` builder. |
| `data_adapter.py` | Converts a `DataResponse` into the price panel `discovery.py` expects. |
| `services.py` | `DataService` / `BacktestEngine` / `ValidationSplitPolicy` Protocols this package depends on. |
| `runtime.py` | Mandate validation, task construction, and an optional LangGraph node adapter (mirrors `technical_trader.runtime`). |
| `errors.py` | Package-local exceptions. |
| `examples/` | Dev-only static data adapters and a runnable end-to-end demo. Not part of the production wiring. |
