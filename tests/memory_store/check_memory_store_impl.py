"""Manual end-to-end check for the in-memory MemoryStore.

Logs two rounds' worth of MemoryRecords for the same workflow and checks
that load_context() correctly aggregates results, critiques, PM decisions,
and lessons across all of them -- not just the most recent round. This is
an exploratory script rather than an automated test, hence no `test_`
prefix in the filename.
"""

import asyncio

from protocols import PMDecision, PMDecisionType
from protocols.research_contracts import MemoryRecord
from services.memory_store_impl import InMemoryMemoryStore

WORKFLOW_ID = "wf-manual-check"


async def main() -> None:
    store = InMemoryMemoryStore()

    # 0. Before anything is recorded, a brand-new workflow should get back
    #    an empty context, not an error.
    empty_context = await store.load_context(WORKFLOW_ID)
    print("=== Context before any rounds ===")
    print(empty_context)

    # 1. Log round 1: the PM wasn't satisfied and asked for another round.
    round_1_decision = PMDecision(
        decision_id="decision-round-1",
        workflow_id=WORKFLOW_ID,
        decision=PMDecisionType.REQUEST_ANOTHER_ROUND,
        rationale="All three candidates were flagged for thin out-of-sample data.",
        next_round_instructions=["Widen the validation window."],
    )
    round_1_record = MemoryRecord(
        record_id="record-round-1",
        workflow_id=WORKFLOW_ID,
        mandate_task_id="mandate-1",
        result_references=["cand-technical.result", "cand-quant.result"],
        critiques=["Sharpe ratio was inflated by a short validation window."],
        pm_decision=round_1_decision,
        lessons_for_future_rounds=["Require a longer out-of-sample window next round."],
    )
    await store.record(round_1_record)

    # 2. Log round 2: the PM selected a winner this time.
    round_2_decision = PMDecision(
        decision_id="decision-round-2",
        workflow_id=WORKFLOW_ID,
        decision=PMDecisionType.SELECT,
        selected_candidate_id="cand-technical-v2",
        rationale="Strongest risk-adjusted return with a clean Risk review.",
    )
    round_2_record = MemoryRecord(
        record_id="record-round-2",
        workflow_id=WORKFLOW_ID,
        mandate_task_id="mandate-1",
        result_references=["cand-technical-v2.result"],
        critiques=[],
        pm_decision=round_2_decision,
        lessons_for_future_rounds=[
            "Longer validation windows reduced false positives."
        ],
    )
    await store.record(round_2_record)

    # 3. Now load_context() should reflect BOTH rounds combined.
    full_context = await store.load_context(WORKFLOW_ID)
    print("\n=== Context after two rounds ===")
    print(full_context)


if __name__ == "__main__":
    asyncio.run(main())
