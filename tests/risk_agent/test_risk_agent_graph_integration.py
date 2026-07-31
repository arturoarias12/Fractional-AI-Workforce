"""End-to-end proof that the Risk agent plugs into the compiled topology.

These tests run the real ``compile_production_workflow`` graph with stub
trader/reporting/memory nodes and the real :class:`RiskAgentImpl`, so the
checklist is exercised across the same JSON state boundary and node
contracts the production run uses.
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

import pytest

from agents.risk_agent import RiskAgentImpl, make_risk_review_node
from protocols import (
    PMDecision,
    PMDecisionType,
    PMMandate,
    ReportingOutput,
    ReportingRequest,
    RiskCheckId,
    RiskReviewResponse,
    SpecialistId,
)
from risk_fixtures import (
    AS_OF,
    MANDATE_TASK_ID,
    RUN_ID,
    StaticAuditReader,
    WORKFLOW_ID,
    single_run_entries,
    three_clean_candidates,
    undeclared_sweep_entries,
)

langgraph = pytest.importorskip(
    "langgraph",
    reason="langgraph extra is not installed",
)

from graph.production import (  # noqa: E402
    ProductionNodeSet,
    compile_production_workflow,
)
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402


AUDIT_REFERENCE = "audit-round-1"
HISTORY_REFERENCE = "history-ref"

_TRADER_STATE_KEYS = {
    SpecialistId.TECHNICAL_TRADER: "technical_trader_package",
    SpecialistId.FUNDAMENTAL_TRADER: "fundamental_trader_package",
    SpecialistId.QUANT_TRADER: "quant_trader_package",
}


def mandate() -> PMMandate:
    return PMMandate(
        workflow_id=WORKFLOW_ID,
        task_id=MANDATE_TASK_ID,
        as_of_date=AS_OF,
        investment_objective=(
            "Find a mean-reversion strategy on liquid index ETFs."
        ),
        permitted_asset_universe=["SPY", "QQQ"],
    )


def memory_read_node(state: Mapping[str, Any]) -> Mapping[str, Any]:
    """Supply the audit/history references a real Memory service would."""

    del state
    return {
        "round_audit_summary_reference": AUDIT_REFERENCE,
        "round_history_reference": HISTORY_REFERENCE,
        "memory_context": None,
    }


def pm_intake_node(state: Mapping[str, Any]) -> Mapping[str, Any]:
    del state
    return {}


def make_trader_node(package):
    state_key = _TRADER_STATE_KEYS[package.trader_id]

    def trader_node(state: Mapping[str, Any]) -> Mapping[str, Any]:
        del state
        return {state_key: package.model_dump(mode="json")}

    return trader_node


class RecordingReportingNode:
    """Capture exactly which candidates Reporting is allowed to see."""

    def __init__(self) -> None:
        self.requests: list[ReportingRequest] = []

    def __call__(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        request = ReportingRequest.model_validate(
            state.get("reporting_request")
        )
        self.requests.append(request)
        return {
            "reporting_output": ReportingOutput(
                output_id=f"{request.request_id}.output",
                request_id=request.request_id,
                surviving_candidate_ids=[
                    str(package.candidate_id)
                    for package in request.surviving_candidates
                ],
            ).model_dump(mode="json"),
        }


def pm_decision_node(state: Mapping[str, Any]) -> Mapping[str, Any]:
    """Close the round without requesting another one."""

    return {
        "pm_decision": PMDecision(
            decision_id=f"{state['workflow_id']}.decision-1",
            workflow_id=str(state["workflow_id"]),
            decision=PMDecisionType.REJECT,
            rationale="Integration run ends after one round.",
        ).model_dump(mode="json"),
        "pending_human_action": None,
    }


def memory_write_node(state: Mapping[str, Any]) -> Mapping[str, Any]:
    del state
    return {"memory_record_id": "memory-record-1"}


def run_graph(*, candidates, risk_agent: RiskAgentImpl):
    reporting = RecordingReportingNode()
    packages = {package.trader_id: package for package in candidates}
    nodes = ProductionNodeSet(
        memory_read=memory_read_node,
        pm_intake=pm_intake_node,
        technical_trader=make_trader_node(
            packages[SpecialistId.TECHNICAL_TRADER]
        ),
        fundamental_trader=make_trader_node(
            packages[SpecialistId.FUNDAMENTAL_TRADER]
        ),
        quant_trader=make_trader_node(packages[SpecialistId.QUANT_TRADER]),
        risk_review=make_risk_review_node(risk_agent),
        reporting=reporting,
        memory_write=memory_write_node,
        pm_decision=pm_decision_node,
    )
    compiled = compile_production_workflow(
        nodes,
        checkpointer=MemorySaver(),
        max_rounds=3,
    )
    final_state = asyncio.run(
        compiled.ainvoke(
            {"pm_mandate": mandate().model_dump(mode="json"), "run_id": RUN_ID},
            config={"configurable": {"thread_id": "risk-integration"}},
        )
    )
    return final_state, reporting


def test_clean_round_flows_through_to_reporting_and_pm():
    candidates = three_clean_candidates()
    final_state, reporting = run_graph(
        candidates=candidates,
        risk_agent=RiskAgentImpl(),
    )

    response = RiskReviewResponse.model_validate(
        final_state["risk_review_response"]
    )
    assert len(response.decisions) == 3, (
        "every settled candidate must receive exactly one verdict"
    )
    assert set(final_state["surviving_candidate_ids"]) == {
        "cand-technical",
        "cand-fundamental",
        "cand-quant",
    }
    assert len(reporting.requests) == 1
    assert len(reporting.requests[0].surviving_candidates) == 3
    assert final_state["pm_decision"]["decision"] == "reject"


def test_planted_sweep_is_vetoed_inside_the_real_graph():
    """The signature demo beat, executed through the production topology."""

    candidates = three_clean_candidates()
    agent = RiskAgentImpl(
        audit_reader=StaticAuditReader(
            [*single_run_entries(candidates[:2]), *undeclared_sweep_entries()]
        ),
    )
    final_state, reporting = run_graph(candidates=candidates, risk_agent=agent)

    response = RiskReviewResponse.model_validate(
        final_state["risk_review_response"]
    )
    quant = next(
        decision
        for decision in response.decisions
        if decision.candidate_id == "cand-quant"
    )
    assert RiskCheckId.REPORT_EVERYTHING_TRIED in quant.veto_reason_codes

    # The vetoed candidate must never reach Reporting or become selectable.
    assert set(final_state["surviving_candidate_ids"]) == {
        "cand-technical",
        "cand-fundamental",
    }
    reported = {
        str(package.candidate_id)
        for package in reporting.requests[0].surviving_candidates
    }
    assert "cand-quant" not in reported


def test_risk_flags_reach_the_reporting_request():
    """CP-7 disclosure must survive the graph's JSON state boundary."""

    final_state, reporting = run_graph(
        candidates=three_clean_candidates(),
        risk_agent=RiskAgentImpl(),
    )
    del final_state

    flags = reporting.requests[0].risk_response.required_reporting_flags()
    assert any(
        "Multiple-comparison disclosure" in flag for flag in flags
    ), "Reporting must be told how many hypotheses competed this round"


