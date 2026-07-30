"""
Reporting Agent implementation.

TODO:
- Collect surviving candidates from RiskReviewResponse
- Build cross-lens comparison
- Generate PM-facing strategy memo using model_client
- Construct ReportingOutput
"""

from .reporting_agent import ReportingAgent
from protocols.research_contracts import ReportingOutput, ReportingRequest


class ReportingAgentImpl(ReportingAgent):

    agent_id = "reporting_agent"

    async def report(self, request: ReportingRequest) -> ReportingOutput:

        candidates = self._collect_candidates(request)

        comparison = self._build_comparison(candidates, request.risk_response)

        memo = await self._generate_memo(candidates, comparison)

        # return ReportingOutput()
        raise NotImplementedError

    def _collect_candidates(self, request):
        raise NotImplementedError

    def _build_comparison(self, candidates, risk_response):
        raise NotImplementedError

    async def _generate_memo(self, candidates, comparison):
        raise NotImplementedError
