"""Standalone runtime and LangGraph-compatible adapter for Quant Trader.

Mirrors ``technical_trader.runtime`` so the production graph can wire in
whichever traders are ready without special-casing this one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import ValidationError

from protocols import (
    ConstraintCheckStatus,
    MandateConstraintAssessment,
    PMMandate,
    ResearchExecutionContext,
    RunStatus,
    SpecialistId,
    TaskLineage,
    TraderFailure,
    TraderStrategyPackage,
    TraderTask,
)

from .agent import QuantTraderAgent
from .errors import MandateValidationError


class QuantTraderRuntime:
    """Application boundary for hiring and invoking one Quant Trader."""

    def __init__(self, *, agent: QuantTraderAgent) -> None:
        self._agent = agent

    @property
    def agent(self) -> QuantTraderAgent:
        return self._agent

    async def research(
        self,
        mandate: PMMandate | Mapping[str, Any],
        *,
        execution_context: (
            ResearchExecutionContext | Mapping[str, Any] | None
        ) = None,
    ) -> TraderStrategyPackage:
        validated = self._validate_mandate(mandate)
        context = self._validate_execution_context(
            mandate=validated, execution_context=execution_context,
        )
        task = self._task(validated, context)
        return await self._agent.run(task)

    @staticmethod
    def _validate_mandate(mandate: PMMandate | Mapping[str, Any]) -> PMMandate:
        if isinstance(mandate, PMMandate):
            return mandate
        if not isinstance(mandate, Mapping):
            raise MandateValidationError(
                "QuantTraderRuntime requires a PMMandate or mapping."
            )
        try:
            return PMMandate.model_validate(mandate)
        except ValidationError as exc:
            raise MandateValidationError(
                f"Invalid normalized PM mandate: {exc}"
            ) from exc

    @staticmethod
    def _validate_execution_context(
        *,
        mandate: PMMandate,
        execution_context: (
            ResearchExecutionContext | Mapping[str, Any] | None
        ),
    ) -> ResearchExecutionContext:
        if execution_context is None:
            return ResearchExecutionContext(run_id=mandate.workflow_id, round_number=1)
        if isinstance(execution_context, ResearchExecutionContext):
            return execution_context
        if not isinstance(execution_context, Mapping):
            raise MandateValidationError(
                "QuantTraderRuntime execution_context must be a "
                "ResearchExecutionContext or mapping."
            )
        try:
            return ResearchExecutionContext.model_validate(execution_context)
        except ValidationError as exc:
            raise MandateValidationError(
                f"Invalid Quant Trader execution context: {exc}"
            ) from exc

    @staticmethod
    def _task(
        mandate: PMMandate, execution_context: ResearchExecutionContext,
    ) -> TraderTask:
        lineage = TaskLineage(
            workflow_id=mandate.workflow_id,
            task_id=(
                f"{mandate.task_id}.round-"
                f"{execution_context.round_number}.quant.trader"
            ),
            parent_task_id=mandate.task_id,
            source_task_id=mandate.task_id,
            attempt=execution_context.attempt,
        )
        return TraderTask(
            mandate=mandate,
            lineage=lineage,
            trader_id=SpecialistId.QUANT_TRADER,
            execution_context=execution_context,
        )


def make_langgraph_node(
    runtime: QuantTraderRuntime,
    *,
    input_key: str = "pm_mandate",
    output_key: str = "quant_trader_package",
) -> Callable[[Mapping[str, Any]], Awaitable[dict[str, Any]]]:
    """Return an async graph node without importing or pinning LangGraph."""

    async def node(state: Mapping[str, Any]) -> dict[str, Any]:
        if input_key not in state:
            raise KeyError(f"Graph state is missing required key: {input_key}")
        mandate = runtime._validate_mandate(state[input_key])
        context_payload = {
            "run_id": state.get("run_id") or mandate.workflow_id,
            "round_number": state.get("round_number", 1),
            "attempt": state.get("trader_attempt", 1),
            "canonical_universe_id": state.get("canonical_universe_id"),
            "evaluation_policy_id": state.get("evaluation_policy_id"),
        }
        package = await runtime.research(mandate, execution_context=context_payload)
        return {output_key: package.model_dump(mode="json")}

    return node


__all__ = ["QuantTraderRuntime", "make_langgraph_node"]
