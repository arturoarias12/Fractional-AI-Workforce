"""Provisional candidate-rule and deterministic Backtest Engine contracts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from .common import (
    ContractModel,
    ExtensibleModel,
    NonEmptyStr,
    TaskLineage,
    TraderType,
)


class CandidateRuleDraft(ContractModel):
    """LLM-generated, codeable rule with no embedded performance claims."""

    strategy_name: NonEmptyStr
    hypothesis: NonEmptyStr
    rule_summary: NonEmptyStr
    asset_eligibility_logic: NonEmptyStr
    signal_logic: NonEmptyStr
    position_logic: NonEmptyStr
    entry_logic: NonEmptyStr
    exit_logic: NonEmptyStr
    rebalancing_logic: NonEmptyStr
    parameters: dict[str, Any] = Field(default_factory=dict)
    technical_evidence_ids: list[NonEmptyStr] = Field(min_length=1)
    technical_evidence_usage: dict[NonEmptyStr, NonEmptyStr] = Field(
        min_length=1
    )
    required_data_fields: list[NonEmptyStr] = Field(default_factory=list)
    constraint_handling: list[NonEmptyStr] = Field(default_factory=list)
    implementation_notes: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def map_every_evidence_reference(self) -> "CandidateRuleDraft":
        if set(self.technical_evidence_ids) != set(
            self.technical_evidence_usage
        ):
            raise ValueError(
                "technical_evidence_usage must explain every cited evidence ID "
                "and may not introduce uncited IDs."
            )
        return self


class BacktestPlanDraft(ContractModel):
    """Trader-requested evaluation settings; the engine remains authoritative."""

    requested_start_date: date | None = None
    requested_end_date: date | None = None
    frequency: NonEmptyStr
    benchmark: NonEmptyStr | None = None
    transaction_cost_assumptions: dict[str, Any] = Field(default_factory=dict)
    requested_metrics: list[NonEmptyStr] = Field(default_factory=list)
    validation_requirements: list[NonEmptyStr] = Field(default_factory=list)
    held_out_evaluation_required: bool = True


class CandidateProposalDraft(ContractModel):
    rule: CandidateRuleDraft
    backtest_plan: BacktestPlanDraft
    mandate_constraint_mapping: list[NonEmptyStr] = Field(default_factory=list)
    known_constraint_violations: list[NonEmptyStr] = Field(default_factory=list)


class CandidateRuleSpecification(CandidateRuleDraft):
    candidate_id: NonEmptyStr
    trader_type: TraderType
    lineage: TaskLineage


class BacktestRequest(ExtensibleModel):
    request_id: NonEmptyStr
    candidate_id: NonEmptyStr
    trader_type: TraderType
    lineage: TaskLineage
    as_of_date: date
    rule: CandidateRuleSpecification
    plan: BacktestPlanDraft
    data_references: list[NonEmptyStr] = Field(min_length=1)
    mandate_constraints: dict[str, Any] = Field(default_factory=dict)


class BacktestStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INSUFFICIENT_DATA = "insufficient_data"


class BacktestResult(ExtensibleModel):
    """Result calculated by deterministic code, never by an LLM."""

    result_id: NonEmptyStr
    request_id: NonEmptyStr
    candidate_id: NonEmptyStr
    status: BacktestStatus
    computed_by: Literal["deterministic_backtest_engine"]
    engine_name: NonEmptyStr
    engine_version: NonEmptyStr
    metrics: dict[str, float | int | None] = Field(default_factory=dict)
    out_of_sample_metrics: dict[str, float | int | None] = Field(
        default_factory=dict
    )
    benchmark_metrics: dict[str, float | int | None] = Field(default_factory=dict)
    warnings: list[NonEmptyStr] = Field(default_factory=list)
    constraint_violations: list[NonEmptyStr] = Field(default_factory=list)
    artifact_references: list[NonEmptyStr] = Field(default_factory=list)
    failure_reason: NonEmptyStr | None = None
