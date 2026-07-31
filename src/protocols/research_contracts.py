"""Compatibility imports for the former monolithic contract module.

Definitions now live in focused modules under :mod:`protocols`. Existing
components may keep importing this path during migration without creating a
second contract vocabulary.
"""

from .backtest import (
    BacktestPlan,
    BacktestRequest,
    BacktestResult,
    BacktestStatus,
    CandidateRuleSpecification,
)
from .common import RunStatus, SpecialistId, TaskLineage
from .data import DataArtifact, DataProvenance, DataRequest, DataResponse
from .mandate import PMMandate
from .memory import MemoryContext, MemoryRecord
from .pm import PMDecision, PMDecisionType
from .reporting import ReportingOutput, ReportingRequest
from .risk import (
    RiskCandidateDecision,
    RiskReviewRequest,
    RiskReviewResponse,
    RiskVerdict,
)
from .trader import TraderFailure, TraderStrategyPackage

__all__ = [
    "BacktestPlan",
    "BacktestRequest",
    "BacktestResult",
    "BacktestStatus",
    "CandidateRuleSpecification",
    "DataArtifact",
    "DataProvenance",
    "DataRequest",
    "DataResponse",
    "MemoryContext",
    "MemoryRecord",
    "PMDecision",
    "PMDecisionType",
    "PMMandate",
    "ReportingOutput",
    "ReportingRequest",
    "RiskCandidateDecision",
    "RiskReviewRequest",
    "RiskReviewResponse",
    "RiskVerdict",
    "RunStatus",
    "SpecialistId",
    "TaskLineage",
    "TraderFailure",
    "TraderStrategyPackage",
]
