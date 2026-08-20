"""Fundamental Trader: proposes ETF category-benchmark deviation strategies,
never scores them.

Pipeline for one ``run(TraderTask)`` call:

  1. Request point-in-time price data AND ETF metadata (category, fund
     family) for the permitted universe from the injected ``DataService``
     in a single fetch.
  2. Resolve the code-owned train/test ``ValidationSplit`` *before* looking
     for a strategy, and restrict discovery to bars strictly before the
     held-out test window - the anti-look-ahead guarantee.
  3. Run the category-benchmark deviation scan in ``rule_generator.py`` to
     find and rank candidate boutique-tier tickers against their major-tier
     category peers.
  4. Package the strongest candidate as a ``CandidateRuleSpecification``
     bound to the registered ``strategy.py`` executor.
  5. Hand it to the injected ``BacktestEngine`` - Fundamental Trader never
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

from mandate_directives import resolve_mandate_directives

from .data_adapter import extract_fundamental_panel, extract_price_panel
from .errors import MandateValidationError
from .interpretation import build_interpretation
from .rule_generator import (
    DEFAULT_ENTRY_ZSCORE,
    DEFAULT_EXIT_ZSCORE,
    ProposedCategoryDeviation,
    propose_category_deviations,
)
from .services import BacktestEngine, DataService, ValidationSplitPolicy
from .strategy import CATEGORY_DEVIATION_EXECUTOR_ID

DEFAULT_TRADER_TIMEOUT_SECONDS = 120.0
DEFAULT_PROPOSAL_COUNT = 3


class FundamentalTraderAgent:
    """Concrete implementation of ``agents.base.TraderAgent`` for Fundamental Trader."""

    trader_id = SpecialistId.FUNDAMENTAL_TRADER

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
                stage="fundamental_trader.runtime",
                message=(
                    "Fundamental Trader exceeded its configured "
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
                stage="fundamental_trader.data_service",
                message=f"DataService.fetch failed: {type(exc).__name__}: {exc}",
                retryable=True,
                data_request=data_request,
            )

        price_panel = extract_price_panel(data_response)
        fundamental_panel = extract_fundamental_panel(data_response)
        if not price_panel or not fundamental_panel:
            return self._failed_package(
                task,
                stage="fundamental_trader.data_service",
                message=(
                    "DataService returned no usable PRICE_VOLUME and/or "
                    "ETF_METADATA artifacts."
                ),
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
                stage="fundamental_trader.validation_split",
                message=f"ValidationSplitPolicy.resolve failed: {type(exc).__name__}: {exc}",
                retryable=False,
                data_request=data_request,
                data_response=data_response,
            )

        train_panel = {
            symbol: tuple(
                bar for bar in bars if bar.timestamp.date() < split.test_start_date
            )
            for symbol, bars in price_panel.items()
        }
        train_panel = {symbol: bars for symbol, bars in train_panel.items() if bars}

        permitted_symbols = (
            mandate.permitted_asset_universe
            if isinstance(mandate.permitted_asset_universe, list)
            and mandate.permitted_asset_universe
            else None
        )

        # Resolve non-universe mandate fields (risk_profile, investment_horizon,
        # rebalancing_preference, risk_limits, leverage/short constraints,
        # market_context, pm_notes, prior_round_lessons) into concrete
        # parameters - see mandate_directives.py for exactly what each field
        # does and why. Previously none of these had any effect.
        directives = resolve_mandate_directives(
            mandate,
            agent_id=str(SpecialistId.FUNDAMENTAL_TRADER.value),
            permitted_symbols=permitted_symbols,
        )
        if directives.constraint_violations:
            violation_text = "; ".join(directives.constraint_violations)
            return self._failed_package(
                task,
                stage="fundamental_trader.constraints",
                message=violation_text,
                retryable=False,
                data_request=data_request,
                data_response=data_response,
                status=RunStatus.PARTIAL,
                constraint_status=ConstraintCheckStatus.VIOLATION_IDENTIFIED,
                constraint_violations=list(directives.constraint_violations),
            )

        proposals = propose_category_deviations(
            train_panel,
            fundamental_panel,
            permitted_symbols=permitted_symbols,
            excluded_tickers=directives.excluded_tickers,
            top_n=self._top_n_candidates,
            entry_zscore=DEFAULT_ENTRY_ZSCORE * directives.entry_zscore_multiplier,
            exit_zscore=DEFAULT_EXIT_ZSCORE * directives.exit_zscore_multiplier,
            preferred_lookback_days=directives.preferred_lookback_days,
        )
        if not proposals:
            return self._failed_package(
                task,
                stage="fundamental_trader.discovery",
                message=(
                    "No boutique-tier ticker with a sufficiently significant "
                    "category-benchmark deviation was found in the permitted "
                    "universe during the training window."
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
                stage="fundamental_trader.constraints",
                message=violation,
                retryable=False,
                data_request=data_request,
                data_response=data_response,
                status=RunStatus.PARTIAL,
                constraint_status=ConstraintCheckStatus.VIOLATION_IDENTIFIED,
                constraint_violations=[violation],
            )

        candidate_spec = self._build_candidate(task, best, directives.applied_notes)
        # Declare a buy-and-hold benchmark on the traded ticker itself now
        # that it's known - a same-terms baseline (identical period,
        # universe, cost assumptions) for Risk's CP-6 check to compare
        # against. Was previously omitted, which caused every candidate to
        # be vetoed on CP-6 during full-loop integration testing - see
        # docs/fundamental_trader.md.
        plan_draft = plan_draft.model_copy(update={"benchmark": best.ticker})
        plan = BacktestPlan.from_draft(plan_draft, validation_split=split)
        backtest_request = BacktestRequest(
            request_id=f"{task.lineage.task_id}.backtest",
            trader_id=SpecialistId.FUNDAMENTAL_TRADER,
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
                stage="fundamental_trader.backtest_engine",
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
                f"Long-only single-ticker exposure ({best.ticker}) stays "
                "within a one-position-at-a-time risk footprint suitable "
                "for a research-stage mandate.",
            ],
            requires_risk_validation=True,
        )

        if backtest_result.status is not BacktestStatus.SUCCEEDED:
            return TraderStrategyPackage(
                package_id=f"{task.lineage.task_id}.package",
                candidate_id=candidate_spec.candidate_id,
                trader_id=SpecialistId.FUNDAMENTAL_TRADER,
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
                        stage="fundamental_trader.backtest_engine",
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

        if directives.max_drawdown_limit is not None:
            observed_drawdown = backtest_result.metrics.get("max_drawdown")
            if isinstance(observed_drawdown, (int, float)) and abs(observed_drawdown) > directives.max_drawdown_limit:
                return TraderStrategyPackage(
                    package_id=f"{task.lineage.task_id}.package",
                    candidate_id=candidate_spec.candidate_id,
                    trader_id=SpecialistId.FUNDAMENTAL_TRADER,
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
                    constraint_assessment=MandateConstraintAssessment(
                        status=ConstraintCheckStatus.VIOLATION_IDENTIFIED,
                        violations=[
                            f"Observed max drawdown {observed_drawdown:.1%} breaches the "
                            f"mandate's risk_limits.max_drawdown of {directives.max_drawdown_limit:.1%}."
                        ],
                        requires_risk_validation=False,
                    ),
                    failures=[
                        TraderFailure(
                            stage="fundamental_trader.risk_limits",
                            message=(
                                f"Candidate {best.ticker} breached the mandate's stated "
                                f"max drawdown limit ({directives.max_drawdown_limit:.1%}); "
                                "not proposed for Risk review this round. Only the top-ranked "
                                "candidate is screened - a lower-ranked, compliant candidate "
                                "is not automatically retried this round."
                            ),
                            retryable=False,
                        )
                    ],
                    eligible_for_risk_review=False,
                )

        interpretation = build_interpretation(best, backtest_result)

        return TraderStrategyPackage(
            package_id=f"{task.lineage.task_id}.package",
            candidate_id=candidate_spec.candidate_id,
            trader_id=SpecialistId.FUNDAMENTAL_TRADER,
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
            trader_id=SpecialistId.FUNDAMENTAL_TRADER,
            as_of_date=mandate.as_of_date,
            purpose=(
                "Category-benchmark deviation discovery for the Fundamental "
                "Trader lens: price history for backtesting plus ETF "
                "category/fund-family metadata for the ISSUER_SCALE_TIER "
                "heuristic."
            ),
            asset_universe=mandate.permitted_asset_universe,
            categories=[DataCategory.PRICE_VOLUME, DataCategory.ETF_METADATA],
            fields=[
                DataFieldRequirement(
                    name="close",
                    purpose="Daily close prices for return/spread analysis.",
                    required=True,
                    point_in_time_required=True,
                ),
                DataFieldRequirement(
                    name="category",
                    purpose="Groups ETFs into comparable exposure sets.",
                    required=True,
                    point_in_time_required=False,
                ),
                DataFieldRequirement(
                    name="fund_family",
                    purpose="Drives the ISSUER_SCALE_TIER major/boutique split.",
                    required=True,
                    point_in_time_required=False,
                ),
            ],
            end_date=mandate.as_of_date,
            frequency="daily",
            provenance_required=True,
        )

    @staticmethod
    def _hypothesis(proposal: ProposedCategoryDeviation) -> str:
        return (
            f"{proposal.ticker} is statistically likely to converge back "
            f"toward the return of its \"{proposal.category}\" category's "
            "major-issuer peers after diverging by an unusual amount."
        )

    @staticmethod
    def _evidence_payload(proposal: ProposedCategoryDeviation) -> dict[str, Any]:
        evidence = proposal.evidence
        return {
            "ticker": evidence.ticker,
            "category": evidence.category,
            "fund_family": evidence.fund_family,
            "benchmark_tickers": list(evidence.benchmark_tickers),
            "correlation": evidence.correlation,
            "current_zscore": evidence.current_zscore,
            "shared_trading_days": evidence.shared_trading_days,
            "score": evidence.score,
        }

    @staticmethod
    def _check_prohibited_assets(
        proposal: ProposedCategoryDeviation, mandate: Any,
    ) -> str | None:
        prohibited = {item.casefold() for item in mandate.prohibited_assets}
        hit = [
            symbol for symbol in (proposal.ticker, *proposal.benchmark_tickers)
            if symbol.casefold() in prohibited
        ]
        if hit:
            return (
                "Proposed candidate references a prohibited asset under this "
                f"mandate: {', '.join(hit)}."
            )
        return None

    def _build_candidate(
        self,
        task: TraderTask,
        proposal: ProposedCategoryDeviation,
        directive_notes: tuple[str, ...] = (),
    ) -> CandidateRuleSpecification:
        evidence_id = f"fundamental_trader.category_scan.{proposal.ticker}"
        draft = CandidateRuleDraft(
            strategy_name=(
                f"Category-benchmark deviation: {proposal.ticker} vs. "
                f"\"{proposal.category}\" major-tier peers"
            ),
            hypothesis=self._hypothesis(proposal),
            rule_summary=(
                f"Trade {proposal.ticker} against the equal-weight return of "
                f"its category's major-tier peers "
                f"({', '.join(proposal.benchmark_tickers)}): go long "
                f"{proposal.ticker} when its z-score deviation falls to "
                f"-{proposal.entry_zscore}, exit back to cash once it "
                f"recovers to -{proposal.exit_zscore}."
            ),
            executor_id=CATEGORY_DEVIATION_EXECUTOR_ID,
            asset_eligibility_logic=(
                f"Requires point-in-time history for {proposal.ticker} and "
                f"all of {', '.join(proposal.benchmark_tickers)} covering at "
                f"least {proposal.lookback_days} trading days at every "
                "rebalance."
            ),
            signal_logic=(
                f"Daily z-score of the return spread between {proposal.ticker} "
                "and the equal-weight return of its major-tier category "
                f"peers, over a trailing {proposal.lookback_days}-day rolling "
                "window."
            ),
            position_logic=(
                "Single position: fully allocate to the long leg when in the "
                "trade, fully in cash otherwise. No shorting; max gross "
                "leverage 1.0x."
            ),
            entry_logic=(
                f"Enter when the spread z-score falls to or below "
                f"-{proposal.entry_zscore}."
            ),
            exit_logic=(
                f"Exit when the spread z-score rises back to or above "
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
                    "Category-benchmark correlation and deviation z-score "
                    "evidence used to select this ticker and its lookback "
                    "window."
                ),
            },
            required_data_fields=["close", "category", "fund_family"],
            constraint_handling=[
                "Long-only, single-ticker, unlevered - stays within a "
                "research-stage mandate's default risk footprint.",
            ],
            implementation_notes=[
                proposal.rationale,
                "Category benchmark is an in-house equal-weight average of "
                "major-tier issuer peers in the same ETF_info.xlsx category, "
                "not a licensed index.",
                "ISSUER_SCALE_TIER (major vs. boutique fund family) "
                "substitutes for expense ratio / dividend yield / NAV "
                "premium-discount, which are not populated in this fixture.",
                *directive_notes,
            ],
        )
        return CandidateRuleSpecification(
            **draft.model_dump(mode="python"),
            candidate_id=f"{task.lineage.task_id}.candidate",
            trader_id=SpecialistId.FUNDAMENTAL_TRADER,
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
            trader_id=SpecialistId.FUNDAMENTAL_TRADER,
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


__all__ = ["FundamentalTraderAgent"]
