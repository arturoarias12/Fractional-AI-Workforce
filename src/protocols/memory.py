"""Round-to-round external Memory service contracts."""

from __future__ import annotations

from pydantic import Field

from .common import ContractModel, NonEmptyStr
from .pm import PMDecision


class MemoryContext(ContractModel):
    workflow_id: NonEmptyStr
    prior_result_references: list[NonEmptyStr] = Field(default_factory=list)
    prior_critiques: list[NonEmptyStr] = Field(default_factory=list)
    prior_pm_decisions: list[NonEmptyStr] = Field(default_factory=list)
    lessons_for_next_round: list[NonEmptyStr] = Field(default_factory=list)


class MemoryRecord(ContractModel):
    record_id: NonEmptyStr
    workflow_id: NonEmptyStr
    mandate_task_id: NonEmptyStr
    result_references: list[NonEmptyStr] = Field(default_factory=list)
    critiques: list[NonEmptyStr] = Field(default_factory=list)
    pm_decision: PMDecision
    lessons_for_future_rounds: list[NonEmptyStr] = Field(default_factory=list)
