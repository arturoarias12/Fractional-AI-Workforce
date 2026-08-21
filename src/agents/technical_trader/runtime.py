"""Standalone runtime and LangGraph-compatible adapter for one hireable agent."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from math import isfinite
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

from .agents import TechnicalTraderAgent
from .benchmark import BenchmarkSelectionPolicy
from .diagnostics import TechnicalDiagnosticsSink
from .errors import MandateValidationError
from .execution import ExecutionPolicy
from .model_client import MetricsSink, ModelClient
from .prompts import DEFAULT_CANDIDATE_PROMPT_ASSETS
from .services import BacktestEngine, DataService, ValidationSplitPolicy
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
        *,
        execution_context: (
            ResearchExecutionContext | Mapping[str, Any] | None
        ) = None,
    ) -> TraderStrategyPackage:
        """Produce one shared package containing one multi-ETF strategy."""

        validated = self._validate_mandate(mandate)
        context = self._validate_execution_context(
            mandate=validated,
            execution_context=execution_context,
        )
        task = self._task(validated, context)
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
                trader_id=SpecialistId.TECHNICAL_TRADER,
                lineage=task.lineage,
                mandate_reference=validated.reference(),
                status=RunStatus.FAILED,
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
    def _validate_execution_context(
        *,
        mandate: PMMandate,
        execution_context: (
            ResearchExecutionContext | Mapping[str, Any] | None
        ),
    ) -> ResearchExecutionContext:
        if execution_context is None:
            return ResearchExecutionContext(
                run_id=mandate.workflow_id,
                round_number=1,
            )
        if isinstance(execution_context, ResearchExecutionContext):
            return execution_context
        if not isinstance(execution_context, Mapping):
            raise MandateValidationError(
                "TechnicalTraderRuntime execution_context must be a "
                "ResearchExecutionContext or mapping."
            )
        try:
            return ResearchExecutionContext.model_validate(execution_context)
        except ValidationError as exc:
            raise MandateValidationError(
                f"Invalid Technical Trader execution context: {exc}"
            ) from exc

    @staticmethod
    def _task(
        mandate: PMMandate,
        execution_context: ResearchExecutionContext,
    ) -> TraderTask:
        lineage = TaskLineage(
            workflow_id=mandate.workflow_id,
            task_id=(
                f"{mandate.task_id}.round-"
                f"{execution_context.round_number}.technical.trader"
            ),
            parent_task_id=mandate.task_id,
            source_task_id=mandate.task_id,
            attempt=execution_context.attempt,
        )
        return TraderTask(
            mandate=mandate,
            lineage=lineage,
            trader_id=SpecialistId.TECHNICAL_TRADER,
            execution_context=execution_context,
        )


def create_technical_trader_runtime(
    *,
    model_client: ModelClient,
    data_service: DataService,
    backtest_engine: BacktestEngine,
    available_executors: Sequence[str],
    validation_split_policy: ValidationSplitPolicy,
    technical_input_adapter: TechnicalAnalysisInputAdapter | None = None,
    technical_toolkit: TechnicalAnalysisToolkit | None = None,
    benchmark_symbol: str | None = None,
    candidate_prompt_max_assets: int = DEFAULT_CANDIDATE_PROMPT_ASSETS,
    benchmark_selection_policy: BenchmarkSelectionPolicy | None = None,
    metrics_sink: MetricsSink | None = None,
    diagnostics_sink: TechnicalDiagnosticsSink | None = None,
    execution_policy: ExecutionPolicy | None = None,
) -> TechnicalTraderRuntime:
    policy = execution_policy or ExecutionPolicy()
    _validate_model_client_deadline(model_client, policy)
    return TechnicalTraderRuntime(
        agent=TechnicalTraderAgent(
            model_client=model_client,
            data_service=data_service,
            backtest_engine=backtest_engine,
            available_executors=available_executors,
            validation_split_policy=validation_split_policy,
            technical_input_adapter=technical_input_adapter,
            technical_toolkit=technical_toolkit,
            benchmark_symbol=benchmark_symbol,
            candidate_prompt_max_assets=candidate_prompt_max_assets,
            benchmark_selection_policy=benchmark_selection_policy,
            metrics_sink=metrics_sink,
            diagnostics_sink=diagnostics_sink,
            execution_policy=policy,
        ),
        execution_policy=policy,
    )


def _validate_model_client_deadline(
    model_client: ModelClient,
    execution_policy: ExecutionPolicy,
) -> None:
    """Reject a provider retry budget that its runtime would cancel early."""

    minimum_timeout = getattr(
        model_client,
        "minimum_model_call_timeout_seconds",
        None,
    )
    if minimum_timeout is None:
        return
    if (
        isinstance(minimum_timeout, bool)
        or not isinstance(minimum_timeout, (int, float))
        or not isfinite(float(minimum_timeout))
        or minimum_timeout <= 0
    ):
        raise ValueError(
            "Model client's minimum_model_call_timeout_seconds must be a "
            "positive finite number."
        )
    if minimum_timeout >= execution_policy.model_call_timeout_seconds:
        raise ValueError(
            "Model provider timeout/retry budget is incompatible with the "
            "Technical Trader execution policy: the provider requires a "
            f"model-call deadline greater than {minimum_timeout:g} seconds, "
            "but the runtime is configured for "
            f"{execution_policy.model_call_timeout_seconds:g} seconds."
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
        mandate = runtime._validate_mandate(state[input_key])
        context_payload = {
            "run_id": state.get("run_id") or mandate.workflow_id,
            "round_number": state.get("round_number", 1),
            "attempt": state.get("trader_attempt", 1),
            "canonical_universe_id": state.get("canonical_universe_id"),
            "evaluation_policy_id": state.get("evaluation_policy_id"),
        }
        package = await runtime.research(
            mandate,
            execution_context=context_payload,
        )
        return {output_key: package.model_dump(mode="json")}

    return node
