"""Pure identity helpers for fresh, resumable full-system demo attempts."""

from __future__ import annotations

import os
from collections.abc import Mapping


def derive_demo_identifiers(
    environment: Mapping[str, str] | None = None,
) -> tuple[str, str, str]:
    """Derive one coherent run/workflow/task identity for a demo attempt."""

    source = os.environ if environment is None else environment
    workflow_id = source.get(
        "FULL_TEST_WORKFLOW_ID",
        "full-loop-demo-workflow",
    ).strip()
    if not workflow_id:
        raise ValueError("FULL_TEST_WORKFLOW_ID must be non-empty when set.")
    return f"{workflow_id}.run", workflow_id, f"{workflow_id}.task"


__all__ = ["derive_demo_identifiers"]
