# Fractional AI Workforce — Clickable Mockup

This is a Streamlit clickable mockup for a professor review of the Fractional AI Workforce project.
It uses simulated data only. It does not execute trades, call an AI model, or connect to the team backend.

The mockup follows the team workflow:

Human PM mandate → parallel Technical, Fundamental and Quant research → Risk Review → Reporting memo → PM decision → Memory for a future round.

## Run locally

### First-time setup (macOS / Linux)

```bash
cd fractional-ai-dashboard
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

### First-time setup (Windows PowerShell)

```powershell
cd fractional-ai-dashboard
py -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\streamlit run app.py
```

After the first-time setup, the final command in the matching section is all that is needed to start the app again.

## What the prototype demonstrates

- Current lifecycle state, task, input, output, timing, next step and error field for each agent.
- The complete per-agent productivity metrics defined in the schema: task completion time, success rate, API cost, retry count and failed count.
- A summary of the current research round on the dashboard.
- A human PM decision and a Memory record that carries lessons into a later simulated round.
- Simple next-round staffing controls after review. `Hire` restores a benched agent, `Bench` removes an active agent from the next round, and `Pivot` records a new next-round research focus. These controls do not modify a running or completed round.

## Suggested Friday demo

1. Start Research to show the parallel workflow.
2. Choose **Advance Demo to Completed Review** to move directly to the review state.
3. Open **Quant Trader** and show its complete schema fields, metrics, and Risk outcome. Optionally choose **Bench** or **Pivot** for the next round.
4. Return to the dashboard and open the Research Report.
5. Choose **Request Another Round**. Confirm that the dashboard advances from Round 04 to Round 05 and that Memory records the previous lesson.

## Scope

This is intentionally a clickable UI prototype. Live agent execution, live metrics, backend integration, persistent storage and real ETF/backtest data are later integration work.
