"""Contract checks for the dashboard-facing workflow runner."""

from __future__ import annotations

import asyncio

from integration import WorkflowRunner


class RecordingGraph:
    def __init__(self) -> None:
        self.payload = None
        self.config = None

    async def ainvoke(self, payload, *, config):
        self.payload = payload
        self.config = config
        return {"workflow_id": payload["pm_mandate"]["workflow_id"], "agent_lifecycle": {}}


class StreamingGraph(RecordingGraph):
    async def astream(self, payload, *, config, stream_mode):
        self.payload = payload
        self.config = config
        self.state = {"workflow_id": payload["pm_mandate"]["workflow_id"], "agent_lifecycle": {}}
        yield {"prepare_round": {}}
        self.state = {"workflow_id": payload["pm_mandate"]["workflow_id"], "agent_lifecycle": {"quant_trader_agent": {"current_state": "completed"}}}
        yield {"quant_trader": {}}

    async def aget_state(self, config):
        assert config == self.config
        return type("Checkpoint", (), {"values": self.state})()


def test_start_validates_mandate_and_publishes_state() -> None:
    graph = RecordingGraph()
    snapshots = []
    runner = WorkflowRunner(compiled_graph=graph, snapshot_writer=snapshots.append)
    workflow_input = {
        "pm_mandate": {
            "workflow_id": "pilot-run-1",
            "task_id": "pm-mandate-1",
            "as_of_date": "2026-08-18",
            "investment_objective": "Evaluate diversified ETF strategies.",
            "permitted_asset_universe": ["SPY", "QQQ"],
        },
        "active_specialists": ["technical_trader_agent", "quant_trader_agent"],
    }

    state = asyncio.run(runner.start_workflow(workflow_input))

    assert state["workflow_id"] == "pilot-run-1"
    assert graph.config == {"configurable": {"thread_id": "pilot-run-1"}}
    assert graph.payload["run_id"] == "pilot-run-1"
    assert snapshots == [state]


def test_start_publishes_checkpoints_when_graph_supports_streaming() -> None:
    graph = StreamingGraph()
    snapshots = []
    runner = WorkflowRunner(compiled_graph=graph, snapshot_writer=snapshots.append)
    workflow_input = {
        "pm_mandate": {
            "workflow_id": "stream-run-1",
            "task_id": "pm-mandate-1",
            "as_of_date": "2026-08-18",
            "investment_objective": "Evaluate ETF strategies.",
        }
    }

    state = asyncio.run(runner.start_workflow(workflow_input))

    assert state["agent_lifecycle"]["quant_trader_agent"]["current_state"] == "completed"
    assert len(snapshots) >= 2


class ResumeRecordingGraph:
    """Records whatever is passed to ainvoke - a Command, for resume calls."""

    def __init__(self) -> None:
        self.payload = None
        self.config = None

    async def ainvoke(self, payload, *, config):
        self.payload = payload
        self.config = config
        return {"workflow_id": "resumed", "agent_lifecycle": {}}


def test_resume_passes_pm_decision_and_optional_state_update() -> None:
    graph = ResumeRecordingGraph()
    snapshots = []
    runner = WorkflowRunner(compiled_graph=graph, snapshot_writer=snapshots.append)
    pm_decision = {
        "decision_id": "pilot-run-1.decision-1",
        "workflow_id": "pilot-run-1",
        "decision": "request_another_round",
        "rationale": "Widening the universe for round 2.",
    }

    asyncio.run(runner.resume_workflow(
        "pilot-run-1",
        pm_decision,
        state_update={"active_specialists": ["fundamental_trader_agent", "risk_agent"]},
    ))

    command = graph.payload
    assert command.resume["pm_decision"]["decision"] == "request_another_round"
    assert command.update == {"active_specialists": ["fundamental_trader_agent", "risk_agent"]}


def test_resume_without_state_update_still_works() -> None:
    graph = ResumeRecordingGraph()
    snapshots = []
    runner = WorkflowRunner(compiled_graph=graph, snapshot_writer=snapshots.append)
    pm_decision = {
        "decision_id": "pilot-run-2.decision-1",
        "workflow_id": "pilot-run-2",
        "decision": "reject",
        "rationale": "No candidate cleared Risk review.",
    }

    asyncio.run(runner.resume_workflow("pilot-run-2", pm_decision))

    command = graph.payload
    assert command.resume["pm_decision"]["decision"] == "reject"
    assert command.update is None
