"""Graded evaluation harness: operational events to agent productivity metrics.

The harness reads the immutable ``operational_events`` ledger a finished run
leaves in graph state and reconstructs what each agent actually did.  It never
reads an agent's own self-report, so an agent cannot influence its own score.

**On "Success %".**  The workplan asks for a success rate per agent, and the
term has two defensible meanings that lead to different products:

``EXECUTION``
    The share of a agent's tasks that finished without erroring.  Literal,
    cheap, and un-gameable -- but nearly useless for firing, because a trader
    that reliably produces worthless strategies still scores 100%.

``RISK_APPROVAL``
    The share of a trader's proposals that survived Risk review.  Genuinely
    informative about research quality -- and it makes the skeptic the
    scorekeeper for everyone it judges.  Once a trader is measured on its
    approval rate, the way to score well is to propose things Risk waves
    through, which points Goodhart's law straight at the mechanism this
    project is built around.

That choice is a team ruling, not an implementation detail, and it is still
open.  So the harness computes **both**, always, and reports them under
separate names.  ``SuccessMetric`` selects only which one fills the single
``success_rate`` slot the dashboard renders; both remain readable in the full
report.  The default is ``EXECUTION`` because it is the claim the data can
support without argument -- not because the question has been settled.

Every metric here is measured or ``None``.  ``None`` renders as ``N/A``.  No
metric is defaulted to zero: an agent that made no model calls has an unknown
cost, not a cost of nothing, and the difference matters when the number is
attached to a hire/fire control.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

_TERMINAL_EVENTS = {"task_completed", "task_failed", "task_timed_out"}
_FAILURE_EVENTS = {"task_failed", "task_timed_out"}
_MODEL_CALL_EVENT = "model_call_completed"
_TRADER_AGENT_SUFFIX = "trader_agent"


class SuccessMetric(StrEnum):
    """Which reading of "Success %" fills the dashboard's single slot."""

    EXECUTION = "execution"
    RISK_APPROVAL = "risk_approval"


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        return ()
    return tuple(value)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _ratio(numerator: int, denominator: int) -> float | None:
    """A rate, or ``None`` when nothing was observed to compute it from."""

    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def format_duration(total_ms: float | None) -> str | None:
    """Render a measured duration the way the dashboard shows it."""

    if total_ms is None:
        return None
    total_seconds = total_ms / 1000.0
    if total_seconds < 1:
        return f"{total_ms:.0f}ms"
    minutes, seconds = divmod(total_seconds, 60)
    if minutes < 1:
        return f"{seconds:.2f}s"
    return f"{int(minutes)}m {seconds:04.1f}s"


@dataclass(frozen=True)
class AgentProductivity:
    """One agent's measured contribution across every round of a run."""

    agent_id: str
    tasks_observed: int = 0
    tasks_completed: int = 0
    failed_count: int = 0
    retry_count: int = 0
    total_latency_ms: float | None = None
    api_cost: Decimal | None = None
    model_calls: int = 0
    total_tokens: int | None = None
    candidates_reviewed: int = 0
    candidates_approved: int = 0

    @property
    def execution_success_rate(self) -> float | None:
        """Share of this agent's tasks that settled without erroring."""

        return _ratio(self.tasks_completed, self.tasks_observed)

    @property
    def risk_approval_rate(self) -> float | None:
        """Share of this agent's proposals that survived Risk review.

        ``None`` for any agent that does not submit candidates -- Risk and
        Reporting have no approval rate, and reporting 0% for them would read
        as a failing grade rather than as "not applicable".
        """

        return _ratio(self.candidates_approved, self.candidates_reviewed)

    @property
    def task_completion_time(self) -> str | None:
        return format_duration(self.total_latency_ms)

    def success_rate(self, metric: SuccessMetric) -> float | None:
        if metric is SuccessMetric.RISK_APPROVAL:
            return self.risk_approval_rate
        return self.execution_success_rate

    def as_dashboard_metrics(self, metric: SuccessMetric) -> dict[str, Any]:
        """Shape one agent's numbers for the dashboard's metrics panel.

        ``"N/A"`` is used rather than ``None`` so the panel renders the same
        string whether a metric is missing because nothing was observed or
        because the workflow has not run yet.
        """

        success = self.success_rate(metric)
        return {
            "task_completion_time": self.task_completion_time or "N/A",
            "success_rate": "N/A" if success is None else f"{success:.0%}",
            "api_cost": "N/A" if self.api_cost is None else f"{self.api_cost:.4f}",
            "retry_count": self.retry_count if self.tasks_observed else "N/A",
            "failed_count": self.failed_count if self.tasks_observed else "N/A",
            # Both readings stay visible regardless of which one was selected,
            # so the panel can never silently imply the ruling has been made.
            "execution_success_rate": _percent_or_na(self.execution_success_rate),
            "risk_approval_rate": _percent_or_na(self.risk_approval_rate),
            "success_metric": metric.value,
        }


def _percent_or_na(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.0%}"


@dataclass(frozen=True)
class HarnessReport:
    """The graded result of one workflow run."""

    workflow_id: str | None
    rounds_observed: int
    success_metric: SuccessMetric
    agents: dict[str, AgentProductivity] = field(default_factory=dict)

    @property
    def total_api_cost(self) -> Decimal | None:
        costs = [
            agent.api_cost for agent in self.agents.values() if agent.api_cost is not None
        ]
        return sum(costs, Decimal("0")) if costs else None

    @property
    def research_completion_time(self) -> str | None:
        """Wall-clock cost of the run's measured work.

        Summed rather than maxed: the traders run concurrently, so this is
        total agent effort, not elapsed time.  Elapsed time would need run
        start/end timestamps the ledger does not currently carry.
        """

        latencies = [
            agent.total_latency_ms
            for agent in self.agents.values()
            if agent.total_latency_ms is not None
        ]
        return format_duration(sum(latencies)) if latencies else None

    def summary_metrics(self) -> dict[str, Any]:
        total_cost = self.total_api_cost
        return {
            "research_completion_time": self.research_completion_time or "N/A",
            "total_api_cost": "N/A" if total_cost is None else f"{total_cost:.4f}",
            "agents_observed": len(self.agents),
            "rounds_observed": self.rounds_observed,
        }

    def dashboard_metrics(self) -> dict[str, dict[str, Any]]:
        return {
            agent_id: agent.as_dashboard_metrics(self.success_metric)
            for agent_id, agent in self.agents.items()
        }


