"""Provider-neutral prompt rendering for independent trader stages."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


SHARED_TRADER_BOUNDARY = """
Operating boundaries:
- Form a candidate independently through your assigned analytical lens.
- Respect every supplied PM mandate constraint.
- Use only point-in-time data supplied by the shared Data Service.
- Do not fetch uncontrolled data.
- Produce a precise, codeable candidate; do not hard-code a package-level default.
- Never calculate or invent performance metrics.
- The deterministic Backtest Engine is the only source of backtest results.
- Do not approve the candidate. Risk reviews all backtested candidates together,
  and the PM makes the final selection.
- Do not combine candidates or propose portfolio-of-strategies allocation.
""".strip()


def _json(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def render_research_plan(*, mandate: BaseModel, lens_requirements: tuple[str, ...]) -> str:
    lens = "\n".join(f"- {item}" for item in lens_requirements)
    return f"""
Determine the point-in-time data required to research one candidate through your
analytical lens. Request fields rather than assuming they exist.

Lens requirements:
{lens}

Normalized PM mandate:
{_json(mandate)}
""".strip()


def render_candidate_proposal(
    *,
    mandate: BaseModel,
    data_response: BaseModel,
    technical_analysis: BaseModel,
    lens_requirements: tuple[str, ...],
) -> str:
    lens = "\n".join(f"- {item}" for item in lens_requirements)
    return f"""
Using only the supplied point-in-time Data Service summary and deterministic
technical-analysis report, form one precise and codeable candidate strategy
aligned to your analytical lens.

The candidate is dynamically generated for this mandate. Define its hypothesis,
signal, position, entry, exit, rebalance, parameter, data, and constraint logic.
Use at least one supplied support/resistance level_id and cite every used level
or pattern in technical_evidence_ids. In technical_evidence_usage, map each
cited ID to the exact role it plays in the signal, entry, exit, or risk logic.
Provide a Backtest Engine plan, but do not calculate or predict any result.

Lens requirements:
{lens}

Normalized PM mandate:
{_json(mandate)}

Point-in-time Data Service response summary:
{_json(_without_analysis_payload(data_response))}

Deterministic Technical Analysis report:
{_json(technical_analysis)}
""".strip()


def render_backtest_interpretation(
    *,
    mandate: BaseModel,
    candidate_rule: BaseModel,
    backtest_result: BaseModel,
    lens_requirements: tuple[str, ...],
) -> str:
    lens = "\n".join(f"- {item}" for item in lens_requirements)
    return f"""
Interpret the deterministic Backtest Engine result for Risk review.

Reference only metric names present in the result. Do not calculate new metrics,
alter values, approve the candidate, compare it with unseen trader candidates,
or claim that backtested performance will persist.

Lens-specific scrutiny:
{lens}

Normalized PM mandate:
{_json(mandate)}

Candidate rule:
{_json(candidate_rule)}

Deterministic Backtest Engine result:
{_json(backtest_result)}
""".strip()


def _without_analysis_payload(value: BaseModel) -> dict[str, Any]:
    """Keep raw OHLCV payloads out of model prompts after tool computation."""

    payload = value.model_dump(mode="json")
    for artifact in payload.get("artifacts", []):
        if artifact.get("analysis_payload") is not None:
            artifact["analysis_payload"] = (
                "<consumed by deterministic technical-analysis toolkit>"
            )
    return payload
