"""Input and standardized output contracts for the Technical Trader."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from .backtest import (
    BacktestRequest,
    BacktestResult,
    CandidateRuleSpecification,
)
from .common import (
    ConfidenceAssessment,
    ContractModel,
    MandateReference,
    NonEmptyStr,
    TaskLineage,
    TraderRunStatus,
    TraderType,
)
from .data import (
    DataCategory,
    DataFieldRequirement,
    DataRequest,
    DataResponse,
)
from .mandate import PMMandate
from .technical_analysis import TechnicalAnalysisReport


class TraderTask(ContractModel):
    mandate: PMMandate
    lineage: TaskLineage
    trader_type: TraderType


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
    metric_interpretations: list[MetricInterpretation] = Field(default_factory=list)
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
        return cls(
            response_id=response.response_id,
            artifact_ids=[artifact.artifact_id for artifact in response.artifacts],
            data_references=[
                artifact.data_reference for artifact in response.artifacts
            ],
            provenance_ids=[
                provenance.provenance_id
                for artifact in response.artifacts
                for provenance in artifact.provenance
            ],
            unavailable_fields=response.unavailable_fields,
            limitations=[
                *response.limitations,
                *(
                    limitation
                    for artifact in response.artifacts
                    for limitation in artifact.limitations
                ),
            ],
            point_in_time_verified=all(
                provenance.point_in_time_verified
                for artifact in response.artifacts
                for provenance in artifact.provenance
            ),
        )


class TraderStrategyPackage(ContractModel):
    """Provisional Risk-facing output produced by the Technical Trader."""

    package_id: NonEmptyStr
    candidate_id: NonEmptyStr | None = None
    trader_type: TraderType
    lineage: TaskLineage
    mandate_reference: MandateReference
    status: TraderRunStatus
    hypothesis: NonEmptyStr | None = None
    data_request: DataRequest | None = None
    data_usage: DataUsageSummary | None = None
    technical_analysis: TechnicalAnalysisReport | None = None
    candidate_rule: CandidateRuleSpecification | None = None
    backtest_request: BacktestRequest | None = None
    backtest_result: BacktestResult | None = None
    interpretation: BacktestInterpretationDraft | None = None
    constraint_assessment: MandateConstraintAssessment
    failures: list[TraderFailure] = Field(default_factory=list)
    eligible_for_risk_review: bool = False

    @model_validator(mode="after")
    def enforce_risk_eligibility(self) -> "TraderStrategyPackage":
        if self.eligible_for_risk_review:
            required = (
                self.candidate_id,
                self.technical_analysis,
                self.candidate_rule,
                self.backtest_request,
                self.backtest_result,
                self.interpretation,
            )
            if self.status is not TraderRunStatus.COMPLETED or any(
                item is None for item in required
            ):
                raise ValueError(
                    "Risk-eligible packages must be complete and backtested."
                )
        return self
