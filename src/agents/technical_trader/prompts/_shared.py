"""Provider-neutral prompt rendering for independent trader stages."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel
from protocols import PMMandate, ValidationSplit

from ..executors import render_executor_catalog
from ..horizon import resolve_technical_horizon
from .compaction import (
    CandidatePromptScope,
    DEFAULT_CANDIDATE_PROMPT_ASSETS,
    build_opportunity_prompt_report,
    compact_horizon_technical_report,
)


SHARED_TRADER_BOUNDARY = """
Operating boundaries:
- Form a candidate independently through your assigned analytical lens.
- Respect every supplied PM mandate constraint.
- Use only point-in-time data supplied by the shared Data Service.
- Do not fetch uncontrolled data.
- Produce a precise, codeable candidate; do not hard-code a package-level default.
- Select exactly one supplied registered strategy executor. Do not invent one,
  choose an approximate substitute, or write executable code.
- Never calculate or invent performance metrics.
- The deterministic Backtest Engine is the only source of backtest results.
- Do not select the held-out evaluation window; shared code owns that policy.
- Do not approve the candidate. Risk reviews all backtested candidates together,
  and the PM makes the final selection.
- Produce one candidate package. A registered executor may coordinate several
  asset sleeves inside that single strategy, but do not combine independently
  backtested trader candidates after seeing their results.
""".strip()


def _json(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _candidate_prompt_report(
    technical_analysis: BaseModel,
    max_prompt_assets: int,
) -> dict[str, Any]:
    compact = compact_horizon_technical_report(
        technical_analysis.model_dump(mode="json"),
        max_assets=max_prompt_assets,
    )
    scope = CandidatePromptScope.from_compacted_report(compact)
    return build_opportunity_prompt_report(compact, scope)


def render_research_plan(
    *,
    mandate: PMMandate,
    lens_requirements: tuple[str, ...],
    available_executors: tuple[str, ...],
) -> str:
    lens = "\n".join(f"- {item}" for item in lens_requirements)
    executors = render_executor_catalog(available_executors)
    horizon = resolve_technical_horizon(mandate).as_prompt_mapping()
    return f"""
Determine the point-in-time data required to research one candidate through your
analytical lens. Request fields rather than assuming they exist.

Do not choose a symbol or strategy family during this planning operation. Plan
the evidence needed to compare the registered executor families below. Mark a
field required only when every viable registered family needs it. For the
current Technical toolkit, require only symbol plus timestamp/open/high/low/
close daily bars. Treat volume, trading-session flags, ETF lifecycle fields,
liquidity fields, adjustment metadata, exchange metadata, and every other
family-specific enhancement as optional: if one is unavailable, exclude only
the sleeve families that depend on it. Use the canonical frequency `daily`.
Leave start_date and end_date null unless the PM explicitly supplies a research
window; shared code owns the training/evaluation cutoff.

Registered strategy executors:
{executors}

Code-owned Technical horizon policy:
{_json(horizon)}

Lens requirements:
{lens}

Normalized PM mandate:
{_json(mandate)}
""".strip()


def render_candidate_proposal(
    *,
    mandate: PMMandate,
    data_response: BaseModel,
    technical_analysis: BaseModel,
    lens_requirements: tuple[str, ...],
    available_executors: tuple[str, ...],
    validation_split: ValidationSplit,
    required_benchmark: str | None = None,
    max_prompt_assets: int = DEFAULT_CANDIDATE_PROMPT_ASSETS,
    candidate_prompt_report: Mapping[str, Any] | None = None,
) -> str:
    lens = "\n".join(f"- {item}" for item in lens_requirements)
    executors = render_executor_catalog(available_executors)
    horizon = resolve_technical_horizon(mandate).as_prompt_mapping()
    prompt_report = (
        dict(candidate_prompt_report)
        if candidate_prompt_report is not None
        else _candidate_prompt_report(technical_analysis, max_prompt_assets)
    )
    benchmark_instruction = (
        f"Code will bind exactly `{required_benchmark}` as the benchmark."
        if required_benchmark is not None
        else (
            "Select one PM-permitted benchmark and declare it explicitly; "
            "a missing benchmark makes the candidate non-executable."
        )
    )
    return f"""
Using only the supplied point-in-time Data Service summary and deterministic
technical-analysis report, form one precise and codeable candidate strategy
aligned to your analytical lens. The strategy may contain several ETF sleeves
when the selected registered executor explicitly supports them.

The candidate is dynamically generated for this mandate. Define its hypothesis,
signal, position, entry, exit, rebalance, parameter, data, and constraint logic.
For each sleeve, select exactly one supplied `opportunity_ref`. Return only the
reference, expected_return_rationale, and model-authored family parameters for
that sleeve. Do not return a sleeve symbol, executor, evidence ID, opportunity
ID, rank, or score. Deterministic code binds all of those fields atomically from
the selected opportunity, restores canonical audit IDs, and binds evidence-
derived prices and windows before validation and execution. Do not mention an
`O###` reference in narrative fields; describe the ETF and Technical setup.
In backtest_plan, return only the closed transaction_cost_assumptions object
described by the response schema. Do not return dates, frequency, benchmark,
requested metrics, validation requirements, or held-out flags. Shared code
binds the exact held-out window below, daily frequency, required benchmark,
metrics, and validation policy after the response:
{_json(validation_split)}
{benchmark_instruction}

