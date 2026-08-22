"""Clickable Streamlit dashboard for the Fractional AI Workforce project.

Sends a controlled PM mandate to the team's offline research-loop
integration script and renders the real, exported result. There is no
separate demo/simulated mode - see the removal note in show_header() for
why (shared session state with the real workflow led to real crashes as
the real workflow gained states the simulated mode never learned about).
"""

from __future__ import annotations

from datetime import date, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4

import streamlit as st

# Don't rely solely on the editable pip install (`-e .`) having made src/'s
# packages (evaluation, agents, protocols, ...) importable at the top level -
# that assumption held for local development and for
# scripts/run_full_research_loop_demo.py (which already does this same
# insertion defensively), but broke on Streamlit Community Cloud's build,
# which processes requirements.txt differently than a local `pip install -e .`
# and left this file's own local modules (workflow_adapter, data_bootstrap)
# unable to find src/'s packages via a plain top-level import.
_REPO_ROOT_FOR_IMPORTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORTS / "src"))
sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORTS))

from data_bootstrap import ensure_offline_data_present
from workflow_adapter import load_dashboard_snapshot


def _copy_secrets_into_environment() -> None:
    """Copy configured Streamlit secrets into os.environ.

    Streamlit Cloud (and other hosts using st.secrets) expose configured
    secrets to *this* process via st.secrets, not as real environment
    variables - so a child process started with subprocess.Popen (see
    launch_live_research/launch_live_resume below) would not see them
    otherwise. Local development, which already sets these via a real
    .env file loaded by python-dotenv, is unaffected: setdefault never
    overwrites a value already present in the environment. Best-effort -
    st.secrets raises if no secrets are configured at all (e.g. running
    locally with no secrets.toml), which is expected, not an error.
    """
    relevant_keys = (
        "TECHNICAL_TRADER_MODEL_PROVIDER", "TECHNICAL_TRADER_MODEL",
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY", "GEMINI_MODEL", "MODEL_PROVIDER", "MODEL_NAME",
        "ETF_HISTORICAL_PRICES_URL", "ETF_INFO_URL",
    )
    try:
        secrets = dict(st.secrets)
    except Exception:
        return
    for key in relevant_keys:
        value = secrets.get(key)
        if value:
            os.environ.setdefault(key, str(value))


_copy_secrets_into_environment()
ensure_offline_data_present()


