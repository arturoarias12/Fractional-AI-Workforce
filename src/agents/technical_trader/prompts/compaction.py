"""Provider-neutral prompt bounding for full-universe Technical evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from protocols import CandidateProposalDraft

from ..executors.catalog import TECHNICAL_EXECUTOR_SPEC_BY_ID
from ..models.opportunity_selection import (
    OpportunityCandidateProposalDraft,
    TARGET_TECHNICAL_SLEEVES,
)


DEFAULT_CANDIDATE_PROMPT_ASSETS = 20
MIN_CANDIDATE_PROMPT_ASSETS = 10
MAX_CANDIDATE_PROMPT_ASSETS = 120


_PORTFOLIO_EXECUTOR_ID = "technical.multi_asset_portfolio.v1"
_OPPORTUNITY_REF_PATTERN = re.compile(r"\bO\d{3,}\b", re.IGNORECASE)
_OPPORTUNITY_REF_FULL_PATTERN = re.compile(r"O\d{3,}", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class OpportunityBinding:
    """Canonical deterministic opportunity hidden behind one prompt ref."""

    opportunity_ref: str
    opportunity_id: str
    symbol: str
    executor_id: str
    evidence_ids: tuple[str, ...]
    rank: int
    score: float

    @property
    def narrative_label(self) -> str:
        family = self.executor_id.removeprefix("technical.").removesuffix(
            ".v1"
        )
        return f"{self.symbol} {family.replace('_', ' ')} opportunity"


@dataclass(frozen=True, slots=True)
class CandidatePromptScope:
    """Exact canonical scope plus atomic model-facing opportunity refs."""

    symbols: frozenset[str]
    evidence_ids: frozenset[str]
    opportunity_keys: frozenset[tuple[str, str, tuple[str, ...]]]
    opportunity_by_ref: Mapping[str, OpportunityBinding] = field(
        default_factory=dict
    )

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
        ordered_opportunities = sorted(
            (
                opportunity
                for opportunity in raw_opportunities
                if isinstance(opportunity, dict)
            ),
            key=lambda item: (
                int(item.get("rank", 10**9)),
                str(item.get("symbol", "")),
                str(item.get("executor_id", "")),
            ),
        )
        reference_width = max(3, len(str(len(ordered_opportunities))))
        opportunity_by_ref: dict[str, OpportunityBinding] = {}
        for index, opportunity in enumerate(ordered_opportunities, start=1):
            if not isinstance(opportunity, dict):
                continue
            symbol = str(opportunity.get("symbol", "")).strip()
            executor_id = str(opportunity.get("executor_id", "")).strip()
            opportunity_id = str(
                opportunity.get("opportunity_id", "")
            ).strip()
            raw_evidence = opportunity.get("evidence_ids")
            if (
                not symbol
                or not executor_id
                or not opportunity_id
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
            opportunity_ref = f"O{index:0{reference_width}d}"
            opportunity_by_ref[opportunity_ref] = OpportunityBinding(
                opportunity_ref=opportunity_ref,
                opportunity_id=opportunity_id,
                symbol=symbol,
                executor_id=executor_id,
                evidence_ids=opportunity_evidence,
                rank=int(opportunity.get("rank", index)),
                score=float(opportunity.get("score", 0.0)),
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
            opportunity_by_ref=opportunity_by_ref,
        )

    def expand_opportunity_proposal(
        self,
        proposal: OpportunityCandidateProposalDraft,
    ) -> CandidateProposalDraft:
        """Bind model refs into one canonical shared candidate proposal."""

        if not self.opportunity_by_ref:
            raise ValueError("Candidate prompt scope has no opportunity refs.")

        raw_selections = proposal.rule.portfolio.sleeves
        validated_bindings: list[OpportunityBinding] = []
        seen_refs: set[str] = set()
        seen_symbols: set[str] = set()
        for sleeve_number, selection in enumerate(raw_selections, start=1):
            raw_ref = selection.opportunity_ref.strip()
            normalized_ref = raw_ref.upper()
            if _OPPORTUNITY_REF_FULL_PATTERN.fullmatch(raw_ref) is None:
                raise ValueError(
                    f"Candidate portfolio sleeve {sleeve_number} has "
                    f"malformed opportunity reference '{raw_ref}'."
                )
            binding = self.opportunity_by_ref.get(normalized_ref)
            if binding is None:
                raise ValueError(
                    f"Candidate portfolio sleeve {sleeve_number} selected "
                    f"unknown opportunity reference '{raw_ref}'."
                )
            if normalized_ref in seen_refs:
                raise ValueError(
                    f"Candidate portfolio sleeve {sleeve_number} reused "
                    f"opportunity reference '{normalized_ref}'."
                )
            if binding.symbol in seen_symbols:
                raise ValueError(
                    f"Candidate portfolio sleeve {sleeve_number} would reuse "
                    f"ETF symbol '{binding.symbol}'."
                )
            seen_refs.add(normalized_ref)
            seen_symbols.add(binding.symbol)
            authored_parameters = selection.parameters.authored_mapping()
            spec = TECHNICAL_EXECUTOR_SPEC_BY_ID.get(binding.executor_id)
            if spec is None:
                raise ValueError(
                    f"Candidate portfolio sleeve {sleeve_number} selected "
                    f"an unregistered executor '{binding.executor_id}'."
                )
            expected_parameters = set(spec.model_authored_parameters)
            actual_parameters = set(authored_parameters)
            if actual_parameters != expected_parameters:
                missing = sorted(expected_parameters - actual_parameters)
                unexpected = sorted(actual_parameters - expected_parameters)
                details: list[str] = []
                if missing:
                    details.append("missing " + ", ".join(missing))
                if unexpected:
                    details.append("unexpected " + ", ".join(unexpected))
                raise ValueError(
                    f"Candidate portfolio sleeve {sleeve_number} parameters "
                    f"do not match {binding.executor_id}: "
                    + "; ".join(details)
                    + "."
                )
            validated_bindings.append(binding)

        raw_payload = proposal.model_dump(mode="python")
        labels = {
            reference: binding.narrative_label
            for reference, binding in self.opportunity_by_ref.items()
        }
        sanitized_payload = _replace_opportunity_tokens(raw_payload, labels)
        sanitized_selections = sanitized_payload["rule"]["portfolio"][
            "sleeves"
        ]
        bound_sleeves: list[dict[str, Any]] = []
        referenced_evidence: list[str] = []
        evidence_usage: dict[str, str] = {}
        for sleeve_number, (selection, sanitized, binding) in enumerate(
            zip(
                raw_selections,
                sanitized_selections,
                validated_bindings,
                strict=True,
            ),
            start=1,
        ):
            rationale = str(
                sanitized["expected_return_rationale"]
            ).strip()
            for evidence_id in binding.evidence_ids:
                if evidence_id in evidence_usage:
                    raise ValueError(
                        "Deterministic opportunities reused canonical "
                        f"evidence across sleeves: {evidence_id}"
                    )
                referenced_evidence.append(evidence_id)
                evidence_usage[evidence_id] = (
                    f"Supports the selected {binding.narrative_label}: "
                    f"{rationale}"
                )
            bound_sleeves.append(
                {
                    "symbol": binding.symbol,
                    "executor_id": binding.executor_id,
                    "evidence_ids": list(binding.evidence_ids),
                    "expected_return_rationale": rationale,
                    "parameters": selection.parameters.authored_mapping(),
                }
            )

        sanitized_rule = sanitized_payload["rule"]
        portfolio = proposal.rule.portfolio
        shared_payload = {
            "rule": {
                "strategy_name": sanitized_rule["strategy_name"],
                "hypothesis": sanitized_rule["hypothesis"],
                "rule_summary": sanitized_rule["rule_summary"],
                "executor_id": _PORTFOLIO_EXECUTOR_ID,
                "asset_eligibility_logic": sanitized_rule[
                    "asset_eligibility_logic"
                ],
                "signal_logic": sanitized_rule["signal_logic"],
                "position_logic": sanitized_rule["position_logic"],
                "entry_logic": sanitized_rule["entry_logic"],
                "exit_logic": sanitized_rule["exit_logic"],
                "rebalancing_logic": sanitized_rule["rebalancing_logic"],
                "parameters": {
                    "target_asset_count": TARGET_TECHNICAL_SLEEVES,
                    "selected_asset_count": len(bound_sleeves),
                    "portfolio_target_gross_weight": (
                        portfolio.portfolio_target_gross_weight
                    ),
                    "allocation_method": "equal_weight",
                    "selection_threshold": (
                        "positive_expected_return_from_training_evidence"
                    ),
                    "omission_rationale": sanitized_rule["portfolio"][
                        "omission_rationale"
                    ],
                    "common_risk_parameters": {},
                    "sleeves": bound_sleeves,
                },
                "specialty_evidence_ids": referenced_evidence,
                "specialty_evidence_usage": evidence_usage,
                "required_data_fields": sanitized_rule[
                    "required_data_fields"
                ],
                "constraint_handling": sanitized_rule[
                    "constraint_handling"
                ],
                "implementation_notes": sanitized_rule[
                    "implementation_notes"
                ],
            },
            "backtest_plan": {
                "frequency": "daily",
                "transaction_cost_assumptions": (
                    proposal.backtest_plan.transaction_cost_assumptions.model_dump(
                        mode="python"
                    )
                ),
            },
            "mandate_constraint_mapping": sanitized_payload[
                "mandate_constraint_mapping"
            ],
            "known_constraint_violations": sanitized_payload[
                "known_constraint_violations"
            ],
        }
        assert_no_opportunity_references(shared_payload)
        return CandidateProposalDraft.model_validate(shared_payload)

    def diagnostic_catalog(self) -> list[dict[str, Any]]:
        """Return the local-only ref-to-canonical audit mapping."""

        return [
            {
                "opportunity_ref": reference,
                "opportunity_id": binding.opportunity_id,
                "symbol": binding.symbol,
                "executor_id": binding.executor_id,
                "evidence_ids": list(binding.evidence_ids),
                "rank": binding.rank,
                "score": binding.score,
            }
            for reference, binding in self.opportunity_by_ref.items()
        ]

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


def build_opportunity_prompt_report(
    report: dict[str, Any],
    scope: CandidatePromptScope,
) -> dict[str, Any]:
    """Render atomic opportunity choices without exposing canonical IDs."""

    raw_assets = report.get("assets")
    raw_opportunities = report.get("horizon_opportunities")
    if not isinstance(raw_assets, list) or not isinstance(
        raw_opportunities, list
    ):
        raise ValueError(
            "Compacted Technical report must contain assets and opportunities."
        )

    evidence_by_id: dict[str, dict[str, Any]] = {}
    asset_context: list[dict[str, Any]] = []
    collection_specs = (
        ("support_resistance_levels", "level_id", "price_level"),
        ("chart_patterns", "pattern_id", "chart_pattern"),
        ("moving_averages", "moving_average_id", "moving_average"),
    )
    for raw_asset in raw_assets:
        if not isinstance(raw_asset, dict):
            continue
        symbol = str(raw_asset.get("symbol", "")).strip()
        for collection_name, identifier_name, evidence_kind in (
            collection_specs
        ):
            for item in raw_asset.get(collection_name, []):
                if not isinstance(item, dict):
                    continue
                identifier = str(item.get(identifier_name, "")).strip()
                if identifier:
                    evidence_by_id[identifier] = {
                        "evidence_kind": evidence_kind,
                        "symbol": symbol,
                        **{
                            key: value
                            for key, value in item.items()
                            if key != identifier_name
                        },
                    }
        volume = raw_asset.get("volume_observation")
        if isinstance(volume, dict):
            identifier = str(volume.get("volume_id", "")).strip()
            if identifier:
                evidence_by_id[identifier] = {
                    "evidence_kind": "volume_observation",
                    "symbol": symbol,
                    **{
                        key: value
                        for key, value in volume.items()
                        if key != "volume_id"
                    },
                }
        asset_context.append(
            {
                key: value
                for key, value in raw_asset.items()
                if key
                not in {
                    "artifact_id",
                    "support_resistance_levels",
                    "chart_patterns",
                    "moving_averages",
                    "moving_average",
                    "volume_observation",
                    "screening_evidence",
                }
            }
        )

    raw_opportunity_by_id = {
        str(item.get("opportunity_id", "")).strip(): item
        for item in raw_opportunities
        if isinstance(item, dict)
        and str(item.get("opportunity_id", "")).strip()
    }
    catalog: list[dict[str, Any]] = []
    for reference, binding in scope.opportunity_by_ref.items():
        raw = raw_opportunity_by_id.get(binding.opportunity_id)
        if raw is None:
            raise ValueError(
                f"Opportunity '{binding.opportunity_id}' is missing from "
                "the compacted report."
            )
        evidence_detail: list[dict[str, Any]] = []
        for evidence_id in binding.evidence_ids:
            detail = evidence_by_id.get(evidence_id)
            if detail is None:
                raise ValueError(
                    f"Opportunity '{binding.opportunity_id}' references "
                    f"unresolved evidence '{evidence_id}'."
                )
            evidence_detail.append(detail)
        catalog.append(
            {
                "opportunity_ref": reference,
                "symbol": binding.symbol,
                "executor_id": binding.executor_id,
                "rank": binding.rank,
                "score": binding.score,
                "score_components": raw.get("score_components", {}),
                "horizon_trading_days": raw.get(
                    "horizon_trading_days"
                ),
                "rationale": raw.get("rationale"),
                "evidence_detail": evidence_detail,
                "additional_fields": raw.get("additional_fields", {}),
            }
        )

    return {
        "generated_by": report.get("generated_by"),
        "toolkit_version": report.get("toolkit_version"),
        "as_of_date": report.get("as_of_date"),
        "horizon_context": report.get("horizon_context"),
        "asset_context": asset_context,
        "opportunity_catalog": catalog,
        "prompt_screening_summary": report.get(
            "prompt_screening_summary", {}
        ),
        "warnings": report.get("warnings", []),
        "opportunity_reference_contract": {
            "format": "O followed by at least three digits",
            "allowed_references": list(scope.opportunity_by_ref),
            "instruction": (
                "Select opportunity_ref values exactly. Code binds symbol, "
                "executor, evidence IDs, rank, score, and opportunity ID."
            ),
        },
    }


def _replace_opportunity_tokens(
    value: Any,
    labels: Mapping[str, str],
) -> Any:
    if isinstance(value, str):
        result = value
        for reference, label in labels.items():
            result = re.sub(
                rf"\b{re.escape(reference)}\b",
                label,
                result,
                flags=re.IGNORECASE,
            )
        unknown = sorted(set(_OPPORTUNITY_REF_PATTERN.findall(result)))
        if unknown:
            raise ValueError(
                "Candidate narrative contains unknown opportunity "
                "references: " + ", ".join(unknown)
            )
        return result
    if isinstance(value, list):
        return [_replace_opportunity_tokens(item, labels) for item in value]
    if isinstance(value, tuple):
        return tuple(
            _replace_opportunity_tokens(item, labels) for item in value
        )
    if isinstance(value, dict):
        return {
            key: (
                item
                if key == "opportunity_ref"
                else _replace_opportunity_tokens(item, labels)
            )
            for key, item in value.items()
        }
    return value


def assert_no_opportunity_references(value: Any) -> None:
    """Reject prompt-local O### tokens at the canonical package boundary."""

    if isinstance(value, str):
        match = _OPPORTUNITY_REF_PATTERN.search(value)
        if match is not None:
            raise ValueError(
                "Prompt-local opportunity reference escaped canonical "
                f"expansion: {match.group(0)}"
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            assert_no_opportunity_references(str(key))
            assert_no_opportunity_references(item)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            assert_no_opportunity_references(item)


def redact_opportunity_references(value: str) -> str:
    """Remove prompt-local aliases from text entering shared artifacts."""

    return _OPPORTUNITY_REF_PATTERN.sub(
        "[prompt-local opportunity reference]",
        value,
    )


__all__ = [
    "CandidatePromptScope",
    "DEFAULT_CANDIDATE_PROMPT_ASSETS",
    "MAX_CANDIDATE_PROMPT_ASSETS",
    "MIN_CANDIDATE_PROMPT_ASSETS",
    "OpportunityBinding",
    "assert_no_opportunity_references",
    "build_opportunity_prompt_report",
    "compact_horizon_technical_report",
    "redact_opportunity_references",
]
