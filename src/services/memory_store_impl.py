"""Implementation of the MemoryStore protocol.

TODO:
1. Round-to-round memory: after a round finishes, `record()` logs the results,
Risk's critiques, and the PM's decision.
2. Before the next round starts, `load_context()` should hand back a distilled MemoryContext
so the PM and the traders can learn from what happened before.

"""

from __future__ import annotations

from protocols.research_contracts import MemoryContext, MemoryRecord


class InMemoryMemoryStore:

    def __init__(self) -> None:
        # workflow_id -> list of every MemoryRecord logged for that workflow,
        # in the order they were recorded (oldest first).
        self._records: dict[str, list[MemoryRecord]] = {}

    async def record(self, record: MemoryRecord) -> str:
        """Persist results, critiques, the PM decision, and lessons."""

        # A single workflow can span multiple rounds (the PM may "request another round"),
        # so we keep every round's record, not just the latest one.
        self._records.setdefault(record.workflow_id, []).append(record)
        return record.record_id

    async def load_context(self, workflow_id: str) -> MemoryContext:
        """Return controlled context for a later PM research round."""

        records = self._records.get(workflow_id, [])

        prior_result_references: list[str] = []
        prior_critiques: list[str] = []
        prior_pm_decisions: list[str] = []
        lessons_for_next_round: list[str] = []

        for record in records:
            prior_result_references.extend(record.result_references)
            prior_critiques.extend(record.critiques)
            prior_pm_decisions.append(record.pm_decision.decision_id)
            lessons_for_next_round.extend(record.lessons_for_future_rounds)

        return MemoryContext(
            workflow_id=workflow_id,
            prior_result_references=prior_result_references,
            prior_critiques=prior_critiques,
            prior_pm_decisions=prior_pm_decisions,
            lessons_for_next_round=lessons_for_next_round,
        )
