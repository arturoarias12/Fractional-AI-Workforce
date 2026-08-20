"""Convert graph-owned ``WorkflowState`` data into dashboard-safe JSON.

The LangGraph workflow remains the source of truth.  This module deliberately
does not invoke agents or mutate graph state; it gives the Streamlit dashboard
a stable, small read model that can evolve independently from the graph.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluation.harness import HarnessReport, SuccessMetric, grade_workflow_state


SNAPSHOT_SCHEMA_VERSION = "0.1.0"
DEFAULT_SNAPSHOT_PATH = Path(__file__).parent / "data" / "workflow_snapshot.json"

AGENTS: dict[str, dict[str, str]] = {
    "technical": {
        "workflow_id": "technical_trader_agent",
        "name": "Technical Trader",
        "role": "Price action, volume and indicators",
    },
    "fundamental": {
        "workflow_id": "fundamental_trader_agent",
        "name": "Fundamental Trader",
        "role": "ETF fund characteristics and exposure",
    },
    "quant": {
        "workflow_id": "quant_trader_agent",
        "name": "Quant Trader",
        "role": "Statistical anomalies and correlations",
    },
    "risk": {
        "workflow_id": "risk_agent",
        "name": "Risk / Skeptic",
        "role": "Overfitting and cherry-picking review",
    },
    "reporting": {
        "workflow_id": "reporting_agent",
        "name": "Reporting",
        "role": "PM-facing research memo",
    },
}

_STATE_LABELS = {
    "idle": "Idle",
    "assigned": "Assigned",
    "running": "Running",
    "waiting_for_tool": "Waiting for Tool",
    "waiting_for_review": "Waiting for Review",
    "completed": "Completed",
    "failed": "Failed",
}


def build_dashboard_snapshot(workflow_state: Mapping[str, Any]) -> dict[str, Any]:
    """Build a JSON-compatible dashboard view from one final graph state.

    Missing workflow fields are represented as ``None``/``N/A`` rather than
    omitted.  That lets the UI preserve the State Graph and productivity-metric
    schema while individual agents are still being integrated.
    """

    state = dict(workflow_state)
    lifecycle = _mapping(state.get("agent_lifecycle"))
    active = {str(item) for item in _sequence(state.get("active_specialists"))}
    events = _sequence(state.get("operational_events"))
    # Single source of truth for every non-time productivity metric - see
    # src/evaluation/harness.py. Previously this module computed its own,
    # separate metrics locally and left success_rate hardcoded to "N/A"
    # unconditionally, duplicating (and disagreeing with) the harness's
    # already-tested logic. Graded once per snapshot build, not per agent.
    harness_report = grade_workflow_state(state, success_metric=SuccessMetric.EXECUTION)

    agents = {
        dashboard_id: _agent_snapshot(
            dashboard_id=dashboard_id,
            definition=definition,
            lifecycle=_mapping(lifecycle.get(definition["workflow_id"])),
            state=state,
            active=definition["workflow_id"] in active,
            harness_report=harness_report,
        )
        for dashboard_id, definition in AGENTS.items()
    }

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "source": "workflow_state",
        "generated_at": datetime.now().astimezone().isoformat(),
        "workflow": {
            "workflow_id": state.get("workflow_id"),
            "run_id": state.get("run_id"),
            "round_number": state.get("round_number"),
            "status": _workflow_status(state, agents),
        },
        "mandate": _mapping(state.get("pm_mandate")),
        "agents": agents,
        "summary_metrics": {
            **harness_report.summary_metrics(),
            "active_agents": sum(agent["staffing_status"] == "Active" for agent in agents.values()),
        },
        "risk_review": _mapping(state.get("risk_review_response")),
        "risk_failure": _mapping(state.get("risk_failure")),
        "reporting": _mapping(state.get("reporting_output")),
        "reporting_failure": _mapping(state.get("reporting_failure")),
        "pm_decision": _mapping(state.get("pm_decision")),
        "memory": {
            "record_id": state.get("memory_record_id"),
            "context": state.get("memory_context"),
        },
        "operational_events": events,
    }


def write_dashboard_snapshot(
    workflow_state: Mapping[str, Any], path: Path | str = DEFAULT_SNAPSHOT_PATH
) -> Path:
    """Serialize a graph state for the dashboard's read-only snapshot mode."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(build_dashboard_snapshot(workflow_state), indent=2, default=str)
        + "\n",
        encoding="utf-8",
    )
    return destination


