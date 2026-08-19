"""File-backed implementation of the MemoryStore protocol.

InMemoryMemoryStore (memory_store_impl.py) already existed and was
unit-tested, and is genuinely correct - but it only lives inside one
Python process. The live dashboard pilot launches each research round as
a fresh subprocess (see dashboard/app.py's launch_live_research /
scripts/run_full_research_loop_demo.py), so anything held only in that
process's memory is gone the instant the round finishes. This class keeps
the exact same load_context()/record() contract and the exact same
distillation logic as InMemoryMemoryStore, but persists records to a JSON
file on disk between rounds, so round 2's memory_context genuinely
reflects round 1's outcome even though it runs in a brand new process.

Not a database - a single JSON file per workflow, adequate for a local,
single-user demo. Concurrent writers are not supported; the dashboard
only ever runs one round at a time.
"""

from __future__ import annotations

import json
from pathlib import Path

from protocols.research_contracts import MemoryContext, MemoryRecord


class FileBackedMemoryStore:
    """Same distillation logic as InMemoryMemoryStore, persisted to disk."""

    def __init__(self, storage_dir: Path | str) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, workflow_id: str) -> Path:
        # workflow_id is produced by our own mandate builder (see
        # scripts/run_full_research_loop_demo.py), not arbitrary user input,
        # so a light sanitization pass is enough here.
        safe_name = "".join(
            ch if ch.isalnum() or ch in "-_." else "_" for ch in workflow_id
        )
        return self._storage_dir / f"{safe_name}.json"

    def _load_records(self, workflow_id: str) -> list[MemoryRecord]:
        path = self._path_for(workflow_id)
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [MemoryRecord.model_validate(item) for item in raw]

    def _save_records(self, workflow_id: str, records: list[MemoryRecord]) -> None:
        path = self._path_for(workflow_id)
        payload = [record.model_dump(mode="json") for record in records]
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    async def record(self, record: MemoryRecord) -> str:
        """Persist results, critiques, the PM decision, and lessons."""
        records = self._load_records(record.workflow_id)
        records.append(record)
        self._save_records(record.workflow_id, records)
        return record.record_id

    async def load_context(self, workflow_id: str) -> MemoryContext:
        """Return controlled context for a later PM research round."""
        records = self._load_records(workflow_id)

        prior_result_references: list[str] = []
        prior_critiques: list[str] = []
        prior_pm_decisions: list[str] = []
        lessons_for_next_round: list[str] = []

        for stored in records:
            prior_result_references.extend(stored.result_references)
            prior_critiques.extend(stored.critiques)
            prior_pm_decisions.append(stored.pm_decision.decision_id)
            lessons_for_next_round.extend(stored.lessons_for_future_rounds)

        return MemoryContext(
            workflow_id=workflow_id,
            prior_result_references=prior_result_references,
            prior_critiques=prior_critiques,
            prior_pm_decisions=prior_pm_decisions,
            lessons_for_next_round=lessons_for_next_round,
        )


__all__ = ["FileBackedMemoryStore"]
