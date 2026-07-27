"""Version-zero, provider-neutral research contracts.

These dataclasses are architectural placeholders, not final cross-team schemas.
Fields should be versioned or adapted when component owners publish their
contracts; provider-specific SDK objects must not leak into this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal, Mapping


class SpecialistId(StrEnum):
    TECHNICAL_TRADER = "technical_trader_agent"
    FUNDAMENTAL_TRADER = "fundamental_trader_agent"
    QUANT_TRADER = "quant_trader_agent"
    RISK = "risk_agent"
    REPORTING = "reporting_agent"


TRADER_IDS: tuple[SpecialistId, ...] = (
    SpecialistId.TECHNICAL_TRADER,
    SpecialistId.FUNDAMENTAL_TRADER,
    SpecialistId.QUANT_TRADER,
)


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class TaskLineage:
    workflow_id: str
    task_id: str
    parent_task_id: str
    source_task_id: str
    attempt: int = 1


@dataclass(frozen=True, slots=True)
class PMMandate:
    workflow_id: str
    task_id: str
    as_of_date: date
    investment_objective: str
    permitted_asset_universe: tuple[str, ...] = ()
    prohibited_assets: tuple[str, ...] = ()
    risk_profile: str | Mapping[str, Any] | None = None
    investment_horizon: str | Mapping[str, Any] | None = None
    liquidity_requirements: str | Mapping[str, Any] | None = None
    leverage_constraints: str | Mapping[str, Any] | None = None
    short_selling_constraints: str | Mapping[str, Any] | None = None
    risk_limits: Mapping[str, Any] = field(default_factory=dict)
    rebalancing_preference: str | Mapping[str, Any] | None = None
    prior_round_lessons: tuple[str, ...] = ()
    additional_fields: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DataRequest:
    request_id: str
    lineage: TaskLineage
    trader_id: SpecialistId
    as_of_date: date
    purpose: str
    asset_universe: tuple[str, ...]
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...] = ()
    start_date: date | None = None
    end_date: date | None = None
    frequency: str | None = None
    provenance_required: bool = True
    additional_fields: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DataProvenance:
    provenance_id: str
    provider: str
    source_reference: str
    retrieved_at: datetime
    point_in_time_verified: bool
    effective_at: datetime | None = None
    published_at: datetime | None = None
    version: str | None = None
    checksum: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DataArtifact:
    artifact_id: str
    data_reference: str
    description: str
    schema_fields: tuple[str, ...]
    asset_scope: tuple[str, ...]
    provenance: tuple[DataProvenance, ...]
    coverage_start: date | None = None
    coverage_end: date | None = None
    frequency: str | None = None
    limitations: tuple[str, ...] = ()
    adapter_payload: Any | None = None


@dataclass(frozen=True, slots=True)
class DataResponse:
    response_id: str
    request_id: str
    lineage: TaskLineage
    as_of_date: date
    complete: bool
    artifacts: tuple[DataArtifact, ...] = ()
    unavailable_fields: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    additional_fields: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CandidateRuleSpecification:
    candidate_id: str
    trader_id: SpecialistId
    lineage: TaskLineage
    strategy_name: str
    hypothesis: str
    rule_summary: str
    asset_eligibility_logic: str
    signal_logic: str
    position_logic: str
    entry_logic: str
    exit_logic: str
    rebalancing_logic: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    specialty_evidence_ids: tuple[str, ...] = ()
    specialty_evidence_usage: Mapping[str, str] = field(default_factory=dict)
    required_data_fields: tuple[str, ...] = ()
    constraint_handling: tuple[str, ...] = ()
    implementation_notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BacktestPlan:
    frequency: str
    requested_start_date: date | None = None
    requested_end_date: date | None = None
    benchmark: str | None = None
    transaction_cost_assumptions: Mapping[str, Any] = field(
        default_factory=dict
    )
    requested_metrics: tuple[str, ...] = ()
    validation_requirements: tuple[str, ...] = ()
    held_out_evaluation_required: bool = True


@dataclass(frozen=True, slots=True)
class BacktestRequest:
    request_id: str
    lineage: TaskLineage
    candidate: CandidateRuleSpecification
    as_of_date: date
    plan: BacktestPlan
    data_references: tuple[str, ...]
    mandate_constraints: Mapping[str, Any] = field(default_factory=dict)
    additional_fields: Mapping[str, Any] = field(default_factory=dict)


class BacktestStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True, slots=True)
class BacktestResult:
    result_id: str
    request_id: str
    candidate_id: str
    status: BacktestStatus
    engine_name: str
    engine_version: str
    computed_by: Literal["deterministic_backtest_engine"] = (
        "deterministic_backtest_engine"
    )
    metrics: Mapping[str, float | int | None] = field(default_factory=dict)
    out_of_sample_metrics: Mapping[str, float | int | None] = field(
        default_factory=dict
    )
    benchmark_metrics: Mapping[str, float | int | None] = field(
        default_factory=dict
    )
    warnings: tuple[str, ...] = ()
    constraint_violations: tuple[str, ...] = ()
    artifact_references: tuple[str, ...] = ()
    failure_reason: str | None = None
    additional_fields: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TraderFailure:
    stage: str
    message: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class TraderStrategyPackage:
    package_id: str
    trader_id: SpecialistId
    lineage: TaskLineage
    mandate_task_id: str
    as_of_date: date
    status: RunStatus
    candidate_id: str | None = None
    hypothesis: str | None = None
    data_request: DataRequest | None = None
    data_references: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    specialty_evidence: Mapping[str, Any] = field(default_factory=dict)
    candidate_rule: CandidateRuleSpecification | None = None
    backtest_request: BacktestRequest | None = None
    backtest_result: BacktestResult | None = None
    interpretation: Mapping[str, Any] = field(default_factory=dict)
    constraint_assessment: Mapping[str, Any] = field(default_factory=dict)
    failures: tuple[TraderFailure, ...] = ()
    eligible_for_risk_review: bool = False
    additional_fields: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RiskReviewRequest:
    request_id: str
    mandate_task_id: str
    as_of_date: date
    candidates: tuple[TraderStrategyPackage, ...]
    excluded_packages: tuple[TraderStrategyPackage, ...] = ()
    total_candidates_attempted: int = 0
    required_collective_checks: tuple[str, ...] = (
        "overfitting_and_data_snooping",
        "look_ahead_and_point_in_time_integrity",
        "out_of_sample_performance",
        "asset_universe_cherry_picking",
        "cross_candidate_selection_bias",
        "mandate_and_execution_constraints",
    )


class RiskVerdict(StrEnum):
    APPROVE = "approve"
    VETO = "veto"


@dataclass(frozen=True, slots=True)
class RiskCandidateDecision:
    candidate_id: str
    verdict: RiskVerdict
    critiques: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RiskReviewResponse:
    response_id: str
    request_id: str
    decisions: tuple[RiskCandidateDecision, ...]
    collective_critiques: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReportingRequest:
    request_id: str
    mandate_task_id: str
    surviving_candidates: tuple[TraderStrategyPackage, ...]
    risk_response: RiskReviewResponse


@dataclass(frozen=True, slots=True)
class ReportingOutput:
    output_id: str
    request_id: str
    surviving_candidate_ids: tuple[str, ...]
    strategy_memo_reference: str | None = None
    comparison: Mapping[str, Any] = field(default_factory=dict)
    combination_logic_implemented: Literal[False] = False


class PMDecisionType(StrEnum):
    SELECT = "select"
    REJECT = "reject"
    REQUEST_ANOTHER_ROUND = "request_another_round"


@dataclass(frozen=True, slots=True)
class PMDecision:
    decision_id: str
    workflow_id: str
    decision: PMDecisionType
    selected_candidate_id: str | None = None
    rationale: str | None = None
    next_round_instructions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryContext:
    workflow_id: str
    prior_result_references: tuple[str, ...] = ()
    prior_critiques: tuple[str, ...] = ()
    prior_pm_decisions: tuple[str, ...] = ()
    lessons_for_next_round: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    record_id: str
    workflow_id: str
    mandate_task_id: str
    result_references: tuple[str, ...]
    critiques: tuple[str, ...]
    pm_decision: PMDecision
    lessons_for_future_rounds: tuple[str, ...] = ()
