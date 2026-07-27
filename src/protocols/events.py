"""Operational-event placeholder for productivity and cost reconstruction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping


class EventType(StrEnum):
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_TIMED_OUT = "task_timed_out"
    MODEL_CALL_COMPLETED = "model_call_completed"
    AGENT_HIRED = "agent_hired"
    AGENT_BENCHED = "agent_benched"
    PM_DECISION_RECORDED = "pm_decision_recorded"


@dataclass(frozen=True, slots=True)
class OperationalEvent:
    event_id: str
    event_type: EventType
    workflow_id: str
    task_id: str
    agent_id: str
    stage: str
    occurred_at: datetime
    attempt: int = 1
    model_call_id: str | None = None
    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reported_cost: Decimal | None = None
    cost_currency: str | None = None
    latency_ms: float | None = None
    status: str | None = None
    error_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
