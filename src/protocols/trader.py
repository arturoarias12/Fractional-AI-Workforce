"""Lens-neutral trader task and result contracts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from .backtest import (
    BacktestRequest,
    BacktestResult,
    CandidateRuleSpecification,
)
from .common import (
    TERMINAL_TRADER_STATUSES,
    ConfidenceAssessment,
    ContractModel,
    MandateReference,
    NonEmptyStr,
    ResearchExecutionContext,
    RunStatus,
    SpecialistId,
    TaskLineage,
)
from .data import DataCategory, DataFieldRequirement, DataRequest, DataResponse
from .mandate import PMMandate


class TraderTask(ContractModel):
    mandate: PMMandate
    lineage: TaskLineage
    trader_id: SpecialistId
    execution_context: ResearchExecutionContext

    @model_validator(mode="after")
    def align_context_and_lineage(self) -> "TraderTask":
        if self.execution_context.attempt != self.lineage.attempt:
            raise ValueError(
                "TraderTask execution-context and lineage attempts must match."
            )
        return self


class TraderResearchPlanDraft(ContractModel):
    purpose: NonEmptyStr
    categories: list[DataCategory] = Field(min_length=1)
    fields: list[DataFieldRequirement] = Field(min_length=1)
    start_date: date | None = None
    end_date: date | None = None
    frequency: NonEmptyStr | None = None
    rationale: list[NonEmptyStr] = Field(default_factory=list)


class MetricInterpretation(ContractModel):
    metric_name: NonEmptyStr
    interpretation: NonEmptyStr
    result_section: NonEmptyStr


class BacktestInterpretationDraft(ContractModel):
    summary: NonEmptyStr
    metric_interpretations: list[MetricInterpretation] = Field(
        default_factory=list
    )
    out_of_sample_assessment: NonEmptyStr
    strengths: list[NonEmptyStr] = Field(default_factory=list)
    weaknesses: list[NonEmptyStr] = Field(default_factory=list)
    overfitting_risks: list[NonEmptyStr] = Field(default_factory=list)
    limitations: list[NonEmptyStr] = Field(default_factory=list)
    mandate_alignment: list[NonEmptyStr] = Field(default_factory=list)
    open_questions: list[NonEmptyStr] = Field(default_factory=list)
    confidence: ConfidenceAssessment


class ConstraintCheckStatus(StrEnum):
    DECLARED_ALIGNED = "declared_aligned"
    VIOLATION_IDENTIFIED = "violation_identified"
    NOT_EVALUATED = "not_evaluated"


class MandateConstraintAssessment(ContractModel):
    status: ConstraintCheckStatus
    mappings: list[NonEmptyStr] = Field(default_factory=list)
    violations: list[NonEmptyStr] = Field(default_factory=list)
    requires_risk_validation: bool = True


class TraderFailure(ContractModel):
    stage: NonEmptyStr
    message: NonEmptyStr
    retryable: bool


class DataUsageSummary(ContractModel):
    response_id: NonEmptyStr
    artifact_ids: list[NonEmptyStr] = Field(default_factory=list)
    data_references: list[NonEmptyStr] = Field(default_factory=list)
    provenance_ids: list[NonEmptyStr] = Field(default_factory=list)
    unavailable_fields: list[NonEmptyStr] = Field(default_factory=list)
    limitations: list[NonEmptyStr] = Field(default_factory=list)
    point_in_time_verified: bool

    @classmethod
    def from_response(cls, response: DataResponse) -> "DataUsageSummary":
        provenance = [
            item
            for artifact in response.artifacts
            for item in artifact.provenance
        ]
        return cls(
            response_id=response.response_id,
            artifact_ids=[
                artifact.artifact_id for artifact in response.artifacts
            ],
            data_references=[
                artifact.data_reference for artifact in response.artifacts
            ],
            provenance_ids=[item.provenance_id for item in provenance],
            unavailable_fields=response.unavailable_fields,
            limitations=[
                *response.limitations,
                *(
                    limitation
                    for artifact in response.artifacts
                    for limitation in artifact.limitations
                ),
            ],
            point_in_time_verified=bool(provenance) and all(
                item.point_in_time_verified for item in provenance
            ),
        )


class TraderStrategyPackage(ContractModel):
    """Settled Risk-facing output produced by any trader branch."""

    package_id: NonEmptyStr
    candidate_id: NonEmptyStr | None = None
    trader_id: SpecialistId
    lineage: TaskLineage
    mandate_reference: MandateReference
    status: RunStatus
    hypothesis: NonEmptyStr | None = None
    data_request: DataRequest | None = None
    data_usage: DataUsageSummary | None = None
    specialty_evidence: dict[str, Any] = Field(default_factory=dict)
    candidate_rule: CandidateRuleSpecification | None = None
    backtest_request: BacktestRequest | None = None
    backtest_result: BacktestResult | None = None
    interpretation: BacktestInterpretationDraft | None = None
    constraint_assessment: MandateConstraintAssessment
    failures: list[TraderFailure] = Field(default_factory=list)
    eligible_for_risk_review: bool = False
    additional_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def derive_legacy_mandate_reference(cls, value: Any) -> Any:
        if isinstance(value, dict):
            normalized = dict(value)
            if "mandate_reference" not in normalized:
                lineage = normalized.get("lineage")
                workflow_id = (
                    lineage.workflow_id
                    if isinstance(lineage, TaskLineage)
                    else lineage.get("workflow_id")
                    if isinstance(lineage, dict)
                    else None
                )
                task_id = normalized.get("mandate_task_id")
                as_of_date = normalized.get("as_of_date")
                if workflow_id and task_id and as_of_date:
                    normalized["mandate_reference"] = {
                        "workflow_id": workflow_id,
                        "task_id": task_id,
                        "as_of_date": as_of_date,
                    }
                    normalized.pop("mandate_task_id", None)
                    normalized.pop("as_of_date", None)
            return normalized
        return value

    @property
    def mandate_task_id(self) -> str:
        return self.mandate_reference.task_id

    @property
    def as_of_date(self) -> date:
        return self.mandate_reference.as_of_date

    @model_validator(mode="after")
    def restrict_status_to_settled_outcomes(self) -> "TraderStrategyPackage":
        if self.status not in TERMINAL_TRADER_STATUSES:
            raise ValueError(
                "Trader packages must be settled as completed, partial, or "
                "failed."
            )
        return self

    @model_validator(mode="after")
    def enforce_risk_eligibility(self) -> "TraderStrategyPackage":
        if self.eligible_for_risk_review:
            required = (
                self.candidate_id,
                self.candidate_rule,
                self.backtest_request,
                self.backtest_result,
                self.interpretation,
            )
            if (
                self.status is not RunStatus.COMPLETED
                or any(item is None for item in required)
                or not self.specialty_evidence
            ):
                raise ValueError(
                    "Risk-eligible packages must be complete, carry specialty "
                    "evidence, and be backtested."
                )
        return self
