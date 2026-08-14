"""Acceptance tests for Memory Store.

Logs two rounds of MemoryRecords for the same workflow and asserts that
load_context() aggregates results, critiques, PM decisions, and lessons
across every round -- not just the most recent one.
"""

from __future__ import annotations

import asyncio

from protocols import PMDecision, PMDecisionType
from protocols.research_contracts import MemoryRecord
from services.memory_store_impl import InMemoryMemoryStore

WORKFLOW_ID = "wf-test-memory-store"


def _round_1_record() -> MemoryRecord:
    decision = PMDecision(
        decision_id="decision-round-1",
        workflow_id=WORKFLOW_ID,
        decision=PMDecisionType.REQUEST_ANOTHER_ROUND,
        rationale="All three candidates were flagged for thin out-of-sample data.",
        next_round_instructions=["Widen the validation window."],
    )
    return MemoryRecord(
        record_id="record-round-1",
        workflow_id=WORKFLOW_ID,
        mandate_task_id="mandate-1",
        result_references=["cand-technical.result", "cand-quant.result"],
        critiques=["Sharpe ratio was inflated by a short validation window."],
        pm_decision=decision,
        lessons_for_future_rounds=["Require a longer out-of-sample window next round."],
    )


def _round_2_record() -> MemoryRecord:
    decision = PMDecision(
        decision_id="decision-round-2",
        workflow_id=WORKFLOW_ID,
        decision=PMDecisionType.SELECT,
        selected_candidate_id="cand-technical-v2",
        rationale="Strongest risk-adjusted return with a clean Risk review.",
    )
    return MemoryRecord(
        record_id="record-round-2",
        workflow_id=WORKFLOW_ID,
        mandate_task_id="mandate-1",
        result_references=["cand-technical-v2.result"],
        critiques=[],
        pm_decision=decision,
        lessons_for_future_rounds=[
            "Longer validation windows reduced false positives."
        ],
    )


def test_load_context_is_empty_before_any_round_is_recorded():
    store = InMemoryMemoryStore()

    context = asyncio.run(store.load_context(WORKFLOW_ID))

    assert context.prior_result_references == []
    assert context.prior_critiques == []
    assert context.prior_pm_decisions == []
    assert context.lessons_for_next_round == []


def test_record_returns_the_record_id():
    store = InMemoryMemoryStore()

    returned_id = asyncio.run(store.record(_round_1_record()))

    assert returned_id == "record-round-1"


def test_load_context_aggregates_every_round_not_just_the_latest():
    store = InMemoryMemoryStore()
    asyncio.run(store.record(_round_1_record()))
    asyncio.run(store.record(_round_2_record()))

    context = asyncio.run(store.load_context(WORKFLOW_ID))

    assert context.prior_pm_decisions == ["decision-round-1", "decision-round-2"]
    assert context.prior_result_references == [
        "cand-technical.result",
        "cand-quant.result",
        "cand-technical-v2.result",
    ]
    assert context.lessons_for_next_round == [
        "Require a longer out-of-sample window next round.",
        "Longer validation windows reduced false positives.",
    ]


def test_different_workflows_do_not_leak_into_each_other():
    store = InMemoryMemoryStore()
    asyncio.run(store.record(_round_1_record()))

    other_context = asyncio.run(store.load_context("some-other-workflow"))

    assert other_context.prior_result_references == []
