"""
Reporting Agent implementation.

TODO:
- Collect surviving candidates from RiskReviewResponse
- Build cross-lens comparison
- Generate PM-facing strategy memo using model_client
- Construct ReportingOutput
"""

from .reporting_agent import ReportingAgent
from protocols.reporting import ReportingOutput, ReportingRequest

REPORT_AGENT_ID = "report_agent"
REPORT_AGENT_CARD_VERSION = "0.1.0"


class ReportingAgentImpl(ReportingAgent):

    agent_id = "reporting_agent"

    async def report(self, request: ReportingRequest) -> ReportingOutput:

        candidates = self._collect_candidates(request)

        comparison = self._build_comparison(candidates, request.risk_response)

        memo = await self._generate_memo(
            candidates, comparison, request.risk_response
        )  # TODO

        return ReportingOutput(
            output_id="",  # TODO
            request_id=request.request_id,
            surviving_candidate_ids=list(
                candidate.candidate_id
                for candidate in candidates
                if candidate.candidate_id is not None
            ),
            strategy_memo_reference=None,  # TODO
            comparison={},  # TODO
            combination_logic_implemented=False,
        )

    """1. Risk survivor documentation"""

    def _collect_candidates(self, request: ReportingRequest):
        return request.surviving_candidates

    """2. Cross lens comparison"""

    def _build_comparison(self, candidates, risk_response):
        comparison = {}

        # TODO:
        # 1. collect key information from each candidate
        # 2. attach relevant risk review information
        # 3. organize candidates into a common comparison structure

        decisions_by_candidate = {
            decision.candidate_id: decision for decision in risk_response.decisions
        }

        candidate_comparisons = []

        for candidate in candidates:
            decision = decisions_by_candidate.get(candidate.candidate_id)
            backtest_result = candidate.backtest_result
            interpretation = candidate.interpretation

            candidate_comparisons.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "trader_id": candidate.trader_id,
                    "hypothesis": candidate.hypothesis,
                    "metrics": (
                        backtest_result.metrics if backtest_result is not None else {}
                    ),
                    "out_of_sample_metrics": (
                        backtest_result.out_of_sample_metrics
                        if backtest_result is not None
                        else {}
                    ),
                    "interpretation": (
                        interpretation.summary if interpretation is not None else None
                    ),
                    "strengths": (
                        interpretation.strengths if interpretation is not None else []
                    ),
                    "weaknesses": (
                        interpretation.weaknesses if interpretation is not None else []
                    ),
                    "risk_verdict": (
                        decision.verdict if decision is not None else None
                    ),
                    "risk_critiques": (
                        decision.critiques if decision is not None else []
                    ),
                    "reporting_flags": (
                        decision.reporting_flags if decision is not None else []
                    ),
                }
            )

        return {
            "candidates": candidate_comparisons,
            "collective_critiques": risk_response.collective_critiques,
            "reporting_required_flags": list(risk_response.required_reporting_flage()),
        }

    """3. Strategy memo generation"""

    def _build_memo_prompt(self, candidates, comparison, risk_response):

        # TODO: Build a PM-facing prompt for model_client
        # from the comparison and required risk disclosures

        raise NotImplementedError

    async def _generate_memo(self, candidates, comparison, risk_response):
        # TODO: Generate a PM-facing strategy memo

        prompt = self._build_memo_prompt(candidates, comparison, risk_response)

        # TODO: Call model_client with prompt

        raise NotImplementedError
