# Technical-Analysis Tools

The tools in `src/agents/technical_trader/tools` are deterministic code, not
LLM prompts and not external agents.

## Input boundary

`TechnicalAnalysisInputAdapter` converts the pending Data Service response into
one or more validated `PriceSeries` objects. A series requires:

- artifact ID and symbol;
- as-of date;
- frequency;
- at least five bars;
- strictly increasing, unique, timezone-aware timestamps;
- valid positive OHLC values; and
- optional non-negative volume.

The default adapter reads the provisional `DataArtifact.analysis_payload`.
Replace the adapter—not the algorithms—when the final data schema arrives.

## Support and resistance

For each price series, the toolkit:

1. finds strict local high and low pivots using a symmetric window;
2. sorts pivot prices;
3. clusters prices within a configurable percentage tolerance;
4. removes clusters below the configured touch count;
5. averages each retained cluster's pivot prices;
6. emits low-pivot clusters as support and high-pivot clusters as resistance;
7. records touches, timestamps, distance from last close, and source pivots; and
8. assigns a stable level ID.

If no support or resistance cluster survives, the observed range low or high is
returned as an explicitly marked fallback. The report also includes a warning.
This guarantees that the LLM receives both structural boundaries without
pretending a weak fallback is a repeatedly tested level.

Default configuration:

| Parameter | Default |
|---|---:|
| Pivot window | 2 bars per side |
| Merge tolerance | 1% |
| Minimum touches | 2 |
| Maximum levels per kind | 8 |

## Head-and-shoulders

The toolkit separately evaluates consecutive triples of high pivots and low
pivots.

For a normal head-and-shoulders observation:

- the middle high must exceed both shoulders by the configured prominence;
- shoulder prices must fall within the configured tolerance;
- pivots must meet minimum separation and maximum span constraints;
- the neckline is the mean of the two intervening trough lows; and
- confirmation requires a later close below the neckline.

The inverse form applies the corresponding low-pivot geometry and requires a
later close above the neckline.

Default configuration:

| Parameter | Default |
|---|---:|
| Pivot window | 2 bars per side |
| Shoulder tolerance | 4% |
| Head prominence | 3% |
| Minimum pivot separation | 2 bars |
| Maximum pattern span | 126 bars |
| Maximum observations per series | 5 |

`forming` means the geometry exists without a later neckline crossing.
`confirmed` means the historical close-crossing condition occurred. Neither
status predicts subsequent performance.

## Moving averages

The toolkit computes a reusable evidence library at 3/10, 5/20, 10/30, 20/50,
50/100, and 50/200 bars. It reports current values, percentage spread,
bullish/bearish/neutral relationship, most recent crossover direction and
timestamp, and bars since that crossover. A neutral band prevents tiny
numerical differences from being described as meaningful. Ordinary point-in-
time Python performs every calculation; the LLM does not calculate an average.

Code maps the PM mandate to permitted lookbacks. A five-day mandate, for
example, permits 3/10 and 5/20 evidence and rejects 20/50. Longer mandates may
use slower pairs without changing the agent or shared package contract.

| PM horizon (trading days) | Permitted pairs | Maximum level distance |
|---|---|---:|
| 1–5 | 3/10, 5/20 | 3% |
| 6–20 | 5/20, 10/30 | 5% |
| 21–63 | 10/30, 20/50 | 8% |
| 64–126 | 20/50, 50/100 | 12% |
| 127–1,260 | 50/100, 50/200 | 20% |

The maximum holding period is the shorter of the PM horizon and any explicit
holding cap in `risk_limits`. The analytical profile and permitted lookbacks
continue to follow the PM investment horizon; a tighter risk cap limits time in
the position but does not silently rewrite the analytical thesis. Numeric day/
week/month/year mappings, value/unit mappings, and equivalent plain-language
descriptions are accepted. An absent or unparseable horizon conservatively
defaults to five trading days and produces an audit warning. The resolved
profile and its source are stored in the final package.

## Relative volume

When complete volume data exists, the toolkit compares the latest bar's volume
with the mean of the prior 20 bars. It reports both values, their ratio, the
lookback, and the latest close return. Missing or non-positive comparison data
produces a warning and no volume observation; it is never imputed by the LLM.

## Deterministic strategy executors

`src/agents/technical_trader/executors` contains one model-selectable multi-ETF
portfolio executor. It composes five deterministic long-only sleeve families:

- support reaction;
- resistance breakout;
- fast/slow moving-average trend;
- volume-confirmed resistance breakout;
- confirmed inverse-head-and-shoulders breakout.

The bearish head-and-shoulders breakdown implementation remains available as
agent-local analytical code but is not registered in the current long-only
portfolio executor.

The LLM returns one package-level portfolio rule and chooses one sleeve family
per included ETF. Python validates every sleeve, binds it to same-symbol cited
evidence, calculates all signals, freezes each entry-time volatility estimate,
and maintains separate entry/exit state. A second structured LLM pass then
reviews and may revise the whole proposal using the same frozen Technical
report. It must challenge weak evidence, contradictions, false-breakout or
whipsaw risk, concentration, and omissions without using held-out results or
introducing Fundamental or Quant evidence.

