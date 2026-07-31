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

## Evidence enforcement

The tool report supplies:

- `report_id`
- `level_id` for every support/resistance level
- `pattern_id` for every observed chart structure

The LLM must return its cited IDs in `specialty_evidence_ids` and map every ID
to its exact rule role in `specialty_evidence_usage`. Code rejects:

- IDs absent from the report; and
- candidates that cite no non-fallback support/resistance level on the correct
  side of the latest close; and
- missing or extra evidence-usage mappings.

## Limitations

- Pivot and pattern definitions are configurable heuristics.
- When pattern output is capped, the most recent observations are retained.
- Different frequencies can produce different structures.
- Range fallbacks are not equivalent to repeatedly tested levels.
- Adjustment methodology affects historical prices.
- Pattern detection does not model execution, liquidity, or transaction costs.
- Parameter selection can introduce multiple-testing and selection bias.
- Every strategy still requires deterministic backtesting and independent Risk
  review.
