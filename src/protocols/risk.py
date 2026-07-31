"""Collective Risk / Skeptic review contracts.

The interface reflects the team checklist without implementing Risk-agent
judgment. Deterministic audit summaries and provenance references remain
external artifacts; the graph carries their immutable identifiers.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr
from .trader import TraderStrategyPackage


class RiskCheckId(StrEnum):
    REPORT_EVERYTHING_TRIED = "CP-1"
    BEST_OF_N_DISCLOSURE = "CP-2"
    FULL_PERIOD_METRICS = "CP-3"
    NO_POST_HOC_UNIVERSE_TRIMMING = "CP-4"
    FULL_CANONICAL_METRIC_SET = "CP-5"
    SAME_TERMS_BASELINE = "CP-6"
    MULTIPLE_COMPARISON_DISCLOSURE = "CP-7"
    LENS_DUPLICATION = "CP-8"
    NO_BORROWED_EVIDENCE = "CP-9"
    NOTHING_IS_DELETED = "CP-10"
    VALIDATION_TOUCH_BUDGET = "CP-11"
    NO_COSMETIC_RESURRECTION = "CP-12"
    TEST_SET_LOCK = "CP-13"


DEFAULT_COLLECTIVE_CHECKS: tuple[RiskCheckId, ...] = tuple(RiskCheckId)


class RiskCheckVerdict(StrEnum):
    PASS = "pass"
    FLAG = "flag"
    VETO = "veto"


class RiskCheckScope(StrEnum):
    CANDIDATE = "candidate"
    ROUND = "round"


class RiskCheckResult(ContractModel):
    """One grounded checklist decision produced by code or Risk judgment."""

    check_id: RiskCheckId
    verdict: RiskCheckVerdict
    scope: RiskCheckScope
    summary: NonEmptyStr
    candidate_id: NonEmptyStr | None = None
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    deterministic: bool
    requires_human_review: bool = False

    @model_validator(mode="after")
    def validate_scope(self) -> "RiskCheckResult":
        if (
            self.scope is RiskCheckScope.CANDIDATE
            and self.candidate_id is None
        ):
            raise ValueError(
                "Candidate-scoped Risk checks require candidate_id."
            )
        if (
            self.scope is RiskCheckScope.ROUND
            and self.candidate_id is not None
        ):
            raise ValueError(
                "Round-scoped Risk checks cannot name candidate_id."
            )
        return self


class RiskReviewRequest(ContractModel):
    request_id: NonEmptyStr
    mandate_task_id: NonEmptyStr
    as_of_date: date
    round_number: int = Field(default=1, ge=1)
    candidates: list[TraderStrategyPackage] = Field(default_factory=list)
    excluded_packages: list[TraderStrategyPackage] = Field(
        default_factory=list
    )
    round_audit_summary_reference: NonEmptyStr | None = None
    provenance_record_ids: list[NonEmptyStr] = Field(default_factory=list)
    candidate_memo_references: dict[NonEmptyStr, NonEmptyStr] = Field(
        default_factory=dict
    )
    round_history_reference: NonEmptyStr | None = None
    canonical_universe_id: NonEmptyStr | None = None
    evaluation_policy_id: NonEmptyStr | None = None
    required_collective_checks: list[RiskCheckId] = Field(
        default_factory=lambda: list(DEFAULT_COLLECTIVE_CHECKS)
    )
    total_candidates_attempted: int = Field(default=0, ge=0)
    additional_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reconcile_attempt_count(self) -> "RiskReviewRequest":
        computed = len(self.candidates) + len(self.excluded_packages)
        if self.total_candidates_attempted not in (0, computed):
            raise ValueError(
                "total_candidates_attempted must equal candidates plus "
                "excluded_packages."
            )
        object.__setattr__(self, "total_candidates_attempted", computed)
        return self


class RiskVerdict(StrEnum):
    APPROVE = "approve"
    VETO = "veto"


class RiskCandidateDecision(ContractModel):
    candidate_id: NonEmptyStr
    verdict: RiskVerdict
    check_results: list[RiskCheckResult] = Field(default_factory=list)
    critiques: list[NonEmptyStr] = Field(default_factory=list)
    reporting_flags: list[NonEmptyStr] = Field(default_factory=list)
    veto_reason_codes: list[RiskCheckId] = Field(default_factory=list)
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def reconcile_check_results(self) -> "RiskCandidateDecision":
        mismatched = [
            result.check_id
            for result in self.check_results
            if (
                result.scope is RiskCheckScope.CANDIDATE
                and result.candidate_id != self.candidate_id
            )
        ]
        if mismatched:
            raise ValueError(
                "Candidate check_results must match the decision candidate_id."
            )
        veto_codes = [
            result.check_id
            for result in self.check_results
            if result.verdict is RiskCheckVerdict.VETO
        ]
        if veto_codes and self.verdict is not RiskVerdict.VETO:
            raise ValueError("A VETO check result requires a veto decision.")
        if self.veto_reason_codes and set(self.veto_reason_codes) != set(
            veto_codes
        ):
            raise ValueError(
                "veto_reason_codes must match VETO check_results."
            )
        if not self.veto_reason_codes and veto_codes:
            object.__setattr__(self, "veto_reason_codes", veto_codes)
        return self


class RiskReviewResponse(ContractModel):
    response_id: NonEmptyStr
    request_id: NonEmptyStr
    decisions: list[RiskCandidateDecision] = Field(default_factory=list)
    round_check_results: list[RiskCheckResult] = Field(default_factory=list)
    collective_critiques: list[NonEmptyStr] = Field(default_factory=list)
    reporting_required_flags: list[NonEmptyStr] = Field(default_factory=list)
    blocked_progression: bool = False
    reviewed_at: datetime | None = None
    reviewer_card_version: NonEmptyStr | None = None
    additional_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_decision_identity(self) -> "RiskReviewResponse":
        candidate_ids = [
            decision.candidate_id for decision in self.decisions
        ]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError(
                "RiskReviewResponse may contain one decision per candidate."
            )
        if any(
            result.scope is not RiskCheckScope.ROUND
            for result in self.round_check_results
        ):
            raise ValueError(
                "round_check_results may contain only round-scoped checks."
            )
        if any(
            result.verdict is RiskCheckVerdict.VETO
            for result in self.round_check_results
        ) and not self.blocked_progression:
            raise ValueError(
                "A round-level VETO must set blocked_progression."
            )
        return self

    def approved_candidate_ids(self) -> tuple[str, ...]:
        return tuple(
            decision.candidate_id
            for decision in self.decisions
            if decision.verdict is RiskVerdict.APPROVE
        )

    def required_reporting_flags(self) -> tuple[str, ...]:
        candidate_flags = (
            flag
            for decision in self.decisions
            for flag in decision.reporting_flags
        )
        round_flags = (
            result.summary
            for result in self.round_check_results
            if result.verdict is RiskCheckVerdict.FLAG
        )
        return tuple(
            dict.fromkeys(
                (
                    *self.reporting_required_flags,
                    *candidate_flags,
                    *round_flags,
                )
            )
        )


__all__ = [
    "DEFAULT_COLLECTIVE_CHECKS",
    "RiskCandidateDecision",
    "RiskCheckId",
    "RiskCheckResult",
    "RiskCheckScope",
    "RiskCheckVerdict",
    "RiskReviewRequest",
    "RiskReviewResponse",
    "RiskVerdict",
]
