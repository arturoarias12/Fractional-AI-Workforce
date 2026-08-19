"""The harness must measure what happened and refuse to invent the rest."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from evaluation import SuccessMetric, grade_events, grade_workflow_state
from observability import (
    model_call_event,
    node_terminal_event,
    pm_decision_event,
    staffing_event,
)


START = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def _trader_event(
    agent_id: str,
    *,
    succeeded: bool = True,
    candidate_id: str | None = None,
    eligible: bool = True,
    seconds: float = 2.0,
    attempt: int = 1,
    round_number: int = 1,
):
    return node_terminal_event(
        workflow_id="wf-1",
        round_number=round_number,
        task_id=f"task.{agent_id}",
        agent_id=agent_id,
        stage=f"{agent_id}_node",
        started_at=START,
        ended_at=START + timedelta(seconds=seconds),
        succeeded=succeeded,
        attempt=attempt,
        status="completed" if succeeded else "failed",
        error_type=None if succeeded else "RuntimeError",
        metadata={
            "candidate_id": candidate_id,
            "eligible_for_risk_review": eligible,
        },
    )


def _risk_event(*, reviewed: list[str], approved: list[str], round_number: int = 1):
    return node_terminal_event(
        workflow_id="wf-1",
        round_number=round_number,
        task_id="task.risk",
        agent_id="risk_agent",
        stage="risk_collective_review",
        started_at=START,
        ended_at=START + timedelta(seconds=1),
        succeeded=True,
        status="completed",
        metadata={
            "reviewed_candidate_ids": reviewed,
            "approved_candidate_ids": approved,
        },
    )


def test_latency_is_measured_from_the_event_timestamps():
    report = grade_events([_trader_event("quant_trader_agent", seconds=2.5)])

    agent = report.agents["quant_trader_agent"]
    assert agent.total_latency_ms == 2500.0
    assert agent.task_completion_time == "2.50s"


def test_execution_success_rate_counts_settled_tasks():
    report = grade_events(
        [
            _trader_event("quant_trader_agent", succeeded=True),
            _trader_event("quant_trader_agent", succeeded=False, round_number=2),
        ]
    )

    agent = report.agents["quant_trader_agent"]
    assert agent.tasks_observed == 2
    assert agent.failed_count == 1
    assert agent.execution_success_rate == 0.5


def test_risk_approval_rate_uses_risk_verdicts_not_self_report():
    report = grade_events(
        [
            _trader_event("fundamental_trader_agent", candidate_id="cand-f"),
            _trader_event("quant_trader_agent", candidate_id="cand-q"),
            _risk_event(reviewed=["cand-f", "cand-q"], approved=["cand-f"]),
        ]
    )

    assert report.agents["fundamental_trader_agent"].risk_approval_rate == 1.0
    assert report.agents["quant_trader_agent"].risk_approval_rate == 0.0


def test_a_crashed_trader_has_no_risk_approval_rate():
    """A crash is a failure to run, not a rejected proposal.

    The failed package still carries a candidate_id, so without the
    eligibility gate this agent would score 0% approval and be penalised
    twice for one incident.
    """

    report = grade_events(
        [
            _trader_event(
                "technical_trader_agent",
                succeeded=False,
                candidate_id="cand-t",
                eligible=False,
            ),
            _risk_event(reviewed=[], approved=[]),
        ]
    )

    agent = report.agents["technical_trader_agent"]
    assert agent.failed_count == 1
    assert agent.risk_approval_rate is None
    assert agent.execution_success_rate == 0.0


def test_non_proposing_agents_have_no_approval_rate():
    report = grade_events([_risk_event(reviewed=[], approved=[])])

    assert report.agents["risk_agent"].risk_approval_rate is None


def test_both_success_readings_stay_visible_under_either_policy():
    events = [
        _trader_event("quant_trader_agent", candidate_id="cand-q"),
        _risk_event(reviewed=["cand-q"], approved=[]),
    ]

    execution = grade_events(events, success_metric=SuccessMetric.EXECUTION)
    approval = grade_events(events, success_metric=SuccessMetric.RISK_APPROVAL)

    execution_panel = execution.dashboard_metrics()["quant_trader_agent"]
    approval_panel = approval.dashboard_metrics()["quant_trader_agent"]

    # The selected reading changes; the underlying pair never disappears.
    assert execution_panel["success_rate"] == "100%"
    assert approval_panel["success_rate"] == "0%"
    for panel in (execution_panel, approval_panel):
        assert panel["execution_success_rate"] == "100%"
        assert panel["risk_approval_rate"] == "0%"


def test_unobserved_cost_is_na_and_never_zero():
    """An agent that made no model calls has unknown cost, not zero cost."""

    report = grade_events([_trader_event("quant_trader_agent")])

    assert report.agents["quant_trader_agent"].api_cost is None
    assert report.dashboard_metrics()["quant_trader_agent"]["api_cost"] == "N/A"
    assert report.summary_metrics()["total_api_cost"] == "N/A"


def test_model_call_costs_accumulate_exactly():
    report = grade_events(
        [
            model_call_event(
                workflow_id="wf-1",
                round_number=1,
                task_id="task.q",
                agent_id="quant_trader_agent",
                stage="quant_trader",
                occurred_at=START,
                model_call_id=f"call-{index}",
                input_tokens=100,
                output_tokens=50,
                reported_cost=Decimal("0.0001"),
            )
            for index in range(3)
        ]
    )

    agent = report.agents["quant_trader_agent"]
    # Decimal, so three 0.0001 charges sum exactly rather than to 0.00030000004.
    assert agent.api_cost == Decimal("0.0003")
    assert agent.total_tokens == 450
    assert agent.model_calls == 3


def test_retries_are_counted_from_attempt_numbers():
    report = grade_events(
        [
            _trader_event("quant_trader_agent", attempt=1),
            _trader_event("quant_trader_agent", attempt=3, round_number=2),
        ]
    )

    # attempt=1 is the first try; attempt=3 means two retries.
    assert report.agents["quant_trader_agent"].retry_count == 2


def test_rounds_are_counted_from_event_metadata():
    report = grade_events(
        [
            _trader_event("quant_trader_agent", round_number=1),
            _trader_event("quant_trader_agent", round_number=2),
            _trader_event("quant_trader_agent", round_number=2),
        ]
    )

    assert report.rounds_observed == 2


def test_benched_and_pm_events_do_not_count_as_tasks():
    report = grade_events(
        [
            staffing_event(
                workflow_id="wf-1",
                round_number=1,
                task_id="task.t",
                agent_id="technical_trader_agent",
                stage="technical_trader",
                occurred_at=START,
                hired=False,
            ),
            pm_decision_event(
                workflow_id="wf-1",
                round_number=1,
                task_id="decision-1",
                stage="pm_decision",
                occurred_at=START,
                decision="reject",
            ),
        ]
    )

    benched = report.agents["technical_trader_agent"]
    assert benched.tasks_observed == 0
    # Nothing ran, so there is no rate to report -- not a 0% score.
    assert benched.execution_success_rate is None
    assert report.dashboard_metrics()["technical_trader_agent"]["success_rate"] == "N/A"


def test_empty_ledger_grades_to_an_empty_report():
    report = grade_events([])

    assert report.agents == {}
    assert report.summary_metrics()["research_completion_time"] == "N/A"


def test_grade_workflow_state_reads_the_ledger_off_final_state():
    state = {
        "workflow_id": "wf-1",
        "operational_events": (_trader_event("quant_trader_agent"),),
    }

    report = grade_workflow_state(state)

    assert report.workflow_id == "wf-1"
    assert report.agents["quant_trader_agent"].tasks_completed == 1


def test_malformed_events_are_skipped_rather_than_crashing():
    report = grade_events(
        [None, {}, {"agent_id": "   "}, _trader_event("quant_trader_agent")]
    )

    assert set(report.agents) == {"quant_trader_agent"}
