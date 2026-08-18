"""Quant Trader: proposes cross-asset statistical strategies, never scores them.

Pipeline for one ``run(TraderTask)`` call:

  1. Request point-in-time price data for the permitted universe from the
     injected ``DataService``.
  2. Resolve the code-owned train/test ``ValidationSplit`` *before* looking
     for a strategy, and restrict discovery to bars strictly before the
     held-out test window - the anti-look-ahead guarantee.
  3. Run the statistical pair scan in ``discovery.py`` to find and rank
     candidate cross-asset mean-reversion pairs.
  4. Package the strongest candidate as a ``CandidateRuleSpecification``
     bound to the registered ``strategy.py`` executor.
  5. Hand it to the injected ``BacktestEngine`` - Quant Trader never
     computes its own performance numbers.
  6. Interpret the settled result and assemble a ``TraderStrategyPackage``.

Any stage that fails returns a settled (non-eligible) package rather than
raising, per ``TraderAgent``'s contract: ordinary failures are data, not
exceptions.
"""

from __future__ import annotations

import asyncio
from typing import Any

from protocols import (
    BacktestPlan,
    BacktestPlanDraft,
    BacktestRequest,
    BacktestStatus,
    CandidateRuleDraft,
    CandidateRuleSpecification,
    ConstraintCheckStatus,
    DataCategory,
    DataFieldRequirement,
    DataRequest,
    DataUsageSummary,
    MandateConstraintAssessment,
    RunStatus,
    SpecialistId,
    TraderFailure,
    TraderStrategyPackage,
    TraderTask,
)

from .data_adapter import extract_price_panel
from .discovery import ProposedPair, propose_pairs
from .errors import MandateValidationError
from .interpretation import build_interpretation
from .services import BacktestEngine, DataService, ValidationSplitPolicy
from .strategy import CROSS_ASSET_SPREAD_EXECUTOR_ID

DEFAULT_TRADER_TIMEOUT_SECONDS = 120.0
DEFAULT_PROPOSAL_COUNT = 3


