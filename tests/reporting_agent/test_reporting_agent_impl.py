"""Acceptance tests for the Reporting Agent.

Each test builds a real RiskReviewResponse (by running the real
RiskAgentImpl against three clean candidate packages), then feeds the
surviving candidates into ReportingAgentImpl.report() and asserts on the
shape of the result.

Wire GeminiModelClient into check_reporting_agent_impl.py to manually
verify end-to-end memo generation through the real Risk -> Reporting
chain (kept out of the pytest suite intentionally, since it makes a
real paid API call)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "risk_agent"))  # type: ignore

from risk_fixtures import build_request, three_clean_candidates  # noqa: E402

from agents.risk_agent import RiskAgentImpl  # noqa: E402
from agents.reporting_agent.reporting_agent_impl import ReportingAgentImpl  # noqa: E402
from protocols.reporting import ReportingRequest  # noqa: E402


def _build_reporting_request() -> ReportingRequest:
    """Run the real Risk Agent over three clean candidates, then package
    up whichever candidates it approved into a ReportingRequest."""

    candidates = three_clean_candidates()
    risk_request = build_request(candidates)
    risk_response = asyncio.run(RiskAgentImpl().review(risk_request))

    surviving_ids = set(risk_response.approved_candidate_ids())
    surviving_candidates = [
        candidate
        for candidate in candidates
        if str(candidate.candidate_id) in surviving_ids
    ]

    return ReportingRequest(
        request_id=f"{risk_request.request_id}.reporting",
        mandate_task_id=risk_request.mandate_task_id,
        surviving_candidates=surviving_candidates,
        risk_response=risk_response,
    )


def report(request: ReportingRequest):
    return asyncio.run(ReportingAgentImpl().report(request))


def test_report_lists_every_surviving_candidate():
    request = _build_reporting_request()
    output = report(request)

    assert set(output.surviving_candidate_ids) == {
        "cand-technical",
        "cand-fundamental",
        "cand-quant",
    }


def test_comparison_covers_every_surviving_candidate():
    request = _build_reporting_request()
    output = report(request)

    compared_ids = {
        candidate["candidate_id"] for candidate in output.comparison["candidates"]
    }
    assert compared_ids == {"cand-technical", "cand-fundamental", "cand-quant"}


def test_output_has_non_empty_identifiers():
    request = _build_reporting_request()
    output = report(request)

    assert output.output_id
    assert output.request_id == request.request_id
