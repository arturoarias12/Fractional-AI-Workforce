"""Collective Risk / Skeptic review contracts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr
from .trader import TraderStrategyPackage


DEFAULT_COLLECTIVE_CHECKS: tuple[str, ...] = (
    "overfitting_and_data_snooping",
    "look_ahead_and_point_in_time_integrity",
    "out_of_sample_performance",
    "asset_universe_cherry_picking",
    "cross_candidate_selection_bias",
    "mandate_and_execution_constraints",
)


class RiskReviewRequest(ContractModel):
    request_id: NonEmptyStr
    mandate_task_id: NonEmptyStr
    as_of_date: date
    candidates: list[TraderStrategyPackage] = Field(default_factory=list)
    excluded_packages: list[TraderStrategyPackage] = Field(
        default_factory=list
    )
    required_collective_checks: list[NonEmptyStr] = Field(
        default_factory=lambda: list(DEFAULT_COLLECTIVE_CHECKS)
    )
    total_candidates_attempted: int = Field(default=0, ge=0)

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
    critiques: list[NonEmptyStr] = Field(default_factory=list)


class RiskReviewResponse(ContractModel):
    response_id: NonEmptyStr
    request_id: NonEmptyStr
    decisions: list[RiskCandidateDecision] = Field(default_factory=list)
    collective_critiques: list[NonEmptyStr] = Field(default_factory=list)

    def approved_candidate_ids(self) -> tuple[str, ...]:
        return tuple(
            decision.candidate_id
            for decision in self.decisions
            if decision.verdict is RiskVerdict.APPROVE
        )
