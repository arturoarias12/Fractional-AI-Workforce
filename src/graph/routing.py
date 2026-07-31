"""Pure routing helpers for the planned workflow."""

from __future__ import annotations

from enum import StrEnum
from typing import Iterable

from protocols import (
    PMDecision,
    PMDecisionType,
    RiskReviewResponse,
    RiskVerdict,
    SpecialistId,
    TRADER_IDS,
)


class SelectionOutcome(StrEnum):
    NO_SURVIVORS = "no_surviving_candidates"
    SINGLE_SURVIVOR = "single_surviving_candidate"
    PM_SELECTION_REQUIRED = "multiple_candidates_require_pm_selection"


class PostDecisionRoute(StrEnum):
    WRITE_MEMORY_AND_FINISH = "write_memory_and_finish"
    WRITE_MEMORY_AND_START_NEXT_ROUND = "write_memory_and_start_next_round"


def active_traders(
    active_specialists: Iterable[SpecialistId | str],
) -> tuple[SpecialistId, ...]:
    """Return hired trader branches in stable graph order."""

    normalized = {SpecialistId(item) for item in active_specialists}
    return tuple(trader_id for trader_id in TRADER_IDS if trader_id in normalized)


def surviving_candidate_ids(
    response: RiskReviewResponse,
) -> tuple[str, ...]:
    return tuple(
        decision.candidate_id
        for decision in response.decisions
        if decision.verdict is RiskVerdict.APPROVE
    )


def selection_outcome(
    candidate_ids: Iterable[str],
) -> SelectionOutcome:
    count = len(tuple(candidate_ids))
    if count == 0:
        return SelectionOutcome.NO_SURVIVORS
    if count == 1:
        return SelectionOutcome.SINGLE_SURVIVOR
    return SelectionOutcome.PM_SELECTION_REQUIRED


def route_after_pm_decision(decision: PMDecision) -> PostDecisionRoute:
    if decision.decision is PMDecisionType.REQUEST_ANOTHER_ROUND:
        return PostDecisionRoute.WRITE_MEMORY_AND_START_NEXT_ROUND
    return PostDecisionRoute.WRITE_MEMORY_AND_FINISH
