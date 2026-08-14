"""Manual end-to-end check for the Reporting Agent.

Chains: technical/fundamental/quant -> risk -> reporting.

Fakes settled technical/fundamental/quant trader packages the way the graph
would deliver them, runs the real RiskAgentImpl to produce a genuine
RiskReviewResponse, and feeds the surviving candidates into
ReportingAgentImpl.report() so the full data flow can be inspected by eye.
This is an exploratory script rather than an automated test, hence no `test_`
prefix in the filename.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "risk_agent"))

from risk_fixtures import (
    three_clean_candidates,
    build_request,
)  # noqa: E402

from agents.risk_agent import RiskAgentImpl  # noqa: E402
from agents.reporting_agent.reporting_agent_impl import ReportingAgentImpl  # noqa: E402
from protocols.reporting import ReportingRequest  # noqa: E402


async def main() -> None:
    # 1. Fake the technical / fundamental / quant trader outputs
    # (no real trader code needed).
    candidates = three_clean_candidates()
    risk_request = build_request(candidates)

    # 2. Actually run the Risk Agent
    risk_agent = RiskAgentImpl()
    risk_response = await risk_agent.review(risk_request)

    print("=== Risk decisions ===")
    for decision in risk_response.decisions:
        print(f"  {decision.candidate_id}: {decision.verdict}")

    # 3. Only pass the candidates Risk approved along to Reporting.
    surviving_ids = set(risk_response.approved_candidate_ids())
    surviving_candidates = [
        candidate
        for candidate in candidates
        if str(candidate.candidate_id) in surviving_ids
    ]

    reporting_request = ReportingRequest(
        request_id=f"{risk_request.request_id}.reporting",
        mandate_task_id=risk_request.mandate_task_id,
        surviving_candidates=surviving_candidates,
        risk_response=risk_response,
    )

    # 4. Actually run the Reporting Agent.
    reporting_agent = ReportingAgentImpl()
    output = await reporting_agent.report(reporting_request)

    print("\n=== Reporting Agent output ===")
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
