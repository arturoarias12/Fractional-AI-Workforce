"""One dashboard-facing entry point for a compiled Fractional AI workflow.

This module does not construct agents.  The orchestration owner supplies a
compiled LangGraph graph with its real Technical, Fundamental, Quant, Risk,
Reporting, and Memory nodes.  The dashboard only needs this small boundary:
start a run, resume a PM decision, and receive a snapshot after either action.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from protocols import PMDecision, PMMandate


SnapshotWriter = Callable[[Mapping[str, Any]], Any | Awaitable[Any]]


class WorkflowRunner:
    """Run or resume one compiled graph without exposing individual agents."""

    def __init__(self, *, compiled_graph: Any, snapshot_writer: SnapshotWriter) -> None:
        self._compiled_graph = compiled_graph
        self._snapshot_writer = snapshot_writer

    async def start_workflow(
        self, workflow_input: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Validate dashboard input, start a graph run, and publish its state."""

        payload = dict(workflow_input)
        mandate = PMMandate.model_validate(payload.get("pm_mandate"))
        payload["pm_mandate"] = mandate.model_dump(mode="json")
        payload.setdefault("run_id", mandate.workflow_id)

        state = await self._compiled_graph.ainvoke(
            payload,
            config=self._config_for(str(payload["run_id"])),
        )
        await self._publish_snapshot(state)
        return state

    async def resume_workflow(
        self, run_id: str, pm_decision: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Resume the graph's durable PM interrupt with a validated decision."""

        decision = PMDecision.model_validate(pm_decision)
        if decision.workflow_id != run_id:
            raise ValueError("PM decision workflow_id must match the run_id.")

        try:
            from langgraph.types import Command
        except ImportError as error:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Install the project's langgraph extra to resume a PM decision."
            ) from error

        state = await self._compiled_graph.ainvoke(
            Command(resume={"pm_decision": decision.model_dump(mode="json")}),
            config=self._config_for(run_id),
        )
        await self._publish_snapshot(state)
        return state

    @staticmethod
    def _config_for(run_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": run_id}}

    async def _publish_snapshot(self, state: Mapping[str, Any]) -> None:
        result = self._snapshot_writer(state)
        if hasattr(result, "__await__"):
            await result
