"""Focused checks for the dashboard's WorkflowState handoff."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "dashboard"))

from workflow_adapter import build_dashboard_snapshot  # noqa: E402


def test_snapshot_preserves_lifecycle_and_marks_missing_events_na() -> None:
    state = json.loads(
        (REPOSITORY_ROOT / "dashboard" / "data" / "sample_workflow_state.json").read_text()
    )

    snapshot = build_dashboard_snapshot(state)

    assert snapshot["agents"]["technical"]["state"] == "Completed"
    assert snapshot["agents"]["fundamental"]["staffing_status"] == "Benched"
    assert snapshot["agents"]["technical"]["metrics"]["task_completion_time"] == "0:03:06"
    assert snapshot["agents"]["technical"]["metrics"]["success_rate"] == "N/A"
