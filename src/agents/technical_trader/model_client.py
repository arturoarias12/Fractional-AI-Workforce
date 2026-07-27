"""Provider-neutral model, usage, and metrics interfaces.

Concrete adapters (OpenAI, Azure OpenAI, Anthropic, and others) implement
``ModelClient`` outside the agents. Every call returns both structured content
and normalized usage metadata. The base agent records a separate operational
event through ``MetricsSink``; financial outputs remain free of telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from threading import Lock
from typing import (
    Annotated,
    Any,
    Generic,
    Mapping,
    Protocol,
    TypeVar,
    runtime_checkable,
)
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)
NonEmptyOperationalStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class _OperationalModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class ModelUsage(_OperationalModel):
    """Normalized provider usage and optional reported cost.

    If a provider cannot supply usage, adapters must return
    ``ModelUsage.unavailable(...)`` rather than omit the usage channel.
    """

    usage_available: bool = True
    unavailable_reason: NonEmptyOperationalStr | None = None
    provider: NonEmptyOperationalStr | None = None
    model: NonEmptyOperationalStr | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    provider_request_id: NonEmptyOperationalStr | None = None
    reported_cost: Decimal | None = Field(default=None, ge=0)
    cost_currency: NonEmptyOperationalStr | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_availability_contract(self) -> "ModelUsage":
        if self.usage_available:
            if self.provider is None or self.model is None:
                raise ValueError(
                    "Available usage must identify both provider and model."
                )
            if self.unavailable_reason is not None:
                raise ValueError(
                    "unavailable_reason must be absent when usage is available."
                )
        elif self.unavailable_reason is None:
            raise ValueError(
                "Unavailable usage must include unavailable_reason."
            )

        if self.reported_cost is not None and self.cost_currency is None:
            raise ValueError(
                "cost_currency is required when reported_cost is supplied."
            )
        return self

    @classmethod
    def unavailable(
        cls,
        reason: str,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> "ModelUsage":
        return cls(
            usage_available=False,
            unavailable_reason=reason,
            provider=provider,
            model=model,
        )


class ModelRequestContext(_OperationalModel):
    """Correlation metadata supplied to model adapters and metrics sinks."""

    agent_id: NonEmptyOperationalStr
    operation: NonEmptyOperationalStr
    workflow_id: NonEmptyOperationalStr
    task_id: NonEmptyOperationalStr
    model_call_id: NonEmptyOperationalStr = Field(
        default_factory=lambda: uuid4().hex
    )
    attempt: int = Field(default=1, ge=1)


@dataclass(frozen=True, slots=True)
class ModelCallResult(Generic[StructuredOutputT]):
    """Required adapter return envelope."""

    output: StructuredOutputT | Mapping[str, Any]
    usage: ModelUsage


class ModelCallStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class ModelCallMetrics(_OperationalModel):
    """Operational event emitted once for every attempted model call."""

    context: ModelRequestContext
    status: ModelCallStatus
    started_at: datetime
    completed_at: datetime
    latency_ms: float = Field(ge=0)
    usage: ModelUsage | None = None
    error_type: NonEmptyOperationalStr | None = None
    error_message: NonEmptyOperationalStr | None = None


@runtime_checkable
class ModelClient(Protocol):
    """Minimal provider adapter required by the subsystem."""

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredOutputT],
        context: ModelRequestContext,
    ) -> ModelCallResult[StructuredOutputT]:
        """Generate structured content and return normalized usage."""


@runtime_checkable
class MetricsSink(Protocol):
    """Non-blocking operational event sink.

    Implementations should enqueue or record synchronously and must avoid
    network I/O in this method. The wider application can drain the queue into
    its chosen persistence/metrics system.
    """

    def record_model_call(self, event: ModelCallMetrics) -> None:
        """Record one completed, failed, timed-out, or cancelled model call."""


class NullMetricsSink:
    """Explicit opt-out sink."""

    def record_model_call(self, event: ModelCallMetrics) -> None:
        del event


class InMemoryMetricsSink:
    """Thread-safe default sink suitable for local integration and tests."""

    def __init__(self) -> None:
        self._events: list[ModelCallMetrics] = []
        self._lock = Lock()

    def record_model_call(self, event: ModelCallMetrics) -> None:
        with self._lock:
            self._events.append(event)

    def snapshot(
        self,
        *,
        workflow_id: str | None = None,
    ) -> tuple[ModelCallMetrics, ...]:
        with self._lock:
            events = tuple(self._events)
        if workflow_id is None:
            return events
        return tuple(
            event
            for event in events
            if event.context.workflow_id == workflow_id
        )

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
