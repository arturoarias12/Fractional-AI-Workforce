"""Public package interface for the Reporting Agent.

This initializer exposes Emma's current interface and implementation without
changing either module. It will need to be expanded when the other agents and
shared tools are implemented, including the finalized Risk handoff, round-audit
artifacts, model adapter, reporting tools, and production integration adapters.
"""

from .reporting_agent import ReportingAgent
from .reporting_agent_impl import ReportingAgentImpl

__all__ = [
    "ReportingAgent",
    "ReportingAgentImpl",
]