st.set_page_config(
    page_title="Fractional AI Workforce",
    page_icon="◈",
    layout="wide",
)

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap');

      :root {
        --ink: #0F1B2D;
        --paper: #F6F7FA;
        --navy: #1E3A5F;
        --navy-dark: #142943;
        --teal: #0F766E;
        --teal-bg: #DCFCE7;
        --amber: #B45309;
        --amber-bg: #FEF3C7;
        --red: #B91C1C;
        --red-bg: #FEE2E2;
        --slate: #E5E7EB;
        --slate-ink: #374151;
        --rule: #D8DEE9;
        --muted: #64748B;
      }

      html, body, [class*="css"] {
        font-family: 'IBM Plex Sans', -apple-system, sans-serif;
        color: var(--ink);
      }
      .stApp {background: var(--paper);}
      .block-container {max-width: 1400px; padding-top: 1.5rem;}

      h1, h2, h3 {
        font-family: 'IBM Plex Sans', sans-serif;
        font-weight: 700;
        letter-spacing: -0.01em;
        color: var(--navy-dark);
      }

      /* Masthead: the app's own title, given real weight instead of a
         plain default st.title() */
      h1:first-of-type {
        margin-bottom: .3rem;
      }

      /* Streamlit's own platform toolbar (Deploy button + hamburger menu) -
         not app content, hidden since it reads as a stray link near the
         title on a page meant to look like a finished product. */
      [data-testid="stToolbar"], [data-testid="stDecoration"] {
        display: none;
      }

      /* The plain-language explainer every first-time visitor needs before
         anything else - the project's own thesis, not the interface's
         controls, is the first thing on the page. */
      .hero {
        background: #fff; border: 1px solid var(--rule);
        border-left: 4px solid var(--teal); border-radius: 8px;
        padding: 1.1rem 1.3rem; margin: .6rem 0 1.4rem 0;
      }
      .hero-lede {
        font-size: 1.02rem; line-height: 1.55; color: var(--ink);
        margin: 0;
      }

      /* Status badges - the project's own signature element. State
         tracking is the entire thesis of this system, so the badge that
         shows an agent's current state gets consistent, terminal-style
         treatment everywhere it appears, rather than a plain colored pill. */
      .status {
        border-radius: 4px; padding: .22rem .62rem; font-size: .74rem;
        font-family: 'IBM Plex Mono', monospace; font-weight: 600;
        letter-spacing: .04em; text-transform: uppercase;
        display: inline-block; border: 1px solid transparent;
      }
      .idle, .assigned {background: var(--slate); color: var(--slate-ink); border-color: #CBD2DC;}
      .running {background: #DBEAFE; color: var(--navy-dark); border-color: #BFDBFE;}
      .waiting {background: var(--amber-bg); color: var(--amber); border-color: #FDE68A;}
      .completed {background: var(--teal-bg); color: var(--teal); border-color: #A7F3D0;}
      .failed, .vetoed {background: var(--red-bg); color: var(--red); border-color: #FECACA;}

      .workflow-box {
        border: 1px solid var(--rule); border-radius: 8px; padding: .8rem;
        text-align: center; min-height: 76px; background: #fff;
        box-shadow: 0 1px 2px rgba(15,27,45,.04);
      }
      .small-label {
        font-family: 'IBM Plex Mono', monospace; font-size: .7rem;
        color: var(--muted); text-transform: uppercase; letter-spacing: .06em;
      }
      .agent-name {font-size: 1.08rem; font-weight: 700; color: var(--navy-dark);}
      .demo-note {
        background: #EEF2F8; color: var(--navy-dark); border: 1px solid var(--rule);
        border-left: 3px solid var(--navy); border-radius: 6px;
        padding: .7rem 1rem; margin-bottom: 1rem; font-size: .92rem;
      }
      .parallel-label {
        font-family: 'IBM Plex Mono', monospace; font-size: .72rem;
        color: var(--muted); text-align: center; margin-bottom: .35rem;
        font-weight: 600; letter-spacing: .06em; text-transform: uppercase;
      }
      .workflow-middle-spacer {height: 112px;}

      /* All measured/reported figures (cost, latency, %) get monospace
         treatment for real alignment, matching how trading terminals set
         numerals - not decorative, this is the grounded typographic choice
         for this subject. */
      [data-testid="stMetricValue"] {
        font-family: 'IBM Plex Mono', monospace; font-weight: 600;
        color: var(--navy-dark); font-size: 1.6rem;
      }
      [data-testid="stMetricLabel"] {
        font-family: 'IBM Plex Mono', monospace; font-size: .72rem;
        text-transform: uppercase; letter-spacing: .05em; color: var(--muted);
      }

      .stButton > button[kind="primary"] {
        background: var(--navy); border-color: var(--navy);
        font-weight: 600;
      }
      .stButton > button[kind="primary"]:hover {
        background: var(--navy-dark); border-color: var(--navy-dark);
      }
      .stButton > button[kind="primary"]:disabled,
      .stButton > button[kind="primary"]:disabled:hover {
        background: var(--slate); border-color: #CBD2DC; color: var(--slate-ink);
        opacity: 1;
      }

      [data-testid="stSidebar"] {
        background: #FFFFFF; border-right: 1px solid var(--rule);
      }
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
LIVE_RUNNER_PATH = REPO_ROOT / "scripts" / "run_full_research_loop_demo.py"
# Updated together with the offline workbook. This keeps the PM date truthful:
# the current fixture's last observed trading date is 2026-06-29.
OFFLINE_DATA_MAX_DATE = date(2026, 6, 29)
# The Risk framework allows at most three validation-touch rounds. Keeping the
# PM controls aligned with that guard prevents a request that is guaranteed to
# be vetoed only because it exceeds the research budget.
MAX_RESEARCH_ROUNDS = 3


def _sanitize_workflow_id(workflow_id: str) -> str:
    """Match run_full_research_loop_demo.py's own sanitization exactly, so
    both sides always agree on the same directory for the same run."""
    return "".join(
        ch if ch.isalnum() or ch in "-_." else "_" for ch in workflow_id
    )


def _session_dir_for(workflow_id: str) -> Path:
    """One run's private data directory, keyed by its own workflow_id.

    Every live-mode file this dashboard reads or writes is scoped under
    this directory, and the same workflow_id is what the backend script
    uses to build the identical directory (see _session_data_dir in
    run_full_research_loop_demo.py) - so two people using this dashboard
    at the same time, e.g. on a public deployment, each get their own
    checkpoint DB, Memory store, and snapshot file instead of silently
    overwriting each other's run. Previously these paths were fixed,
    shared by every caller regardless of who was using the app. Keying off
    the mandate's own workflow_id (already uniquely generated per "Create
    Mandate" submission - see f"dashboard-demo-{uuid4().hex[:8]}" below)
    rather than a separate browser-session id keeps the dashboard and the
    script from ever disagreeing about which directory a run's files live in.
    """
    path = REPO_ROOT / "dashboard" / "data" / "sessions" / _sanitize_workflow_id(workflow_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _current_run_workflow_id() -> str | None:
    """The workflow_id of the PM's current run, if one has been created yet."""
    mandate = st.session_state.get("pm_mandate")
    if mandate and mandate.get("workflow_id"):
        return str(mandate["workflow_id"])
    return None


def _live_input_path(workflow_id: str) -> Path:
    return _session_dir_for(workflow_id) / "latest_pm_mandate.json"


def _live_decision_path(workflow_id: str) -> Path:
    return _session_dir_for(workflow_id) / "latest_pm_decision.json"


def _live_log_path(workflow_id: str) -> Path:
    return _session_dir_for(workflow_id) / "live_workflow.log"


def _live_snapshot_path(workflow_id: str) -> Path:
    return _session_dir_for(workflow_id) / "workflow_snapshot.json"


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
        for key, status in effective_staffing().items()
        if status == "Active" and key in STAFFING_KEY_TO_SPECIALIST_ID
    ]


def launch_live_research(mandate: dict[str, Any]) -> subprocess.Popen[str]:
    """Start the offline integration pilot without blocking the dashboard.

    The dashboard can be refreshed while the runner publishes checkpoints. A
    deployed product would replace this local child process with a durable job
    service, but the separation keeps this prototype visibly interactive.
    """

    workflow_id = str(mandate["workflow_id"])
    _live_input_path(workflow_id).write_text(
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
    with _live_log_path(workflow_id).open("w", encoding="utf-8") as log_file:
        return subprocess.Popen(
            [python, str(LIVE_RUNNER_PATH), "--mandate-json", str(_live_input_path(workflow_id))],
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
        # Streamlit session state resets on a browser/server reload, while the
        # graph snapshot persists. Rehydrate the original mandate from that
        # snapshot before adding a pivot lesson; never replace a valid graph
        # mandate with a partial {"prior_round_lessons": ...} payload.
        current_mandate = dict(st.session_state.pm_mandate or {})
        if not current_mandate.get("workflow_id"):
            current_mandate = dict((snapshot_data() or {}).get("mandate") or {})
        if not current_mandate.get("workflow_id"):
            raise OSError(
                "The original PM mandate is unavailable. Refresh the live snapshot "
                "before requesting another round."
            )
        existing_lessons = list(current_mandate.get("prior_round_lessons") or [])
        current_mandate["prior_round_lessons"] = (
            existing_lessons + list(st.session_state.pending_pivot_lessons)
        )
        state_update["pm_mandate"] = current_mandate
        st.session_state.pm_mandate = current_mandate
        st.session_state.pending_pivot_lessons = []

    LIVE_DECISION_PATH = _live_decision_path(run_id)
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
    # The choice has now been handed to the workflow. A later completed round
    # starts with a fresh set of staffing choices for its own next round.
    st.session_state.next_round_actions = {}
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    python = str(venv_python if venv_python.exists() else Path(sys.executable))
    with _live_log_path(run_id).open("w", encoding="utf-8") as log_file:
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
        workflow_id = _current_run_workflow_id()
        try:
            status = (
                load_dashboard_snapshot(_live_snapshot_path(workflow_id)).get("workflow", {}).get("status")
                if workflow_id else None
            )
        except (OSError, ValueError):
            status = None
        if status == "Waiting for PM Decision":
            st.session_state.phase = "awaiting_decision"
            return "awaiting_decision", "Round complete. Awaiting a PM decision to continue."
        st.session_state.phase = "completed"
        return "completed", "Live research completed. The dashboard now shows its exported workflow snapshot."

    workflow_id = _current_run_workflow_id()
    log_lines = (
        _live_log_path(workflow_id).read_text(encoding="utf-8").strip().splitlines()
        if workflow_id else []
    )
    detail = log_lines[-1] if log_lines else "The live workflow ended without an error message."
    st.session_state.phase = "idle"
    return "failed", detail


def make_agents(phase: str, staffing: dict[str, str] | None = None) -> dict[str, dict]:
    """Fallback agent view before any real snapshot exists for this round.

    Only reached when there is genuinely no live snapshot yet (a fresh
    mandate, or a round still running) - see current_agents() below.
    """
    trader_states = {
        "idle": ("Idle", "Waiting for a research task"),
        "running": ("Running", "Analyze market evidence and draft a rule"),
        "completed": ("Completed", "Strategy package submitted to Risk Review"),
    }
    # .get() with a safe default rather than a bare lookup: phase can hold
    # real-workflow-only values (e.g. "awaiting_decision") that this
    # fallback view was never meant to render - a bare trader_states[phase]
    # crashed with a real KeyError in production the one time this
    # happened, rather than degrading gracefully.
    state, task = trader_states.get(phase, trader_states["idle"])
    risk_state, risk_task = {
        "idle": ("Idle", "Waiting for trader results"),
        "running": ("Waiting for Review", "Waiting for all three trader packages"),
        "completed": ("Completed", "Review trader strategies for overfitting"),
    }.get(phase, ("Idle", "Waiting for trader results"))
    report_state, report_task = {
        "idle": ("Idle", "Waiting for Risk approval"),
        "running": ("Assigned", "Waiting for approved research packages"),
        "completed": ("Completed", "Create PM-facing research memo"),
    }.get(phase, ("Idle", "Waiting for Risk approval"))

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
        "round_number": 1, "pm_decision": None,
        "pm_mandate": None,
        "staffing": {key: "Active" for key in ["technical", "fundamental", "quant", "risk", "reporting"]},
        "memory": [],
        "notice": "",
        "live_snapshot_ready": False, "live_process": None,
        "pending_pivot_lessons": [],
        "next_round_actions": {},
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

    # A newly authored mandate is intentionally shown before it is sent to the
    # workflow, rather than being visually mixed with the prior run's result.
    if st.session_state.pm_mandate and not st.session_state.live_snapshot_ready:
        return None
    workflow_id = _current_run_workflow_id()
    if not workflow_id:
        return None
    try:
        return load_dashboard_snapshot(_live_snapshot_path(workflow_id))
    except (OSError, ValueError) as error:
        st.warning(f"Could not load workflow snapshot: {error}")
        return None


def effective_staffing(snapshot: dict[str, Any] | None = None) -> dict[str, str]:
    """Return the staffing that would be sent into the next live round.

    A graph-exported snapshot is authoritative for the current round. Browser
    session state only overlays a staffing decision the PM has made during the
    currently open review, so stale demo state cannot turn a benched trader
    back into Active on screen or in the workflow input.
    """
    snapshot = snapshot if snapshot is not None else snapshot_data()
    staffing = dict(st.session_state.staffing)
    if snapshot and snapshot.get("workflow", {}).get("status") == "Waiting for PM Decision":
        for agent_id, agent in snapshot.get("agents", {}).items():
            if agent_id in staffing and agent.get("staffing_status"):
                staffing[agent_id] = agent["staffing_status"]
    for agent_id, action in st.session_state.next_round_actions.items():
        staffing[agent_id] = {"Hire": "Active", "Bench": "Benched", "Pivot": "Active"}[action]
    return staffing


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
    if st.session_state.phase == "idle":
        return "No round has started yet. These figures will populate once a research request runs."
    return "Waiting for the live run to produce a result. Use Refresh live snapshot to check again."


def display_value(value: Any) -> None:
    if isinstance(value, (dict, list)):
        st.json(value)
    else:
        st.write(value if value not in (None, "") else "N/A")


def format_percent(value: Any) -> str:
    return f"{value:.1%}" if isinstance(value, (int, float)) else "N/A"


def format_decimal(value: Any) -> str:
    return f"{value:.2f}" if isinstance(value, (int, float)) else "N/A"


def candidate_label(snapshot: dict[str, Any], candidate_id: str) -> str:
    """Return a PM-readable label instead of exposing an internal ID."""

    candidates = snapshot.get("reporting", {}).get("comparison", {}).get("candidates", [])
    candidate = next(
        (item for item in candidates if item.get("candidate_id") == candidate_id),
        {},
    )
    trader_id = str(candidate.get("trader_id", ""))
    dashboard_id = {
        "fundamental_trader_agent": "fundamental",
        "quant_trader_agent": "quant",
        "technical_trader_agent": "technical",
    }.get(trader_id)
    package = (
        snapshot.get("agents", {}).get(dashboard_id or "", {}).get("package", {})
    )
    parameters = (package.get("candidate_rule") or {}).get("parameters") or {}
    symbols = parameters.get("ticker") or "/".join(
        item for item in (parameters.get("ticker_a"), parameters.get("ticker_b")) if item
    )
    lens = trader_id.replace("_agent", "").replace("_", " ").title() or "Candidate"
    return f"{lens} — {symbols or 'strategy candidate'}"


def applied_mandate_notes(snapshot: dict[str, Any]) -> list[str]:
    """Collect explicit directive notes emitted by the trader packages."""

    notes: list[str] = []
    for agent_id in ("fundamental", "quant", "technical"):
        package = snapshot.get("agents", {}).get(agent_id, {}).get("package", {})
        rule = package.get("candidate_rule") or {}
        for note in rule.get("implementation_notes") or []:
            text = str(note)
            if any(
                term in text
                for term in (
                    "risk_profile",
                    "investment_horizon",
                    "rebalancing_preference",
                    "risk_limits",
                    "leverage",
                    "short",
                    "PIVOT",
                )
            ) and text not in notes:
                notes.append(text)
    return notes


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
    if not mandate or not mandate.get("workflow_id"):
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
        "Risk profile, horizon, rebalancing preference, risk limits, leverage/short-selling constraints, and ticker exclusions in PM notes "
        "are translated into documented rule directives for Fundamental and Quant. The free-text objective remains descriptive."
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
        st.session_state.next_round_actions[agent_id] = action
        timestamp = datetime.now().strftime("%H:%M")
        snapshot = snapshot_data()
        live_round = (snapshot or {}).get("workflow", {}).get("round_number")
        next_round = int(live_round) + 1 if live_round else st.session_state.round_number + 1
        if action == "Pivot":
            entry = f"{timestamp} — PM pivoted {agent['name']} for Round {next_round}: {reason}"
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
            entry = f"{timestamp} — PM chose to {action.lower()} {agent['name']} for Round {next_round}. Reason: {reason}"
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
    st.title("Fractional AI Workforce")
    st.markdown("<div class='demo-note'>Create a research request below, run it, then review the real results. Some figures show as N/A until the system actually has data to report.</div>", unsafe_allow_html=True)
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
    st.markdown(
        """
        <div class="hero">
          <p class="hero-lede">
            A human Portfolio Manager delegates ETF research to five AI
            specialists instead of doing it alone — three independent
            traders propose strategies, a Risk agent checks their work for
            overfitting and cherry-picking, and a Reporting agent writes up
            whatever survives. Every number here comes from what the system
            actually did, not a self-report — so the PM can hire, bench, or
            pivot an agent based on measured performance, the way a manager
            runs a small team of people.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    live_run_state, live_run_message = poll_live_research()
    if live_run_state == "running":
        st.info("Research is running. This page updates automatically — no need to refresh.")
        time.sleep(4)
        st.rerun()
    elif live_run_state == "completed":
        st.success(live_run_message)
    elif live_run_state == "failed":
        st.error(f"Live workflow did not complete: {live_run_message}")
    snapshot = snapshot_data()
    agents = current_agents(snapshot)
    workflow = snapshot.get("workflow", {}) if snapshot else {}
    mandate_data = snapshot.get("mandate", {}) if snapshot else (st.session_state.pm_mandate or {})
    current_round = workflow.get("round_number") or st.session_state.round_number
    # Real workflow without a real snapshot yet - covers both "nothing
    # submitted" (phase idle) and "submitted/running but the live
    # subprocess hasn't produced a result yet" (phase running). Prevents
    # showing a fabricated number ($0.48, 92%, etc.) as if it were real.
    no_real_data_yet = not snapshot
    placeholder = "—"

    st.subheader(f"Round {current_round:02d} · ETF Research")
    st.caption(
        "You can run up to 3 rounds total — this limit exists so the team "
        "can't just keep re-testing the same data until something looks "
        "good by chance. Once a round finishes, open **View Research "
        "Report** and choose to Select a strategy, Reject it, or "
        "**Request Another Round**. Each new round remembers what happened "
        "before — it doesn't start from scratch."
    )
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
        if snapshot:
            directive_notes = applied_mandate_notes(snapshot)
            if directive_notes:
                with st.expander("How the PM mandate affected this run", expanded=False):
                    for note in directive_notes:
                        st.write(f"• {note}")
    with controls:
        st.write("")
        if st.button("Create PM Research Request", type="primary", use_container_width=True):
            pm_request_dialog()
        if snapshot:
            st.caption("This round is complete. Create a new request to start another.")
        else:
            st.caption(
                "Runs the real system: all three trader agents, Risk "
                "review, and the Reporting agent. Technical Trader uses a "
                "real AI model if one is configured for this deployment; "
                "otherwise it's clearly marked as unavailable for this run."
            )
            can_start = bool(st.session_state.pm_mandate) and st.session_state.phase in {"idle", "completed"}
            if st.button("Start Research", type="primary", use_container_width=True, disabled=not can_start):
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
                st.session_state.phase = "running"
                st.session_state.notice = "Live workflow started. Refresh the snapshot while it runs."
                st.rerun()
        # Visible here directly, not behind a separate tab - the report is
        # the natural next PM action once the round settles.
        report_ready = bool(snapshot.get("reporting")) if snapshot else st.session_state.phase == "completed"
        if st.button("View Research Report", use_container_width=True, disabled=not report_ready):
            st.session_state.view = "report"
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
        for trader_id, trader_label in (
            ("technical", "Technical Trader"),
            ("fundamental", "Fundamental Trader"),
            ("quant", "Quant Trader"),
        ):
            workflow_box(trader_label, "Independent branch", agents[trader_id]["state"])
            # Same staffing-availability condition as the Agent Workforce
            # cards below and agent_detail() itself - only a real, clickable
            # action when it would actually do something.
            staffing_actionable = (
                (snapshot and workflow.get("status") == "Waiting for PM Decision")
                or (not snapshot and st.session_state.phase == "completed")
            )
            if staffing_actionable:
                if st.button("Hire / Bench / Pivot", key=f"workflow-staff-{trader_id}", use_container_width=True):
                    st.session_state.selected_agent = trader_id
                    st.session_state.view = "detail"
                    st.rerun()
    with risk_col:
        st.markdown("<div class='workflow-middle-spacer'></div>", unsafe_allow_html=True)
        workflow_box("Risk Review", "Reviews all traders' work", agents["risk"]["state"])
    with report_col:
        st.markdown("<div class='workflow-middle-spacer'></div>", unsafe_allow_html=True)
        workflow_box("Reporting", "PM-facing memo", agents["reporting"]["state"])
    st.caption("Technical, Fundamental, and Quant Trader all work at the same time on the same request. Risk Review starts only once all three finish.")

    st.markdown("#### Current Round Summary")
    metric_cols = st.columns(4)
    summary = snapshot.get("summary_metrics", {}) if snapshot else {}
    metric_cols[0].metric(
        "Research Completion Time",
        placeholder if no_real_data_yet else
        summary.get("research_completion_time") if snapshot else
        ("6m 42s" if st.session_state.phase == "completed" else "In progress"),
    )
    total_cost = summary.get("total_api_cost") if snapshot else ("$1.13" if st.session_state.phase == "completed" else "$0.48")
    metric_cols[1].metric(
        "Total API Cost",
        placeholder if no_real_data_yet else
        (f"${total_cost}" if snapshot and total_cost != "N/A" else total_cost),
    )
    # Active Agents and Round Status are not fabricated demo numbers -
    # they reflect the PM's real staffing choices and the workflow's
    # real phase, so they're shown regardless of no_real_data_yet.
    active = summary.get("active_agents") if snapshot else sum(status == "Active" for status in st.session_state.staffing.values())
    metric_cols[2].metric("Active Agents", f"{active} / 5")
    metric_cols[3].metric(
        "Round Status",
        workflow.get("status") if snapshot else st.session_state.phase.title(),
    )
    st.caption(metrics_disclaimer(snapshot))

    st.divider()
    st.markdown(f"##### Round {current_round:02d} · Agent Workforce")
    st.caption(metrics_disclaimer(snapshot))
    for row in [["technical", "fundamental", "quant"], ["risk", "reporting"]]:
        columns = st.columns(3)
        for col, agent_id in zip(columns, row):
            agent = agents[agent_id]
            with col:
                staffing_status = (
                    effective_staffing(snapshot)[agent_id]
                    if snapshot and workflow.get("status") == "Waiting for PM Decision"
                    else agent.get("staffing_status") if snapshot else st.session_state.staffing[agent_id]
                )
                # Mirrors agent_detail()'s exact staffing-availability check,
                # so this hint only appears when the real Hire/Bench/Pivot
                # controls (on that page) are actually usable - previously
                # this was only discoverable by clicking into an agent.
                staffing_actionable = agent_id in {"technical", "fundamental", "quant"} and (
                    (snapshot and workflow.get("status") == "Waiting for PM Decision")
                    or (not snapshot and st.session_state.phase == "completed")
                )
                st.markdown(f"<div class='agent-name'>{agent['name']}</div>{status_badge(agent['state'])} &nbsp; <span style='font-size:.85rem'>Next round: {staffing_status}</span>", unsafe_allow_html=True)
                if staffing_actionable:
                    st.markdown(
                        "<div style='color:var(--teal); font-size:.82rem; font-weight:600; margin:.2rem 0;'>"
                        "🔧 Staffing available — Hire, Bench, or Pivot on the detail page below</div>",
                        unsafe_allow_html=True,
                    )
                st.caption(agent["role"])
                st.write(f"**Current task:** {agent['task']}")
                a, b = st.columns(2)
                a.caption(f"Success rate\n\n**{placeholder if no_real_data_yet else agent_value(agent, 'success_rate')}**")
                b.caption(f"Completion time\n\n**{placeholder if no_real_data_yet else agent_value(agent, 'task_completion_time')}**")
                c, d = st.columns(2)
                c.caption(f"API cost\n\n**{placeholder if no_real_data_yet else agent_value(agent, 'api_cost')}**")
                retries_failed_text = placeholder if no_real_data_yet else f"{agent_value(agent, 'retry_count')} / {agent_value(agent, 'failed_count')}"
                d.caption(f"Retries / Failed\n\n**{retries_failed_text}**")
                if st.button("View Agent Detail", key=f"view-{agent_id}", use_container_width=True):
                    st.session_state.selected_agent = agent_id
                    st.session_state.view = "detail"
                    st.rerun()

    st.divider()
    st.markdown("#### Recent Memory / Previous Lessons")
    if snapshot:
        memory = snapshot.get("memory", {})
        context = memory.get("context") or {}
        lessons = list(snapshot.get("mandate", {}).get("prior_round_lessons") or [])
        # The runner stores a generic receipt for every PM decision. It is
        # useful for auditing, but repeating it in the PM-facing Memory
        # panel adds no decision context. Show only distinct, actionable
        # lessons here.
        context_lessons = [
            lesson for lesson in (context.get("lessons_for_next_round") or [])
            if lesson != "PM decision recorded from the live dashboard."
            and lesson not in lessons
        ]
        memory_entries = [
            f"Previous decision record: {memory.get('record_id') or 'loaded for this round'}",
            *[f"Next-round directive: {lesson}" for lesson in lessons],
            *[f"Saved lesson: {lesson}" for lesson in context_lessons],
        ]
        if len(memory_entries) == 1:
            memory_entries.append("No previous-round lessons have been recorded yet.")
    else:
        memory_entries = [
            "Live Memory will be available after this research round reaches PM review."
        ]
    for entry in memory_entries[:5]:
        st.write(f"• {entry}")


def agent_detail() -> None:
    show_header()
    snapshot = snapshot_data()
    agents = current_agents(snapshot)
    agent_id = st.session_state.selected_agent
    agent = agents[agent_id]
    no_real_data_yet = not snapshot
    placeholder = "—"
    if st.button("← Back to Dashboard"):
        st.session_state.view = "dashboard"
        st.rerun()
    st.title(agent["name"])
    awaiting_pm_decision = bool(
        snapshot and snapshot.get("workflow", {}).get("status") == "Waiting for PM Decision"
    )
    staffing_status = (
        effective_staffing(snapshot)[agent_id]
        if awaiting_pm_decision
        else agent.get("staffing_status") if snapshot else st.session_state.staffing[agent_id]
    )
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
        elif no_real_data_yet:
            st.caption("Nothing to show yet - this agent hasn't produced a result for the current round.")
        else:
            st.write(agent_value(agent, "output"))
        times = st.columns(2)
        times[0].markdown(f"**Start Time**  \n{placeholder if no_real_data_yet else agent_value(agent, 'start_time')}")
        times[1].markdown(f"**End Time**  \n{placeholder if no_real_data_yet else agent_value(agent, 'end_time')}")
        st.markdown(f"**Next Step**  \n{placeholder if no_real_data_yet else agent_value(agent, 'next_step')}")
        st.markdown(f"**Error Message**  \n{placeholder if no_real_data_yet else agent_value(agent, 'error_message')}")
    with metrics:
        st.subheader("Productivity Metrics")
        st.metric("Task Completion Time", placeholder if no_real_data_yet else agent_value(agent, "task_completion_time"))
        st.metric("Success Rate", placeholder if no_real_data_yet else agent_value(agent, "success_rate"))
        st.metric("API Cost", placeholder if no_real_data_yet else agent_value(agent, "api_cost"))
        st.metric("Retry Count", placeholder if no_real_data_yet else agent_value(agent, "retry_count"))
        st.metric("Failed Count", placeholder if no_real_data_yet else agent_value(agent, "failed_count"))
        st.caption(metrics_disclaimer(snapshot))

    st.divider()
    if snapshot:
        with st.expander("Technical details · exported agent data"):
            st.json(agent)
    elif not no_real_data_yet:
        st.subheader("Risk Feedback")
        st.info(agent["risk_feedback"])
    st.subheader("Staffing Actions")
    if agent_id not in {"technical", "fundamental", "quant"}:
        st.caption("Risk Review and Reporting are downstream workflow stages, not next-round staffing choices.")
        return
    if snapshot and not awaiting_pm_decision:
        st.caption("This workflow is closed. Staffing choices are available only while a PM decision is pending.")
        return
    if not snapshot and st.session_state.phase != "completed":
        st.caption("Staffing changes are available after the current round is completed and apply to the next round.")
        return

    st.caption(
        "These choices configure the next round only. Pivot excludes this agent's current "
        "candidate ticker and records your reason in the next-round mandate."
    )
    if snapshot:
        specialist_id = STAFFING_KEY_TO_SPECIALIST_ID[agent_id]
        prior_pivot_applied = any(
            str(lesson).startswith(f"PIVOT[{specialist_id}]:")
            for lesson in snapshot.get("mandate", {}).get("prior_round_lessons", [])
        )
        if prior_pivot_applied:
            st.info(
                "A previous Pivot has already been applied to this completed round. "
                "Any action below concerns the next round and this agent's current candidate."
            )
    selected_action = st.session_state.next_round_actions.get(agent_id)
    if selected_action:
        st.success(f"{selected_action} selected for this agent's next round.")
        if st.button("Change next-round selection", key=f"change-{agent_id}"):
            if selected_action == "Pivot":
                specialist_id = STAFFING_KEY_TO_SPECIALIST_ID[agent_id]
                st.session_state.pending_pivot_lessons = [
                    lesson for lesson in st.session_state.pending_pivot_lessons
                    if not lesson.startswith(f"PIVOT[{specialist_id}]:")
                ]
            st.session_state.next_round_actions.pop(agent_id, None)
            # Restore the actual current-round status before presenting the
            # alternatives. For example, a currently benched Quant Trader
            # returns to a single Hire option, not Bench/Pivot.
            if snapshot:
                st.session_state.staffing[agent_id] = agent.get("staffing_status", "Active")
            st.rerun()
        return
    staffing_status = effective_staffing(snapshot)[agent_id] if snapshot else st.session_state.staffing[agent_id]
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
            if decision_type == "request_another_round" and round_number >= MAX_RESEARCH_ROUNDS:
                st.error(f"This pilot is limited to {MAX_RESEARCH_ROUNDS} research rounds. Select a strategy or reject this round.")
                return
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
            if decision_type == "request_another_round":
                # Continuing research is a workflow-level action. Return to
                # the dashboard so the PM can watch the next round progress.
                st.session_state.view = "dashboard"
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
                format_func=lambda cid: candidate_label(snapshot, cid),
            )
        else:
            selected = None
            st.caption("No surviving candidate this round - Select Strategy is unavailable.")

        one, two, three = st.columns(3)
        if one.button("Select Strategy", type="primary", use_container_width=True, disabled=not selected):
            _resume("select", selected_candidate_id=selected)
        if two.button("Reject", use_container_width=True):
            _resume("reject")
        if three.button(
            "Request Another Round",
            use_container_width=True,
            disabled=round_number >= MAX_RESEARCH_ROUNDS,
        ):
            _resume("request_another_round")
        if round_number >= MAX_RESEARCH_ROUNDS:
            st.caption(f"The {MAX_RESEARCH_ROUNDS}-round validation budget has been reached.")
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
