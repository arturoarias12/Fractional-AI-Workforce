"""Compatibility imports for shared contract primitives.

New code should import these names from :mod:`protocols`.
"""

from protocols import (
    ConfidenceAssessment,
    ConfidenceLevel,
    ContractModel,
    ExtensibleModel,
    MandateReference,
    NonEmptyStr,
    RunStatus,
    SpecialistId,
    TaskLineage,
)

TraderRunStatus = RunStatus
TraderType = SpecialistId

__all__ = [
    "ConfidenceAssessment",
    "ConfidenceLevel",
    "ContractModel",
    "ExtensibleModel",
    "MandateReference",
    "NonEmptyStr",
    "RunStatus",
    "SpecialistId",
    "TaskLineage",
    "TraderRunStatus",
    "TraderType",
]