class QuantTraderAgent:
    """Concrete implementation of ``agents.base.TraderAgent`` for Quant Trader."""

    trader_id = SpecialistId.QUANT_TRADER

    def __init__(
        self,
        *,
        data_service: DataService,
        backtest_engine: BacktestEngine,
        validation_split_policy: ValidationSplitPolicy,
        top_n_candidates: int = DEFAULT_PROPOSAL_COUNT,
        trader_timeout_seconds: float = DEFAULT_TRADER_TIMEOUT_SECONDS,
    ) -> None:
        self._data_service = data_service
        self._backtest_engine = backtest_engine
        self._validation_split_policy = validation_split_policy
        self._top_n_candidates = top_n_candidates
        self._trader_timeout_seconds = trader_timeout_seconds

    async def run(self, request: TraderTask) -> TraderStrategyPackage:
        try:
            async with asyncio.timeout(self._trader_timeout_seconds):
                return await self._run(request)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return self._failed_package(
                request,
                stage="quant_trader.runtime",
                message=(
                    "Quant Trader exceeded its configured "
                    f"{self._trader_timeout_seconds:g}-second deadline."
                ),
                retryable=True,
            )

    async def _run(self, task: TraderTask) -> TraderStrategyPackage:
        mandate = task.mandate

        data_request = self._build_data_request(task)
        try:
            data_response = await self._data_service.fetch(data_request)
        except Exception as exc:  # noqa: BLE001 - normalized into a settled package
            return self._failed_package(
                task,
                stage="quant_trader.data_service",
                message=f"DataService.fetch failed: {type(exc).__name__}: {exc}",
                retryable=True,
                data_request=data_request,
            )

        panel = extract_price_panel(data_response)
        if not panel:
            return self._failed_package(
                task,
                stage="quant_trader.data_service",
                message="DataService returned no usable PRICE_VOLUME artifacts.",
                retryable=True,
                data_request=data_request,
                data_response=data_response,
            )

        plan_draft = BacktestPlanDraft(
            requested_end_date=mandate.as_of_date,
            frequency="daily",
            requested_metrics=[
                "total_return", "annualized_return", "max_drawdown",
                "sharpe_ratio", "transaction_count",
            ],
            validation_requirements=["held_out_out_of_sample_test"],
            held_out_evaluation_required=True,
        )
        try:
            split = self._validation_split_policy.resolve(
                task=task, plan=plan_draft, data_response=data_response,
            )
        except Exception as exc:  # noqa: BLE001
            return self._failed_package(
                task,
                stage="quant_trader.validation_split",
                message=f"ValidationSplitPolicy.resolve failed: {type(exc).__name__}: {exc}",
                retryable=False,
                data_request=data_request,
                data_response=data_response,
            )

        train_panel = {
            symbol: tuple(
                bar for bar in bars if bar.timestamp.date() < split.test_start_date
            )
            for symbol, bars in panel.items()
        }
        train_panel = {symbol: bars for symbol, bars in train_panel.items() if bars}

        permitted_symbols = (
            mandate.permitted_asset_universe
            if isinstance(mandate.permitted_asset_universe, list)
            and mandate.permitted_asset_universe
            else None
        )
        proposals = propose_pairs(
            train_panel,
            permitted_symbols=permitted_symbols,
            top_n=self._top_n_candidates,
        )
        if not proposals:
            return self._failed_package(
                task,
                stage="quant_trader.discovery",
                message=(
                    "No statistically significant, mean-reverting pair was "
                    "found in the permitted universe during the training "
                    "window."
                ),
                retryable=False,
                data_request=data_request,
                data_response=data_response,
            )

        best = proposals[0]
        violation = self._check_prohibited_assets(best, mandate)
        if violation is not None:
            return self._failed_package(
                task,
                stage="quant_trader.constraints",
                message=violation,
                retryable=False,
                data_request=data_request,
                data_response=data_response,
                status=RunStatus.PARTIAL,
                constraint_status=ConstraintCheckStatus.VIOLATION_IDENTIFIED,
                constraint_violations=[violation],
            )

        candidate_spec = self._build_candidate(task, best)
        # Declare a buy-and-hold benchmark on ticker_a now that it's known -
        # a same-terms baseline (identical period, universe, cost
        # assumptions) for Risk's CP-6 check to compare against. Was
        # previously omitted, which caused every Quant Trader candidate to
        # be vetoed on CP-6 during full-loop integration testing. Identical
        # fix already applied to Fundamental Trader's agent.py - flagging
        # for Shaurya's review since this file isn't Aditi's to own, but
        # left unfixed it silently blocks every Quant Trader result from
        # ever reaching Reporting. See docs/fundamental_trader.md.
        plan_draft = plan_draft.model_copy(update={"benchmark": best.ticker_a})
        plan = BacktestPlan.from_draft(plan_draft, validation_split=split)
        backtest_request = BacktestRequest(
            request_id=f"{task.lineage.task_id}.backtest",
            trader_id=SpecialistId.QUANT_TRADER,
            lineage=task.lineage.child("backtest"),
            execution_context=task.execution_context,
            as_of_date=mandate.as_of_date,
            candidate=candidate_spec,
            plan=plan,
            data_references=[
                artifact.data_reference for artifact in data_response.artifacts
            ] or [data_response.response_id],
            mandate_constraints={
                "prohibited_assets": list(mandate.prohibited_assets),
                "permitted_asset_universe": mandate.permitted_asset_universe,
            },
        )

        try:
            backtest_result = await self._backtest_engine.run(backtest_request)
        except Exception as exc:  # noqa: BLE001
            return self._failed_package(
                task,
                stage="quant_trader.backtest_engine",
                message=f"BacktestEngine.run failed: {type(exc).__name__}: {exc}",
                retryable=True,
                data_request=data_request,
                data_response=data_response,
                candidate_rule=candidate_spec,
                backtest_request=backtest_request,
            )

        data_usage = DataUsageSummary.from_response(data_response)
        constraint_assessment = MandateConstraintAssessment(
            status=ConstraintCheckStatus.DECLARED_ALIGNED,
            mappings=[
                f"Long-only single-pair exposure ({best.ticker_a}/{best.ticker_b}) "
                "stays within a one-position-at-a-time risk footprint suitable "
                "for a research-stage mandate.",
            ],
            requires_risk_validation=True,
        )

        if backtest_result.status is not BacktestStatus.SUCCEEDED:
            return TraderStrategyPackage(
                package_id=f"{task.lineage.task_id}.package",
                candidate_id=candidate_spec.candidate_id,
                trader_id=SpecialistId.QUANT_TRADER,
                lineage=task.lineage,
                mandate_reference=mandate.reference(),
                status=RunStatus.FAILED,
                hypothesis=self._hypothesis(best),
                data_request=data_request,
                data_usage=data_usage,
                specialty_evidence=self._evidence_payload(best),
                candidate_rule=candidate_spec,
                backtest_request=backtest_request,
                backtest_result=backtest_result,
                constraint_assessment=constraint_assessment,
                failures=[
                    TraderFailure(
                        stage="quant_trader.backtest_engine",
                        message=(
                            backtest_result.failure_reason
                            or f"Backtest engine reported status "
                            f"{backtest_result.status.value}."
                        ),
                        retryable=True,
                    )
                ],
                eligible_for_risk_review=False,
            )

        interpretation = build_interpretation(best, backtest_result)

        return TraderStrategyPackage(
            package_id=f"{task.lineage.task_id}.package",
            candidate_id=candidate_spec.candidate_id,
            trader_id=SpecialistId.QUANT_TRADER,
            lineage=task.lineage,
            mandate_reference=mandate.reference(),
            status=RunStatus.COMPLETED,
            hypothesis=self._hypothesis(best),
            data_request=data_request,
            data_usage=data_usage,
            specialty_evidence=self._evidence_payload(best),
            candidate_rule=candidate_spec,
            backtest_request=backtest_request,
            backtest_result=backtest_result,
            interpretation=interpretation,
            constraint_assessment=constraint_assessment,
            eligible_for_risk_review=True,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_data_request(self, task: TraderTask) -> DataRequest:
        mandate = task.mandate
        return DataRequest(
            request_id=f"{task.lineage.task_id}.data",
            lineage=task.lineage.child("data"),
            trader_id=SpecialistId.QUANT_TRADER,
            as_of_date=mandate.as_of_date,
            purpose=(
                "Cross-asset correlation and mean-reversion pair discovery "
                "for the Quant Trader lens."
            ),
            asset_universe=mandate.permitted_asset_universe,
            categories=[DataCategory.PRICE_VOLUME],
            fields=[
                DataFieldRequirement(
                    name="close",
                    purpose="Daily close prices for correlation and spread analysis.",
                    required=True,
                    point_in_time_required=True,
                ),
            ],
            end_date=mandate.as_of_date,
            frequency="daily",
            provenance_required=True,
        )

    @staticmethod
    def _hypothesis(proposal: ProposedPair) -> str:
        return (
            f"{proposal.ticker_a} is statistically likely to converge back "
            f"toward its historical price relationship with {proposal.ticker_b} "
            "after diverging by an unusual amount."
        )

    @staticmethod
    def _evidence_payload(proposal: ProposedPair) -> dict[str, Any]:
        evidence = proposal.evidence
        return {
            "ticker_a": evidence.ticker_a,
            "ticker_b": evidence.ticker_b,
            "correlation": evidence.correlation,
            "half_life_days": evidence.half_life_days,
            "shared_trading_days": evidence.shared_trading_days,
            "score": evidence.score,
        }

    @staticmethod
    def _check_prohibited_assets(proposal: ProposedPair, mandate: Any) -> str | None:
        prohibited = {item.casefold() for item in mandate.prohibited_assets}
        hit = [
            symbol for symbol in (proposal.ticker_a, proposal.ticker_b)
            if symbol.casefold() in prohibited
        ]
        if hit:
            return (
                "Proposed pair references a prohibited asset under this "
                f"mandate: {', '.join(hit)}."
            )
        return None

    def _build_candidate(
        self, task: TraderTask, proposal: ProposedPair,
    ) -> CandidateRuleSpecification:
        evidence_id = (
            f"quant_trader.pair_scan.{proposal.ticker_a}_{proposal.ticker_b}"
        )
        draft = CandidateRuleDraft(
            strategy_name=(
                f"Cross-asset spread mean reversion: "
                f"{proposal.ticker_a}/{proposal.ticker_b}"
            ),
            hypothesis=self._hypothesis(proposal),
            rule_summary=(
                f"Trade the {proposal.ticker_a}/{proposal.ticker_b} price "
                f"ratio: go long {proposal.ticker_a} when its z-score versus "
                f"{proposal.ticker_b} falls to -{proposal.entry_zscore}, exit "
                f"back to cash once it recovers to -{proposal.exit_zscore}."
            ),
            executor_id=CROSS_ASSET_SPREAD_EXECUTOR_ID,
            asset_eligibility_logic=(
                f"Requires point-in-time history for both {proposal.ticker_a} "
                f"and {proposal.ticker_b} covering at least "
                f"{proposal.lookback_days} trading days at every rebalance."
            ),
            signal_logic=(
                f"Daily z-score of the {proposal.ticker_a}/{proposal.ticker_b} "
                f"closing-price ratio over a trailing {proposal.lookback_days}"
                "-day rolling window."
            ),
            position_logic=(
                "Single position: fully allocate to the long leg when in the "
                "trade, fully in cash otherwise. No shorting; max gross "
                "leverage 1.0x."
            ),
            entry_logic=(
                f"Enter when the ratio z-score falls to or below "
                f"-{proposal.entry_zscore}."
            ),
            exit_logic=(
                f"Exit when the ratio z-score rises back to or above "
                f"-{proposal.exit_zscore}."
            ),
            rebalancing_logic=(
                "Rebalances only when the entry/exit condition changes; "
                "otherwise holds the current position unchanged."
            ),
            parameters=proposal.as_strategy_parameters(),
            specialty_evidence_ids=[evidence_id],
            specialty_evidence_usage={
                evidence_id: (
                    "Correlation and AR(1) mean-reversion half-life evidence "
                    "used to select this pair and size its lookback window."
                ),
            },
            required_data_fields=["close"],
            constraint_handling=[
                "Long-only, single-pair, unlevered - stays within a "
                "research-stage mandate's default risk footprint.",
            ],
            implementation_notes=[proposal.rationale],
        )
        return CandidateRuleSpecification(
            **draft.model_dump(mode="python"),
            candidate_id=f"{task.lineage.task_id}.candidate",
            trader_id=SpecialistId.QUANT_TRADER,
            lineage=task.lineage.child("candidate"),
        )

    def _failed_package(
        self,
        task: TraderTask,
        *,
        stage: str,
        message: str,
        retryable: bool,
        status: RunStatus = RunStatus.FAILED,
        data_request: DataRequest | None = None,
        data_response: Any | None = None,
        candidate_rule: CandidateRuleSpecification | None = None,
        backtest_request: BacktestRequest | None = None,
        constraint_status: ConstraintCheckStatus = ConstraintCheckStatus.NOT_EVALUATED,
        constraint_violations: list[str] | None = None,
    ) -> TraderStrategyPackage:
        return TraderStrategyPackage(
            package_id=f"{task.lineage.task_id}.package",
            candidate_id=candidate_rule.candidate_id if candidate_rule else None,
            trader_id=SpecialistId.QUANT_TRADER,
            lineage=task.lineage,
            mandate_reference=task.mandate.reference(),
            status=status,
            data_request=data_request,
            data_usage=(
                DataUsageSummary.from_response(data_response)
                if data_response is not None
                else None
            ),
            candidate_rule=candidate_rule,
            backtest_request=backtest_request,
            constraint_assessment=MandateConstraintAssessment(
                status=constraint_status,
                violations=constraint_violations or [],
                requires_risk_validation=False,
            ),
            failures=[
                TraderFailure(stage=stage, message=message, retryable=retryable),
            ],
            eligible_for_risk_review=False,
        )


__all__ = ["QuantTraderAgent"]
