"""Reporting request and output contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .common import ContractModel, NonEmptyStr
from .risk import RiskReviewResponse
from .trader import TraderStrategyPackage


class ReportingRequest(ContractModel):
    request_id: NonEmptyStr
    mandate_task_id: NonEmptyStr
    surviving_candidates: list[TraderStrategyPackage] = Field(
        default_factory=list
    )
    risk_response: RiskReviewResponse


class ReportingOutput(ContractModel):
    output_id: NonEmptyStr
    request_id: NonEmptyStr
    surviving_candidate_ids: list[NonEmptyStr] = Field(default_factory=list)
    strategy_memo_reference: NonEmptyStr | None = None
    comparison: dict[str, Any] = Field(default_factory=dict)
    combination_logic_implemented: Literal[False] = False
