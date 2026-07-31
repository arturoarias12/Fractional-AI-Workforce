"""Candidate-rule and deterministic Backtest Engine contracts.

Models may describe and parameterize a strategy, but only a registered
deterministic executor may run it and only the engine may report performance.
The validation split is code-owned and supplied by shared evaluation policy.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from .common import (
    ContractModel,
    ExtensibleModel,
    NonEmptyStr,
    SpecialistId,
    TaskLineage,
)


class CandidateRuleDraft(ContractModel):
    """LLM-authored rule restricted to a registered executor."""

    strategy_name: NonEmptyStr
    hypothesis: NonEmptyStr
    rule_summary: NonEmptyStr
    executor_id: NonEmptyStr
    asset_eligibility_logic: NonEmptyStr
    signal_logic: NonEmptyStr
    position_logic: NonEmptyStr
    entry_logic: NonEmptyStr
    exit_logic: NonEmptyStr
    rebalancing_logic: NonEmptyStr
    parameters: dict[str, Any] = Field(default_factory=dict)
    specialty_evidence_ids: list[NonEmptyStr] = Field(min_length=1)
    specialty_evidence_usage: dict[NonEmptyStr, NonEmptyStr] = Field(
        min_length=1
    )
    required_data_fields: list[NonEmptyStr] = Field(default_factory=list)
    constraint_handling: list[NonEmptyStr] = Field(default_factory=list)
    implementation_notes: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def map_every_evidence_reference(self) -> "CandidateRuleDraft":
        if set(self.specialty_evidence_ids) != set(
            self.specialty_evidence_usage
        ):
            raise ValueError(
                "specialty_evidence_usage must explain every cited evidence "
                "ID and may not introduce uncited IDs."
            )
        return self


class CandidateRuleSpecification(CandidateRuleDraft):
    candidate_id: NonEmptyStr
    trader_id: SpecialistId
    lineage: TaskLineage


class BacktestPlanDraft(ContractModel):
    """Model-requested settings before code adds evaluation policy."""

    requested_start_date: date | None = None
    requested_end_date: date | None = None
    frequency: NonEmptyStr
    benchmark: NonEmptyStr | None = None
    transaction_cost_assumptions: dict[str, Any] = Field(default_factory=dict)
    requested_metrics: list[NonEmptyStr] = Field(default_factory=list)
    validation_requirements: list[NonEmptyStr] = Field(default_factory=list)
    held_out_evaluation_required: bool = True

    @model_validator(mode="after")
    def validate_requested_window(self) -> "BacktestPlanDraft":
        if (
            self.requested_start_date is not None
            and self.requested_end_date is not None
            and self.requested_start_date > self.requested_end_date
        ):
            raise ValueError(
                "requested_start_date must not exceed requested_end_date."
            )
        return self


class ValidationSplit(ContractModel):
    """Fixed, code-owned test window shared across trader evaluations."""

    test_start_date: date
    test_end_date: date

    @model_validator(mode="after")
    def validate_window(self) -> "ValidationSplit":
        if self.test_start_date > self.test_end_date:
            raise ValueError(
                "test_start_date must not exceed test_end_date."
            )
        return self


class BacktestPlan(BacktestPlanDraft):
    """Finalized plan sent to the deterministic engine."""

    validation_split: ValidationSplit | None = None

    @model_validator(mode="after")
    def require_split_when_held_out_is_required(self) -> "BacktestPlan":
        if self.held_out_evaluation_required and self.validation_split is None:
            raise ValueError(
                "A finalized held-out plan requires a code-owned "
                "validation_split."
            )
        return self

    @classmethod
    def from_draft(
        cls,
        draft: BacktestPlanDraft,
        *,
        validation_split: ValidationSplit | None,
    ) -> "BacktestPlan":
        return cls(
            **draft.model_dump(mode="python"),
            validation_split=validation_split,
        )


class CandidateProposalDraft(ContractModel):
    rule: CandidateRuleDraft
    backtest_plan: BacktestPlanDraft
    mandate_constraint_mapping: list[NonEmptyStr] = Field(default_factory=list)
    known_constraint_violations: list[NonEmptyStr] = Field(default_factory=list)


class BacktestRequest(ExtensibleModel):
    request_id: NonEmptyStr
    trader_id: SpecialistId
    lineage: TaskLineage
    as_of_date: date
    candidate: CandidateRuleSpecification
    plan: BacktestPlan
    data_references: list[NonEmptyStr] = Field(min_length=1)
    mandate_constraints: dict[str, Any] = Field(default_factory=dict)
    additional_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def derive_legacy_identity(cls, value: Any) -> Any:
        if isinstance(value, dict):
            normalized = dict(value)
            candidate = normalized.get("candidate")
            if "trader_id" not in normalized:
                if isinstance(candidate, CandidateRuleSpecification):
                    normalized["trader_id"] = candidate.trader_id
                elif isinstance(candidate, dict) and "trader_id" in candidate:
                    normalized["trader_id"] = candidate["trader_id"]
            return normalized
        return value

    @property
    def candidate_id(self) -> str:
        return self.candidate.candidate_id

    @property
    def executor_id(self) -> str:
        return self.candidate.executor_id

    @model_validator(mode="after")
    def validate_identity_and_windows(self) -> "BacktestRequest":
        if self.candidate.trader_id is not self.trader_id:
            raise ValueError(
                "Backtest request and candidate trader_id must match."
            )
        if self.candidate.lineage.workflow_id != self.lineage.workflow_id:
            raise ValueError(
                "Backtest request and candidate workflow lineage must match."
            )
        if (
            self.plan.requested_end_date is not None
            and self.plan.requested_end_date > self.as_of_date
        ):
            raise ValueError(
                "Backtest end date cannot exceed the request as-of date."
            )
        split = self.plan.validation_split
        if split is not None and split.test_end_date > self.as_of_date:
            raise ValueError(
                "Validation split cannot exceed the request as-of date."
            )
        return self


class BacktestStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INSUFFICIENT_DATA = "insufficient_data"


class BacktestResult(ExtensibleModel):
    """Performance output calculated only by deterministic code."""

    result_id: NonEmptyStr
    request_id: NonEmptyStr
    candidate_id: NonEmptyStr
    status: BacktestStatus
    computed_by: Literal["deterministic_backtest_engine"] = (
        "deterministic_backtest_engine"
    )
    engine_name: NonEmptyStr
    engine_version: NonEmptyStr
    metrics: dict[str, float | int | None] = Field(default_factory=dict)
    out_of_sample_metrics: dict[str, float | int | None] = Field(
        default_factory=dict
    )
    benchmark_metrics: dict[str, float | int | None] = Field(
        default_factory=dict
    )
    warnings: list[NonEmptyStr] = Field(default_factory=list)
    constraint_violations: list[NonEmptyStr] = Field(default_factory=list)
    artifact_references: list[NonEmptyStr] = Field(default_factory=list)
    failure_reason: NonEmptyStr | None = None
    additional_fields: dict[str, Any] = Field(default_factory=dict)
