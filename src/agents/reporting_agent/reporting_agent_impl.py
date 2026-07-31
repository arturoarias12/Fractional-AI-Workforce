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

        memo = await self._generate_memo(candidates, comparison)  # TODO

        return ReportingOutput(
            output_id="",  # TODO
            request_id=request.request_id,
            surviving_candidate_ids=tuple(
                candidate.candidate_id
                for candidate in candidates
                if candidate.candidate_id is not None
            ),
            strategy_memo_reference=None,  # TODO
            comparison={},  # TODO
            combination_logic_implemented=False,
        )

    def _collect_candidates(self, request: ReportingRequest):
        raise NotImplementedError

    def _build_comparison(self, candidates, risk_response):
        raise NotImplementedError

    async def _generate_memo(self, candidates, comparison):
        raise NotImplementedError