A second registered executor implements the code-owned benchmark fallback. It
submits one long benchmark target and holds it until deterministic end
liquidation. It adds no new Technical indicator family and is never exposed as
a model-selectable strategy.

## Multi-ETF portfolio candidate

The current daily toolkit makes asset identity plus timestamp/open/high/low/
close mandatory. Volume, session flags, lifecycle data, liquidity fields, and
other metadata remain optional. When optional evidence is unavailable, only the
sleeve families that depend on it are excluded; the whole Technical run does
not fail. Code normalizes this boundary before calling the Data Service.

`TechnicalTraderRuntime.research(...)` returns exactly one shared
`TraderStrategyPackage`, matching the other trader branches and the production
graph contract. Its one candidate rule targets 10 unique permitted ETFs but may
contain fewer when training-period Technical evidence does not support a
positive expected tactical return for all 10. At least one sleeve is required.

Selection is ex ante: neither the LLM nor deterministic selection logic sees
held-out results before membership is finalized. Fewer than 10 sleeves require
an explicit omission rationale. Every included sleeve must provide a unique
symbol, a supported family, a positive-expectation rationale grounded in
training evidence, and the exact evidence IDs required by that family.

Before the candidate call, code converts the PM's flexible horizon into an
auditable profile containing the holding limit, permitted moving-average pairs,
recent-crossover age, level-actionability distance, and minimum warm-up sample.
It then ranks family-specific opportunities from frozen training evidence. The
score combines only ex-ante properties relevant to the family: proximity,
repeated-touch quality, recency, volatility-scaled trend strength, relative
volume when available, and capped daily movement capacity. The last component
penalizes very low-volatility assets but caps at 1% daily volatility, so it does
not award additional points for leverage-like volatility. The score is a
deterministic selection aid, not a return forecast.

Every selected sleeve must match one ranked opportunity by symbol, executor,
and evidence IDs. Code binds the opportunity ID, rank, and score into the final
package. This makes ties and deviations auditable while leaving the LLM free to
choose a lower-ranked opportunity for a stated evidence-based diversification
reason.

Evidence IDs are authoritative for deterministic numeric inputs. Before
validation and execution, code resolves the cited support/resistance price,
moving-average windows, volume lookback, or confirmed pattern neckline and
binds it into the sleeve parameters. The LLM chooses the evidence but does not
retype or estimate those values.

The executor equal-weights the selected sleeves within the declared portfolio
gross target. Each sleeve independently decides when to enter and exit; inactive
sleeve capital remains in cash. When any sleeve changes state, the executor
returns the full active target mapping, so the shared engine may also
drift-correct other active sleeves toward their equal weights. This intentional
portfolio-level rebalancing can add turnover. The Backtest Engine receives one
rule, produces one portfolio result and ledger entry, and applies the shared
costs, mandate, and evaluation split once.

Code compares that result's out-of-sample `total_return` with the requested
benchmark value returned by the engine. Strict outperformance retains the
Technical portfolio. Equality or underperformance builds and backtests the
benchmark fallback under the same assumptions. The final output remains one
shared package; the rejected Technical candidate and result remain attached as
audit data. Because this decision reuses the held-out window, a later untouched
post-selection test is required before claiming independent validation.

The package retains the complete deterministic cross-universe report. Because
there is only one package, that report is not duplicated ten times. Artifact
size must not be reduced by dropping otherwise qualified ETF sleeves; external
artifact storage by reference can be introduced later if graph-state limits
require it.

## Evidence enforcement

The tool report supplies:

- `report_id`
- `level_id` for every support/resistance level
- `pattern_id` for every observed chart structure
- `moving_average_id` for every available moving-average observation
- `volume_id` for every available relative-volume observation

The LLM must return its cited IDs in `specialty_evidence_ids` and map every ID
to its exact rule role in `specialty_evidence_usage`. Code rejects:

- IDs absent from the report;
- asset-level evidence that belongs to a different symbol;
- missing executor-required evidence;
- evidence that does not match one ranked mandate-horizon opportunity;
- moving-average windows or crossover recency inconsistent with the mandate;
- levels too far from price for the mandate horizon;
- fallback or wrong-side levels;
- ambiguous or missing evidence needed to bind a level price, moving-average
  window pair, volume lookback, or pattern neckline;
- forming or wrong-type patterns supplied to a pattern executor; and
- missing or extra evidence-usage mappings.

## Limitations

- Pivot and pattern definitions are configurable heuristics.
- When pattern output is capped, the most recent observations are retained.
- Different frequencies can produce different structures.
- Range fallbacks are not equivalent to repeatedly tested levels.
- Adjustment methodology affects historical prices.
- Pattern detection does not model execution, liquidity, or transaction costs.
- Parameter selection can introduce multiple-testing and selection bias.
- Opportunity scores are heuristic evidence rankings, not expected-return
  estimates and not guarantees of better held-out performance.
- Every strategy still requires deterministic backtesting and independent Risk
  review.
