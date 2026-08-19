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

`PM mandate → Fundamental + Quant → Risk → Reporting → dashboard snapshot`

- Fundamental, Quant, Risk, and Reporting use the team's current code.
- The dashboard renders candidate rules, held-out backtest metrics, Risk review,
  and the PM-facing comparison without requiring an LLM.
- The dashboard reads workflow state through a stable snapshot contract:
  `WorkflowState → workflow_adapter → workflow_snapshot.json → dashboard`.

## Current limitations

- Technical Trader is shown as unavailable because the repository does not yet
  provide a concrete `ModelClient`.
- The final PM decision is scripted as `Reject` in this one-round pilot.
  Select / Reject / Another Round are not yet connected to workflow resume.
- In the live pilot, as-of date, permitted ETF universe, and prohibited assets
  affect Fundamental and Quant. Other PM mandate fields are preserved but do
  not yet change their fixed research rules.
- The ETF workbooks are offline historical data. The current fixture ends on
  `2026-06-29`; it is for backtesting, not a live market recommendation.
- Task duration is available from lifecycle state. Success rate, API cost,
  retries, and failure counts show `N/A` until the workflow emits operational
  event records.
- Hire, Bench, and Pivot are simulated interactions only; they do not yet
  change the next live workflow run.
