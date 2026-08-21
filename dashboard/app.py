"""Clickable Streamlit dashboard for the Fractional AI Workforce project.

Interactive demo mode uses simulated data.  The local live-pilot mode sends a
controlled PM mandate to the team's offline research-loop integration script.
"""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
from uuid import uuid4

import streamlit as st

from workflow_adapter import load_dashboard_snapshot


st.set_page_config(
    page_title="Fractional AI Workforce",
    page_icon="◈",
    layout="wide",
)

st.markdown(
    """
    <style>
      .block-container {max-width: 1400px; padding-top: 1.5rem;}
      .status {border-radius: 999px; padding: .22rem .62rem; font-size: .82rem;
               font-weight: 650; display: inline-block;}
      .idle, .assigned {background:#e5e7eb; color:#374151;}
      .running {background:#dbeafe; color:#1d4ed8;}
      .waiting {background:#fef3c7; color:#92400e;}
      .completed {background:#dcfce7; color:#166534;}
      .failed, .vetoed {background:#fee2e2; color:#b91c1c;}
      .workflow-box {border: 1px solid #dbe3ef; border-radius: 12px; padding: .7rem;
                     text-align: center; min-height: 76px; background:#fff;}
      .small-label {font-size:.76rem; color:#64748b; text-transform:uppercase;
                    letter-spacing:.04em;}
      .agent-name {font-size:1.1rem; font-weight:700;}
      .demo-note {background:#eff6ff; color:#1e3a8a; border:1px solid #bfdbfe;
                  border-radius:10px; padding:.7rem 1rem; margin-bottom:1rem;}
      .parallel-label {font-size:.78rem; color:#64748b; text-align:center;
                       margin-bottom:.35rem; font-weight:650;}
      .workflow-middle-spacer {height:112px;}
    </style>
    """,
    unsafe_allow_html=True,
)


RISK_OPTIONS = ["Conservative", "Moderate", "Growth"]
OBJECTIVE_OPTIONS = [
    "Evaluate diversified ETF strategies for risk-adjusted return.",
    "Compare technical and quantitative ETF strategy candidates.",
    "Identify a moderate-risk ETF strategy with broad diversification.",
]
UNIVERSE_OPTIONS = {
    "All available offline ETF data (120 ETFs)": [],
    "Core liquid ETF pilot": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT"],
    "Sector ETF pilot": ["XLK", "XLF", "XLV", "XLE", "XLY", "XLP"],
}

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_INPUT_PATH = REPO_ROOT / "dashboard" / "data" / "latest_pm_mandate.json"
LIVE_DECISION_PATH = REPO_ROOT / "dashboard" / "data" / "latest_pm_decision.json"
LIVE_RUNNER_PATH = REPO_ROOT / "scripts" / "run_full_research_loop_demo.py"
LIVE_LOG_PATH = REPO_ROOT / "dashboard" / "data" / "live_workflow.log"
# Updated together with the offline workbook. This keeps the PM date truthful:
# the current fixture's last observed trading date is 2026-06-29.
OFFLINE_DATA_MAX_DATE = date(2026, 6, 29)

# Maps this dashboard's short staffing keys (make_agents' dict keys) to the
# SpecialistId strings the backend graph's active_specialists check expects
# (graph.production._agent_is_active). Kept here rather than imported so this
# file has no import-time dependency on the src/ package layout.
STAFFING_KEY_TO_SPECIALIST_ID = {
    "technical": "technical_trader_agent",
    "fundamental": "fundamental_trader_agent",
    "quant": "quant_trader_agent",
    "risk": "risk_agent",
    "reporting": "reporting_agent",
}


def _active_specialists_from_staffing() -> list[str]:
    """Translate the PM's current Hire/Bench choices into backend agent ids."""
    return [
        STAFFING_KEY_TO_SPECIALIST_ID[key]
        for key, status in st.session_state.staffing.items()
        if status == "Active" and key in STAFFING_KEY_TO_SPECIALIST_ID
    ]