def load_dashboard_snapshot(path: Path | str = DEFAULT_SNAPSHOT_PATH) -> dict[str, Any]:
    """Load and minimally validate a previously exported dashboard snapshot."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "agents" not in payload:
        raise ValueError("Dashboard snapshot must be an object with an 'agents' field.")
    return payload


def _agent_snapshot(
    *,
    dashboard_id: str,
    definition: Mapping[str, str],
    lifecycle: Mapping[str, Any],
    state: Mapping[str, Any],
    active: bool,
    harness_report: HarnessReport,
) -> dict[str, Any]:
    agent_id = definition["workflow_id"]
    package = _package_for_agent(dashboard_id, state)
    metrics = _metrics_for_agent(agent_id, lifecycle, harness_report)
    lifecycle_state = str(lifecycle.get("current_state", ""))

    return {
        "agent_id": agent_id,
        "name": definition["name"],
        "role": definition["role"],
        "staffing_status": "Active" if active else "Benched",
        "state": _STATE_LABELS.get(lifecycle_state, "Idle" if not active else "N/A"),
        "task": lifecycle.get("current_task") or ("Benched for this round" if not active else "N/A"),
        "input": lifecycle.get("input"),
        "output": lifecycle.get("output") or _package_summary(package),
        "start_time": lifecycle.get("start_time"),
        "end_time": lifecycle.get("end_time"),
        "next_step": lifecycle.get("next_step"),
        "error_message": lifecycle.get("error_message"),
        "metrics": metrics,
        "package": package,
    }


def _package_for_agent(agent_id: str, state: Mapping[str, Any]) -> Mapping[str, Any]:
    key = {
        "technical": "technical_trader_package",
        "fundamental": "fundamental_trader_package",
        "quant": "quant_trader_package",
    }.get(agent_id)
    if key:
        return _mapping(state.get(key))
    if agent_id == "risk":
        return _mapping(state.get("risk_review_response"))
    if agent_id == "reporting":
        return _mapping(state.get("reporting_output"))
    return {}


def _package_summary(package: Mapping[str, Any]) -> str | None:
    if not package:
        return None
    for field in ("hypothesis", "strategy_memo_reference", "summary"):
        if package.get(field):
            return str(package[field])
    return "Workflow output recorded."


def _metrics_for_agent(
    agent_id: str, lifecycle: Mapping[str, Any], harness_report: HarnessReport,
) -> dict[str, Any]:
    productivity = harness_report.agents.get(agent_id)
    if productivity is None:
        # No operational_events were recorded for this agent at all (e.g. it
        # was benched this round) - nothing measured, not zero.
        return {
            "task_completion_time": _duration(lifecycle.get("start_time"), lifecycle.get("end_time")),
            "success_rate": "N/A",
            "api_cost": "N/A",
            "retry_count": "N/A",
            "failed_count": "N/A",
        }

    metrics = dict(productivity.as_dashboard_metrics(harness_report.success_metric))
    if metrics["task_completion_time"] == "N/A":
        # The harness only measures latency from timed events; fall back to
        # the lifecycle's own start/end timestamps if those exist instead.
        metrics["task_completion_time"] = _duration(
            lifecycle.get("start_time"), lifecycle.get("end_time"),
        )
    return metrics


def _workflow_status(state: Mapping[str, Any], agents: Mapping[str, Mapping[str, Any]]) -> str:
    if state.get("pending_human_action"):
        return "Waiting for PM Decision"
    states = {agent["state"] for agent in agents.values()}
    if "Failed" in states:
        return "Needs Review"
    if "Running" in states or "Assigned" in states:
        return "Running"
    if "Completed" in states:
        return "Completed"
    return "Idle"


def _duration(start: Any, end: Any) -> str:
    if not start or not end:
        return "N/A"
    try:
        return str(datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start)))
    except ValueError:
        return "N/A"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    return list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
