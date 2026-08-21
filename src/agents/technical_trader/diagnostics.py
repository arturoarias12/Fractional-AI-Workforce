"""Optional, package-external diagnostics for rejected Technical drafts."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field

from protocols import ContractModel, NonEmptyStr


class TechnicalCandidateDiagnostic(ContractModel):
    """Whitelisted audit data for one rejected parsed model proposal."""

    diagnostic_id: NonEmptyStr
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    workflow_id: NonEmptyStr
    task_id: NonEmptyStr
    attempt: int = Field(ge=1)
    stage: NonEmptyStr
    error_type: NonEmptyStr
    error_message: NonEmptyStr
    raw_proposal: Any | None = None
    expanded_proposal: dict[str, Any] | None = None
    opportunity_catalog: list[dict[str, Any]] = Field(default_factory=list)


class TechnicalDiagnosticsSink(Protocol):
    """Replaceable destination kept outside the shared strategy package."""

    def record(self, diagnostic: TechnicalCandidateDiagnostic) -> None:
        """Persist one whitelisted Technical diagnostic."""


class NullTechnicalDiagnosticsSink:
    def record(self, diagnostic: TechnicalCandidateDiagnostic) -> None:
        del diagnostic


class InMemoryTechnicalDiagnosticsSink:
    def __init__(self) -> None:
        self.records: list[TechnicalCandidateDiagnostic] = []

    def record(self, diagnostic: TechnicalCandidateDiagnostic) -> None:
        self.records.append(diagnostic)


class JsonFileTechnicalDiagnosticsSink:
    """Atomically write local JSON artifacts without serializing clients/env."""

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)

    @property
    def directory(self) -> Path:
        return self._directory

    def record(self, diagnostic: TechnicalCandidateDiagnostic) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "-",
            diagnostic.diagnostic_id,
        ).strip(".-")
        if not safe_id:
            raise ValueError("Diagnostic ID produced an empty filename.")
        target = self._directory / f"{safe_id}.json"
        payload = diagnostic.model_dump(mode="json")
        serialized = json.dumps(payload, indent=2, sort_keys=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                delete=False,
                dir=self._directory,
                prefix=f".{safe_id}.",
                suffix=".tmp",
            ) as temporary:
                temporary.write(serialized)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            os.replace(temporary_name, target)
        finally:
            if temporary_name is not None:
                temporary_path = Path(temporary_name)
                if temporary_path.exists():
                    temporary_path.unlink()


def proposal_payload(value: Any) -> Any | None:
    """Serialize only parsed proposal-shaped values, never provider objects."""

    if value is None:
        return None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(mode="json")
        return dict(payload) if isinstance(payload, Mapping) else None
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (list, str, int, float, bool)):
        return value
    return None


__all__ = [
    "InMemoryTechnicalDiagnosticsSink",
    "JsonFileTechnicalDiagnosticsSink",
    "NullTechnicalDiagnosticsSink",
    "TechnicalCandidateDiagnostic",
    "TechnicalDiagnosticsSink",
    "proposal_payload",
]
