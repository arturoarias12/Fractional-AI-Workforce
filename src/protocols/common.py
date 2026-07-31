"""Shared typed primitives for project-wide integration contracts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


NonEmptyStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class ContractModel(BaseModel):
    """Strict internal boundary model."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )


class ExtensibleModel(BaseModel):
    """Forward-compatible integration model that preserves unknown fields."""

    model_config = ConfigDict(
        extra="allow",
        validate_assignment=True,
        str_strip_whitespace=True,
    )


class SpecialistId(StrEnum):
    """Stable identity used by routing, registry, metrics, and lineage."""

    TECHNICAL_TRADER = "technical_trader_agent"
    FUNDAMENTAL_TRADER = "fundamental_trader_agent"
    QUANT_TRADER = "quant_trader_agent"
    RISK = "risk_agent"
    REPORTING = "reporting_agent"

    # Transitional alias for callers of the former Technical-only TraderType.
    TECHNICAL = TECHNICAL_TRADER


TRADER_IDS: tuple[SpecialistId, ...] = (
    SpecialistId.TECHNICAL_TRADER,
    SpecialistId.FUNDAMENTAL_TRADER,
    SpecialistId.QUANT_TRADER,
)


class RunStatus(StrEnum):
    """Lifecycle status shared by graph branches and settled packages."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_TRADER_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.COMPLETED, RunStatus.PARTIAL, RunStatus.FAILED}
)


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class MandateReference(ContractModel):
    workflow_id: NonEmptyStr
    task_id: NonEmptyStr
    as_of_date: date


class TaskLineage(ContractModel):
    """Code-owned correlation data for one task and its child operations."""

    workflow_id: NonEmptyStr
    task_id: NonEmptyStr
    parent_task_id: NonEmptyStr
    source_task_id: NonEmptyStr
    attempt: int = Field(default=1, ge=1)

    def child(self, suffix: str) -> "TaskLineage":
        suffix = suffix.strip()
        if not suffix:
            raise ValueError("Child lineage suffix must be non-empty.")
        return TaskLineage(
            workflow_id=self.workflow_id,
            task_id=f"{self.task_id}.{suffix}",
            parent_task_id=self.task_id,
            source_task_id=self.source_task_id,
            attempt=self.attempt,
        )


class ConfidenceAssessment(ContractModel):
    level: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    rationale: NonEmptyStr
    uncertainty_drivers: list[NonEmptyStr] = Field(default_factory=list)
