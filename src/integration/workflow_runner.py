"""One dashboard-facing entry point for a compiled Fractional AI workflow.

This module does not construct agents.  The orchestration owner supplies a
compiled LangGraph graph with its real Technical, Fundamental, Quant, Risk,
Reporting, and Memory nodes.  The dashboard only needs this small boundary:
start a run, resume a PM decision, and receive a snapshot after either action.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from inspect import isawaitable
from typing import Any

from protocols import PMDecision, PMMandate


SnapshotWriter = Callable[[Mapping[str, Any]], Any | Awaitable[Any]]


class WorkflowRunner:
    """Run or resume one compiled graph without exposing individual agents."""

    def __init__(self, *, compiled_graph: Any, snapshot_writer: SnapshotWriter) -> None:
        self._compiled_graph = compiled_graph
        self._snapshot_writer = snapshot_writer

    async def start_workflow(
        self, workflow_input: Mapping[str, Any], *, publish_progress: bool = True
    ) -> Mapping[str, Any]:
        """Validate dashboard input, start a graph run, and publish its state.

        LangGraph's checkpoint state is published after every node update when
        the compiled graph supports streaming. This is what lets a polling
        dashboard show lifecycle transitions instead of only the final result.
        """

        payload = dict(workflow_input)
        mandate = PMMandate.model_validate(payload.get("pm_mandate"))
        payload["pm_mandate"] = mandate.model_dump(mode="json")
        payload.setdefault("run_id", mandate.workflow_id)

        config = self._config_for(str(payload["run_id"]))
        if publish_progress and hasattr(self._compiled_graph, "astream"):
            return await self._stream_and_publish(payload, config=config)

        state = await self._compiled_graph.ainvoke(payload, config=config)
        await self._publish_snapshot(state)
        return state

    async def resume_workflow(
        self,
        run_id: str,
        pm_decision: Mapping[str, Any],
        *,
        state_update: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Resume the graph's durable PM interrupt with a validated decision.

        ``state_update`` is optional and additive (flagged for review - added
        to support staffing changes for the *next* round, e.g.
        ``{"active_specialists": [...]}`` when the PM chooses to bench/hire
        an agent before requesting another round; existing callers that only
        pass ``pm_decision`` are unaffected).
        """

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
            Command(
                resume={"pm_decision": decision.model_dump(mode="json")},
                update=dict(state_update) if state_update else None,
            ),
            config=self._config_for(run_id),
        )
        await self._publish_snapshot(state)
        return state

    @staticmethod
    def _config_for(run_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": run_id}}

    async def _publish_snapshot(self, state: Mapping[str, Any]) -> None:
        result = self._snapshot_writer(state)
        if isawaitable(result):
            await result

    async def _stream_and_publish(
        self,
        payload: Mapping[str, Any],
        *,
        config: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Publish each checkpoint while preserving the graph's final state."""

        latest: Mapping[str, Any] = {}
        async for _update in self._compiled_graph.astream(
            payload,
            config=config,
            stream_mode="updates",
        ):
            checkpoint = await self._compiled_graph.aget_state(config)
            values = getattr(checkpoint, "values", checkpoint)
            if isinstance(values, Mapping):
                latest = values
                await self._publish_snapshot(latest)

        if not latest:
            checkpoint = await self._compiled_graph.aget_state(config)
            values = getattr(checkpoint, "values", checkpoint)
            if isinstance(values, Mapping):
                latest = values
        if latest:
            await self._publish_snapshot(latest)
        return latest
