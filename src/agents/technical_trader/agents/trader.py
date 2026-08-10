"""Staged pipeline used by the Technical Trader Agent."""

from __future__ import annotations

import asyncio
import math
from abc import abstractmethod
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from protocols import (
    BacktestInterpretationDraft,
    BacktestPlan,
    BacktestRequest,
    BacktestResult,
    BacktestStatus,
    CandidateProposalDraft,
    CandidateRuleSpecification,
    ConstraintCheckStatus,
    DataCategory,
    DataFieldRequirement,
    DataRequest,
    DataResponse,
    DataUsageSummary,
    MandateConstraintAssessment,
    RunStatus,
    SpecialistId,
    TraderFailure,
    TraderResearchPlanDraft,
    TraderStrategyPackage,
    TraderTask,
)

from ..errors import (
    AgentInputValidationError,
    AgentOutputValidationError,
    ServiceContractError,
)
from ..benchmark import BenchmarkSelectionPolicy
from ..executors import (
    BENCHMARK_FALLBACK_EXECUTOR_ID,
    HEAD_PATTERN_EXECUTOR_ID,
    HORIZON_ADAPTIVE_TREND_EXECUTOR_ID,
    INVERSE_PATTERN_EXECUTOR_ID,
    MOVING_AVERAGE_TREND_EXECUTOR_ID,
    MULTI_ASSET_PORTFOLIO_EXECUTOR_ID,
    RESISTANCE_BREAKOUT_EXECUTOR_ID,
    ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID,
    ROLLING_SUPPORT_REACTION_EXECUTOR_ID,
    ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID,
    SUPPORT_REACTION_EXECUTOR_ID,
    TECHNICAL_EXECUTOR_SPEC_BY_ID,
    TechnicalPortfolioParameters,
    VOLUME_BREAKOUT_EXECUTOR_ID,
)
from ..execution import ExecutionPolicy
from ..horizon import (
    resolve_technical_horizon,
    screen_horizon_opportunities,
    validate_horizon_evaluation_window,
)
from ..model_client import MetricsSink, ModelClient, ModelRequestContext
from ..models.technical_analysis import (
    ChartPatternStatus,
    ChartPatternType,
    MovingAverageCrossDirection,
    MovingAverageRelationship,
    PriceLevelKind,
    TechnicalAnalysisReport,
)
from ..prompts import (
    render_backtest_interpretation,
    render_candidate_proposal,
    render_candidate_review,
    render_research_plan,
)
from ..services import (
    BacktestEngine,
    DataService,
    ValidationSplitPolicy,
)
from ..tools import TechnicalAnalysisInputAdapter, TechnicalAnalysisToolkit
from .base import BaseAgent


