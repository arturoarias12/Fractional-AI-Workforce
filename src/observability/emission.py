"""Build the records that fill ``WorkflowState.operational_events``.

The channel and its append reducer already existed in :mod:`graph.state`, but
nothing ever wrote to it, so every downstream productivity metric resolved to
``N/A``.  This module supplies the records.

One rule governs everything here: **a field is either measured or left
``None``.**  Nothing in this module estimates, back-fills, or substitutes a
plausible default for a number that was never observed.  A missing metric is
recoverable; an invented one is not, because the productivity panel is what a
PM fires an agent on.  ``api_cost`` therefore stays ``None`` until a real
``ModelClient`` reports tokens, rather than becoming a tidy ``0.0`` that reads
as "this agent was free".

Events are written into checkpointed graph state, so every value returned here
is JSON-compatible: timestamps are ISO-8601 strings and ``Decimal`` costs are
serialized as strings to survive a float round-trip intact.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from protocols.events import EventType


def _event_id(
    *,
    workflow_id: str,
    round_number: int,
    stage: str,
    event_type: EventType,
    attempt: int,
) -> str:
    """Build a stable, collision-free identity for one event.

    Deterministic rather than random so a replayed checkpoint produces the same
    ledger, and round-scoped so a multi-round loop cannot overwrite round 1's
    record with round 2's.
    """

    return (
        f"{workflow_id}.round-{round_number}.{stage}"
        f".{event_type.value}.attempt-{attempt}"
    )


def _latency_ms(started_at: datetime | None, ended_at: datetime | None) -> float | None:
    """Measured wall-clock duration, or ``None`` when either end is unknown."""

    if started_at is None or ended_at is None:
        return None
    delta = (ended_at - started_at).total_seconds() * 1000.0
    return round(delta, 3) if delta >= 0 else None


def _base_event(
    *,
    event_type: EventType,
    workflow_id: str,
    round_number: int,
    task_id: str,
    agent_id: str,
    stage: str,
    occurred_at: datetime,
    attempt: int,
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "event_id": _event_id(
            workflow_id=workflow_id,
            round_number=round_number,
            stage=stage,
            event_type=event_type,
            attempt=attempt,
        ),
        "event_type": event_type.value,
        "workflow_id": workflow_id,
        "task_id": task_id,
        "agent_id": agent_id,
        "stage": stage,
        "occurred_at": occurred_at.isoformat(),
        "attempt": attempt,
        "metadata": {"round_number": round_number, **dict(metadata or {})},
    }


def node_terminal_event(
    *,
    workflow_id: str,
    round_number: int,
    task_id: str,
    agent_id: str,
    stage: str,
    started_at: datetime,
    ended_at: datetime,
    succeeded: bool,
    attempt: int = 1,
    status: str | None = None,
    error_type: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record one node execution that has settled, successfully or not.

    Emitted once per node run rather than as a started/completed pair: the
    graph wrappers execute a node atomically, so a separate start record would
    describe a moment nothing could observe while doubling the ledger.  Both
    timestamps are carried on the single event, which is what latency needs.
    """

    event_type = EventType.TASK_COMPLETED if succeeded else EventType.TASK_FAILED
    event = _base_event(
        event_type=event_type,
        workflow_id=workflow_id,
        round_number=round_number,
        task_id=task_id,
        agent_id=agent_id,
        stage=stage,
        occurred_at=ended_at,
        attempt=attempt,
        metadata=metadata,
    )
    event["started_at"] = started_at.isoformat()
    event["latency_ms"] = _latency_ms(started_at, ended_at)
    event["status"] = status
    event["error_type"] = error_type if not succeeded else None
    return event


def model_call_event(
    *,
    workflow_id: str,
    round_number: int,
    task_id: str,
    agent_id: str,
    stage: str,
    occurred_at: datetime,
    model_call_id: str,
    provider: str | None = None,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    reported_cost: Decimal | None = None,
    cost_currency: str | None = None,
    latency_ms: float | None = None,
    attempt: int = 1,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record one completed model call, with whatever the provider reported.

    Technical model adapters implement ``ModelClient`` and return token usage,
    but the current graph does not yet bridge those per-call records into this
    shared event channel or attach centrally maintained prices. ``api_cost``
    therefore legitimately remains ``N/A`` until that integration is made.
    """

    event = _base_event(
        event_type=EventType.MODEL_CALL_COMPLETED,
        workflow_id=workflow_id,
        round_number=round_number,
        task_id=task_id,
        agent_id=agent_id,
        stage=stage,
        occurred_at=occurred_at,
        attempt=attempt,
        metadata=metadata,
    )
    total_tokens = None
    if input_tokens is not None or output_tokens is not None:
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
    event.update(
        {
            "model_call_id": model_call_id,
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            # str() keeps Decimal exact through JSON; float() would not.
            "reported_cost": None if reported_cost is None else str(reported_cost),
            "cost_currency": cost_currency,
            "latency_ms": latency_ms,
        }
    )
    return event


def pm_decision_event(
    *,
    workflow_id: str,
    round_number: int,
    task_id: str,
    stage: str,
    occurred_at: datetime,
    decision: str,
    agent_id: str = "portfolio_manager",
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record the human PM's ruling for a round."""

    event = _base_event(
        event_type=EventType.PM_DECISION_RECORDED,
        workflow_id=workflow_id,
        round_number=round_number,
        task_id=task_id,
        agent_id=agent_id,
        stage=stage,
        occurred_at=occurred_at,
        attempt=1,
        metadata={"decision": decision, **dict(metadata or {})},
    )
    event["status"] = decision
    return event


def staffing_event(
    *,
    workflow_id: str,
    round_number: int,
    task_id: str,
    agent_id: str,
    stage: str,
    occurred_at: datetime,
    hired: bool,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a hire or bench ruling so staffing is auditable per round."""

    return _base_event(
        event_type=EventType.AGENT_HIRED if hired else EventType.AGENT_BENCHED,
        workflow_id=workflow_id,
        round_number=round_number,
        task_id=task_id,
        agent_id=agent_id,
        stage=stage,
        occurred_at=occurred_at,
        attempt=1,
        metadata=metadata,
    )


__all__ = [
    "model_call_event",
    "node_terminal_event",
    "pm_decision_event",
    "staffing_event",
]
