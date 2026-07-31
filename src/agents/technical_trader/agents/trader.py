"""Staged pipeline used by the Technical Trader Agent."""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import Mapping, Sequence
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
from ..execution import ExecutionPolicy
from ..model_client import MetricsSink, ModelClient, ModelRequestContext
from ..models.technical_analysis import TechnicalAnalysisReport
from ..prompts import (
    render_backtest_interpretation,
    render_candidate_proposal,
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
                ),
                response_model=TraderResearchPlanDraft,
                context=self._model_context(request, "plan_data"),
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
            technical_analysis = self._technical_toolkit.analyze(
                series=series,
                as_of_date=request.mandate.as_of_date,
                report_id=f"{request.lineage.task_id}.technical-analysis",
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

        try:
            proposal = await self._generate_structured(
                system_prompt=self._system_prompt,
                user_prompt=render_candidate_proposal(
                    mandate=request.mandate,
                    data_response=data_response,
                    technical_analysis=technical_analysis,
                    lens_requirements=self._lens_requirements,
                    available_executors=self._available_executors,
                ),
                response_model=CandidateProposalDraft,
                context=self._model_context(request, "propose_candidate"),
            )
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

        try:
            interpretation = await self._generate_structured(
                system_prompt=self._system_prompt,
                user_prompt=render_backtest_interpretation(
                    mandate=request.mandate,
                    candidate_rule=candidate_rule,
                    backtest_result=backtest_result,
                    lens_requirements=self._lens_requirements,
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

        constraint_assessment = self._constraint_assessment(
            proposal.known_constraint_violations,
            proposal.mandate_constraint_mapping,
            backtest_result.constraint_violations,
        )
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
            eligible_for_risk_review=True,
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
        self._validate_technical_evidence(
            proposal=proposal,
            technical_analysis=technical_analysis,
        )
        self._validate_executor_selection(proposal)
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

    def _validate_executor_selection(
        self,
        proposal: CandidateProposalDraft,
    ) -> None:
        executor_id = proposal.rule.executor_id
        if executor_id not in self._available_executors:
            raise AgentOutputValidationError(
                f"Candidate selected unregistered executor '{executor_id}'. "
                "Available executors: "
                + ", ".join(self._available_executors)
                + "."
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
            "timestamp": ("timestamp", "datetime", "date"),
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
        if not referenced.intersection(reliable_levels):
            raise AgentOutputValidationError(
                "Candidate must use at least one non-fallback support level at "
                "or below the latest close, or resistance level at or above it."
            )
        cited_levels = referenced.intersection(technical_analysis.level_ids())
        unreliable_cited_levels = sorted(cited_levels - reliable_levels)
        if unreliable_cited_levels:
            raise AgentOutputValidationError(
                "Candidate may not cite fallback or wrong-side support/"
                "resistance levels: " + ", ".join(unreliable_cited_levels)
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
        if not all(
            provenance.point_in_time_verified
            for artifact in data_response.artifacts
            for provenance in artifact.provenance
        ):
            raise ServiceContractError(
                "Data Service response contains unverified point-in-time evidence."
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