Compare instruments as potential sleeves. Do not reward an asset merely
because it has more detected levels. Raw touch counts are not directly
comparable across different histories and volatility regimes; interpret them
with observation_count and annualized_volatility from the deterministic report.
Use only signals permitted by the code-owned horizon policy. The preferred
horizon-adaptive trend sleeve may enter a prevailing bullish relationship at a
scheduled review, while its legacy crossover-only counterpart still requires a
fresh bullish crossover. Training-cutoff evidence establishes family
eligibility; rolling executors recompute their actual signal from past bars at
each code-owned review. When deterministic opportunity ranks are supplied,
treat rank
only as a reproducible tie-breaker, not as an instruction to copy the first
unique symbols. Compare available Technical families, signal recency, evidence
quality, conflicting observations, likely whipsaw or false-breakout exposure,
and overlap visible in the supplied price-based evidence. Do not invent sector,
fundamental, macroeconomic, or statistical-return information that was not
provided. Select fewer than the target when the Technical case is not strong
enough. Every sleeve must select one distinct supplied opportunity_ref, and no
two sleeves may resolve to the same ETF. A heuristic opportunity score ranks present Technical
setups; it is not proof of positive expected return.

The final shared executor is code-owned as the multi-asset Technical portfolio.
Do not output a top-level executor_id. Supply only family parameters appropriate
for each selected opportunity's displayed executor. Never approximate a
different family when the selected opportunity is not suitable.

Registered strategy executors:
{executors}

Code-owned Technical horizon policy:
{_json(horizon)}

Lens requirements:
{lens}

Normalized PM mandate:
{_json(mandate)}

Point-in-time Data Service response summary:
{_json(_without_analysis_payload(data_response))}

Deterministic Technical Analysis report:
{_json(prompt_report)}
""".strip()


def render_candidate_review(
    *,
    mandate: PMMandate,
    initial_proposal: BaseModel,
    technical_analysis: BaseModel,
    lens_requirements: tuple[str, ...],
    available_executors: tuple[str, ...],
    validation_split: ValidationSplit,
    required_benchmark: str | None = None,
    max_prompt_assets: int = DEFAULT_CANDIDATE_PROMPT_ASSETS,
    candidate_prompt_report: Mapping[str, Any] | None = None,
) -> str:
    lens = "\n".join(f"- {item}" for item in lens_requirements)
    executors = render_executor_catalog(available_executors)
    horizon = resolve_technical_horizon(mandate).as_prompt_mapping()
    prompt_report = (
        dict(candidate_prompt_report)
        if candidate_prompt_report is not None
        else _candidate_prompt_report(technical_analysis, max_prompt_assets)
    )
    benchmark_instruction = (
        f"Code will keep exactly `{required_benchmark}` as the benchmark."
        if required_benchmark is not None
        else "Keep one explicit PM-permitted benchmark."
    )
    return f"""
Act as the second-pass Technical portfolio reviewer. Return a complete revised
OpportunityCandidateProposalDraft, not commentary. Preserve a valid initial proposal only
when it survives scrutiny; otherwise replace its sleeve selection or reduce its
size.

Reason comparatively across the entire supplied shortlist. Check that every
sleeve has a genuinely horizon-aligned Technical case, that the chosen family
is the strongest supplied Technical expression for that ETF, and that the
portfolio is not merely the first ten unique opportunity ranks. Look for
conflicting price-based evidence, stale or fragile setups, likely crossover
whipsaw, false-breakout exposure, repeated use of very similar Technical
conditions, and avoidable concentration visible from the supplied Technical
evidence. Rank remains only a tie-breaker. Ten ETFs are a target, not a quota.

Stay strictly within the Technical Trader lens. Do not add fundamental, macro,
factor, predictive-statistical, or optimized-return claims. Do not calculate
performance, infer expected return from the heuristic score, inspect held-out
data, change the code-owned horizon, or invent evidence. Keep the registered
executor, costs, and implementation contracts valid. Every retained sleeve
must select exactly one supplied opportunity_ref.
Do not output or reconstruct its symbol, executor, canonical evidence IDs,
opportunity ID, rank, or score. Do not mention O### references in narrative
fields. Code expands each reference atomically after your response.

The code-owned held-out window is {_json(validation_split)}. In backtest_plan,
return only the closed transaction_cost_assumptions object. Do not output the
window, daily frequency, held-out flag, benchmark, metrics, or validation
requirements; code binds them after the response. {benchmark_instruction}

Registered model-selectable executor:
{executors}

Code-owned Technical horizon policy:
{_json(horizon)}

Lens requirements:
{lens}

Normalized PM mandate:
{_json(mandate)}

Initial candidate proposal to challenge:
{_json(initial_proposal)}

Deterministic Technical Analysis report:
{_json(prompt_report)}
""".strip()


def render_backtest_interpretation(
    *,
    mandate: BaseModel,
    candidate_rule: BaseModel,
    backtest_result: BaseModel,
    lens_requirements: tuple[str, ...],
    benchmark_selection: dict[str, Any] | None = None,
) -> str:
    lens = "\n".join(f"- {item}" for item in lens_requirements)
    return f"""
Interpret the deterministic Backtest Engine result for Risk review.

Reference only metric names present in the result. Do not calculate new metrics,
alter values, approve the candidate, compare it with unseen trader candidates,
or claim that backtested performance will persist.
Treat result warnings as binding analytical limitations. If a warning identifies
zero or too few transactions, explicitly state that performance metrics are
analytically inconclusive even though the integration run succeeded.
When benchmark-selection context is supplied, explain whether the original
Technical portfolio beat the benchmark, whether the code-owned fallback was
applied, and why the final package contains its selected rule. Do not override
the deterministic gate. If the fallback was selected using the same held-out
window, identify that model-selection reuse as a limitation rather than
describing the fallback result as a fresh independent test.

Lens-specific scrutiny:
{lens}

Normalized PM mandate:
{_json(mandate)}

Candidate rule:
{_json(candidate_rule)}

Benchmark-selection context:
{_json(benchmark_selection or {})}

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