class StagedTraderAgent(BaseAgent[TraderTask, TraderStrategyPackage]):
    """Independent mandate → data → rule → backtest → interpretation pipeline."""

    trader_id: SpecialistId

    def __init__(
        self,
        *,
        agent_id: str,
        model_client: ModelClient,
        data_service: DataService,
        backtest_engine: BacktestEngine,
        available_executors: Sequence[str],
        validation_split_policy: ValidationSplitPolicy | None,
        technical_input_adapter: TechnicalAnalysisInputAdapter,
        technical_toolkit: TechnicalAnalysisToolkit,
        system_prompt: str,
        lens_requirements: tuple[str, ...],
        benchmark_selection_policy: BenchmarkSelectionPolicy | None = None,
        metrics_sink: MetricsSink | None = None,
        execution_policy: ExecutionPolicy | None = None,
    ) -> None:
        self._execution_policy = execution_policy or ExecutionPolicy()
        super().__init__(
            agent_id=agent_id,
            model_client=model_client,
            metrics_sink=metrics_sink,
            model_timeout_seconds=(
                self._execution_policy.model_call_timeout_seconds
            ),
        )
        self._data_service = data_service
        self._backtest_engine = backtest_engine
        self._available_executors = tuple(
            dict.fromkeys(
                executor.strip()
                for executor in available_executors
                if executor and executor.strip()
            )
        )
        if not self._available_executors:
            raise ValueError(
                "available_executors must name at least one deterministic "
                "strategy executor registered with the Backtest Engine."
            )
        self._model_selectable_executors = tuple(
            executor
            for executor in self._available_executors
            if executor != BENCHMARK_FALLBACK_EXECUTOR_ID
        )
        if not self._model_selectable_executors:
            raise ValueError(
                "available_executors must include at least one model-"
                "selectable Technical strategy executor."
            )
        self._benchmark_selection_policy = (
            benchmark_selection_policy or BenchmarkSelectionPolicy()
        )
        self._validation_split_policy = validation_split_policy
        self._technical_input_adapter = technical_input_adapter
        self._technical_toolkit = technical_toolkit
        self._system_prompt = system_prompt
        self._lens_requirements = lens_requirements

    @property
    @abstractmethod
    def capabilities(self) -> tuple[str, ...]:
        """Human-readable capabilities for a future registry."""

    @property
    def available_executors(self) -> tuple[str, ...]:
        return self._available_executors

    async def run(self, request: TraderTask) -> TraderStrategyPackage:
        if not isinstance(request, TraderTask):
            raise AgentInputValidationError(
                f"{self.agent_id} requires a TraderTask input."
            )
        if request.trader_id is not self.trader_id:
            raise AgentInputValidationError(
                f"{self.agent_id} handles {self.trader_id.value}, not "
                f"{request.trader_id.value}."
            )

        data_request: DataRequest | None = None
        data_response: DataResponse | None = None
        technical_analysis: TechnicalAnalysisReport | None = None
        candidate_rule: CandidateRuleSpecification | None = None
        backtest_request: BacktestRequest | None = None
        backtest_result: BacktestResult | None = None

        try:
            research_plan = await self._generate_structured(
                system_prompt=self._system_prompt,
                user_prompt=render_research_plan(
                    mandate=request.mandate,
                    lens_requirements=self._lens_requirements,
                    available_executors=self._model_selectable_executors,
                ),
                response_model=TraderResearchPlanDraft,
                context=self._model_context(request, "plan_data"),
            )
            research_plan = self._normalize_technical_research_plan(
                research_plan
            )
            self._validate_technical_research_plan(research_plan)
            data_request = self._build_data_request(request, research_plan)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self._failure_package(
                request,
                stage="research_plan",
                exc=exc,
                retryable=True,
            )

        try:
            async with asyncio.timeout(
                self._execution_policy.data_service_timeout_seconds
            ):
                raw_data_response = await self._data_service.fetch(data_request)
            data_response = self._coerce_data_response(raw_data_response)
            self._validate_data_response(
                request=request,
                data_request=data_request,
                data_response=data_response,
            )
            self._ensure_required_data_available(
                research_plan=research_plan,
                data_response=data_response,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            return self._failure_package(
                request,
                stage="data_service",
                exc=ServiceContractError(
                    f"Data Service timed out after "
                    f"{self._execution_policy.data_service_timeout_seconds:g} "
                    "seconds."
                ),
                retryable=True,
                data_request=data_request,
            )
        except Exception as exc:
            return self._failure_package(
                request,
                stage="data_service",
                exc=exc,
                retryable=True,
                data_request=data_request,
                data_response=data_response,
            )

        try:
            series = self._technical_input_adapter.extract(data_response)
            evidence_cutoff_date = max(
                price_series.bars[-1].timestamp.date()
                for price_series in series
            )
            technical_analysis = self._technical_toolkit.analyze(
                series=series,
                as_of_date=evidence_cutoff_date,
                report_id=f"{request.lineage.task_id}.technical-analysis",
            )
            technical_analysis = screen_horizon_opportunities(
                technical_analysis,
                resolve_technical_horizon(request.mandate),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self._failure_package(
                request,
                stage="technical_analysis",
                exc=exc,
                retryable=True,
                data_request=data_request,
                data_response=data_response,
            )

        review_failures: list[TraderFailure] = []
        candidate_review_applied = False
        try:
            initial_proposal = await self._generate_structured(
                system_prompt=self._system_prompt,
                user_prompt=render_candidate_proposal(
                    mandate=request.mandate,
                    data_response=data_response,
                    technical_analysis=technical_analysis,
                    lens_requirements=self._lens_requirements,
                    available_executors=self._model_selectable_executors,
                ),
                response_model=CandidateProposalDraft,
                context=self._model_context(request, "propose_candidate"),
            )
            proposal = initial_proposal
            try:
                proposal = await self._generate_structured(
                    system_prompt=self._system_prompt,
                    user_prompt=render_candidate_review(
                        mandate=request.mandate,
                        initial_proposal=initial_proposal,
                        technical_analysis=technical_analysis,
                        lens_requirements=self._lens_requirements,
                        available_executors=(
                            self._model_selectable_executors
                        ),
                    ),
                    response_model=CandidateProposalDraft,
                    context=self._model_context(request, "review_candidate"),
                )
                candidate_review_applied = True
            except asyncio.CancelledError:
                raise
            except Exception as review_exc:
                review_failures.append(
                    TraderFailure(
                        stage="candidate_review",
                        message=(
                            "Second-pass Technical review was unavailable; "
                            "the validated initial proposal was retained. "
                            f"{type(review_exc).__name__}: {review_exc}"
                        )[:1000],
                        retryable=True,
                    )
                )

            try:
                candidate_rule, backtest_request = (
                    self._build_candidate_and_backtest(
                        request=request,
                        data_request=data_request,
                        data_response=data_response,
                        technical_analysis=technical_analysis,
                        proposal=proposal,
                    )
                )
            except Exception as review_validation_exc:
                if not candidate_review_applied:
                    raise
                review_failures.append(
                    TraderFailure(
                        stage="candidate_review_validation",
                        message=(
                            "Second-pass Technical proposal failed deterministic "
                            "validation; the validated initial proposal was "
                            "retained. "
                            f"{type(review_validation_exc).__name__}: "
                            f"{review_validation_exc}"
                        )[:1000],
                        retryable=True,
                    )
                )
                proposal = initial_proposal
                candidate_review_applied = False
                candidate_rule, backtest_request = self._build_candidate_and_backtest(
                    request=request,
                    data_request=data_request,
                    data_response=data_response,
                    technical_analysis=technical_analysis,
                    proposal=proposal,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self._failure_package(
                request,
                stage="candidate_proposal",
                exc=exc,
                retryable=True,
                data_request=data_request,
                data_response=data_response,
                technical_analysis=technical_analysis,
            )

        try:
            async with asyncio.timeout(
                self._execution_policy.backtest_timeout_seconds
            ):
                raw_backtest_result = await self._backtest_engine.run(
                    backtest_request
                )
            backtest_result = self._coerce_backtest_result(raw_backtest_result)
            self._validate_backtest_result(backtest_request, backtest_result)
            if backtest_result.status is not BacktestStatus.SUCCEEDED:
                raise ServiceContractError(
                    backtest_result.failure_reason
                    or f"Backtest completed with status "
                    f"{backtest_result.status.value}."
                )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return self._failure_package(
                request,
                stage="backtest",
                exc=ServiceContractError(
                    f"Backtest Engine timed out after "
                    f"{self._execution_policy.backtest_timeout_seconds:g} "
                    "seconds."
                ),
                retryable=True,
                data_request=data_request,
                data_response=data_response,
                technical_analysis=technical_analysis,
                candidate_rule=candidate_rule,
                backtest_request=backtest_request,
            )
        except Exception as exc:
            return self._failure_package(
                request,
                stage="backtest",
                exc=exc,
                retryable=True,
                data_request=data_request,
                data_response=data_response,
                technical_analysis=technical_analysis,
                candidate_rule=candidate_rule,
                backtest_request=backtest_request,
                backtest_result=backtest_result,
            )

        technical_candidate_rule = candidate_rule
        technical_backtest_request = backtest_request
        technical_backtest_result = backtest_result
        benchmark_candidate_rule = None
        benchmark_backtest_request = None
        benchmark_backtest_result = None
        try:
            self._validate_benchmark_comparison_window(
                technical_backtest_request
            )
            benchmark_symbol = str(
                technical_backtest_request.plan.benchmark or ""
            ).strip()
            if not benchmark_symbol:
                raise ServiceContractError(
                    "Technical benchmark selection requires a benchmark symbol."
                )
            if BENCHMARK_FALLBACK_EXECUTOR_ID not in self._available_executors:
                raise ServiceContractError(
                    "A like-for-like Technical benchmark comparison requires "
                    "the Backtest Engine to register the additive executor "
                    f"'{BENCHMARK_FALLBACK_EXECUTOR_ID}'."
                )
            benchmark_candidate_rule, benchmark_backtest_request = (
                self._build_benchmark_fallback(
                    request=request,
                    technical_analysis=technical_analysis,
                    technical_backtest_request=technical_backtest_request,
                    benchmark_symbol=benchmark_symbol,
                )
            )
            self._validate_like_for_like_benchmark_requests(
                technical_backtest_request,
                benchmark_backtest_request,
            )
            async with asyncio.timeout(
                self._execution_policy.backtest_timeout_seconds
            ):
                raw_benchmark_result = await self._backtest_engine.run(
                    benchmark_backtest_request
                )
            benchmark_backtest_result = self._coerce_backtest_result(
                raw_benchmark_result
            )
            self._validate_backtest_result(
                benchmark_backtest_request,
                benchmark_backtest_result,
            )
            if benchmark_backtest_result.status is not BacktestStatus.SUCCEEDED:
                raise ServiceContractError(
                    benchmark_backtest_result.failure_reason
                    or "Executable benchmark backtest did not succeed."
                )
            comparison = self._benchmark_selection_policy.compare(
                result=technical_backtest_result,
                benchmark_symbol=benchmark_symbol,
                executable_benchmark_result=benchmark_backtest_result,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return self._failure_package(
                request,
                stage="executable_benchmark_backtest",
                exc=ServiceContractError(
                    "Executable benchmark backtest timed out after "
                    f"{self._execution_policy.backtest_timeout_seconds:g} "
                    "seconds."
                ),
                retryable=True,
                data_request=data_request,
                data_response=data_response,
                technical_analysis=technical_analysis,
                candidate_rule=technical_candidate_rule,
                backtest_request=technical_backtest_request,
                backtest_result=technical_backtest_result,
            )
        except Exception as exc:
            return self._failure_package(
                request,
                stage="benchmark_comparison",
                exc=exc,
                retryable=True,
                data_request=data_request,
                data_response=data_response,
                technical_analysis=technical_analysis,
                candidate_rule=technical_candidate_rule,
                backtest_request=technical_backtest_request,
                backtest_result=technical_backtest_result,
            )

        if (
            benchmark_candidate_rule is None
            or benchmark_backtest_request is None
            or benchmark_backtest_result is None
        ):
            raise RuntimeError(
                "Executable benchmark comparison lost its construction invariant."
            )

        horizon_profile = resolve_technical_horizon(request.mandate)
        validation_split = technical_backtest_request.plan.validation_split
        if validation_split is None:
            raise RuntimeError(
                "Benchmark comparison lost its validation-split invariant."
            )
        evaluation_window = validate_horizon_evaluation_window(
            request.mandate,
            test_start_date=validation_split.test_start_date,
            test_end_date=validation_split.test_end_date,
        )

        benchmark_selection = {
            "policy": {
                "rule": (
                    "retain Technical only when its out-of-sample total "
                    "return strictly exceeds an executable benchmark "
                    "backtested under the identical plan"
                ),
                "comparison": comparison.as_mapping(),
            },
            "technical_candidate": {
                "candidate_id": technical_candidate_rule.candidate_id,
                "executor_id": technical_candidate_rule.executor_id,
                "result_id": technical_backtest_result.result_id,
                "metrics": dict(technical_backtest_result.metrics),
                "out_of_sample_metrics": dict(
                    technical_backtest_result.out_of_sample_metrics
                ),
                "benchmark_metrics": dict(
                    technical_backtest_result.benchmark_metrics
                ),
                "warnings": list(technical_backtest_result.warnings),
            },
            "executable_benchmark": {
                "candidate_id": benchmark_candidate_rule.candidate_id,
                "executor_id": benchmark_candidate_rule.executor_id,
                "result_id": benchmark_backtest_result.result_id,
                "metrics": dict(benchmark_backtest_result.metrics),
                "out_of_sample_metrics": dict(
                    benchmark_backtest_result.out_of_sample_metrics
                ),
                "warnings": list(benchmark_backtest_result.warnings),
            },
            "shared_engine_benchmark_reference": {
                "used_for_selection": False,
                "metrics": dict(technical_backtest_result.benchmark_metrics),
                "reason": (
                    "The engine reference may use different entry timing; "
                    "selection uses the separately executed benchmark instead."
                ),
            },
            "fallback_applied": False,
            "comparison_window": {
                "requested_start_date": (
                    technical_backtest_request.plan.requested_start_date
                ),
                "requested_end_date": (
                    technical_backtest_request.plan.requested_end_date
                    or technical_backtest_request.as_of_date
                ),
                "validation_test_start_date": (
                    technical_backtest_request.plan.validation_split.test_start_date
                    if technical_backtest_request.plan.validation_split
                    else None
                ),
                "validation_test_end_date": (
                    technical_backtest_request.plan.validation_split.test_end_date
                    if technical_backtest_request.plan.validation_split
                    else None
                ),
                "benchmark_requested_start_date": (
                    benchmark_backtest_request.plan.requested_start_date
                ),
                "benchmark_requested_end_date": (
                    benchmark_backtest_request.plan.requested_end_date
                    or benchmark_backtest_request.as_of_date
                ),
                "technical_and_benchmark_windows_coincide": True,
                **evaluation_window.as_mapping(),
            },
            "comparison_execution": {
                "plans_are_identical": True,
                "transaction_cost_assumptions_are_identical": True,
                "execution_context_is_identical": True,
                "data_references_are_identical": True,
                "technical_plan": technical_backtest_request.plan.model_dump(
                    mode="json"
                ),
                "benchmark_plan": benchmark_backtest_request.plan.model_dump(
                    mode="json"
                ),
            },
            "selection_uses_evaluation_window": True,
            "independent_post_selection_test_required": True,
        }

        if comparison.fallback_required:
            candidate_rule = benchmark_candidate_rule
            backtest_request = benchmark_backtest_request
            backtest_result = benchmark_backtest_result
            benchmark_selection.update(
                {
                    "fallback_applied": True,
                    "final_candidate": {
                        "candidate_id": candidate_rule.candidate_id,
                        "executor_id": candidate_rule.executor_id,
                        "result_id": backtest_result.result_id,
                        "metrics": dict(backtest_result.metrics),
                        "out_of_sample_metrics": dict(
                            backtest_result.out_of_sample_metrics
                        ),
                        "warnings": list(backtest_result.warnings),
                    },
                }
            )

        try:
            interpretation = await self._generate_structured(
                system_prompt=self._system_prompt,
                user_prompt=render_backtest_interpretation(
                    mandate=request.mandate,
                    candidate_rule=candidate_rule,
                    backtest_result=backtest_result,
                    lens_requirements=self._lens_requirements,
                    benchmark_selection=benchmark_selection,
                ),
                response_model=BacktestInterpretationDraft,
                context=self._model_context(request, "interpret_backtest"),
            )
            self._validate_metric_references(interpretation, backtest_result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self._failure_package(
                request,
                stage="backtest_interpretation",
                exc=exc,
                retryable=True,
                data_request=data_request,
                data_response=data_response,
                technical_analysis=technical_analysis,
                candidate_rule=candidate_rule,
                backtest_request=backtest_request,
                backtest_result=backtest_result,
            )

        constraint_mappings = list(proposal.mandate_constraint_mapping)
        if comparison.fallback_required:
            constraint_mappings.append(
                "Code selected the PM-permitted benchmark after the reviewed "
                "Technical portfolio failed the deterministic out-of-sample "
                "total-return gate."
            )
        constraint_assessment = self._constraint_assessment(
            proposal.known_constraint_violations,
            constraint_mappings,
            backtest_result.constraint_violations,
        )
        horizon_profile = resolve_technical_horizon(request.mandate)
        return TraderStrategyPackage(
            package_id=f"{request.lineage.task_id}.package",
            candidate_id=candidate_rule.candidate_id,
            trader_id=self.trader_id,
            lineage=request.lineage,
            mandate_reference=request.mandate.reference(),
            status=RunStatus.COMPLETED,
            hypothesis=candidate_rule.hypothesis,
            data_request=data_request,
            data_usage=DataUsageSummary.from_response(data_response),
            specialty_evidence=self._specialty_evidence(technical_analysis),
            candidate_rule=candidate_rule,
            backtest_request=backtest_request,
            backtest_result=backtest_result,
            interpretation=interpretation,
            constraint_assessment=constraint_assessment,
            failures=review_failures,
            eligible_for_risk_review=True,
            additional_fields={
                "technical_horizon": horizon_profile.as_prompt_mapping(),
                "technical_opportunity_count": len(
                    technical_analysis.horizon_opportunities
                ),
                "selected_opportunity_ranks": [
                    sleeve.get("opportunity_rank")
                    for sleeve in candidate_rule.parameters.get("sleeves", [])
                    if isinstance(sleeve, Mapping)
                ],
                "candidate_review": {
                    "requested": True,
                    "applied": candidate_review_applied,
                    "initial_selected_symbols": [
                        str(sleeve.get("symbol", "")).strip()
                        for sleeve in initial_proposal.rule.parameters.get(
                            "sleeves", []
                        )
                        if isinstance(sleeve, Mapping)
                    ],
                    "reviewed_selected_symbols": [
                        str(sleeve.get("symbol", "")).strip()
                        for sleeve in technical_candidate_rule.parameters.get(
                            "sleeves", []
                        )
                        if isinstance(sleeve, Mapping)
                    ],
                    "non_fatal_failures": len(review_failures),
                },
                "benchmark_selection": benchmark_selection,
                **(
                    {
                        "technical_candidate_before_benchmark_fallback": {
                            "candidate_rule": (
                                technical_candidate_rule.model_dump(
                                    mode="json"
                                )
                            ),
                            "backtest_request": (
                                technical_backtest_request.model_dump(
                                    mode="json"
                                )
                            ),
                            "backtest_result": (
                                technical_backtest_result.model_dump(
                                    mode="json"
                                )
                            ),
                        }
                    }
                    if comparison.fallback_required
                    else {}
                ),
                "evaluation_semantics": {
                    "holding_horizon_trading_days": (
                        horizon_profile.horizon_trading_days
                    ),
                    "primary_evaluation_window_role": (
                        "horizon-matched held-out performance comparison"
                    ),
                    "primary_evaluation_window": (
                        evaluation_window.as_mapping()
                    ),
                    "technical_and_benchmark_use_identical_plan": True,
                    "benchmark_gate_uses_executable_benchmark": True,
                    "shared_engine_reference_used_for_selection": False,
                    "post_selection_independent_test_required": True,
                },
            },
        )

    def _model_context(
        self,
        request: TraderTask,
        operation: str,
    ) -> ModelRequestContext:
        return ModelRequestContext(
            agent_id=self.agent_id,
            operation=operation,
            workflow_id=request.lineage.workflow_id,
            task_id=request.lineage.task_id,
            attempt=request.lineage.attempt,
        )

    def _build_data_request(
        self,
        request: TraderTask,
        plan: TraderResearchPlanDraft,
    ) -> DataRequest:
        lineage = request.lineage.child("data")
        return DataRequest(
            request_id=lineage.task_id,
            lineage=lineage,
            trader_id=self.trader_id,
            as_of_date=request.mandate.as_of_date,
            purpose=plan.purpose,
            asset_universe=request.mandate.permitted_asset_universe,
            categories=plan.categories,
            fields=plan.fields,
            start_date=plan.start_date,
            end_date=plan.end_date or request.mandate.as_of_date,
            frequency=plan.frequency,
            provenance_required=True,
        )

    def _build_candidate_and_backtest(
        self,
        *,
        request: TraderTask,
        data_request: DataRequest,
        data_response: DataResponse,
        technical_analysis: TechnicalAnalysisReport,
        proposal: CandidateProposalDraft,
    ) -> tuple[CandidateRuleSpecification, BacktestRequest]:
        proposal = self._bind_evidence_derived_parameters(
            proposal=proposal,
            technical_analysis=technical_analysis,
        )
        self._validate_technical_evidence(
            proposal=proposal,
            technical_analysis=technical_analysis,
        )
        self._validate_executor_selection(
            proposal=proposal,
            request=request,
            technical_analysis=technical_analysis,
        )
        candidate_lineage = request.lineage.child("candidate")
        candidate = CandidateRuleSpecification(
            **proposal.rule.model_dump(mode="python"),
            candidate_id=candidate_lineage.task_id,
            trader_id=self.trader_id,
            lineage=candidate_lineage,
        )
        validation_split = None
        if proposal.backtest_plan.held_out_evaluation_required:
            if self._validation_split_policy is None:
                raise ServiceContractError(
                    "Held-out evaluation requires an injected shared "
                    "ValidationSplitPolicy; the Technical Trader does not "
                    "choose its own test window."
                )
            validation_split = self._validation_split_policy.resolve(
                task=request,
                plan=proposal.backtest_plan,
                data_response=data_response,
            )
            try:
                validate_horizon_evaluation_window(
                    request.mandate,
                    test_start_date=validation_split.test_start_date,
                    test_end_date=validation_split.test_end_date,
                )
            except ValueError as exc:
                raise ServiceContractError(str(exc)) from exc
        plan = BacktestPlan.from_draft(
            proposal.backtest_plan,
            validation_split=validation_split,
        )
        backtest_lineage = request.lineage.child("backtest")
        backtest_request = BacktestRequest(
            request_id=backtest_lineage.task_id,
            trader_id=self.trader_id,
            lineage=backtest_lineage,
            execution_context=request.execution_context,
            as_of_date=request.mandate.as_of_date,
            candidate=candidate,
            plan=plan,
            data_references=[
                artifact.data_reference for artifact in data_response.artifacts
            ],
            mandate_constraints=self._mandate_constraints(request),
        )
        return candidate, backtest_request

    def _build_benchmark_fallback(
        self,
        *,
        request: TraderTask,
        technical_analysis: TechnicalAnalysisReport,
        technical_backtest_request: BacktestRequest,
        benchmark_symbol: str,
    ) -> tuple[CandidateRuleSpecification, BacktestRequest]:
        benchmark = benchmark_symbol.strip()
        if not benchmark:
            raise ServiceContractError(
                "Technical benchmark selection requires a benchmark symbol."
            )
        permitted = request.mandate.permitted_asset_universe
        if isinstance(permitted, list) and benchmark.casefold() not in {
            symbol.casefold() for symbol in permitted
        }:
            raise ServiceContractError(
                f"Benchmark fallback symbol '{benchmark}' is outside the "
                "PM-permitted universe."
            )
        if benchmark.casefold() in {
            symbol.casefold() for symbol in request.mandate.prohibited_assets
        }:
            raise ServiceContractError(
                f"Benchmark fallback symbol '{benchmark}' is prohibited by "
                "the PM mandate."
            )

        raw_leverage = technical_backtest_request.plan.transaction_cost_assumptions.get(
            "max_gross_leverage",
            1.0,
        )
        if (
            isinstance(raw_leverage, bool)
            or not isinstance(raw_leverage, (int, float))
            or not math.isfinite(float(raw_leverage))
            or float(raw_leverage) <= 0
        ):
            raise ServiceContractError(
                "Benchmark fallback requires a positive finite gross-"
                "leverage limit in the Backtest Plan."
            )
        leverage_limits = [float(raw_leverage), 1.0]
        mandate_leverage = request.mandate.leverage_constraints
        if isinstance(mandate_leverage, Mapping):
            mandate_max_gross = mandate_leverage.get("max_gross_leverage")
            if (
                not isinstance(mandate_max_gross, bool)
                and isinstance(mandate_max_gross, (int, float))
                and math.isfinite(float(mandate_max_gross))
                and float(mandate_max_gross) > 0
            ):
                leverage_limits.append(float(mandate_max_gross))
        target_weight = min(leverage_limits)
        candidate_lineage = request.lineage.child(
            "candidate-benchmark-fallback"
        )
        report_id = technical_analysis.report_id
        candidate = CandidateRuleSpecification(
            candidate_id=candidate_lineage.task_id,
            trader_id=self.trader_id,
            lineage=candidate_lineage,
            strategy_name=f"{benchmark} benchmark fallback",
            hypothesis=(
                "An executable benchmark portfolio provides a like-for-like "
                "baseline for the reviewed Technical portfolio under the "
                "same evaluation and execution assumptions."
            ),
            rule_summary=(
                f"Establish one long-only {benchmark} target and hold it until "
                "the Backtest Engine's configured end liquidation."
            ),
            executor_id=BENCHMARK_FALLBACK_EXECUTOR_ID,
            asset_eligibility_logic=(
                f"Use only the requested, PM-permitted benchmark {benchmark}."
            ),
            signal_logic=(
                "Submit the benchmark target once when its first evaluation "
                "bar is available."
            ),
            position_logic=(
                f"Maintain a {target_weight:g} long target weight in "
                f"{benchmark}; residual capital remains cash."
            ),
            entry_logic=(
                "Submit the initial target from the first observed evaluation "
                "bar and use the plan's ordinary delayed execution semantics."
            ),
            exit_logic=(
                "Make no model-timed exit; use deterministic end-of-evaluation "
                "liquidation from the Backtest Plan."
            ),
            rebalancing_logic=(
                "Submit the target once and do not issue tactical rebalances."
            ),
            parameters={
                "symbol": benchmark,
                "target_weight": target_weight,
            },
            specialty_evidence_ids=[report_id],
            specialty_evidence_usage={
                report_id: (
                    "Identifies the frozen Technical report that produced the "
                    "portfolio evaluated by the benchmark gate; it is audit "
                    "lineage, not a benchmark entry signal."
                )
            },
            required_data_fields=["symbol", "timestamp", "open", "close"],
            constraint_handling=[
                "The fallback is long-only.",
                f"Target weight is capped at {target_weight:g} by the supplied "
                "plan and structured mandate gross-leverage limits.",
                "The benchmark must remain in the permitted universe and "
                "outside prohibited assets.",
            ],
            implementation_notes=[
                "This code-owned baseline is evaluated before the deterministic "
                "selection gate and becomes final only if Technical does not "
                "strictly outperform it.",
                "The fallback is not a new Technical signal and does not add "
                "fundamental or Quant analysis.",
                "The fallback is backtested again through the registered "
                "executor and the same cost and evaluation assumptions.",
                "Because the gate and fallback result use the same evaluation "
                "window, a later untouched test is required before claiming "
                "independent out-of-sample validation.",
            ],
        )
        backtest_lineage = request.lineage.child(
            "backtest-benchmark-fallback"
        )
        fallback_request = BacktestRequest(
            request_id=backtest_lineage.task_id,
            trader_id=self.trader_id,
            lineage=backtest_lineage,
            execution_context=request.execution_context,
            as_of_date=request.mandate.as_of_date,
            candidate=candidate,
            plan=technical_backtest_request.plan,
            data_references=list(technical_backtest_request.data_references),
            mandate_constraints=self._mandate_constraints(request),
            additional_fields={
                "executable_benchmark_comparison": True,
                "technical_candidate_id": (
                    technical_backtest_request.candidate_id
                ),
            },
        )
        return candidate, fallback_request

    @staticmethod
    def _bind_evidence_derived_parameters(
        *,
        proposal: CandidateProposalDraft,
        technical_analysis: TechnicalAnalysisReport,
    ) -> CandidateProposalDraft:
        """Resolve code-owned sleeve numerics from cited deterministic evidence.

        The model chooses symbols, strategy families, and evidence IDs. It is
        not responsible for reproducing high-precision prices or window values
        that already exist in the deterministic report.
        """

        if proposal.rule.executor_id != MULTI_ASSET_PORTFOLIO_EXECUTOR_ID:
            return proposal
        portfolio_parameters = proposal.rule.parameters
        raw_sleeves = portfolio_parameters.get("sleeves")
        if not isinstance(raw_sleeves, list):
            return proposal
        horizon = technical_analysis.horizon_context
        if horizon is None:
            raise AgentOutputValidationError(
                "Technical horizon context is required before evidence binding."
            )
        raw_common_risk = portfolio_parameters.get("common_risk_parameters")
        if not isinstance(raw_common_risk, Mapping):
            raise AgentOutputValidationError(
                "Portfolio common_risk_parameters must be a mapping."
            )
        bound_common_risk = dict(raw_common_risk)
        bound_common_risk.update(
            {
                "max_holding_bars": horizon.maximum_holding_bars,
                "volatility_lookback_bars": horizon.volatility_lookback_bars,
                "profit_target_sigma_multiple": (
                    horizon.profit_target_sigma_multiple
                ),
                "stop_loss_sigma_multiple": (
                    horizon.stop_loss_sigma_multiple
                ),
            }
        )

        reliable_levels = technical_analysis.reliable_level_ids()
        level_by_id = {
            level.level_id: (asset.symbol, level)
            for asset in technical_analysis.assets
            for level in asset.support_resistance_levels
        }
        pattern_by_id = {
            pattern.pattern_id: (asset.symbol, pattern)
            for asset in technical_analysis.assets
            for pattern in asset.chart_patterns
        }
        moving_average_by_id = {
            observation.moving_average_id: (
                asset.symbol,
                observation,
            )
            for asset in technical_analysis.assets
            for observation in asset.available_moving_averages()
        }
        volume_by_id = {
            asset.volume_observation.volume_id: (
                asset.symbol,
                asset.volume_observation,
            )
            for asset in technical_analysis.assets
            if asset.volume_observation is not None
        }

        def one_matching_observation(
            *,
            sleeve_number: int,
            symbol: str,
            evidence_ids: set[str],
            evidence_by_id: Mapping[str, tuple[str, Any]],
            evidence_label: str,
            predicate: Callable[[str, Any], bool] | None = None,
        ) -> Any:
            matches = [
                observation
                for evidence_id, (owner_symbol, observation) in (
                    evidence_by_id.items()
                )
                if evidence_id in evidence_ids
                and owner_symbol == symbol
                and (predicate is None or predicate(evidence_id, observation))
            ]
            if len(matches) != 1:
                raise AgentOutputValidationError(
                    f"Portfolio sleeve {sleeve_number} for '{symbol}' must "
                    f"cite exactly one matching {evidence_label}; found "
                    f"{len(matches)}."
                )
            return matches[0]

        bound_sleeves: list[dict[str, Any]] = []
        for sleeve_number, raw_sleeve in enumerate(raw_sleeves, start=1):
            if not isinstance(raw_sleeve, Mapping):
                raise AgentOutputValidationError(
                    f"Portfolio sleeve {sleeve_number} must be a mapping."
                )
            symbol = str(raw_sleeve.get("symbol", "")).strip()
            executor_id = str(raw_sleeve.get("executor_id", "")).strip()
            raw_evidence_ids = raw_sleeve.get("evidence_ids")
            raw_family_parameters = raw_sleeve.get("parameters")
            if not isinstance(raw_evidence_ids, list):
                raise AgentOutputValidationError(
                    f"Portfolio sleeve {sleeve_number}.evidence_ids must be "
                    "a list."
                )
            if not isinstance(raw_family_parameters, Mapping):
                raise AgentOutputValidationError(
                    f"Portfolio sleeve {sleeve_number}.parameters must be a "
                    "mapping."
                )
            evidence_ids = {
                str(evidence_id).strip()
                for evidence_id in raw_evidence_ids
                if str(evidence_id).strip()
            }
            family_parameters = dict(raw_family_parameters)

            if executor_id in {
                SUPPORT_REACTION_EXECUTOR_ID,
                ROLLING_SUPPORT_REACTION_EXECUTOR_ID,
            }:
                level = one_matching_observation(
                    sleeve_number=sleeve_number,
                    symbol=symbol,
                    evidence_ids=evidence_ids,
                    evidence_by_id=level_by_id,
                    evidence_label="reliable support",
                    predicate=lambda evidence_id, observation: (
                        evidence_id in reliable_levels
                        and observation.kind is PriceLevelKind.SUPPORT
                    ),
                )
                if executor_id == SUPPORT_REACTION_EXECUTOR_ID:
                    family_parameters["anchor_level"] = level.price
            elif executor_id in {
                RESISTANCE_BREAKOUT_EXECUTOR_ID,
                VOLUME_BREAKOUT_EXECUTOR_ID,
                ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID,
                ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID,
            }:
                level = one_matching_observation(
                    sleeve_number=sleeve_number,
                    symbol=symbol,
                    evidence_ids=evidence_ids,
                    evidence_by_id=level_by_id,
                    evidence_label="reliable resistance",
                    predicate=lambda evidence_id, observation: (
                        evidence_id in reliable_levels
                        and observation.kind is PriceLevelKind.RESISTANCE
                    ),
                )
                if executor_id in {
                    RESISTANCE_BREAKOUT_EXECUTOR_ID,
                    VOLUME_BREAKOUT_EXECUTOR_ID,
                }:
                    family_parameters["anchor_level"] = level.price

            if executor_id in {
                MOVING_AVERAGE_TREND_EXECUTOR_ID,
                HORIZON_ADAPTIVE_TREND_EXECUTOR_ID,
            }:
                observation = one_matching_observation(
                    sleeve_number=sleeve_number,
                    symbol=symbol,
                    evidence_ids=evidence_ids,
                    evidence_by_id=moving_average_by_id,
                    evidence_label="moving-average observation",
                )
                family_parameters["fast_window"] = observation.fast_window
                family_parameters["slow_window"] = observation.slow_window
            elif executor_id in {
                VOLUME_BREAKOUT_EXECUTOR_ID,
                ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID,
            }:
                observation = one_matching_observation(
                    sleeve_number=sleeve_number,
                    symbol=symbol,
                    evidence_ids=evidence_ids,
                    evidence_by_id=volume_by_id,
                    evidence_label="volume observation",
                )
                family_parameters["volume_lookback_bars"] = (
                    observation.lookback_window
                )
            elif executor_id == INVERSE_PATTERN_EXECUTOR_ID:
                pattern = one_matching_observation(
                    sleeve_number=sleeve_number,
                    symbol=symbol,
                    evidence_ids=evidence_ids,
                    evidence_by_id=pattern_by_id,
                    evidence_label=(
                        "confirmed inverse-head-and-shoulders pattern"
                    ),
                    predicate=lambda _evidence_id, observation: (
                        observation.pattern_type
                        is ChartPatternType.INVERSE_HEAD_AND_SHOULDERS
                        and observation.status is ChartPatternStatus.CONFIRMED
                    ),
                )
                family_parameters["neckline_price"] = pattern.neckline_price

            if executor_id in {
                ROLLING_SUPPORT_REACTION_EXECUTOR_ID,
                ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID,
                ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID,
            }:
                family_parameters.update(
                    {
                        "review_interval_bars": horizon.review_interval_bars,
                        "rolling_level_lookback_bars": (
                            horizon.rolling_level_lookback_bars
                        ),
                        "pivot_window": horizon.rolling_pivot_window,
                        "merge_tolerance_percent": (
                            horizon.rolling_merge_tolerance_percent
                        ),
                        "min_touches": horizon.rolling_min_touches,
                        "maximum_level_distance_percent": (
                            horizon.maximum_level_distance_percent
                        ),
                    }
                )
            elif executor_id == HORIZON_ADAPTIVE_TREND_EXECUTOR_ID:
                family_parameters["review_interval_bars"] = (
                    horizon.review_interval_bars
                )

            matching_opportunities = [
                opportunity
                for opportunity in technical_analysis.horizon_opportunities
                if opportunity.symbol == symbol
                and opportunity.executor_id == executor_id
                and set(opportunity.evidence_ids) == evidence_ids
            ]
            if len(matching_opportunities) != 1:
                raise AgentOutputValidationError(
                    f"Portfolio sleeve {sleeve_number} for '{symbol}' must "
                    "match exactly one deterministic horizon opportunity; "
                    f"found {len(matching_opportunities)}."
                )
            opportunity = matching_opportunities[0]
            bound_sleeve = dict(raw_sleeve)
            bound_sleeve["parameters"] = family_parameters
            bound_sleeve["opportunity_id"] = opportunity.opportunity_id
            bound_sleeve["opportunity_rank"] = opportunity.rank
            bound_sleeve["opportunity_score"] = opportunity.score
            bound_sleeves.append(bound_sleeve)

        bound_portfolio_parameters = dict(portfolio_parameters)
        bound_portfolio_parameters["common_risk_parameters"] = (
            bound_common_risk
        )
        bound_portfolio_parameters["sleeves"] = bound_sleeves
        bound_rule = proposal.rule.model_copy(
            update={"parameters": bound_portfolio_parameters}
        )
        return proposal.model_copy(update={"rule": bound_rule})

    def _validate_executor_selection(
        self,
        *,
        proposal: CandidateProposalDraft,
        request: TraderTask,
        technical_analysis: TechnicalAnalysisReport,
    ) -> None:
        executor_id = proposal.rule.executor_id
        if executor_id not in self._model_selectable_executors:
            raise AgentOutputValidationError(
                f"Candidate selected unavailable or code-owned executor "
                f"'{executor_id}'. Model-selectable executors: "
                + ", ".join(self._model_selectable_executors)
                + "."
            )
        specification = TECHNICAL_EXECUTOR_SPEC_BY_ID.get(executor_id)
        if executor_id == MULTI_ASSET_PORTFOLIO_EXECUTOR_ID:
            try:
                portfolio = TechnicalPortfolioParameters.from_mapping(
                    proposal.rule.parameters
                )
            except ValueError as exc:
                raise AgentOutputValidationError(str(exc)) from exc
            permitted = request.mandate.permitted_asset_universe
            permitted_set = set(permitted) if isinstance(permitted, list) else None
            prohibited = {
                symbol.casefold()
                for symbol in request.mandate.prohibited_assets
            }
            invalid = [
                sleeve.symbol
                for sleeve in portfolio.sleeves
                if (
                    permitted_set is not None
                    and sleeve.symbol not in permitted_set
                )
                or sleeve.symbol.casefold() in prohibited
            ]
            if invalid:
                raise AgentOutputValidationError(
                    "Portfolio sleeves must remain inside the PM-permitted "
                    "universe and outside prohibited assets: "
                    + ", ".join(sorted(invalid))
                )
            profile = resolve_technical_horizon(request.mandate)
            holding_bars = portfolio.common_risk_parameters.get(
                "max_holding_bars"
            )
            if (
                isinstance(holding_bars, bool)
                or not isinstance(holding_bars, int)
                or not 1 <= holding_bars <= profile.maximum_holding_bars
            ):
                raise AgentOutputValidationError(
                    "Portfolio max_holding_bars must be a positive integer no "
                    f"greater than the mandate horizon limit of "
                    f"{profile.maximum_holding_bars}."
                )
            expected_common_risk = {
                "max_holding_bars": profile.maximum_holding_bars,
                "volatility_lookback_bars": (
                    profile.volatility_lookback_bars
                ),
                "profit_target_sigma_multiple": (
                    profile.profit_target_sigma_multiple
                ),
                "stop_loss_sigma_multiple": (
                    profile.stop_loss_sigma_multiple
                ),
            }
            if dict(portfolio.common_risk_parameters) != expected_common_risk:
                raise AgentOutputValidationError(
                    "Portfolio common risk parameters must equal the "
                    "code-owned horizon policy."
                )

            moving_average_by_id = {
                observation.moving_average_id: (asset.symbol, observation)
                for asset in technical_analysis.assets
                for observation in asset.available_moving_averages()
            }
            level_by_id = {
                level.level_id: (asset.symbol, level)
                for asset in technical_analysis.assets
                for level in asset.support_resistance_levels
            }
            allowed_windows = set(profile.moving_average_windows)
            for sleeve in portfolio.sleeves:
                if sleeve.executor_id in {
                    ROLLING_SUPPORT_REACTION_EXECUTOR_ID,
                    ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID,
                    ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID,
                }:
                    expected_rolling = {
                        "review_interval_bars": profile.review_interval_bars,
                        "rolling_level_lookback_bars": (
                            profile.rolling_level_lookback_bars
                        ),
                        "pivot_window": profile.rolling_pivot_window,
                        "merge_tolerance_percent": (
                            profile.rolling_merge_tolerance_percent
                        ),
                        "min_touches": profile.rolling_min_touches,
                        "maximum_level_distance_percent": (
                            profile.maximum_level_distance_percent
                        ),
                    }
                    if any(
                        sleeve.family_parameters.get(key) != value
                        for key, value in expected_rolling.items()
                    ):
                        raise AgentOutputValidationError(
                            f"Rolling sleeve '{sleeve.symbol}' changed a "
                            "code-owned horizon parameter."
                        )
                elif (
                    sleeve.executor_id
                    == HORIZON_ADAPTIVE_TREND_EXECUTOR_ID
                    and sleeve.family_parameters.get("review_interval_bars")
                    != profile.review_interval_bars
                ):
                    raise AgentOutputValidationError(
                        f"Adaptive trend sleeve '{sleeve.symbol}' changed "
                        "the code-owned review cadence."
                    )
                if sleeve.executor_id in {
                    MOVING_AVERAGE_TREND_EXECUTOR_ID,
                    HORIZON_ADAPTIVE_TREND_EXECUTOR_ID,
                }:
                    windows = (
                        int(sleeve.family_parameters["fast_window"]),
                        int(sleeve.family_parameters["slow_window"]),
                    )
                    if windows not in allowed_windows:
                        raise AgentOutputValidationError(
                            f"Moving-average sleeve '{sleeve.symbol}' uses "
                            f"{windows[0]}/{windows[1]}, which is not allowed "
                            f"for the {profile.horizon_trading_days}-trading-"
                            "day mandate."
                        )
                    observations = [
                        observation
                        for evidence_id in sleeve.evidence_ids
                        if evidence_id in moving_average_by_id
                        for owner_symbol, observation in (
                            moving_average_by_id[evidence_id],
                        )
                        if owner_symbol == sleeve.symbol
                    ]
                    if len(observations) != 1:
                        raise AgentOutputValidationError(
                            f"Moving-average sleeve '{sleeve.symbol}' must "
                            "cite exactly one same-symbol moving-average "
                            "observation."
                        )
                    observation = observations[0]
                    requires_fresh_cross = (
                        sleeve.executor_id
                        == MOVING_AVERAGE_TREND_EXECUTOR_ID
                    )
                    if (
                        observation.relationship
                        is not MovingAverageRelationship.BULLISH
                        or (
                            requires_fresh_cross
                            and (
                                observation.latest_cross_direction
                                is not MovingAverageCrossDirection.BULLISH
                                or observation.bars_since_latest_cross is None
                                or observation.bars_since_latest_cross
                                > profile.maximum_recent_cross_age_bars
                            )
                        )
                    ):
                        raise AgentOutputValidationError(
                            f"Moving-average sleeve '{sleeve.symbol}' must "
                            "cite a currently bullish observation aligned "
                            "with the mandate horizon; legacy crossover-only "
                            "sleeves must also cite a recent bullish cross."
                        )
                elif sleeve.executor_id in {
                    SUPPORT_REACTION_EXECUTOR_ID,
                    RESISTANCE_BREAKOUT_EXECUTOR_ID,
                    VOLUME_BREAKOUT_EXECUTOR_ID,
                    ROLLING_SUPPORT_REACTION_EXECUTOR_ID,
                    ROLLING_RESISTANCE_BREAKOUT_EXECUTOR_ID,
                    ROLLING_VOLUME_BREAKOUT_EXECUTOR_ID,
                }:
                    cited_levels = [
                        level
                        for evidence_id in sleeve.evidence_ids
                        if evidence_id in level_by_id
                        for owner_symbol, level in (level_by_id[evidence_id],)
                        if owner_symbol == sleeve.symbol
                    ]
                    if len(cited_levels) != 1:
                        raise AgentOutputValidationError(
                            f"Level-based sleeve '{sleeve.symbol}' must cite "
                            "exactly one same-symbol technical level."
                        )
                    if any(
                        abs(level.distance_from_last_close_percent)
                        > profile.maximum_level_distance_percent
                        for level in cited_levels
                    ):
                        raise AgentOutputValidationError(
                            f"Level-based sleeve '{sleeve.symbol}' exceeds the "
                            f"{profile.maximum_level_distance_percent:g}% "
                            "actionability distance for the mandate horizon."
                        )
            return
        if specification is None or not specification.supports_short:
            return

        short_constraints = request.mandate.short_selling_constraints
        mandate_allows_short = (
            isinstance(short_constraints, Mapping)
            and short_constraints.get("allow_short") is True
        )
        plan_allows_short = (
            proposal.backtest_plan.transaction_cost_assumptions.get(
                "allow_short"
            )
            is True
        )
        if not mandate_allows_short or not plan_allows_short:
            raise AgentOutputValidationError(
                f"Executor '{executor_id}' requires shorting to be explicitly "
                "permitted by both the PM mandate and Backtest Plan."
            )

    @staticmethod
    def _normalize_technical_research_plan(
        plan: TraderResearchPlanDraft,
    ) -> TraderResearchPlanDraft:
        """Make core daily OHLC requirements code-owned and extras optional."""

        core_purposes = {
            "symbol": "Identify each ETF and keep observations asset-scoped.",
            "timestamp": (
                "Preserve point-in-time chronology for signals and execution."
            ),
            "open": "Support deterministic next-bar-open execution.",
            "high": "Compute pivots, levels, patterns, and risk exits.",
            "low": "Compute pivots, levels, patterns, and risk exits.",
            "close": "Compute completed-bar signals, returns, and indicators.",
        }

        def core_label(field_name: str) -> str | None:
            normalized = (
                field_name.casefold().replace("-", "_").replace(" ", "_")
            )
            tokens = set(normalized.split("_"))
            if tokens.intersection({"symbol", "ticker"}) or normalized in {
                "instrument",
                "instrument_id",
                "instrument_identifier",
                "asset_id",
            }:
                return "symbol"
            if tokens.intersection({"timestamp", "datetime", "date"}):
                return "timestamp"
            for label in ("open", "high", "low", "close"):
                if label in tokens:
                    return label
            return None

        normalized_fields: list[DataFieldRequirement] = []
        present_core: set[str] = set()
        for field in plan.fields:
            label = core_label(field.name)
            if label is not None:
                present_core.add(label)
            normalized_fields.append(
                field.model_copy(update={"required": label is not None})
            )
        for label, purpose in core_purposes.items():
            if label not in present_core:
                normalized_fields.append(
                    DataFieldRequirement(
                        name=label,
                        purpose=purpose,
                        required=True,
                        point_in_time_required=True,
                        publication_date_required=False,
                    )
                )

        rationale_note = (
            "Code requires only symbol and daily OHLC chronology; volume, "
            "session, lifecycle, liquidity, and metadata fields are optional. "
            "Unavailable optional evidence excludes dependent sleeve families."
        )
        rationale = list(plan.rationale)
        if rationale_note not in rationale:
            rationale.append(rationale_note)
        categories = list(plan.categories)
        if DataCategory.PRICE_VOLUME not in categories:
            categories.append(DataCategory.PRICE_VOLUME)
        return plan.model_copy(
            update={
                "categories": categories,
                "fields": normalized_fields,
                "frequency": "daily",
                "rationale": rationale,
            }
        )

    @staticmethod
    def _validate_technical_research_plan(
        plan: TraderResearchPlanDraft,
    ) -> None:
        if DataCategory.PRICE_VOLUME not in plan.categories:
            raise AgentOutputValidationError(
                "Technical Trader research plans must request price_volume data."
            )
        field_names = [
            field.name.casefold().replace("-", "_").replace(" ", "_")
            for field in plan.fields
            if field.required
        ]
        requirements = {
            "symbol": ("symbol", "ticker", "instrument"),
            "timestamp": ("timestamp", "datetime", "date"),
            "open": ("open",),
            "high": ("high",),
            "low": ("low",),
            "close": ("close",),
        }
        missing = [
            label
            for label, aliases in requirements.items()
            if not any(
                alias in field_name
                for field_name in field_names
                for alias in aliases
            )
        ]
        if missing:
            raise AgentOutputValidationError(
                "Technical Trader research plans must require OHLC chronology; "
                "missing: " + ", ".join(missing)
            )

    @staticmethod
    def _validate_technical_evidence(
        *,
        proposal: CandidateProposalDraft,
        technical_analysis: TechnicalAnalysisReport,
    ) -> None:
        referenced = set(proposal.rule.specialty_evidence_ids)
        unknown = sorted(referenced - technical_analysis.evidence_ids())
        if unknown:
            raise AgentOutputValidationError(
                "Candidate cited technical evidence absent from the deterministic "
                "report: " + ", ".join(unknown)
            )
        reliable_levels = technical_analysis.reliable_level_ids()
        cited_levels = referenced.intersection(technical_analysis.level_ids())
        unreliable_cited_levels = sorted(cited_levels - reliable_levels)
        if unreliable_cited_levels:
            raise AgentOutputValidationError(
                "Candidate may not cite fallback or wrong-side support/"
                "resistance levels: " + ", ".join(unreliable_cited_levels)
            )

        executor_id = proposal.rule.executor_id
        specification = TECHNICAL_EXECUTOR_SPEC_BY_ID.get(executor_id)
        if specification is None:
            if not referenced.intersection(reliable_levels):
                raise AgentOutputValidationError(
                    "A candidate using an externally supplied executor must "
                    "cite at least one reliable support or resistance level."
                )
            return

        parameters = proposal.rule.parameters
        if executor_id == MULTI_ASSET_PORTFOLIO_EXECUTOR_ID:
            try:
                portfolio = TechnicalPortfolioParameters.from_mapping(
                    parameters
                )
            except ValueError as exc:
                raise AgentOutputValidationError(str(exc)) from exc
            sleeve_evidence = {
                evidence_id
                for sleeve in portfolio.sleeves
                for evidence_id in sleeve.evidence_ids
            }
            if sleeve_evidence != referenced:
                raise AgentOutputValidationError(
                    "Portfolio specialty_evidence_ids must equal the union "
                    "of every sleeve's evidence_ids."
                )
            sleeve_weight = (
                portfolio.portfolio_target_gross_weight
                / portfolio.selected_asset_count
            )
            for sleeve in portfolio.sleeves:
                child_parameters = {
                    **portfolio.common_risk_parameters,
                    **sleeve.family_parameters,
                    "symbol": sleeve.symbol,
                    "target_weight": sleeve_weight,
                }
                child_rule = proposal.rule.model_copy(
                    update={
                        "executor_id": sleeve.executor_id,
                        "parameters": child_parameters,
                        "specialty_evidence_ids": list(sleeve.evidence_ids),
                        "specialty_evidence_usage": {
                            evidence_id: (
                                proposal.rule.specialty_evidence_usage[
                                    evidence_id
                                ]
                            )
                            for evidence_id in sleeve.evidence_ids
                        },
                    }
                )
                child_proposal = proposal.model_copy(
                    update={"rule": child_rule}
                )
                StagedTraderAgent._validate_technical_evidence(
                    proposal=child_proposal,
                    technical_analysis=technical_analysis,
                )
            return

        selected_symbol = parameters.get("symbol")
        if not isinstance(selected_symbol, str) or not selected_symbol.strip():
            raise AgentOutputValidationError(
                "A Technical executor candidate must identify a non-empty "
                "symbol parameter."
            )
        selected_symbol = selected_symbol.strip()

        level_by_id = {
            level.level_id: (asset.symbol, level)
            for asset in technical_analysis.assets
            for level in asset.support_resistance_levels
        }
        pattern_by_id = {
            pattern.pattern_id: (asset.symbol, pattern)
            for asset in technical_analysis.assets
            for pattern in asset.chart_patterns
        }
        moving_average_by_id = {
            observation.moving_average_id: (
                asset.symbol,
                observation,
            )
            for asset in technical_analysis.assets
            for observation in asset.available_moving_averages()
        }
        volume_by_id = {
            asset.volume_observation.volume_id: (
                asset.symbol,
                asset.volume_observation,
            )
            for asset in technical_analysis.assets
            if asset.volume_observation is not None
        }
        asset_evidence = {
            **level_by_id,
            **pattern_by_id,
            **moving_average_by_id,
            **volume_by_id,
        }
        wrong_symbol = sorted(
            evidence_id
            for evidence_id in referenced
            if evidence_id in asset_evidence
            and asset_evidence[evidence_id][0] != selected_symbol
        )
        if wrong_symbol:
            raise AgentOutputValidationError(
                "Asset-level technical evidence must belong to the selected "
                f"symbol '{selected_symbol}': " + ", ".join(wrong_symbol)
            )

        def matching_levels(kind: PriceLevelKind) -> list[Any]:
            return [
                level
                for evidence_id, (symbol, level) in level_by_id.items()
                if evidence_id in referenced
                and symbol == selected_symbol
                and level.kind is kind
                and evidence_id in reliable_levels
            ]

        def require_exact_numeric(
            parameter_name: str,
            expected_values: Sequence[float],
            evidence_label: str,
        ) -> None:
            value = parameters.get(parameter_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AgentOutputValidationError(
                    f"Technical executor parameter '{parameter_name}' must "
                    f"match its cited {evidence_label}."
                )
            if not any(
                math.isclose(
                    float(value),
                    float(expected),
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                )
                for expected in expected_values
            ):
                raise AgentOutputValidationError(
                    f"Technical executor parameter '{parameter_name}' does "
                    f"not match its cited {evidence_label}."
                )

        if executor_id == SUPPORT_REACTION_EXECUTOR_ID:
            supports = matching_levels(PriceLevelKind.SUPPORT)
            if not supports:
                raise AgentOutputValidationError(
                    "Support-reaction candidates must cite a reliable support "
                    "level for the selected symbol."
                )
            require_exact_numeric(
                "anchor_level",
                [level.price for level in supports],
                "support price",
            )
        elif executor_id in {
            RESISTANCE_BREAKOUT_EXECUTOR_ID,
            VOLUME_BREAKOUT_EXECUTOR_ID,
        }:
            resistances = matching_levels(PriceLevelKind.RESISTANCE)
            if not resistances:
                raise AgentOutputValidationError(
                    "Breakout candidates must cite a reliable resistance "
                    "level for the selected symbol."
                )
            require_exact_numeric(
                "anchor_level",
                [level.price for level in resistances],
                "resistance price",
            )

        if executor_id == MOVING_AVERAGE_TREND_EXECUTOR_ID:
            observations = [
                observation
                for evidence_id, (symbol, observation) in (
                    moving_average_by_id.items()
                )
                if evidence_id in referenced and symbol == selected_symbol
            ]
            if not observations:
                raise AgentOutputValidationError(
                    "Moving-average candidates must cite the deterministic "
                    "moving-average observation for the selected symbol."
                )
            require_exact_numeric(
                "fast_window",
                [observation.fast_window for observation in observations],
                "moving-average fast window",
            )
            require_exact_numeric(
                "slow_window",
                [observation.slow_window for observation in observations],
                "moving-average slow window",
            )
        elif executor_id == VOLUME_BREAKOUT_EXECUTOR_ID:
            observations = [
                observation
                for evidence_id, (symbol, observation) in volume_by_id.items()
                if evidence_id in referenced and symbol == selected_symbol
            ]
            if not observations:
                raise AgentOutputValidationError(
                    "Volume-confirmed breakouts must cite the deterministic "
                    "volume observation for the selected symbol."
                )
            require_exact_numeric(
                "volume_lookback_bars",
                [observation.lookback_window for observation in observations],
                "volume lookback",
            )
        elif executor_id in {
            INVERSE_PATTERN_EXECUTOR_ID,
            HEAD_PATTERN_EXECUTOR_ID,
        }:
            expected_type = (
                ChartPatternType.INVERSE_HEAD_AND_SHOULDERS
                if executor_id == INVERSE_PATTERN_EXECUTOR_ID
                else ChartPatternType.HEAD_AND_SHOULDERS
            )
            patterns = [
                pattern
                for evidence_id, (symbol, pattern) in pattern_by_id.items()
                if evidence_id in referenced
                and symbol == selected_symbol
                and pattern.pattern_type is expected_type
                and pattern.status is ChartPatternStatus.CONFIRMED
            ]
            if not patterns:
                raise AgentOutputValidationError(
                    "Pattern executors require a cited, confirmed matching "
                    "pattern for the selected symbol."
                )
            require_exact_numeric(
                "neckline_price",
                [pattern.neckline_price for pattern in patterns],
                "confirmed pattern neckline",
            )

    @staticmethod
    def _mandate_constraints(request: TraderTask) -> dict[str, Any]:
        mandate = request.mandate
        return {
            "risk_profile": mandate.risk_profile,
            "investment_horizon": mandate.investment_horizon,
            "liquidity_requirements": mandate.liquidity_requirements,
            "permitted_asset_universe": mandate.permitted_asset_universe,
            "prohibited_assets": mandate.prohibited_assets,
            "leverage_constraints": mandate.leverage_constraints,
            "short_selling_constraints": mandate.short_selling_constraints,
            "risk_limits": mandate.risk_limits,
            "rebalancing_preference": mandate.rebalancing_preference,
        }

    @staticmethod
    def _coerce_data_response(value: Any) -> DataResponse:
        if isinstance(value, DataResponse):
            return value
        if isinstance(value, Mapping):
            try:
                return DataResponse.model_validate(value)
            except ValidationError as exc:
                raise ServiceContractError(
                    f"Invalid Data Service response: {exc}"
                ) from exc
        raise ServiceContractError(
            f"Data Service returned {type(value).__name__}, expected DataResponse."
        )

    @staticmethod
    def _validate_data_response(
        *,
        request: TraderTask,
        data_request: DataRequest,
        data_response: DataResponse,
    ) -> None:
        if data_response.request_id != data_request.request_id:
            raise ServiceContractError("Data response request_id does not match.")
        if data_response.lineage.workflow_id != request.lineage.workflow_id:
            raise ServiceContractError("Data response workflow lineage does not match.")
        if data_response.as_of_date > request.mandate.as_of_date:
            raise ServiceContractError(
                "Data response exceeds the PM mandate as-of date."
            )

    @staticmethod
    def _ensure_required_data_available(
        *,
        research_plan: TraderResearchPlanDraft,
        data_response: DataResponse,
    ) -> None:
        if not data_response.artifacts:
            raise ServiceContractError("Data Service returned no data artifacts.")
        if not all(artifact.provenance for artifact in data_response.artifacts):
            raise ServiceContractError(
                "Data Service response is missing provenance."
            )
        unavailable = {item.casefold() for item in data_response.unavailable_fields}
        missing_required = [
            field.name
            for field in research_plan.fields
            if field.required and field.name.casefold() in unavailable
        ]
        if missing_required:
            raise ServiceContractError(
                "Required fields are unavailable: " + ", ".join(missing_required)
            )

    @staticmethod
    def _coerce_backtest_result(value: Any) -> BacktestResult:
        if isinstance(value, BacktestResult):
            return value
        if isinstance(value, Mapping):
            try:
                return BacktestResult.model_validate(value)
            except ValidationError as exc:
                raise ServiceContractError(
                    f"Invalid Backtest Engine result: {exc}"
                ) from exc
        raise ServiceContractError(
            f"Backtest Engine returned {type(value).__name__}, "
            "expected BacktestResult."
        )

    @staticmethod
    def _validate_backtest_result(
        request: BacktestRequest,
        result: BacktestResult,
    ) -> None:
        if result.request_id != request.request_id:
            raise ServiceContractError("Backtest result request_id does not match.")
        if result.candidate_id != request.candidate_id:
            raise ServiceContractError("Backtest result candidate_id does not match.")

    @staticmethod
    def _validate_benchmark_comparison_window(
        request: BacktestRequest,
    ) -> None:
        plan = request.plan
        split = plan.validation_split
        requested_end = plan.requested_end_date or request.as_of_date
        if (
            split is None
            or plan.requested_start_date is None
            or plan.requested_start_date != split.test_start_date
            or requested_end != split.test_end_date
        ):
            raise ServiceContractError(
                "The Technical benchmark gate currently requires the "
                "requested Backtest Plan window to exactly equal the "
                "injected shared validation split."
            )

    @staticmethod
    def _validate_like_for_like_benchmark_requests(
        technical_request: BacktestRequest,
        benchmark_request: BacktestRequest,
    ) -> None:
        """Require every comparison input except the candidate to be equal."""

        unequal_fields = []
        if technical_request.plan != benchmark_request.plan:
            unequal_fields.append("plan")
        if (
            technical_request.execution_context
            != benchmark_request.execution_context
        ):
            unequal_fields.append("execution_context")
        if technical_request.as_of_date != benchmark_request.as_of_date:
            unequal_fields.append("as_of_date")
        if technical_request.data_references != benchmark_request.data_references:
            unequal_fields.append("data_references")
        if (
            technical_request.mandate_constraints
            != benchmark_request.mandate_constraints
        ):
            unequal_fields.append("mandate_constraints")
        if technical_request.trader_id is not benchmark_request.trader_id:
            unequal_fields.append("trader_id")
        if unequal_fields:
            raise ServiceContractError(
                "Technical and executable benchmark requests are not "
                "like-for-like; unequal fields: " + ", ".join(unequal_fields)
            )

    @staticmethod
    def _validate_metric_references(
        interpretation: BacktestInterpretationDraft,
        result: BacktestResult,
    ) -> None:
        known_metrics = {
            *result.metrics,
            *result.out_of_sample_metrics,
            *result.benchmark_metrics,
        }
        unknown = [
            item.metric_name
            for item in interpretation.metric_interpretations
            if item.metric_name not in known_metrics
        ]
        if unknown:
            raise AgentOutputValidationError(
                "Interpretation referenced metrics absent from the deterministic "
                "result: " + ", ".join(unknown)
            )

    @staticmethod
    def _constraint_assessment(
        proposal_violations: list[str],
        mappings: list[str],
        engine_violations: list[str],
    ) -> MandateConstraintAssessment:
        violations = [*proposal_violations, *engine_violations]
        return MandateConstraintAssessment(
            status=(
                ConstraintCheckStatus.VIOLATION_IDENTIFIED
                if violations
                else ConstraintCheckStatus.DECLARED_ALIGNED
            ),
            mappings=mappings,
            violations=violations,
            requires_risk_validation=True,
        )

    def _failure_package(
        self,
        request: TraderTask,
        *,
        stage: str,
        exc: Exception,
        retryable: bool,
        data_request: DataRequest | None = None,
        data_response: DataResponse | None = None,
        technical_analysis: TechnicalAnalysisReport | None = None,
        candidate_rule: CandidateRuleSpecification | None = None,
        backtest_request: BacktestRequest | None = None,
        backtest_result: BacktestResult | None = None,
    ) -> TraderStrategyPackage:
        partial = any(
            item is not None
            for item in (
                data_request,
                data_response,
                technical_analysis,
                candidate_rule,
                backtest_request,
                backtest_result,
            )
        )
        return TraderStrategyPackage(
            package_id=f"{request.lineage.task_id}.package",
            candidate_id=(
                candidate_rule.candidate_id if candidate_rule is not None else None
            ),
            trader_id=self.trader_id,
            lineage=request.lineage,
            mandate_reference=request.mandate.reference(),
            status=RunStatus.PARTIAL if partial else RunStatus.FAILED,
            hypothesis=(
                candidate_rule.hypothesis if candidate_rule is not None else None
            ),
            data_request=data_request,
            data_usage=(
                DataUsageSummary.from_response(data_response)
                if data_response is not None
                else None
            ),
            specialty_evidence=self._specialty_evidence(technical_analysis),
            candidate_rule=candidate_rule,
            backtest_request=backtest_request,
            backtest_result=backtest_result,
            interpretation=None,
            constraint_assessment=MandateConstraintAssessment(
                status=ConstraintCheckStatus.NOT_EVALUATED,
                requires_risk_validation=True,
            ),
            failures=[
                TraderFailure(
                    stage=stage,
                    message=str(exc) or type(exc).__name__,
                    retryable=retryable,
                )
            ],
            eligible_for_risk_review=False,
        )

    @staticmethod
    def _specialty_evidence(
        technical_analysis: TechnicalAnalysisReport | None,
    ) -> dict[str, Any]:
        if technical_analysis is None:
            return {}
        return {
            "technical_analysis": technical_analysis.model_dump(mode="json")
        }
