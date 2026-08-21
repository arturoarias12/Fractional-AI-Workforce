# Fractional AI Workforce Dashboard

A Streamlit dashboard for the team's ETF research workflow. It is a classroom
prototype: it displays research workflow state and does not execute trades.

## Quick start

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[full-demo]'
.venv/bin/pip install -r dashboard/requirements.txt
.venv/bin/streamlit run dashboard/app.py
```

Open the local URL shown by Streamlit.

To run the **local live pilot**, also place these team-provided files in the
repository root :

```text
ETF_historical_prices.xlsx
ETF_info.xlsx
```

Copy the repository root `.env.example` to `.env` and configure an OpenAI or
Anthropic API key to run the real Technical Trader. The same configuration is
used whether the workflow is launched from the terminal or the dashboard.

## What to use in the app

- **Current workflow** is the main path. Create a PM Research Request, keep
  **Run local live pilot** on, and choose **Start Research**. The dashboard
  starts the local workflow and then shows its exported result.
- **Interactive demo (click-through)** is only for rehearsing the interface
  with simulated data.

## What is connected now

The local pilot runs this workflow:

`PM mandate → Technical + Fundamental + Quant → Risk → Reporting → PM decision → Memory → (next round)`

- Fundamental, Quant, Risk, Reporting, and Memory use the team's current
  code. Technical Trader runs for real when credentials are configured (see
  Current limitations below), and falls back to a labeled stub otherwise so
  the rest of the workflow still runs end-to-end.
- The dashboard renders candidate rules, held-out backtest metrics, Risk
  review, and the PM-facing comparison without requiring an LLM for
  Fundamental/Quant/Risk/Reporting.
- The dashboard reads workflow state through a stable snapshot contract:
  `WorkflowState → workflow_adapter → workflow_snapshot.json → dashboard`.
- PM decisions pause and resume the real workflow (a durable interrupt, not
  a script), so a "Request Another Round" decision genuinely starts a new
  round rather than only advancing a UI counter.

## Current limitations

- Technical Trader runs for real when `TECHNICAL_TRADER_MODEL_PROVIDER`,
  `TECHNICAL_TRADER_MODEL`, and the matching API key are set (see
  `src/agents/technical_trader/docs/integration.md`); otherwise it falls back
  to a labeled stub so the workflow still runs end-to-end. The OpenAI path has
  completed credentialed Technical-only and full-workflow tests; Anthropic
  remains interchangeable through the same agent contract.
- PM decisions (Select / Reject / Request Another Round) pause and resume the
  real workflow through a durable interrupt - not scripted. Hire, Bench, and
  Pivot changes are carried into the next round's run.
- In the live pilot, as-of date, permitted ETF universe, prohibited assets,
  risk_profile, investment_horizon, rebalancing_preference, risk_limits, and
  leverage/short constraints all affect Fundamental and Quant Trader (see
  `src/mandate_directives.py` for exactly what each field does). Pivot
  excludes that agent's current candidate from its next proposal, scoped to
  the pivoted agent only. `market_context`, `pm_notes`, and
  `prior_round_lessons` affect research rules only via a keyword scan (e.g.
  "avoid/exclude TICKER") against the permitted universe - not full language
  understanding, since these traders are deterministic by design.
- The ETF workbooks are offline historical data. The current fixture ends on
  `2026-06-29`; it is for backtesting, not a live market recommendation.
- Task duration, success rate, API cost, retries, and failure counts are all
  computed from real operational events via `evaluation.harness` once a
  round has run. A benched agent shows no data for that round rather than a
  zero, since nothing was measured. Technical model adapters return token
  usage, but their per-call usage is not yet bridged into the shared event
  ledger and centrally priced, so API cost may remain unavailable.
- A mandate's `risk_limits.max_drawdown`, if set, is checked only against
  the single top-ranked candidate per trader - a candidate that breaches it
  is not proposed for Risk review, but a lower-ranked, compliant alternative
  is not automatically retried the same round.
- Memory and paused-round checkpoints persist to local files under
  `dashboard/data/` (`memory/`, `workflow_checkpoints.sqlite`) so they
  survive the live pilot's subprocess-per-round design. This is local,
  single-machine state, not a shared or hosted store.
