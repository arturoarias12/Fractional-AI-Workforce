"""Provider-neutral prompt bounding for full-universe Technical evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from protocols import CandidateProposalDraft


DEFAULT_CANDIDATE_PROMPT_ASSETS = 20
MIN_CANDIDATE_PROMPT_ASSETS = 10
MAX_CANDIDATE_PROMPT_ASSETS = 120


@dataclass(frozen=True, slots=True)
class CandidatePromptScope:
    """Exact symbols and evidence exposed to candidate-generation calls."""

    symbols: frozenset[str]
    evidence_ids: frozenset[str]
    opportunity_keys: frozenset[tuple[str, str, tuple[str, ...]]]

    @classmethod
    def from_compacted_report(
        cls,
        report: dict[str, Any],
    ) -> "CandidatePromptScope":
        raw_assets = report.get("assets")
        raw_opportunities = report.get("horizon_opportunities")
        if not isinstance(raw_assets, list) or not isinstance(
            raw_opportunities,
            list,
        ):
            raise ValueError(
                "Compacted Technical report must contain asset and "
                "horizon-opportunity lists."
            )

        symbols = frozenset(
            str(asset.get("symbol", "")).strip()
            for asset in raw_assets
            if isinstance(asset, dict)
            and str(asset.get("symbol", "")).strip()
        )
        opportunity_keys: set[tuple[str, str, tuple[str, ...]]] = set()
        evidence_ids: set[str] = set()
        for opportunity in raw_opportunities:
            if not isinstance(opportunity, dict):
                continue
            symbol = str(opportunity.get("symbol", "")).strip()
            executor_id = str(opportunity.get("executor_id", "")).strip()
            raw_evidence = opportunity.get("evidence_ids")
            if (
                not symbol
                or not executor_id
                or not isinstance(raw_evidence, list)
            ):
                continue
            opportunity_evidence = tuple(
                sorted(
                    str(evidence_id).strip()
                    for evidence_id in raw_evidence
                    if str(evidence_id).strip()
                )
            )
            evidence_ids.update(opportunity_evidence)
            opportunity_keys.add(
                (symbol, executor_id, opportunity_evidence)
            )

        if not symbols or not opportunity_keys:
            raise ValueError(
                "Compacted Technical report produced an empty candidate "
                "prompt scope."
            )
        return cls(
            symbols=symbols,
            evidence_ids=frozenset(evidence_ids),
            opportunity_keys=frozenset(opportunity_keys),
        )

    def validate_proposal(self, proposal: CandidateProposalDraft) -> None:
        """Reject any model choice that was absent from its exact prompt."""

        referenced = {
            evidence_id.strip()
            for evidence_id in proposal.rule.specialty_evidence_ids
        }
        outside_evidence = sorted(referenced - self.evidence_ids)
        if outside_evidence:
            raise ValueError(
                "Candidate cited evidence outside its submitted Technical "
                "shortlist: " + ", ".join(outside_evidence)
            )

        parameters = proposal.rule.parameters
        top_level_symbol = parameters.get("symbol")
        if (
            isinstance(top_level_symbol, str)
            and top_level_symbol.strip() not in self.symbols
        ):
            raise ValueError(
                "Candidate selected symbol outside its submitted Technical "
                f"shortlist: {top_level_symbol.strip()}"
            )

        raw_sleeves = parameters.get("sleeves")
        if raw_sleeves is None:
            return
        if not isinstance(raw_sleeves, list):
            raise ValueError("Candidate portfolio sleeves must be a list.")

        for sleeve_number, sleeve in enumerate(raw_sleeves, start=1):
            if not isinstance(sleeve, dict):
                raise ValueError(
                    f"Candidate portfolio sleeve {sleeve_number} must be a "
                    "mapping."
                )
            symbol = str(sleeve.get("symbol", "")).strip()
            executor_id = str(sleeve.get("executor_id", "")).strip()
            raw_evidence = sleeve.get("evidence_ids")
            if symbol not in self.symbols:
                raise ValueError(
                    f"Candidate portfolio sleeve {sleeve_number} selected "
                    "a symbol outside its submitted Technical shortlist: "
                    f"{symbol or '<empty>'}"
                )
            if not isinstance(raw_evidence, list):
                raise ValueError(
                    f"Candidate portfolio sleeve {sleeve_number}.evidence_ids "
                    "must be a list."
                )
            evidence = tuple(
                sorted(
                    str(evidence_id).strip()
                    for evidence_id in raw_evidence
                    if str(evidence_id).strip()
                )
            )
            if (symbol, executor_id, evidence) not in self.opportunity_keys:
                raise ValueError(
                    f"Candidate portfolio sleeve {sleeve_number} did not "
                    "match a symbol, executor, and evidence combination in "
                    "its submitted Technical shortlist."
                )


def compact_horizon_technical_report(
    report: dict[str, Any],
    *,
    max_assets: int = DEFAULT_CANDIDATE_PROMPT_ASSETS,
) -> dict[str, Any]:
    """Retain the highest-ranked unique ETFs and their exact evidence.

    Deterministic analysis still covers the complete PM universe and the full
    report remains in the final package. Only the two candidate-reasoning
    prompts receive this bounded view. Ranking uses frozen training evidence;
    held-out returns never influence the shortlist.
    """

    if (
        isinstance(max_assets, bool)
        or not MIN_CANDIDATE_PROMPT_ASSETS
        <= max_assets
        <= MAX_CANDIDATE_PROMPT_ASSETS
    ):
        raise ValueError(
            "max_assets must be from "
            f"{MIN_CANDIDATE_PROMPT_ASSETS} through "
            f"{MAX_CANDIDATE_PROMPT_ASSETS}."
        )

    raw_assets = report.get("assets")
    raw_opportunities = report.get("horizon_opportunities")
    if not isinstance(raw_assets, list) or not isinstance(
        raw_opportunities, list
    ):
        raise ValueError(
            "Technical report must contain assets and horizon_opportunities."
        )

    opportunities = sorted(
        (
            item
            for item in raw_opportunities
            if isinstance(item, dict)
            and str(item.get("symbol", "")).strip()
            and str(item.get("executor_id", "")).strip()
        ),
        key=lambda item: (
            int(item.get("rank", 10**9)),
            str(item.get("symbol", "")),
            str(item.get("executor_id", "")),
        ),
    )
    if not opportunities:
        raise ValueError(
            "The deterministic horizon screen produced no LLM-eligible "
            "Technical opportunities."
        )

    opportunities_by_symbol: dict[str, list[dict[str, Any]]] = {}
    ordered_symbols: list[str] = []
    for opportunity in opportunities:
        symbol = str(opportunity["symbol"]).strip()
        if symbol not in opportunities_by_symbol:
            opportunities_by_symbol[symbol] = []
            ordered_symbols.append(symbol)
        opportunities_by_symbol[symbol].append(opportunity)

    selected_symbols = ordered_symbols[:max_assets]
    asset_by_symbol = {
        str(asset.get("symbol", "")).strip(): asset
        for asset in raw_assets
        if isinstance(asset, dict) and str(asset.get("symbol", "")).strip()
    }
    selected_assets: list[dict[str, Any]] = []
    selected_opportunities: list[dict[str, Any]] = []
    for symbol in selected_symbols:
        asset = asset_by_symbol.get(symbol)
        if asset is None:
            continue
        symbol_opportunities = opportunities_by_symbol[symbol]
        evidence_ids = {
            str(evidence_id)
            for opportunity in symbol_opportunities
            for evidence_id in opportunity.get("evidence_ids", [])
        }
        compact_asset = dict(asset)
        compact_asset["support_resistance_levels"] = [
            level
            for level in asset.get("support_resistance_levels", [])
            if str(level.get("level_id", "")) in evidence_ids
        ]
        compact_asset["chart_patterns"] = [
            pattern
            for pattern in asset.get("chart_patterns", [])
            if str(pattern.get("pattern_id", "")) in evidence_ids
        ]
        compact_asset["moving_averages"] = [
            observation
            for observation in asset.get("moving_averages", [])
            if str(observation.get("moving_average_id", "")) in evidence_ids
        ]
        legacy_moving_average = asset.get("moving_average")
        if not isinstance(legacy_moving_average, dict) or str(
            legacy_moving_average.get("moving_average_id", "")
        ) not in evidence_ids:
            compact_asset["moving_average"] = None
        volume = asset.get("volume_observation")
        if not isinstance(volume, dict) or str(
            volume.get("volume_id", "")
        ) not in evidence_ids:
            compact_asset["volume_observation"] = None
        compact_asset["screening_evidence"] = {
            "best_opportunity_rank": int(symbol_opportunities[0]["rank"]),
            "best_opportunity_score": float(
                symbol_opportunities[0].get("score", 0.0)
            ),
            "eligible_opportunities": symbol_opportunities,
        }
        selected_assets.append(compact_asset)
        selected_opportunities.extend(symbol_opportunities)

    if not selected_assets:
        raise ValueError(
            "No shortlisted opportunity matched an analyzed Technical asset."
        )

    compact_report = dict(report)
    compact_report["assets"] = selected_assets
    compact_report["horizon_opportunities"] = selected_opportunities
    compact_report["prompt_screening_summary"] = {
        "source_asset_count": len(raw_assets),
        "eligible_asset_count": len(opportunities_by_symbol),
        "submitted_asset_count": len(selected_assets),
        "maximum_submitted_assets": max_assets,
        "selection_basis": (
            "Lowest code-owned horizon-opportunity rank by unique symbol, "
            "computed exclusively from frozen training evidence."
        ),
        "full_report_preserved_outside_prompt": True,
    }
    return compact_report


__all__ = [
    "CandidatePromptScope",
    "DEFAULT_CANDIDATE_PROMPT_ASSETS",
    "MAX_CANDIDATE_PROMPT_ASSETS",
    "MIN_CANDIDATE_PROMPT_ASSETS",
    "compact_horizon_technical_report",
]
