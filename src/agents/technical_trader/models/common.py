"""Shared typed values for Technical Trader and integration contracts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


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


class TraderType(StrEnum):
    TECHNICAL = "technical"


class TraderRunStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


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
    """Code-owned lineage; models and shared services may not overwrite it."""

    workflow_id: NonEmptyStr
    task_id: NonEmptyStr
    parent_task_id: NonEmptyStr
    source_task_id: NonEmptyStr


class ConfidenceAssessment(ContractModel):
    level: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    rationale: NonEmptyStr
    uncertainty_drivers: list[NonEmptyStr] = Field(default_factory=list)
