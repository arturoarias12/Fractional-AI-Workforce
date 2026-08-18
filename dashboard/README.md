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

- A controlled PM Research Request form that builds a schema-valid
  `PMMandate`: objective, risk profile, horizon, as-of date, permitted universe,
  prohibited assets, leverage and short-selling constraints, risk limits, and
  optional PM notes. It also shows the exact top-level `WorkflowInput` handoff.
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

For the final integrated version, submitting the PM Research Request should call
the orchestration team's create-run/submit-mandate function with the displayed
`WorkflowInput`. That function validates the `PMMandate`, assigns active traders,
and exports an updated snapshot whenever the workflow reaches a meaningful state
transition. The dashboard deliberately does not call individual trader files.

The local `src/integration/WorkflowRunner` now provides that boundary for an
already compiled graph: `start_workflow(workflow_input)` and
`resume_workflow(run_id, pm_decision)`. The orchestration owner still needs to
construct the graph with the real agent nodes and a durable checkpointer.

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

## Scope

The interactive demo is intentionally a clickable prototype. Snapshot export is
the first integration seam; live agent execution, live event emission, persistent
storage and real ETF/backtest data remain team integration work.
