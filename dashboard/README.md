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

`PM mandate → Technical + Fundamental + Quant → Risk → Reporting → PM → Memory`

- Technical uses the selected model provider plus deterministic analysis and
  backtesting. Without provider configuration, its branch is clearly labeled
  as stubbed and is not eligible for Risk review.
- Fundamental, Quant, Risk, and Reporting use the project's current runtime
  implementations.
- The dashboard renders candidate rules, held-out backtest metrics, Risk review,
  and the PM-facing comparison without requiring an LLM.
- The dashboard reads workflow state through a stable snapshot contract:
  `WorkflowState → workflow_adapter → workflow_snapshot.json → dashboard`.
- The final PM decision is a durable LangGraph interrupt. A run can be resumed
  after the decision without losing its checkpoint or Memory record.

## Current limitations

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
