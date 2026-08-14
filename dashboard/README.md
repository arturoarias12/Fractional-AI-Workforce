# Fractional AI Workforce — Clickable Mockup

This is a Streamlit dashboard for the Fractional AI Workforce project. It has two
safe modes: an interactive simulated demo, and a read-only WorkflowState snapshot.
It does not execute trades or invoke agents from the UI.

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

## Workflow snapshot integration

The LangGraph workflow is the source of truth. The dashboard reads one exported
JSON file rather than calling five agents independently:

`WorkflowState → dashboard/workflow_adapter.py → dashboard/data/workflow_snapshot.json → Streamlit`

The included `data/sample_workflow_state.json` and `data/workflow_snapshot.json`
show the expected handoff using the currently available workflow fields. In the
app sidebar, choose **Workflow snapshot** to view it. This mode is deliberately
read-only: PM decisions and staffing controls stay in the workflow, then appear
in the dashboard after a new export.

To export a graph result that has already been saved as JSON:

```bash
cd dashboard
python3 export_snapshot.py data/sample_workflow_state.json
```

This overwrites `data/workflow_snapshot.json` with the dashboard-safe version.
When the orchestration team has a final `WorkflowState`, they can save that state
as JSON and run the same command with its path.

The adapter preserves every required productivity-metric field. Until the
workflow emits `operational_events`, event-derived values (success rate, API
cost, retries, and failures) intentionally show `N/A` instead of invented data.

## Suggested Friday demo

1. Start Research to show the parallel workflow.
2. Choose **Advance Demo to Completed Review** to move directly to the review state.
3. Open **Quant Trader** and show its complete schema fields, metrics, and Risk outcome. Optionally choose **Bench** or **Pivot** for the next round.
4. Return to the dashboard and open the Research Report.
5. Choose **Request Another Round**. Confirm that the dashboard advances from Round 04 to Round 05 and that Memory records the previous lesson.

## Scope

The interactive demo is intentionally a clickable prototype. Snapshot export is
the first integration seam; live agent execution, live event emission, persistent
storage and real ETF/backtest data remain team integration work.
