"""Shared builders for Risk-agent tests.

Packages are constructed the way the trader join delivers them: settled,
risk-eligible, and carrying the engine's own run-ledger entry. Keeping the
builders faithful to :mod:`tools.backtest_engine` output matters — a fixture
that omits fields the real engine writes hides real defects.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from agents.technical_trader.model_client import (
    ModelCallResult,
    ModelRequestContext,
    ModelUsage,
)
from protocols import (
    BacktestPlan,
    BacktestRequest,
    BacktestResult,
    BacktestRunLedgerEntry,
    BacktestStatus,
    CandidateRuleSpecification,
    ConfidenceAssessment,
    MandateReference,
    ResearchExecutionContext,
    RiskReviewRequest,
    RunStatus,
    SpecialistId,
    TaskLineage,
    TraderStrategyPackage,
)
from protocols.backtest import ValidationSplit
from protocols.common import ConfidenceLevel
from protocols.trader import (
    BacktestInterpretationDraft,
    ConstraintCheckStatus,
    MandateConstraintAssessment,
)


AS_OF = date(2020, 12, 31)
WORKFLOW_ID = "wf-1"
MANDATE_TASK_ID = "mandate-1"
RUN_ID = "run-1"

CLEAN_METRICS: dict[str, float | int | None] = {
    "total_return": 0.42,
    "annualized_return": 0.08,
    "max_drawdown": -0.15,
    "annualized_volatility": 0.12,
    "sharpe_ratio": 0.9,
}
DEFAULT_RESOLVED_END = datetime(2020, 12, 30, 21, tzinfo=timezone.utc)


def lineage_for(candidate_id: str, *, round_number: int = 1) -> TaskLineage:
    return TaskLineage(
        workflow_id=WORKFLOW_ID,
        task_id=f"{MANDATE_TASK_ID}.round-{round_number}.{candidate_id}",
        parent_task_id=MANDATE_TASK_ID,
        source_task_id=MANDATE_TASK_ID,
    )


def ledger_entry(
    *,
    candidate_id: str,
    trader_id: SpecialistId,
    parameters: Mapping[str, Any],
    strategy_name: str,
    metrics: Mapping[str, float | int | None],
    resolved_end: datetime = DEFAULT_RESOLVED_END,
    suffix: str = "",
    validation_split_end: date = AS_OF,
    round_number: int = 1,
) -> BacktestRunLedgerEntry:
    """Mirror the fields :class:`DeterministicBacktestEngine` records."""

    identity = f"{candidate_id}{suffix}"
    return BacktestRunLedgerEntry(
        additional_fields={
            "as_of_date": AS_OF,
            "held_out_evaluation_required": True,
            "validation_split": {
                "test_start_date": date(2018, 1, 1),
                "test_end_date": validation_split_end,
            },
        },
        ledger_entry_id=f"{identity}.ledger",
        recorded_at=datetime(2020, 12, 31, 21, tzinfo=timezone.utc),
        run_id=f"{identity}.attempt-1",
        workflow_run_id=RUN_ID,
        workflow_id=WORKFLOW_ID,
        round_number=round_number,
        task_id=f"{MANDATE_TASK_ID}.round-{round_number}.{candidate_id}",
        attempt=1,
        request_id=f"{identity}.bt",
        result_id=f"{identity}.result",
        trader_id=trader_id,
        candidate_id=candidate_id,
        strategy_name=strategy_name,
        executor_id="mean_reversion_v1",
        parameters=dict(parameters),
        resolved_symbols=["QQQ", "SPY"],
        status=BacktestStatus.SUCCEEDED,
        metrics=dict(metrics),
        out_of_sample_metrics=dict(metrics),
        benchmark_metrics=dict(metrics),
        resolved_start_time=datetime(2010, 1, 4, 21, tzinfo=timezone.utc),
        resolved_end_time=resolved_end,
    )


def build_package(
    *,
    candidate_id: str,
    trader_id: SpecialistId,
    parameters: Mapping[str, Any] | None = None,
    metrics: Mapping[str, float | int | None] | None = None,
    benchmark: str | None = "SPY",
    benchmark_metrics: Mapping[str, float | int | None] | None = None,
    additional_fields: Mapping[str, Any] | None = None,
    extra_evidence_ids: Sequence[str] = (),
    ledger_resolved_end: datetime | None = None,
    strategy_name: str | None = None,
    validation_split_end: date = AS_OF,
    round_number: int = 1,
) -> TraderStrategyPackage:
    """Build one risk-eligible settled package as the trader join would."""

    parameters = dict(parameters or {"lookback": 20, "z_entry": 1.5})
    metrics = dict(metrics or CLEAN_METRICS)
    strategy_name = strategy_name or f"{candidate_id}-mean-reversion"
    lineage = lineage_for(candidate_id, round_number=round_number)
    evidence_ids = [f"{candidate_id}.evidence", *extra_evidence_ids]
    rule = CandidateRuleSpecification(
        candidate_id=candidate_id,
        trader_id=trader_id,
        lineage=lineage,
        strategy_name=strategy_name,
        hypothesis="Short-term dislocations revert to the rolling mean.",
        rule_summary="Enter on z-score extremes; exit at the mean.",
        executor_id="mean_reversion_v1",
        asset_eligibility_logic="Index ETFs in the canonical universe.",
        signal_logic="Rolling z-score of close versus lookback mean.",
        position_logic="Equal-weight open signals.",
        entry_logic="z below -z_entry.",
        exit_logic="z reverts through zero.",
        rebalancing_logic="Daily at next open.",
        parameters=parameters,
        specialty_evidence_ids=evidence_ids,
        specialty_evidence_usage={
            evidence_id: "Supports the reversion signal construction."
            for evidence_id in evidence_ids
        },
    )
    plan = BacktestPlan(
        requested_start_date=date(2010, 1, 1),
        requested_end_date=AS_OF,
        frequency="daily",
        benchmark=benchmark,
        held_out_evaluation_required=True,
        validation_split=ValidationSplit(
            test_start_date=date(2018, 1, 1),
            test_end_date=AS_OF,
        ),
    )
    request = BacktestRequest(
        request_id=f"{candidate_id}.bt",
        trader_id=trader_id,
        lineage=lineage,
        execution_context=ResearchExecutionContext(
            run_id=RUN_ID,
            round_number=round_number,
        ),
        as_of_date=AS_OF,
        candidate=rule,
        plan=plan,
        data_references=["data-ref-1"],
    )
    entry = ledger_entry(
        candidate_id=candidate_id,
        trader_id=trader_id,
        parameters=parameters,
        strategy_name=strategy_name,
        metrics=metrics,
        resolved_end=ledger_resolved_end or DEFAULT_RESOLVED_END,
        validation_split_end=validation_split_end,
        round_number=round_number,
    )
    result = BacktestResult(
        result_id=f"{candidate_id}.result",
        request_id=f"{candidate_id}.bt",
        candidate_id=candidate_id,
        status=BacktestStatus.SUCCEEDED,
        engine_name="fractional_ai_workforce_backtest_engine",
        engine_version="0.5.0",
        metrics=metrics,
        out_of_sample_metrics=dict(metrics),
        benchmark_metrics=dict(
            benchmark_metrics
            if benchmark_metrics is not None
            else (CLEAN_METRICS if benchmark else {})
        ),
        ledger_entry=entry,
    )
    return TraderStrategyPackage(
        package_id=f"{candidate_id}.package",
        candidate_id=candidate_id,
        trader_id=trader_id,
        lineage=lineage,
        mandate_reference=MandateReference(
            workflow_id=WORKFLOW_ID,
            task_id=MANDATE_TASK_ID,
            as_of_date=AS_OF,
        ),
        status=RunStatus.COMPLETED,
        hypothesis=rule.hypothesis,
        specialty_evidence={
            evidence_id: {"kind": "signal_study"}
            for evidence_id in evidence_ids
        },
        candidate_rule=rule,
        backtest_request=request,
        backtest_result=result,
        interpretation=BacktestInterpretationDraft(
            summary="Reversion effect is present in and out of sample.",
            out_of_sample_assessment=(
                "Validation-window performance decays modestly but holds."
            ),
            confidence=ConfidenceAssessment(
                level=ConfidenceLevel.MEDIUM,
                rationale="Consistent effect across the universe.",
            ),
        ),
        constraint_assessment=MandateConstraintAssessment(
            status=ConstraintCheckStatus.DECLARED_ALIGNED,
        ),
        eligible_for_risk_review=True,
        additional_fields=dict(additional_fields or {}),
    )


def build_request(
    candidates,
    *,
    round_number: int = 1,
    audit_reference: str | None = None,
    history_reference: str | None = None,
) -> RiskReviewRequest:
    return RiskReviewRequest(
        request_id=f"{MANDATE_TASK_ID}.round-{round_number}.risk",
        mandate_task_id=MANDATE_TASK_ID,
        as_of_date=AS_OF,
        round_number=round_number,
        candidates=list(candidates),
        round_audit_summary_reference=audit_reference,
        round_history_reference=history_reference,
    )


def three_clean_candidates() -> list[TraderStrategyPackage]:
    return [
        build_package(
            candidate_id="cand-technical",
            trader_id=SpecialistId.TECHNICAL_TRADER,
            parameters={"lookback": 20, "z_entry": 1.5},
        ),
        build_package(
            candidate_id="cand-fundamental",
            trader_id=SpecialistId.FUNDAMENTAL_TRADER,
            parameters={"lookback": 60, "discount": 0.05},
        ),
        build_package(
            candidate_id="cand-quant",
            trader_id=SpecialistId.QUANT_TRADER,
            parameters={"lookback": 10, "z_entry": 2.0},
        ),
    ]


def undeclared_sweep_entries(
    *,
    candidate_id: str = "cand-quant",
    trader_id: SpecialistId = SpecialistId.QUANT_TRADER,
    variants: int = 50,
) -> list[BacktestRunLedgerEntry]:
    """Ledger evidence of a sweep the trader never disclosed."""

    return [
        ledger_entry(
            candidate_id=candidate_id,
            trader_id=trader_id,
            parameters={"lookback": 10, "z_entry": 2.0 + 0.01 * index},
            strategy_name=f"{candidate_id}-mean-reversion",
            metrics=CLEAN_METRICS,
            suffix=f".sweep-{index}",
        )
        for index in range(variants)
    ]


def single_run_entries(packages) -> list[BacktestRunLedgerEntry]:
    return [
        ledger_entry(
            candidate_id=str(package.candidate_id),
            trader_id=package.trader_id,
            parameters=dict(package.candidate_rule.parameters),
            strategy_name=package.candidate_rule.strategy_name,
            metrics=CLEAN_METRICS,
        )
        for package in packages
    ]


class StaticAuditReader:
    """Round-audit stub returning a fixed set of ledger entries."""

    def __init__(self, entries) -> None:
        self._entries = list(entries)

    async def ledger_entries(self, *, reference: str):
        del reference
        return list(self._entries)


class StaticHistoryReader:
    def __init__(self, summaries) -> None:
        self._summaries = list(summaries)

    async def prior_round_summaries(self, *, reference: str):
        del reference
        return list(self._summaries)


class ScriptedModelClient:
    """Model stub returning one predetermined structured judgment."""

    def __init__(self, judgment) -> None:
        self._judgment = judgment
        self.contexts: list[ModelRequestContext] = []

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model,
        context: ModelRequestContext,
    ):
        del system_prompt, user_prompt, response_model
        self.contexts.append(context)
        return ModelCallResult(
            output=self._judgment,
            usage=ModelUsage.unavailable("scripted test client"),
        )


def checks_by_id(results, check_id):
    return [result for result in results if result.check_id is check_id]


def decision_for(response, candidate_id: str):
    return next(
        decision
        for decision in response.decisions
        if decision.candidate_id == candidate_id
    )
