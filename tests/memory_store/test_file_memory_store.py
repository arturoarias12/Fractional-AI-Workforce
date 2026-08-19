"""Acceptance tests for FileBackedMemoryStore.

Mirrors test_memory_store_impl.py's coverage (empty context, record id
round-trip, cross-round aggregation, workflow isolation), plus the one
behavior that is the actual point of this class: state must survive a
fresh instance being constructed against the same directory, since the
live dashboard pilot launches each round as a new subprocess.
"""

from __future__ import annotations

import asyncio

from protocols import PMDecision, PMDecisionType
from protocols.research_contracts import MemoryRecord
from services.file_memory_store import FileBackedMemoryStore

WORKFLOW_ID = "wf-test-file-memory-store"


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
        lessons_for_future_rounds=["Longer validation windows reduced false positives."],
    )


def test_load_context_is_empty_before_any_round_is_recorded(tmp_path):
    store = FileBackedMemoryStore(tmp_path)

    context = asyncio.run(store.load_context(WORKFLOW_ID))

    assert context.prior_result_references == []
    assert context.prior_pm_decisions == []


def test_record_returns_the_record_id(tmp_path):
    store = FileBackedMemoryStore(tmp_path)

    returned_id = asyncio.run(store.record(_round_1_record()))

    assert returned_id == "record-round-1"


def test_load_context_aggregates_every_round_not_just_the_latest(tmp_path):
    store = FileBackedMemoryStore(tmp_path)
    asyncio.run(store.record(_round_1_record()))
    asyncio.run(store.record(_round_2_record()))

    context = asyncio.run(store.load_context(WORKFLOW_ID))

    assert context.prior_pm_decisions == ["decision-round-1", "decision-round-2"]
    assert context.lessons_for_next_round == [
        "Require a longer out-of-sample window next round.",
        "Longer validation windows reduced false positives.",
    ]


def test_different_workflows_do_not_leak_into_each_other(tmp_path):
    store = FileBackedMemoryStore(tmp_path)
    asyncio.run(store.record(_round_1_record()))

    other_context = asyncio.run(store.load_context("some-other-workflow"))

    assert other_context.prior_result_references == []


def test_state_survives_a_fresh_instance_against_the_same_directory(tmp_path):
    """The actual point of this class: simulate a subprocess restart.

    The live dashboard pilot launches each round as a brand-new Python
    process, so InMemoryMemoryStore's state would be gone between rounds.
    This confirms a *new* FileBackedMemoryStore instance, pointed at the
    same directory, picks up exactly where the old one left off.
    """
    first_process_store = FileBackedMemoryStore(tmp_path)
    asyncio.run(first_process_store.record(_round_1_record()))
    del first_process_store  # simulate the round-1 subprocess exiting

    second_process_store = FileBackedMemoryStore(tmp_path)
    context = asyncio.run(second_process_store.load_context(WORKFLOW_ID))

    assert context.prior_pm_decisions == ["decision-round-1"]
    assert context.lessons_for_next_round == [
        "Require a longer out-of-sample window next round."
    ]

    asyncio.run(second_process_store.record(_round_2_record()))
    del second_process_store  # simulate the round-2 subprocess exiting

    third_process_store = FileBackedMemoryStore(tmp_path)
    final_context = asyncio.run(third_process_store.load_context(WORKFLOW_ID))

    assert final_context.prior_pm_decisions == ["decision-round-1", "decision-round-2"]