class _Accumulator:
    """Mutable per-agent tally, frozen into ``AgentProductivity`` at the end."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self.tasks_observed = 0
        self.tasks_completed = 0
        self.failed_count = 0
        self.retry_count = 0
        self.latency_ms: float | None = None
        self.api_cost: Decimal | None = None
        self.model_calls = 0
        self.total_tokens: int | None = None
        self.candidate_ids: set[str] = set()
        self.approved_candidate_ids: set[str] = set()

    def add_latency(self, value: Any) -> None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            self.latency_ms = (self.latency_ms or 0.0) + float(value)

    def add_cost(self, value: Any) -> None:
        cost = _decimal_or_none(value)
        if cost is not None:
            self.api_cost = (self.api_cost or Decimal("0")) + cost

    def add_tokens(self, value: Any) -> None:
        if isinstance(value, int) and not isinstance(value, bool):
            self.total_tokens = (self.total_tokens or 0) + value

    def freeze(self) -> AgentProductivity:
        return AgentProductivity(
            agent_id=self.agent_id,
            tasks_observed=self.tasks_observed,
            tasks_completed=self.tasks_completed,
            failed_count=self.failed_count,
            retry_count=self.retry_count,
            total_latency_ms=self.latency_ms,
            api_cost=self.api_cost,
            model_calls=self.model_calls,
            total_tokens=self.total_tokens,
            candidates_reviewed=len(self.candidate_ids),
            candidates_approved=len(
                self.candidate_ids & self.approved_candidate_ids
            ),
        )


def grade_events(
    events: Sequence[Any],
    *,
    workflow_id: str | None = None,
    success_metric: SuccessMetric = SuccessMetric.EXECUTION,
) -> HarnessReport:
    """Reconstruct per-agent productivity from an operational-event ledger."""

    accumulators: dict[str, _Accumulator] = {}
    rounds: set[int] = set()
    approved_ids: set[str] = set()
    resolved_workflow_id = workflow_id

    records = [_as_mapping(event) for event in _as_sequence(events)]

    # Risk's verdicts are the authority on which candidates survived, so they
    # are collected before the traders are scored against them.
    for record in records:
        metadata = _as_mapping(record.get("metadata"))
        approved_ids.update(
            str(candidate_id)
            for candidate_id in _as_sequence(metadata.get("approved_candidate_ids"))
        )

    for record in records:
        agent_id = str(record.get("agent_id") or "").strip()
        if not agent_id:
            continue
        event_type = str(record.get("event_type") or "")
        metadata = _as_mapping(record.get("metadata"))
        if resolved_workflow_id is None and record.get("workflow_id"):
            resolved_workflow_id = str(record["workflow_id"])
        round_number = metadata.get("round_number")
        if isinstance(round_number, int) and not isinstance(round_number, bool):
            rounds.add(round_number)

        accumulator = accumulators.setdefault(agent_id, _Accumulator(agent_id))

        if event_type in _TERMINAL_EVENTS:
            accumulator.tasks_observed += 1
            accumulator.add_latency(record.get("latency_ms"))
            if event_type in _FAILURE_EVENTS:
                accumulator.failed_count += 1
            else:
                accumulator.tasks_completed += 1
            attempt = record.get("attempt")
            if isinstance(attempt, int) and not isinstance(attempt, bool):
                # attempt=1 is the first try; anything beyond it is a retry.
                accumulator.retry_count += max(0, attempt - 1)
            # A crashed trader still carries a candidate_id, but Risk never
            # reviewed it. Counting it as an unapproved proposal would score a
            # crash as a research-quality failure and double-penalise the
            # agent, which already shows the failure in failed_count.
            candidate_id = metadata.get("candidate_id")
            if candidate_id and metadata.get("eligible_for_risk_review") is True:
                accumulator.candidate_ids.add(str(candidate_id))

        elif event_type == _MODEL_CALL_EVENT:
            accumulator.model_calls += 1
            accumulator.add_cost(record.get("reported_cost"))
            accumulator.add_tokens(record.get("total_tokens"))
            accumulator.add_latency(record.get("latency_ms"))

    for accumulator in accumulators.values():
        accumulator.approved_candidate_ids = approved_ids

    return HarnessReport(
        workflow_id=resolved_workflow_id,
        rounds_observed=len(rounds),
        success_metric=success_metric,
        agents={
            agent_id: accumulator.freeze()
            for agent_id, accumulator in sorted(accumulators.items())
        },
    )


def grade_workflow_state(
    state: Mapping[str, Any],
    *,
    success_metric: SuccessMetric = SuccessMetric.EXECUTION,
) -> HarnessReport:
    """Grade one finished run straight from its final graph state."""

    return grade_events(
        state.get("operational_events") or (),
        workflow_id=(str(state["workflow_id"]) if state.get("workflow_id") else None),
        success_metric=success_metric,
    )


__all__ = [
    "AgentProductivity",
    "HarnessReport",
    "SuccessMetric",
    "format_duration",
    "grade_events",
    "grade_workflow_state",
]
