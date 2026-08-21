# Fractional AI Workforce Dashboard

A Streamlit dashboard for the team's ETF research workflow. It is a classroom
prototype: it displays research workflow state and does not execute trades.

## Quick start

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[langgraph,fundamental-demo,quant-demo]'
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
- While a PM decision is pending, the trader detail pages provide next-round
  Hire, Bench, and Pivot controls. A Pivot excludes the trader's current
  candidate ticker and records its reason in the next-round mandate. One
  staffing choice is applied per trader per PM review; it can be changed
  before the PM submits the decision.
- When the PM requests another round, the workflow reloads its durable
  Memory, returns the user to the Dashboard, and applies the selected
  staffing and Pivot directives to the new round. The pilot is limited to
  three research rounds, matching the Risk validation-touch budget.
- The live form's horizon, risk profile, rebalancing preference, risk
  limits, constraints, and ticker-exclusion notes are translated into
  documented Fundamental/Quant directives; the applied directives are
  visible on the Dashboard.
- The dashboard reads workflow state through a stable snapshot contract:
  `WorkflowState → workflow_adapter → workflow_snapshot.json → dashboard`.
- PM decisions pause and resume the real workflow (a durable interrupt, not
  a script), so a "Request Another Round" decision genuinely starts a new
  round rather than only advancing a UI counter.

### Optional Reporting memo

The Reporting Agent always produces a structured candidate comparison. To
also generate an LLM-written narrative memo, install the optional provider
dependency and set a Gemini key in the environment that runs the workflow:

```bash
.venv/bin/pip install -e '.[reporting-models]'
export GEMINI_API_KEY='your-key-here'
```

Do not commit or share API keys. Without this configuration, the Dashboard
shows the structured comparison and clearly labels the missing narrative memo.

## Current limitations

- Technical Trader runs for real when `TECHNICAL_TRADER_MODEL_PROVIDER`,
  `TECHNICAL_TRADER_MODEL`, and the matching API key are set (see
  `agents/technical_trader/docs/integration.md`); otherwise it settles as a
  clearly labelled failed package while the remaining workflow continues. A
  live smoke test with real credentials is still needed to confirm the
  actual model call works, not just the wiring around it.
- Reporting's optional Gemini narrative memo also requires its own
  environment key (`GEMINI_API_KEY`). It is not generated merely because
  the model-client code is present; without it, the Dashboard shows the
  structured comparison and clearly labels the missing narrative memo.
- PM decisions (Select / Reject / Request Another Round) pause and resume
  the real workflow through a durable interrupt - not scripted. Hire,
  Bench, and Pivot changes are carried into the next round's run.
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
  round has run. Success rate measures workflow execution reliability, not
  investment return - a fresh one-attempt workflow will naturally show 100%
  for agents that completed successfully. A benched agent shows no data for
  that round rather than a zero, since nothing was measured. Cost is `N/A`
  when the underlying provider does not report a monetary amount.
- A mandate's `risk_limits.max_drawdown`, if set, is checked only against
  the single top-ranked candidate per trader - a candidate that breaches it
  is not proposed for Risk review, but a lower-ranked, compliant alternative
  is not automatically retried the same round.
- Memory and paused-round checkpoints persist to local files under
  `dashboard/data/` (`memory/`, `workflow_checkpoints.sqlite`) so they
  survive the live pilot's subprocess-per-round design. This is local,
  single-machine state, not a shared or hosted store.