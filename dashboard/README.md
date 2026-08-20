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

`PM mandate → parallel traders → Risk → Reporting → PM decision → Memory / next round`

- Fundamental, Quant, Risk, and Reporting use the team's current code.
- The dashboard renders candidate rules, held-out backtest metrics, Risk review,
  a PM-facing comparison, and a human PM decision.
- While a PM decision is pending, the trader detail pages provide next-round
  Hire, Bench, and Pivot controls. A Pivot excludes the trader's current
  candidate ticker and records its reason in the next-round mandate.
- The live form's horizon, risk profile, rebalancing preference, risk limits,
  constraints, and ticker-exclusion notes are translated into documented
  Fundamental/Quant directives; the applied directives are visible on the
  Dashboard.
- The dashboard reads workflow state through a stable snapshot contract:
  `WorkflowState → workflow_adapter → workflow_snapshot.json → dashboard`.

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

- Technical Trader requires a separately configured OpenAI or Anthropic model
  provider and API key; otherwise it settles as a clearly labelled failed
  package while the remaining workflow continues.
- Reporting's optional Gemini narrative memo also requires its own environment
  key. It is not generated merely because the model-client code is present.
- The ETF workbooks are offline historical data. The current fixture ends on
  `2026-06-29`; it is for backtesting, not a live market recommendation.
- Success rate measures workflow execution reliability, not investment return.
  A fresh one-attempt workflow will naturally show 100% for agents that
  completed successfully. Cost is `N/A` when the underlying provider does not
  report a monetary amount.
