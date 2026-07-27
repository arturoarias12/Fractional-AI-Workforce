"""Agent-to-agent envelope placeholder with stable correlation fields."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping


class MessageType(StrEnum):
    TASK_REQUEST = "task_request"
    TASK_RESULT = "task_result"
    TASK_FAILURE = "task_failure"
    REVIEW_REQUEST = "review_request"
    REVIEW_RESULT = "review_result"
    DECISION = "decision"


@dataclass(frozen=True, slots=True)
class A2AMessage:
    message_id: str
    message_type: MessageType
    workflow_id: str
    task_id: str
    source_agent_id: str
    target_agent_id: str
    created_at: datetime
    attempt: int = 1
    parent_task_id: str | None = None
    payload_schema: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
