"""Export a JSON-compatible WorkflowState for the Streamlit dashboard.

Usage:
    python export_snapshot.py path/to/final_workflow_state.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from workflow_adapter import DEFAULT_SNAPSHOT_PATH, write_dashboard_snapshot


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python export_snapshot.py path/to/final_workflow_state.json")
    source = Path(sys.argv[1])
    state = json.loads(source.read_text(encoding="utf-8"))
    destination = write_dashboard_snapshot(state, DEFAULT_SNAPSHOT_PATH)
    print(f"Wrote dashboard snapshot to {destination}")


if __name__ == "__main__":
    main()
