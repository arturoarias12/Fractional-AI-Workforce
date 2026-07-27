"""Standalone runtime and LangGraph-compatible adapter for one hireable agent."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import ValidationError

from .agents import TechnicalTraderAgent
from .errors import MandateValidationError
from .execution import ExecutionPolicy
from .model_client import MetricsSink, ModelClient
from .models.common import TaskLineage, TraderRunStatus, TraderType
from .models.mandate import PMMandate
from .models.trader import (
    ConstraintCheckStatus,
    MandateConstraintAssessment,
    TraderFailure,
    TraderStrategyPackage,
    TraderTask,
)
from .services import BacktestEngine, DataService
from .tools import TechnicalAnalysisInputAdapter, TechnicalAnalysisToolkit


class TechnicalTraderRuntime:
    """Application boundary for hiring and invoking one Technical Trader."""

    def __init__(
        self,
        *,
        agent: TechnicalTraderAgent,
        execution_policy: ExecutionPolicy,
    ) -> None:
        self._agent = agent
        self._execution_policy = execution_policy

    @property
    def agent(self) -> TechnicalTraderAgent:
        return self._agent

    async def research(
        self,
        mandate: PMMandate | Mapping[str, Any],
    ) -> TraderStrategyPackage:
        validated = self._validate_mandate(mandate)
        task = self._task(validated)
        try:
            async with asyncio.timeout(
                self._execution_policy.trader_timeout_seconds
            ):
                return await self._agent.run(task)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return TraderStrategyPackage(
                package_id=f"{task.lineage.task_id}.package",
                trader_type=TraderType.TECHNICAL,
                lineage=task.lineage,
                mandate_reference=validated.reference(),
                status=TraderRunStatus.FAILED,
                constraint_assessment=MandateConstraintAssessment(
                    status=ConstraintCheckStatus.NOT_EVALUATED,
                    requires_risk_validation=True,
                ),
                failures=[
                    TraderFailure(
                        stage="technical_trader_runtime",
                        message=(
                            "Technical Trader exceeded its configured "
                            f"{self._execution_policy.trader_timeout_seconds:g}"
                            "-second deadline."
                        ),
                        retryable=True,
                    )
                ],
                eligible_for_risk_review=False,
            )

    @staticmethod
    def _validate_mandate(
        mandate: PMMandate | Mapping[str, Any],
    ) -> PMMandate:
        if isinstance(mandate, PMMandate):
            return mandate
        if not isinstance(mandate, Mapping):
            raise MandateValidationError(
                "TechnicalTraderRuntime requires a PMMandate or mapping."
            )
        try:
            return PMMandate.model_validate(mandate)
        except ValidationError as exc:
            raise MandateValidationError(
                f"Invalid normalized PM mandate: {exc}"
            ) from exc

    @staticmethod
    def _task(mandate: PMMandate) -> TraderTask:
        lineage = TaskLineage(
            workflow_id=mandate.workflow_id,
            task_id=f"{mandate.task_id}.technical.trader",
            parent_task_id=mandate.task_id,
            source_task_id=mandate.task_id,
        )
        return TraderTask(
            mandate=mandate,
            lineage=lineage,
            trader_type=TraderType.TECHNICAL,
        )


def create_technical_trader_runtime(
    *,
    model_client: ModelClient,
    data_service: DataService,
    backtest_engine: BacktestEngine,
    technical_input_adapter: TechnicalAnalysisInputAdapter | None = None,
    technical_toolkit: TechnicalAnalysisToolkit | None = None,
    metrics_sink: MetricsSink | None = None,
    execution_policy: ExecutionPolicy | None = None,
) -> TechnicalTraderRuntime:
    policy = execution_policy or ExecutionPolicy()
    return TechnicalTraderRuntime(
        agent=TechnicalTraderAgent(
            model_client=model_client,
            data_service=data_service,
            backtest_engine=backtest_engine,
            technical_input_adapter=technical_input_adapter,
            technical_toolkit=technical_toolkit,
            metrics_sink=metrics_sink,
            execution_policy=policy,
        ),
        execution_policy=policy,
    )


def make_langgraph_node(
    runtime: TechnicalTraderRuntime,
    *,
    input_key: str = "pm_mandate",
    output_key: str = "technical_trader_package",
) -> Callable[[Mapping[str, Any]], Awaitable[dict[str, Any]]]:
    """Return an async graph node without importing or pinning LangGraph."""

    async def node(state: Mapping[str, Any]) -> dict[str, Any]:
        if input_key not in state:
            raise KeyError(f"Graph state is missing required key: {input_key}")
        package = await runtime.research(state[input_key])
        return {output_key: package.model_dump(mode="json")}

    return node
