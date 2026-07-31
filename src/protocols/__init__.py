"""The single project-wide integration-contract vocabulary.

Agent-owned analytical models may remain in their own packages. Any model that
crosses an agent, service, graph, or deterministic-tool boundary is defined
here exactly once.
"""

from .a2a_messages import A2AMessage, MessageType
from .agent_cards import AgentCard, RoleType
from .backtest import (
    BacktestPlan,
    BacktestPlanDraft,
    BacktestRequest,
    BacktestResult,
    BacktestStatus,
    CandidateProposalDraft,
    CandidateRuleDraft,
    CandidateRuleSpecification,
    ValidationSplit,
)
from .common import (
    TERMINAL_TRADER_STATUSES,
    TRADER_IDS,
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
from .data import (
    DataArtifact,
    DataCategory,
    DataFieldRequirement,
    DataProvenance,
    DataRequest,
    DataResponse,
)
from .events import EventType, OperationalEvent
from .lifecycle import (
    LIFECYCLE_SCHEMA_VERSION,
    AgentExecutionState,
    AgentLifecycleRecord,
)
from .mandate import PMMandate
from .memory import MemoryContext, MemoryRecord
from .pm import PMDecision, PMDecisionType
from .reporting import ReportingOutput, ReportingRequest
from .risk import (
    DEFAULT_COLLECTIVE_CHECKS,
    RiskCandidateDecision,
    RiskCheckId,
    RiskCheckResult,
    RiskCheckScope,
    RiskCheckVerdict,
    RiskReviewRequest,
    RiskReviewResponse,
    RiskVerdict,
)
from .trader import (
    BacktestInterpretationDraft,
    ConstraintCheckStatus,
    DataUsageSummary,
    MandateConstraintAssessment,
    MetricInterpretation,
    TraderFailure,
    TraderResearchPlanDraft,
    TraderStrategyPackage,
    TraderTask,
)

__all__ = [
    "A2AMessage",
    "AgentExecutionState",
    "AgentLifecycleRecord",
    "AgentCard",
    "BacktestInterpretationDraft",
    "BacktestPlan",
    "BacktestPlanDraft",
    "BacktestRequest",
    "BacktestResult",
    "BacktestStatus",
    "CandidateProposalDraft",
    "CandidateRuleDraft",
    "CandidateRuleSpecification",
    "ConfidenceAssessment",
    "ConfidenceLevel",
    "ConstraintCheckStatus",
    "ContractModel",
    "DEFAULT_COLLECTIVE_CHECKS",
    "DataArtifact",
    "DataCategory",
    "DataFieldRequirement",
    "DataProvenance",
    "DataRequest",
    "DataResponse",
    "DataUsageSummary",
    "EventType",
    "ExtensibleModel",
    "LIFECYCLE_SCHEMA_VERSION",
    "MandateConstraintAssessment",
    "MandateReference",
    "MemoryContext",
    "MemoryRecord",
    "MessageType",
    "MetricInterpretation",
    "NonEmptyStr",
    "OperationalEvent",
    "PMDecision",
    "PMDecisionType",
    "PMMandate",
    "ReportingOutput",
    "ReportingRequest",
    "RiskCandidateDecision",
    "RiskCheckId",
    "RiskCheckResult",
    "RiskCheckScope",
    "RiskCheckVerdict",
    "RiskReviewRequest",
    "RiskReviewResponse",
    "RiskVerdict",
    "RoleType",
    "RunStatus",
    "SpecialistId",
    "TERMINAL_TRADER_STATUSES",
    "TRADER_IDS",
    "TaskLineage",
    "TraderFailure",
    "TraderResearchPlanDraft",
    "TraderStrategyPackage",
    "TraderTask",
    "ValidationSplit",
]
