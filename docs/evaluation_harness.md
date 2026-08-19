# Evaluation Harness & Operational Events

Workstream #5. Turns a finished research run into per-agent productivity
metrics, so the hire/fire/pivot controls are attached to something measured.

## Why this existed as a gap

`WorkflowState.operational_events` and its `append_events` reducer were in the
repo from early on, and `dashboard/workflow_adapter.py` already read the
channel. Nothing ever wrote to it. The result was a productivity panel whose
numbers were either `N/A` or hard-coded illustrative values — a panel that
looked like measurement and was not.

Two things were needed: emission (write the ledger) and grading (read it).

## Emission — `src/observability/`

The graph's node wrappers in `graph/production.py` already knew everything an
event needs: which agent ran, at which stage, when it started and ended, and
whether it settled or failed. They wrote that into `agent_lifecycle` and threw
the rest away. Emission attaches an `operational_events` entry alongside, at
each wrapper's exit path:

| Site | Event |
|---|---|
| trader settled | `task_completed` / `task_failed` |
| trader benched | `agent_benched` |
| Risk settled / failed / benched | `task_completed` / `task_failed` / `agent_benched` |
| Reporting settled / failed / benched | `task_completed` / `task_failed` / `agent_benched` |
| PM decision recorded | `pm_decision_recorded` |
| model call *(contract only — see below)* | `model_call_completed` |

**Emission cannot be done by wrapping injected nodes.** Each wrapper in
`production.py` builds a fresh return dict and keeps only the specific key it
expects from the inner node, so any `operational_events` an injected node
returned would be silently dropped. That is why these edits are inside
`production.py` rather than in a decorator around `ProductionNodeSet`.

One terminal event is emitted per node run rather than a `task_started` /
`task_completed` pair: the wrappers execute a node atomically, so a separate
start record would describe a moment nothing could observe. Both timestamps
ride on the single event, which is what latency needs.

## Grading — `src/evaluation/`

```bash
.venv/bin/python scripts/run_evaluation_harness.py
.venv/bin/python scripts/run_evaluation_harness.py --success-metric risk_approval --json
```

The harness reads only the event ledger, never an agent's self-report, so an
agent cannot influence its own score.

```python
from evaluation import grade_workflow_state, SuccessMetric

report = grade_workflow_state(final_state)
report.summary_metrics()      # round/agent counts, total time, total cost
report.dashboard_metrics()    # per-agent, shaped for the dashboard panel
```

## The rule: measured or `N/A`, never defaulted

No metric is defaulted to zero. An agent that made no model calls has an
**unknown** cost, not a cost of nothing, and the difference matters when the
number sits under a fire button. Concretely:

- `api_cost` reads `N/A` for every agent today, because no concrete
  `ModelClient` exists in the repo yet. `model_call_event()` is defined and
  tested so that wiring a real client later is a call site, not a schema
  change.
- A benched agent has no success rate — not 0%.
- A trader that **crashed** has no risk-approval rate. Its failed package still
  carries a `candidate_id`, but Risk never reviewed it, so counting it as a
  rejected proposal would score a crash as a research-quality failure and
  penalise the agent twice for one incident. The harness gates candidate
  counting on `eligible_for_risk_review`.

## Open ruling: what "Success %" means

The workplan asks for a success rate per agent. The term has two defensible
readings, and they lead to different products:

**`execution`** — share of tasks that finished without erroring. Literal,
cheap, un-gameable. Nearly useless for firing: a trader that reliably produces
worthless strategies scores 100%.

**`risk_approval`** — share of a trader's proposals that survived Risk review.
Genuinely informative about research quality. It also makes the skeptic the
scorekeeper for everyone it judges: once a trader is measured on its approval
rate, the way to score well is to propose things Risk waves through. That is
Goodhart's law landing on the exact mechanism this project is built around.

**This is a team ruling and it is still open.** The harness therefore computes
**both, always**, and reports them under separate names. `SuccessMetric`
selects only which one fills the single `success_rate` slot the dashboard
renders; `execution_success_rate` and `risk_approval_rate` both stay visible in
every report regardless, so no view can silently imply the question has been
settled.

Default is `execution` — because it is the claim the data supports without
argument, not because it is the right answer.

## Dashboard integration (not yet wired)

`dashboard/workflow_adapter.py::_metrics_for_agent` currently hard-codes
`"success_rate": "N/A"` and `_summary_metrics` hard-codes
`"research_completion_time": "N/A"`. Both can now be filled from
`grade_workflow_state(state)`, whose `dashboard_metrics()` output is already in
the shape that function returns. That change belongs to whoever owns the
dashboard; it is deliberately not made here.

## Tests

`tests/evaluation/test_harness.py` — 14 tests covering measured latency, both
success readings, the crash-vs-rejection distinction, exact `Decimal` cost
accumulation, retry counting, multi-round accumulation, and malformed input.

Verified end-to-end against real runs: `run_full_research_loop_demo.py` emits 5
events in one round; `run_multi_round_memory_demo.py` emits 10 across two
rounds with per-agent tallies accumulating correctly.
