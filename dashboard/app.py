"""Clickable Streamlit mockup for the Fractional AI Workforce project.

This version deliberately uses simulated data.  It is designed for a clickable
review, not for production trading or live agent execution.
"""

from __future__ import annotations

from datetime import datetime
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
    "Core liquid ETF pilot": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT"],
    "Sector ETF pilot": ["XLK", "XLF", "XLV", "XLE", "XLY", "XLP"],
}


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
        "notice": "", "data_source": "Interactive demo",
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
    """Return the graph-owned snapshot when the user selects that view."""

    if st.session_state.data_source != "Workflow snapshot":
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


def display_value(value: Any) -> None:
    if isinstance(value, (dict, list)):
        st.json(value)
    else:
        st.write(value if value not in (None, "") else "N/A")


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

    st.caption("The form creates a PMMandate-shaped payload. Demo mode does not yet invoke the graph.")
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
        as_of_date = st.date_input("As-of date *")
        universe_name = st.selectbox(
            "Permitted asset universe *", list(UNIVERSE_OPTIONS),
            help="The pilot uses a small explicit ticker list. A later team service can resolve the full 120-ETF universe.",
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
        st.session_state.phase = "idle"
        st.session_state.pm_decision = None
        st.session_state.notice = "PM mandate created. You can now start the simulated research round."
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
        else:
            entry = f"{timestamp} — PM chose to {action.lower()} {agent['name']} for Round {st.session_state.round_number + 1}. Reason: {reason}"
        st.session_state.memory.insert(0, entry)
        st.session_state.notice = f"{agent['name']} is marked {new_status} for the next research round. Decision saved to Memory."
        st.rerun()


def show_header() -> None:
    title, action = st.columns([5, 1])
    title.title("Fractional AI Workforce")
    selected = st.sidebar.radio(
        "Dashboard data", ["Interactive demo", "Workflow snapshot"],
        index=0 if st.session_state.data_source == "Interactive demo" else 1,
        help="The snapshot is exported from the LangGraph WorkflowState. It is read-only in this dashboard.",
    )
    st.session_state.data_source = selected
    if selected == "Workflow snapshot":
        action.markdown("<div style='padding-top:1.1rem'>🟩 Snapshot mode</div>", unsafe_allow_html=True)
        st.markdown("<div class='demo-note'>Workflow snapshot · Read-only data exported from WorkflowState. Missing operational events remain N/A.</div>", unsafe_allow_html=True)
        if st.sidebar.button("Refresh live snapshot", use_container_width=True):
            st.rerun()
        st.sidebar.caption("While the workflow runner is active, use Refresh to load the latest exported lifecycle state.")
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
        if snapshot:
            st.caption("Snapshot mode is read-only. Run the workflow again and export a new snapshot to refresh it.")
        else:
            if st.button("Create PM Research Request", type="primary", use_container_width=True):
                pm_request_dialog()
            can_start = bool(st.session_state.pm_mandate) and st.session_state.phase in {"idle", "completed"}
            if st.button("Start Research", type="primary", use_container_width=True, disabled=not can_start):
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
                "This is the schema-valid payload the dashboard will send to the team's workflow runner. "
                "It is shown for integration review; demo mode does not submit it yet."
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

    st.divider()
    st.markdown("#### Agent Workforce")
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
        st.subheader("Agent Status Schema")
        st.markdown(f"**Current State**  ")
        st.markdown(status_badge(agent["state"]), unsafe_allow_html=True)
        st.markdown(f"**Current Task**  \n{agent['task']}")
        st.markdown("**Input**")
        display_value(agent_value(agent, "input"))
        st.markdown("**Output**")
        display_value(agent_value(agent, "output"))
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
        st.caption("Metrics are simulated in demo mode and exported from workflow events in snapshot mode.")

    st.divider()
    st.subheader("Risk Feedback")
    if snapshot:
        st.info("Risk feedback is available in the exported Risk Review section when the workflow emits it.")
    else:
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
    st.subheader("Risk Review Summary")
    if snapshot:
        risk_review = snapshot.get("risk_review", {})
        if risk_review:
            st.json(risk_review)
        else:
            st.info("No Risk Review output was exported for this workflow run.")
    else:
        st.success("Technical Trader — Approved: stable on held-out simulated data.")
        st.success("Fundamental Trader — Approved: assumptions are documented.")
        st.error("Quant Trader — Risk outcome: Vetoed for possible overfitting; requires out-of-sample validation.")
    st.subheader("Reporting Agent Memo")
    if snapshot:
        reporting = snapshot.get("reporting", {})
        if reporting:
            st.json(reporting)
        else:
            st.info("No Reporting output was exported for this workflow run.")
    else:
        st.markdown(
            "**Recommendation:** Consider the diversified ETF momentum screen, supported by technical and fund-level evidence.\n\n"
            "**Limitation:** Backtest results are simulated in this clickable prototype and do not guarantee future performance."
        )
    st.subheader("Human PM Decision")
    if snapshot:
        decision = snapshot.get("pm_decision", {})
        if decision:
            st.json(decision)
        else:
            st.caption("No PM decision was exported for this workflow run.")
        st.caption("Snapshot mode is read-only. PM decisions are recorded by the workflow and shown after the next export.")
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