def launch_live_research(mandate: dict[str, Any]) -> subprocess.Popen[str]:
    """Start the offline integration pilot without blocking the dashboard.

    The dashboard can be refreshed while the runner publishes checkpoints. A
    deployed product would replace this local child process with a durable job
    service, but the separation keeps this prototype visibly interactive.
    """

    LIVE_INPUT_PATH.write_text(
        json.dumps(
            {
                "pm_mandate": mandate,
                "active_specialists": _active_specialists_from_staffing(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    python = str(venv_python if venv_python.exists() else Path(sys.executable))
    with LIVE_LOG_PATH.open("w", encoding="utf-8") as log_file:
        return subprocess.Popen(
            [python, str(LIVE_RUNNER_PATH), "--mandate-json", str(LIVE_INPUT_PATH)],
            cwd=REPO_ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )


def launch_live_resume(
    run_id: str, pm_decision: dict[str, Any]
) -> subprocess.Popen[str]:
    """Resume a paused live round with a real PM decision.

    Bundles the PM's current Hire/Bench/Pivot selections as a
    ``state_update`` so a "Request Another Round" decision also carries
    forward whatever staffing change the PM just made - the two actions
    (decide, and update staffing for next round) happen together, matching
    the staffing dialog's own caption ("apply to the next round").

    Pivot gets a real effect the same way: any pending pivot lessons
    (tagged "PIVOT[<agent_id>]: ..." in staffing_dialog) are merged into
    the current mandate's prior_round_lessons and sent as part of the same
    state_update, so mandate_directives.py's parser picks them up on the
    next round - see src/mandate_directives.py.
    """

    state_update: dict[str, Any] = {
        "active_specialists": _active_specialists_from_staffing()
    }
    if st.session_state.pending_pivot_lessons:
        current_mandate = dict(st.session_state.pm_mandate or {})
        existing_lessons = list(current_mandate.get("prior_round_lessons") or [])
        current_mandate["prior_round_lessons"] = (
            existing_lessons + list(st.session_state.pending_pivot_lessons)
        )
        state_update["pm_mandate"] = current_mandate
        st.session_state.pm_mandate = current_mandate
        st.session_state.pending_pivot_lessons = []

    LIVE_DECISION_PATH.write_text(
        json.dumps(
            {
                "pm_decision": pm_decision,
                "state_update": state_update,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    python = str(venv_python if venv_python.exists() else Path(sys.executable))
    with LIVE_LOG_PATH.open("w", encoding="utf-8") as log_file:
        return subprocess.Popen(
            [
                python, str(LIVE_RUNNER_PATH),
                "--resume", "--run-id", run_id,
                "--decision-json", str(LIVE_DECISION_PATH),
            ],
            cwd=REPO_ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )


def poll_live_research() -> tuple[str | None, str | None]:
    """Return the current local-run state and promote a finished snapshot.

    Exit code 0 alone is not enough to mean "fully completed": the backend
    script also exits 0 when it pauses at a real PM-decision interrupt
    (see run_full_research_loop_demo.py). The exported snapshot's
    workflow.status is what actually distinguishes the two.
    """

    process = st.session_state.get("live_process")
    if process is None:
        return None, None
    return_code = process.poll()
    if return_code is None:
        return "running", None

    st.session_state.live_process = None
    if return_code == 0:
        st.session_state.live_snapshot_ready = True
        try:
            status = load_dashboard_snapshot().get("workflow", {}).get("status")
        except (OSError, ValueError):
            status = None
        if status == "Waiting for PM Decision":
            st.session_state.phase = "awaiting_decision"
            return "awaiting_decision", "Round complete. Awaiting a PM decision to continue."
        st.session_state.phase = "completed"
        return "completed", "Live research completed. The dashboard now shows its exported workflow snapshot."

    log_lines = LIVE_LOG_PATH.read_text(encoding="utf-8").strip().splitlines()
    detail = log_lines[-1] if log_lines else "The live workflow ended without an error message."
    st.session_state.phase = "idle"
    return "failed", detail


def make_agents(phase: str, staffing: dict[str, str] | None = None) -> dict[str, dict]:
    """Return predictable simulated data for the professor demo."""
    trader_states = {
        "idle": ("Idle", "Waiting for a research task"),
        "running": ("Running", "Analyze market evidence and draft a rule"),
        "completed": ("Completed", "Strategy package submitted to Risk Review"),
    }
    state, task = trader_states[phase]
    risk_state, risk_task = {
        "idle": ("Idle", "Waiting for trader results"),
        "running": ("Waiting for Review", "Waiting for all three trader packages"),
        "completed": ("Completed", "Review trader strategies for overfitting"),
    }[phase]
    report_state, report_task = {
        "idle": ("Idle", "Waiting for Risk approval"),
        "running": ("Assigned", "Waiting for approved research packages"),
        "completed": ("Completed", "Create PM-facing research memo"),
    }[phase]

    agents = {
        "technical": {
            "name": "Technical Trader", "role": "Price action, volume and indicators",
            "state": state, "task": task,
            "input": "PM mandate + point-in-time price and volume data",
            "output": "Momentum rule; backtest summary: 7.4% simulated return",
            "start": "10:02", "end": "10:05" if phase == "completed" else "—",
            "next": "Risk Review" if phase == "completed" else "Backtest Engine",
            "error": "None", "completion_time": "3m 06s", "success_rate": "92%",
            "api_cost": "$0.24", "retry_count": 0, "failed_count": 0,
            "risk_feedback": "Approved — result is stable on held-out data.",
        },
        "fundamental": {
            "name": "Fundamental Trader", "role": "ETF fund characteristics and exposure",
            "state": state, "task": task,
            "input": "PM mandate + ETF metadata and fund characteristics",
            "output": "Low-cost quality ETF screen; backtest summary: 6.8% simulated return",
            "start": "10:02", "end": "10:06" if phase == "completed" else "—",
            "next": "Risk Review" if phase == "completed" else "Data Service",
            "error": "None", "completion_time": "3m 44s", "success_rate": "86%",
            "api_cost": "$0.27", "retry_count": 1, "failed_count": 1,
            "risk_feedback": "Approved — assumptions are documented.",
        },
        "quant": {
            "name": "Quant Trader", "role": "Statistical anomalies and correlations",
            "state": state, "task": task,
            "input": "PM mandate + historical prices + correlation output",
            "output": "Pair-trading rule; backtest summary: 8.1% simulated return",
            "start": "10:02", "end": "10:07" if phase == "completed" else "—",
            "next": "Risk Review" if phase == "completed" else "Backtest Engine",
            "error": "None", "completion_time": "5m 11s", "success_rate": "68%",
            "api_cost": "$0.31", "retry_count": 3, "failed_count": 2,
            "risk_feedback": "Vetoed — possible overfitting; validate out-of-sample.",
        },
        "risk": {
            "name": "Risk / Skeptic", "role": "Overfitting and cherry-picking review",
            "state": risk_state, "task": risk_task,
            "input": "All settled trader packages, including failures",
            "output": "Approved: Technical, Fundamental. Vetoed: Quant.",
            "start": "10:07" if phase == "completed" else "—", "end": "10:09" if phase == "completed" else "—",
            "next": "Reporting" if phase == "completed" else "Wait for all trader branches",
            "error": "None", "completion_time": "2m 03s", "success_rate": "96%",
            "api_cost": "$0.19", "retry_count": 0, "failed_count": 0,
            "risk_feedback": "Signature review stage: detects selection bias across traders.",
        },
        "reporting": {
            "name": "Reporting", "role": "PM-facing research memo",
            "state": report_state, "task": report_task,
            "input": "Only Risk-approved strategies and critiques",
            "output": "Research memo comparing the approved Technical and Fundamental results.",
            "start": "10:09" if phase == "completed" else "—", "end": "10:10" if phase == "completed" else "—",
            "next": "Human PM Decision" if phase == "completed" else "Risk approval",
            "error": "None", "completion_time": "1m 18s", "success_rate": "98%",
            "api_cost": "$0.12", "retry_count": 0, "failed_count": 0,
            "risk_feedback": "Receives approved packages only; it never combines strategies.",
        },
    }
    # A staffing choice affects the next simulated research round, not the
    # completed one in which the decision was made.
    if phase == "running" and staffing:
        for agent_id in ("technical", "fundamental", "quant"):
            if staffing.get(agent_id) == "Benched":
                agents[agent_id].update({
                    "state": "Idle",
                    "task": "Benched for this research round",
                    "input": "No work assigned in this round",
                    "output": "No strategy package submitted",
                    "start": "—",
                    "end": "—",
                    "next": "Hire or pivot before a future round",
                })
    return agents


def init_state() -> None:
    defaults = {
        "view": "dashboard", "selected_agent": "technical", "phase": "idle",
        "round_number": 4, "pm_decision": None,
        "pm_mandate": None,
        "staffing": {key: "Active" for key in ["technical", "fundamental", "quant", "risk", "reporting"]},
        "memory": [
            "Round 03 — Quant strategy required stronger out-of-sample validation.",
            "Round 03 — Technical Trader had the highest completed-task success rate (92%).",
        ],
        "notice": "", "data_source": "Current workflow", "run_live_pilot": True,
        "live_snapshot_ready": False, "live_process": None,
        "pending_pivot_lessons": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def status_class(state: str) -> str:
    return {
        "Idle": "idle", "Assigned": "assigned", "Running": "running",
        "Waiting for Tool": "waiting", "Waiting for Review": "waiting",
        "Completed": "completed", "Failed": "failed",
    }.get(state, "idle")


def status_badge(state: str) -> str:
    return f'<span class="status {status_class(state)}">{state}</span>'


def snapshot_data() -> dict[str, Any] | None:
    """Return the latest graph snapshot for the main PM workspace."""

    if st.session_state.data_source == "Interactive demo":
        return None
    # A newly authored mandate is intentionally shown before it is sent to the
    # workflow, rather than being visually mixed with the prior run's result.
    if st.session_state.pm_mandate and not st.session_state.live_snapshot_ready:
        return None
    try:
        return load_dashboard_snapshot()
    except (OSError, ValueError) as error:
        st.warning(f"Could not load workflow snapshot: {error}")
        return None


def current_agents(snapshot: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return snapshot["agents"] if snapshot else make_agents(st.session_state.phase, st.session_state.staffing)


def agent_value(agent: dict[str, Any], name: str) -> Any:
    """Read one field from either legacy demo data or the snapshot contract."""

    legacy_names = {
        "start_time": "start", "end_time": "end", "next_step": "next",
        "error_message": "error", "task_completion_time": "completion_time",
    }
    if name in {"task_completion_time", "success_rate", "api_cost", "retry_count", "failed_count"}:
        return agent.get("metrics", {}).get(name, agent.get(legacy_names.get(name, name), "N/A"))
    return agent.get(name, agent.get(legacy_names.get(name, name), "N/A"))


def metrics_disclaimer(snapshot: dict[str, Any] | None) -> str:
    """State where the productivity numbers on screen actually came from.

    The two modes render through the same widgets, so without this the
    illustrative demo figures are indistinguishable from measurements.
    """

    if snapshot:
        return (
            "Measured from this run's exported state. Success rate, API cost and "
            "retry counts stay N/A until the workflow emits operational events."
        )
    return (
        ":red[Simulated demo data.] These productivity figures are illustrative "
        "placeholders for interface rehearsal — nothing here was measured."
    )


def display_value(value: Any) -> None:
    if isinstance(value, (dict, list)):
        st.json(value)
    else:
        st.write(value if value not in (None, "") else "N/A")


def format_percent(value: Any) -> str:
    return f"{value:.1%}" if isinstance(value, (int, float)) else "N/A"


def format_decimal(value: Any) -> str:
    return f"{value:.2f}" if isinstance(value, (int, float)) else "N/A"


def package_for(agent: dict[str, Any]) -> dict[str, Any]:
    """Read the detailed strategy package, when this agent produced one."""

    package = agent.get("package", {})
    return package if isinstance(package, dict) else {}


def risk_decision_for(snapshot: dict[str, Any], candidate_id: Any) -> dict[str, Any]:
    decisions = snapshot.get("risk_review", {}).get("decisions", [])
    return next(
        (item for item in decisions if item.get("candidate_id") == candidate_id),
        {},
    )


def render_backtest_metrics(package: dict[str, Any]) -> None:
    """Show the same backtest fields in a readable, non-LLM template."""

    result = package.get("backtest_result") or {}
    training = result.get("metrics") or {}
    held_out = result.get("out_of_sample_metrics") or {}
    if not training and not held_out:
        st.info("No completed backtest was exported for this agent.")
        return

    st.caption("Held-out results are more useful than training results for checking whether a rule generalizes.")
    labels = [
        ("Total Return", "total_return", format_percent),
        ("Sharpe Ratio", "sharpe_ratio", format_decimal),
        ("Maximum Drawdown", "max_drawdown", format_percent),
        ("Trades", "transaction_count", lambda value: str(value) if value is not None else "N/A"),
    ]
    columns = st.columns(len(labels))
    for column, (label, key, formatter) in zip(columns, labels):
        column.metric(label, formatter(held_out.get(key)), help=f"Training: {formatter(training.get(key))}")

    with st.expander("Compare training and held-out backtest metrics"):
        rows = []
        for label, key, formatter in labels:
            rows.append({
                "Metric": label,
                "Training window": formatter(training.get(key)),
                "Held-out window": formatter(held_out.get(key)),
            })
        st.dataframe(rows, hide_index=True, use_container_width=True)


def render_strategy_summary(agent: dict[str, Any], snapshot: dict[str, Any]) -> None:
    """Render an agent strategy package without exposing raw JSON by default."""

    package = package_for(agent)
    candidate = package.get("candidate_rule") or {}
    if not candidate:
        failure = (package.get("failures") or [{}])[0].get("message")
        st.warning(failure or "This agent did not submit a strategy package.")
        return

    st.subheader("Candidate Strategy")
    st.markdown(f"**{candidate.get('strategy_name', 'Unnamed strategy')}**")
    st.write(candidate.get("hypothesis") or "No hypothesis was exported.")
    st.markdown("**Rule in plain language**")
    st.write(candidate.get("rule_summary") or "No rule summary was exported.")
    render_backtest_metrics(package)

    decision = risk_decision_for(snapshot, candidate.get("candidate_id"))
    if decision:
        verdict = str(decision.get("verdict", "pending")).title()
        if verdict == "Approve":
            st.success(f"Risk verdict: {verdict}. This means the candidate may proceed to PM review; it is not an investment recommendation.")
        else:
            st.warning(f"Risk verdict: {verdict}.")
        flags = list(dict.fromkeys(decision.get("reporting_flags") or []))
        if flags:
            st.markdown("**Items for PM review**")
            for flag in flags:
                st.write(f"• {flag}")

    with st.expander("Strategy assumptions and limitations"):
        for label, value in [
            ("Entry", candidate.get("entry_logic")),
            ("Exit", candidate.get("exit_logic")),
            ("Position", candidate.get("position_logic")),
        ]:
            if value:
                st.markdown(f"**{label}:** {value}")
        interpretation = package.get("interpretation") or {}
        for limitation in interpretation.get("limitations") or []:
            st.write(f"• {limitation}")


def workflow_input_for_demo() -> dict[str, Any] | None:
    """Create the exact top-level input shape expected by the graph."""

    mandate = st.session_state.pm_mandate
    if not mandate:
        return None
    return {
        "pm_mandate": mandate,
        "active_specialists": [
            "technical_trader_agent",
            "fundamental_trader_agent",
            "quant_trader_agent",
            "risk_agent",
            "reporting_agent",
        ],
        "run_id": mandate["workflow_id"],
        "canonical_universe_id": None,
        "evaluation_policy_id": None,
    }


@st.dialog("Create PM Research Request")
def pm_request_dialog() -> None:
    """Collect a controlled, graph-valid PMMandate payload."""

    st.caption("The form creates a schema-valid PM mandate. In live-pilot mode, it becomes the input for the research workflow.")
    st.info(
        "Current live-pilot behavior: as-of date, permitted ETF universe, and prohibited assets affect the available research data. "
        "Objective, risk profile, horizon, leverage, short-selling, risk limits, and notes are preserved in the mandate and snapshot, "
        "but the current Fundamental/Quant implementations do not yet use them to change their fixed research rules."
    )
    st.caption(
        f"Offline historical-data pilot: this fixture ends on {OFFLINE_DATA_MAX_DATE.isoformat()}. "
        "It supports historical backtesting, not a live market recommendation."
    )
    with st.form("pm-research-request"):
        objective = st.selectbox(
            "Investment objective *",
            OBJECTIVE_OPTIONS,
            help="Controlled options keep the request reliable for all research agents.",
        )
        risk = st.selectbox(
            "Risk profile *", RISK_OPTIONS, index=1,
        )
        horizon = st.selectbox(
            "Investment horizon *", ["1 month", "3 months", "6 months"], index=1,
        )
        as_of_date = st.date_input(
            "As-of date *",
            value=OFFLINE_DATA_MAX_DATE,
            max_value=OFFLINE_DATA_MAX_DATE,
            help="The local workbook has no observations after this date.",
        )
        universe_name = st.selectbox(
            "Permitted asset universe *", list(UNIVERSE_OPTIONS),
            help="The full-universe option lets the real offline agents search the supplied 120-ETF data. Smaller lists are useful only for constrained pilot tests.",
        )
        prohibited = st.multiselect(
            "Prohibited assets (optional)", ["Leveraged ETFs", "Inverse ETFs", "Crypto-linked ETFs"],
        )
        leverage = st.selectbox(
            "Leverage constraint *", ["No leverage", "Maximum 1.25x gross exposure"],
        )
        short_selling = st.selectbox(
            "Short-selling constraint *", ["Long only", "Short selling not permitted in this pilot"],
        )
        notes = st.text_area(
            "PM notes (optional)",
            placeholder="Optional context for the research team; avoid putting new rules here.",
        )
        submitted = st.form_submit_button("Create Mandate", type="primary", use_container_width=True)

    if submitted:
        workflow_id = f"dashboard-demo-{uuid4().hex[:8]}"
        st.session_state.pm_mandate = {
            "workflow_id": workflow_id,
            "task_id": f"pm-mandate-round-{st.session_state.round_number}",
            "as_of_date": as_of_date.isoformat(),
            "investment_objective": objective,
            "risk_profile": risk,
            "investment_horizon": horizon,
            "permitted_asset_universe": UNIVERSE_OPTIONS[universe_name],
            "prohibited_assets": prohibited,
            "leverage_constraints": leverage,
            "short_selling_constraints": short_selling,
            "risk_limits": {"max_single_position_weight": 0.20},
            "pm_notes": notes.strip() or None,
        }
        st.session_state.round_number = 1
        st.session_state.phase = "idle"
        st.session_state.live_snapshot_ready = False
        st.session_state.pm_decision = None
        st.session_state.notice = "PM mandate created. Choose Demo or Live Pilot when you start research."
        st.rerun()


@st.dialog("Confirm staffing action")
def staffing_dialog(agent_id: str, action: str) -> None:
    agents = make_agents(st.session_state.phase, st.session_state.staffing)
    agent = agents[agent_id]
    st.write(f"**Agent:** {agent['name']}")
    st.write(f"**Action:** {action}")
    default_reason = {
        "Hire": "Bring this agent back into the next research round.",
        "Bench": "Lower success rate and repeated retries in the prior round.",
        "Pivot": "Validate signals on out-of-sample data and reduce overfitting risk.",
    }[action]
    reason = st.text_area("Reason for the next research round", value=default_reason)
    left, right = st.columns(2)
    if left.button("Cancel", use_container_width=True):
        st.rerun()
    if right.button("Confirm", type="primary", use_container_width=True):
        new_status = {"Hire": "Active", "Bench": "Benched", "Pivot": "Active"}[action]
        st.session_state.staffing[agent_id] = new_status
        timestamp = datetime.now().strftime("%H:%M")
        if action == "Pivot":
            entry = f"{timestamp} — PM pivoted {agent['name']} for Round {st.session_state.round_number + 1}: {reason}"
            # Give this a real effect, not just a UI note: tag the lesson to
            # this specific agent's SpecialistId so mandate_directives.py's
            # PIVOT[...] parser excludes its current candidate next round -
            # see src/mandate_directives.py for exactly what this does.
            specialist_id = STAFFING_KEY_TO_SPECIALIST_ID.get(agent_id)
            if specialist_id:
                candidate_ticker = _current_candidate_ticker(agent_id)
                if candidate_ticker:
                    st.session_state.pending_pivot_lessons.append(
                        f"PIVOT[{specialist_id}]: exclude {candidate_ticker} - {reason}"
                    )
                else:
                    st.session_state.pending_pivot_lessons.append(
                        f"PIVOT[{specialist_id}]: {reason} (no current candidate identified to exclude)"
                    )
        else:
            entry = f"{timestamp} — PM chose to {action.lower()} {agent['name']} for Round {st.session_state.round_number + 1}. Reason: {reason}"
        st.session_state.memory.insert(0, entry)
        st.session_state.notice = f"{agent['name']} is marked {new_status} for the next research round. Decision saved to Memory."
        st.rerun()


def _current_candidate_ticker(agent_id: str) -> str | None:
    """Pull the ticker this agent most recently proposed, from the live
    snapshot, so Pivot can tell mandate_directives.py exactly what to
    exclude next round. Returns None outside live mode or if unavailable -
    Pivot still records a lesson either way, just without a specific
    exclusion (see staffing_dialog)."""
    snapshot = snapshot_data()
    if not snapshot:
        return None
    agent_entry = snapshot.get("agents", {}).get(agent_id, {})
    package = agent_entry.get("package") or {}
    parameters = (package.get("candidate_rule") or {}).get("parameters") or {}
    return parameters.get("ticker") or parameters.get("ticker_a")


def show_header() -> None:
    title, action = st.columns([5, 1])
    title.title("Fractional AI Workforce")
    selected = st.sidebar.radio(
        "Workspace", ["Current workflow", "Interactive demo (click-through)"],
        index=1 if st.session_state.data_source == "Interactive demo" else 0,
        help="Current workflow combines PM intake with the latest graph-exported result. The simulated demo is retained only for click-through practice.",
    )
    st.session_state.data_source = (
        "Interactive demo"
        if selected == "Interactive demo (click-through)"
        else "Current workflow"
    )
    if st.session_state.data_source == "Current workflow":
        action.markdown("<div style='padding-top:1.1rem'>🟩 Current workflow</div>", unsafe_allow_html=True)
        st.markdown("<div class='demo-note'>PM workspace · Create a mandate, run the local research workflow, then review its exported state. Missing operational events remain N/A.</div>", unsafe_allow_html=True)
        if st.sidebar.button("Refresh live snapshot", use_container_width=True):
            st.rerun()
        st.sidebar.caption("Use the simulated demo only for a rehearsed click-through. The PM workspace is the main integration path.")
    else:
        action.markdown("<div style='padding-top:1.1rem'>🟦 Demo mode</div>", unsafe_allow_html=True)
        st.markdown("<div class='demo-note'>Interactive demo · Workflow activity, metrics, and decisions use simulated data.</div>", unsafe_allow_html=True)
    if st.session_state.notice:
        st.success(st.session_state.notice)
        st.session_state.notice = ""


def workflow_box(label: str, detail: str, state: str) -> None:
    st.markdown(
        f"<div class='workflow-box'><strong>{label}</strong><br>{status_badge(state)}<br><span style='font-size:.8rem;color:#64748b'>{detail}</span></div>",
        unsafe_allow_html=True,
    )


def dashboard() -> None:
    show_header()
    live_run_state, live_run_message = poll_live_research()
    if live_run_state == "running":
        st.warning(
            "Local research workflow is running. Use **Refresh live snapshot** to view the latest exported checkpoint; the final review will appear when the run finishes."
        )
    elif live_run_state == "completed":
        st.success(live_run_message)
    elif live_run_state == "failed":
        st.error(f"Live workflow did not complete: {live_run_message}")
    snapshot = snapshot_data()
    agents = current_agents(snapshot)
    workflow = snapshot.get("workflow", {}) if snapshot else {}
    mandate_data = snapshot.get("mandate", {}) if snapshot else (st.session_state.pm_mandate or {})
    current_round = workflow.get("round_number") or st.session_state.round_number
    st.subheader(f"Round {current_round:02d} · ETF Research")
    mandate, controls = st.columns([4, 1])
    with mandate:
        st.markdown("#### Human PM Mandate")
        if mandate_data:
            st.write(f"**Objective:** {mandate_data.get('objective') or mandate_data.get('investment_objective') or 'N/A'}")
            st.caption(
                f"Risk tolerance: {mandate_data.get('risk') or mandate_data.get('risk_profile') or 'N/A'} "
                f"· Time horizon: {mandate_data.get('time_horizon') or mandate_data.get('investment_horizon') or 'N/A'} "
                f"· Constraints: {mandate_data.get('constraint') or mandate_data.get('constraints') or mandate_data.get('pm_notes') or 'N/A'}"
            )
        else:
            st.info("No research request has been submitted. Create a PM Research Request to begin.")
    with controls:
        st.write("")
        if st.button("Create PM Research Request", type="primary", use_container_width=True):
            pm_request_dialog()
        if snapshot:
            st.caption("Latest run completed. Create a new PM request to begin another run.")
        else:
            st.toggle(
                "Run local live pilot",
                key="run_live_pilot",
                help=(
                    "Runs the offline three-trader, Risk, Reporting, PM, and "
                    "Memory workflow on this computer. Technical uses the "
                    "OpenAI or Anthropic settings in the environment; without "
                    "them, that branch is clearly labeled as stubbed."
                ),
            )
            can_start = bool(st.session_state.pm_mandate) and st.session_state.phase in {"idle", "completed"}
            if st.button("Start Research", type="primary", use_container_width=True, disabled=not can_start):
                if st.session_state.run_live_pilot:
                    mandate_date = date.fromisoformat(
                        st.session_state.pm_mandate["as_of_date"]
                    )
                    if mandate_date > OFFLINE_DATA_MAX_DATE:
                        st.error(
                            "This saved mandate requests data after the offline fixture ends. "
                            "Create a new PM Research Request and choose the displayed maximum date."
                        )
                        return
                    try:
                        st.session_state.live_process = launch_live_research(
                            st.session_state.pm_mandate
                        )
                    except OSError as error:
                        st.error(f"Could not start the live workflow: {error}")
                        return
                    st.session_state.data_source = "Current workflow"
                    st.session_state.phase = "running"
                    st.session_state.notice = "Live workflow started. Refresh the snapshot while it runs."
                    st.rerun()
                st.session_state.phase = "running"
                st.session_state.pm_decision = None
                active_agents = [name for name, status in st.session_state.staffing.items() if status == "Active"]
                st.session_state.memory.insert(0, f"PM submitted a research mandate for Round {current_round:02d}.")
                st.session_state.notice = f"Round {current_round:02d} is running. Active workforce: {len(active_agents)} agents."
                st.rerun()
            if st.button("Advance Demo to Completed Review", use_container_width=True, disabled=st.session_state.phase == "idle"):
                st.session_state.phase = "completed"
                st.session_state.notice = "Simulated research round completed; Risk review and report are ready."
                st.rerun()

    if not snapshot and st.session_state.pm_mandate:
        with st.expander("Integration handoff · WorkflowInput", expanded=False):
            st.caption(
                "This is the schema-valid payload used by the local workflow runner when Live Pilot is selected. "
                "In simulated demo mode it is shown for integration review only."
            )
            st.json(workflow_input_for_demo())

    st.divider()
    st.markdown("#### Research Workflow")
    pm_col, trader_col, risk_col, report_col = st.columns([1.15, 1.45, 1.2, 1.2])
    with pm_col:
        st.markdown("<div class='workflow-middle-spacer'></div>", unsafe_allow_html=True)
        pm_state = "Completed" if st.session_state.pm_mandate else "Idle"
        workflow_box("PM Intake", "Human mandate", "Completed" if snapshot else pm_state)
    with trader_col:
        st.markdown("<div class='parallel-label'>PARALLEL RESEARCH BRANCHES</div>", unsafe_allow_html=True)
        workflow_box("Technical Trader", "Independent branch", agents["technical"]["state"])
        workflow_box("Fundamental Trader", "Independent branch", agents["fundamental"]["state"])
        workflow_box("Quant Trader", "Independent branch", agents["quant"]["state"])
    with risk_col:
        st.markdown("<div class='workflow-middle-spacer'></div>", unsafe_allow_html=True)
        workflow_box("Risk Review", "Fan-in after active traders", agents["risk"]["state"])
    with report_col:
        st.markdown("<div class='workflow-middle-spacer'></div>", unsafe_allow_html=True)
        workflow_box("Reporting", "PM-facing memo", agents["reporting"]["state"])
    st.caption("Technical, Fundamental, and Quant research run concurrently from the same PM mandate. Risk Review begins only after every active branch settles.")

    st.markdown("#### Current Round Summary")
    metric_cols = st.columns(4)
    summary = snapshot.get("summary_metrics", {}) if snapshot else {}
    metric_cols[0].metric("Research Completion Time", summary.get("research_completion_time") if snapshot else ("6m 42s" if st.session_state.phase == "completed" else "In progress"))
    total_cost = summary.get("total_api_cost") if snapshot else ("$1.13" if st.session_state.phase == "completed" else "$0.48")
    metric_cols[1].metric("Total API Cost", f"${total_cost}" if snapshot and total_cost != "N/A" else total_cost)
    active = summary.get("active_agents") if snapshot else sum(status == "Active" for status in st.session_state.staffing.values())
    metric_cols[2].metric("Active Agents", f"{active} / 5")
    metric_cols[3].metric("Round Status", workflow.get("status") if snapshot else st.session_state.phase.title())
    st.caption(metrics_disclaimer(snapshot))

    st.divider()
    st.markdown("#### Agent Workforce")
    st.caption(metrics_disclaimer(snapshot))
    for row in [["technical", "fundamental", "quant"], ["risk", "reporting"]]:
        columns = st.columns(3)
        for col, agent_id in zip(columns, row):
            agent = agents[agent_id]
            with col:
                staffing_status = agent.get("staffing_status") if snapshot else st.session_state.staffing[agent_id]
                st.markdown(f"<div class='agent-name'>{agent['name']}</div>{status_badge(agent['state'])} &nbsp; <span style='font-size:.85rem'>Next round: {staffing_status}</span>", unsafe_allow_html=True)
                st.caption(agent["role"])
                st.write(f"**Current task:** {agent['task']}")
                a, b = st.columns(2)
                a.caption(f"Success rate\n\n**{agent_value(agent, 'success_rate')}**")
                b.caption(f"Completion time\n\n**{agent_value(agent, 'task_completion_time')}**")
                c, d = st.columns(2)
                c.caption(f"API cost\n\n**{agent_value(agent, 'api_cost')}**")
                d.caption(f"Retries / Failed\n\n**{agent_value(agent, 'retry_count')} / {agent_value(agent, 'failed_count')}**")
                if st.button("View Agent Detail", key=f"view-{agent_id}", use_container_width=True):
                    st.session_state.selected_agent = agent_id
                    st.session_state.view = "detail"
                    st.rerun()

    st.divider()
    left, right = st.columns([2, 1])
    with left:
        st.markdown("#### Recent Memory / Previous Lessons")
        memory_entries = st.session_state.memory if not snapshot else [
            f"Memory record: {snapshot.get('memory', {}).get('record_id') or 'N/A'}",
            snapshot.get("memory", {}).get("context") or "No memory context exported for this run.",
        ]
        for entry in memory_entries[:3]:
            st.write(f"• {entry}")
    with right:
        st.markdown("#### PM Decision")
        report_ready = bool(snapshot.get("reporting")) if snapshot else st.session_state.phase == "completed"
        if st.button("View Research Report", type="primary", use_container_width=True, disabled=not report_ready):
            st.session_state.view = "report"
            st.rerun()


def agent_detail() -> None:
    show_header()
    snapshot = snapshot_data()
    agents = current_agents(snapshot)
    agent_id = st.session_state.selected_agent
    agent = agents[agent_id]
    if st.button("← Back to Dashboard"):
        st.session_state.view = "dashboard"
        st.rerun()
    st.title(agent["name"])
    staffing_status = agent.get("staffing_status") if snapshot else st.session_state.staffing[agent_id]
    st.caption(f"{agent['role']} · Next-round staffing: {staffing_status}")
    st.markdown(status_badge(agent["state"]), unsafe_allow_html=True)

    main, metrics = st.columns([3, 2])
    with main:
        st.subheader("What happened in this round")
        st.markdown(f"**Current task:** {agent['task']}")
        if snapshot and agent_id in {"fundamental", "quant", "technical"}:
            render_strategy_summary(agent, snapshot)
        elif snapshot and agent_id == "risk":
            decisions = snapshot.get("risk_review", {}).get("decisions", [])
            st.write(f"Reviewed {len(decisions)} risk-eligible candidate(s).")
            for decision in decisions:
                st.write(f"• {str(decision.get('verdict', 'pending')).title()} — {decision.get('candidate_id', 'Unknown candidate')}")
        elif snapshot and agent_id == "reporting":
            candidates = snapshot.get("reporting", {}).get("comparison", {}).get("candidates", [])
            st.write(f"Compared {len(candidates)} Risk-approved candidate(s) for PM review.")
        else:
            st.write(agent_value(agent, "output"))
        times = st.columns(2)
        times[0].markdown(f"**Start Time**  \n{agent_value(agent, 'start_time')}")
        times[1].markdown(f"**End Time**  \n{agent_value(agent, 'end_time')}")
        st.markdown(f"**Next Step**  \n{agent_value(agent, 'next_step')}")
        st.markdown(f"**Error Message**  \n{agent_value(agent, 'error_message')}")
    with metrics:
        st.subheader("Productivity Metrics")
        st.metric("Task Completion Time", agent_value(agent, "task_completion_time"))
        st.metric("Success Rate", agent_value(agent, "success_rate"))
        st.metric("API Cost", agent_value(agent, "api_cost"))
        st.metric("Retry Count", agent_value(agent, "retry_count"))
        st.metric("Failed Count", agent_value(agent, "failed_count"))
        st.caption(metrics_disclaimer(snapshot))

    st.divider()
    if snapshot:
        with st.expander("Technical details · exported agent data"):
            st.json(agent)
    else:
        st.subheader("Risk Feedback")
        st.info(agent["risk_feedback"])
    st.subheader("Staffing Actions")
    if snapshot:
        st.caption("Snapshot mode is read-only. Staffing decisions must be made by the PM workflow, then exported again.")
        return
    if st.session_state.phase != "completed":
        st.caption("Staffing changes are available after the current round is completed and apply to the next round.")
        return

    st.caption("These actions are recorded for the next research round. They do not alter a completed round.")
    staffing_status = st.session_state.staffing[agent_id]
    actions = ["Hire"] if staffing_status == "Benched" else ["Bench", "Pivot"]
    buttons = st.columns(len(actions))
    for col, action in zip(buttons, actions):
        if col.button(action, key=f"{action}-{agent_id}", type="primary" if action == "Hire" else "secondary", use_container_width=True):
            staffing_dialog(agent_id, action)


def report_page() -> None:
    show_header()
    snapshot = snapshot_data()
    if st.button("← Back to Dashboard"):
        st.session_state.view = "dashboard"
        st.rerun()
    current_round = snapshot.get("workflow", {}).get("round_number") if snapshot else st.session_state.round_number
    st.title(f"Research Report · Round {current_round:02d}")
    st.caption("Generated by Reporting Agent from Risk-approved results." if snapshot else "Generated by Reporting Agent from Risk-approved simulated results.")
    if snapshot:
        risk_review = snapshot.get("risk_review", {})
        reporting = snapshot.get("reporting", {})
        candidates = reporting.get("comparison", {}).get("candidates", [])

        st.subheader("PM Summary")
        if not candidates:
            st.info("No Risk-approved candidate was exported for this workflow run.")
        else:
            held_out_returns = [
                item.get("out_of_sample_metrics", {}).get("total_return")
                for item in candidates
            ]
            if all(isinstance(value, (int, float)) and value < 0 for value in held_out_returns):
                st.warning("Both surviving candidates had negative held-out returns. Risk approval means the packages passed workflow checks; it does not mean the PM should invest.")
            else:
                st.info("Risk approval only permits PM review. Compare held-out results and limitations before selecting a strategy.")

        st.subheader("Candidate Comparison")
        rows = []
        for candidate in candidates:
            held_out = candidate.get("out_of_sample_metrics") or {}
            rows.append({
                "Research lens": str(candidate.get("trader_id", "Unknown")).replace("_agent", "").replace("_", " ").title(),
                "Risk verdict": str(candidate.get("risk_verdict", "pending")).title(),
                "Held-out return": format_percent(held_out.get("total_return")),
                "Held-out Sharpe": format_decimal(held_out.get("sharpe_ratio")),
                "Max drawdown": format_percent(held_out.get("max_drawdown")),
                "Trades": held_out.get("transaction_count", "N/A"),
            })
        if rows:
            st.dataframe(rows, hide_index=True, use_container_width=True)

        st.subheader("Candidate Details")
        for candidate in candidates:
            label = str(candidate.get("trader_id", "Unknown")).replace("_agent", "").replace("_", " ").title()
            with st.expander(label, expanded=False):
                st.markdown(f"**Hypothesis:** {candidate.get('hypothesis') or 'N/A'}")
                st.write(candidate.get("interpretation") or "No interpretation was exported.")
                for heading, entries in [("Strengths", candidate.get("strengths") or []), ("PM review flags", candidate.get("reporting_flags") or [])]:
                    if entries:
                        st.markdown(f"**{heading}**")
                        for entry in list(dict.fromkeys(entries)):
                            st.write(f"• {entry}")

        st.subheader("Risk Review Summary")
        for item in risk_review.get("round_check_results") or []:
            st.write(f"• **{item.get('check_id')} — {str(item.get('verdict', 'pending')).title()}:** {item.get('summary')}")
        for critique in risk_review.get("collective_critiques") or []:
            st.write(f"• {critique}")
    else:
        st.subheader("Risk Review Summary")
        st.success("Technical Trader — Approved: stable on held-out simulated data.")
        st.success("Fundamental Trader — Approved: assumptions are documented.")
        st.error("Quant Trader — Risk outcome: Vetoed for possible overfitting; requires out-of-sample validation.")
    st.subheader("Reporting Agent Memo")
    if snapshot:
        memo = reporting.get("strategy_memo_reference")
        if memo:
            st.write(memo)
        else:
            st.info("This Reporting Agent run produced a structured comparison, not an LLM-written narrative memo. The comparison above is rendered directly from that output.")
    else:
        st.markdown(
            "**Recommendation:** Consider the diversified ETF momentum screen, supported by technical and fund-level evidence.\n\n"
            "**Limitation:** Backtest results are simulated in this clickable prototype and do not guarantee future performance."
        )
    st.subheader("Human PM Decision")
    if snapshot:
        decision = snapshot.get("pm_decision", {})
        workflow_info = snapshot.get("workflow", {})
        awaiting_decision = workflow_info.get("status") == "Waiting for PM Decision"

        if not awaiting_decision:
            # A terminal decision (select/reject) was already recorded for
            # this workflow - nothing left to resume, so stay read-only.
            if decision:
                st.write(f"**Recorded decision:** {str(decision.get('decision', 'N/A')).title()}")
                st.write(f"**Rationale:** {decision.get('rationale') or 'No rationale exported.'}")
            else:
                st.caption("No PM decision was exported for this workflow run.")
            st.caption("This workflow has no PM decision awaiting resolution.")
            with st.expander("Technical details · raw Reporting and Risk output"):
                st.json({"reporting": reporting, "risk_review": risk_review, "pm_decision": decision})
            return

        run_id = str(workflow_info.get("workflow_id") or "")
        round_number = workflow_info.get("round_number") or current_round
        surviving_ids = reporting.get("surviving_candidate_ids") or []
        st.caption(
            "This round is complete and paused for a real decision - resuming "
            "will run the next round for real, using your current staffing choices."
        )

        def _resume(decision_type: str, *, selected_candidate_id: str | None = None) -> None:
            rationale = st.session_state.get("pm_decision_rationale", "").strip() or (
                "PM decision recorded from the live dashboard."
            )
            pm_decision = {
                "decision_id": f"{run_id}.decision-{round_number}",
                "workflow_id": run_id,
                "decision": decision_type,
                "rationale": rationale,
            }
            if selected_candidate_id:
                pm_decision["selected_candidate_id"] = selected_candidate_id
            try:
                st.session_state.live_process = launch_live_resume(run_id, pm_decision)
            except OSError as error:
                st.error(f"Could not resume the live workflow: {error}")
                return
            st.session_state.live_snapshot_ready = False
            st.session_state.phase = "running"
            st.session_state.round_number = round_number + 1 if decision_type == "request_another_round" else round_number
            st.session_state.notice = f"Resuming with decision: {decision_type.replace('_', ' ')}."
            st.rerun()

        st.text_input(
            "Rationale for this decision (optional)",
            key="pm_decision_rationale",
            placeholder="e.g. Strongest risk-adjusted return with a clean Risk review.",
        )

        if surviving_ids:
            selected = st.selectbox(
                "Candidate to select (if choosing Select Strategy)",
                options=surviving_ids,
                format_func=lambda cid: cid.split(".")[-2].replace("_", " ").title() if "." in cid else cid,
            )
        else:
            selected = None
            st.caption("No surviving candidate this round - Select Strategy is unavailable.")

        one, two, three = st.columns(3)
        if one.button("Select Strategy", type="primary", use_container_width=True, disabled=not selected):
            _resume("select", selected_candidate_id=selected)
        if two.button("Reject", use_container_width=True):
            _resume("reject")
        if three.button("Request Another Round", use_container_width=True):
            _resume("request_another_round")
        return
    if st.session_state.pm_decision:
        st.success(f"Decision recorded: {st.session_state.pm_decision}")
        st.caption("The decision and its rationale are retained in Memory for future rounds.")
        return
    one, two, three = st.columns(3)
    if one.button("Select Strategy", type="primary", use_container_width=True):
        st.session_state.pm_decision = "Selected diversified ETF momentum strategy"
        st.session_state.memory.insert(0, f"PM selected the diversified ETF momentum strategy in Round {current_round:02d}.")
        st.rerun()
    if two.button("Reject", use_container_width=True):
        st.session_state.pm_decision = "Rejected all strategies"
        st.session_state.memory.insert(0, f"PM rejected all strategies in Round {current_round:02d}; outcome saved to Memory.")
        st.rerun()
    if three.button("Request Another Round", use_container_width=True):
        st.session_state.memory.insert(0, f"PM requested Round {current_round + 1:02d}; prior lessons will guide the new research round.")
        st.session_state.pm_decision = "Requested another research round"
        st.session_state.round_number += 1
        st.session_state.phase = "running"
        st.session_state.notice = f"Round {st.session_state.round_number:02d} started with lessons from Round {current_round:02d}."
        st.session_state.view = "dashboard"
        st.rerun()


init_state()

if st.session_state.view == "dashboard":
    dashboard()
elif st.session_state.view == "detail":
    agent_detail()
else:
    report_page()