def test_benched_risk_agent_blocks_reporting_and_escalates_to_pm():
    """Firing Risk must not silently approve; it escalates to the human."""

    candidates = three_clean_candidates()
    packages = {package.trader_id: package for package in candidates}
    reporting = RecordingReportingNode()
    nodes = ProductionNodeSet(
        memory_read=memory_read_node,
        pm_intake=pm_intake_node,
        technical_trader=make_trader_node(
            packages[SpecialistId.TECHNICAL_TRADER]
        ),
        fundamental_trader=make_trader_node(
            packages[SpecialistId.FUNDAMENTAL_TRADER]
        ),
        quant_trader=make_trader_node(packages[SpecialistId.QUANT_TRADER]),
        risk_review=make_risk_review_node(RiskAgentImpl()),
        reporting=reporting,
        memory_write=memory_write_node,
        pm_decision=pm_decision_node,
    )
    compiled = compile_production_workflow(
        nodes,
        checkpointer=MemorySaver(),
        max_rounds=3,
    )
    active = tuple(
        str(specialist)
        for specialist in SpecialistId
        if specialist is not SpecialistId.RISK
    )
    final_state = asyncio.run(
        compiled.ainvoke(
            {
                "pm_mandate": mandate().model_dump(mode="json"),
                "run_id": RUN_ID,
                "active_specialists": active,
            },
            config={"configurable": {"thread_id": "risk-benched"}},
        )
    )

    assert final_state["risk_review_response"] is None
    assert final_state["risk_failure"]["requires_human_action"] is True
    assert not final_state.get("surviving_candidate_ids")
    assert reporting.requests == [], (
        "no candidate may be reported as reviewed when Risk is benched"
    )
