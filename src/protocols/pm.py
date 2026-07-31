"""Human Portfolio Manager decision contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr


class PMDecisionType(StrEnum):
    SELECT = "select"
    REJECT = "reject"
    REQUEST_ANOTHER_ROUND = "request_another_round"


class PMDecision(ContractModel):
    decision_id: NonEmptyStr
    workflow_id: NonEmptyStr
    decision: PMDecisionType
    selected_candidate_id: NonEmptyStr | None = None
    rationale: NonEmptyStr | None = None
    next_round_instructions: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_selected_candidate(self) -> "PMDecision":
        if (
            self.decision is PMDecisionType.SELECT
            and self.selected_candidate_id is None
        ):
            raise ValueError(
                "A select decision must name selected_candidate_id."
            )
        if (
            self.decision is not PMDecisionType.SELECT
            and self.selected_candidate_id is not None
        ):
            raise ValueError(
                "selected_candidate_id is only valid for a select decision."
            )
        return self
