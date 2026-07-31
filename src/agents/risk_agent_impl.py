"""Collective Risk / Skeptic Agent implementation.

Two-stage review of one settled trader batch per round:

1. a deterministic gate computes every mechanically checkable CP item from
   engine-produced evidence (embedded run-ledger entries, request counts,
   package identity fields) without any model call; and
2. an optional model-judgment stage adds critiques and may *escalate*
   severity (PASS -> FLAG -> VETO) for judgment checks, but can never
   downgrade or remove a deterministic verdict.

Evidence that is not yet reachable (the full round audit ledger and prior
round history arrive as external references) degrades honestly: the affected
checks return FLAG with ``requires_human_review=True`` instead of a
manufactured PASS.

Threshold decisions still open with the team live in one place
(:class:`RiskPolicy`) so a meeting ruling is a one-line change.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from agents.technical_trader.model_client import (
    MetricsSink,
    ModelCallMetrics,
    ModelCallStatus,
    ModelClient,
    ModelRequestContext,
)
from protocols import (
    BacktestRunLedgerEntry,
    BacktestStatus,
    RiskCheckId,
    RiskCheckResult,
    RiskCheckScope,
    RiskCheckVerdict,
    RiskReviewRequest,
    RiskReviewResponse,
    RiskVerdict,
    TraderStrategyPackage,
)
from protocols.risk import RiskCandidateDecision


RISK_AGENT_ID = "risk_agent"
RISK_AGENT_CARD_VERSION = "0.1.0"

# Optional disclosure keys traders may set in package.additional_fields.
DECLARED_RUN_COUNT_KEY = "declared_backtest_run_count"
STABILITY_EVIDENCE_KEY = "stability_evidence"
PARENT_STRATEGY_KEY = "parent_strategy_id"

_SEVERITY_ORDER: dict[RiskCheckVerdict, int] = {
    RiskCheckVerdict.PASS: 0,
    RiskCheckVerdict.FLAG: 1,
    RiskCheckVerdict.VETO: 2,
}


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    """Team-confirmable thresholds for the cherry-picking checklist.

    Proposed defaults follow the checklist draft (§6 open items); update
    here once the team ratifies final values.
    """

    required_metrics: tuple[str, ...] = (
        "total_return",
        "annualized_return",
        "max_drawdown",
        "annualized_volatility",
        "sharpe_ratio",
    )
    sweep_flag_threshold: int = 20
    round_budget: int = 3
    duplication_overlap_threshold: float = 0.7


@runtime_checkable
class RoundAuditReader(Protocol):
    """Resolve a round-audit reference into every engine ledger entry."""

    async def ledger_entries(
        self,
        *,
        reference: str,
    ) -> Sequence[BacktestRunLedgerEntry]:
        """Return all engine runs recorded for the referenced round."""
        raise NotImplementedError


@runtime_checkable
class RoundHistoryReader(Protocol):
    """Resolve a round-history reference into prior-round summaries.

    Each summary is a mapping with at least ``round_number`` and a
    ``vetoed`` sequence of mappings carrying ``candidate_id``,
    ``strategy_name``, ``parameters``, and ``veto_reason_codes``.
    """

    async def prior_round_summaries(
        self,
        *,
        reference: str,
    ) -> Sequence[Mapping[str, Any]]:
        """Return prior-round outcome summaries for this mandate."""
        raise NotImplementedError


class JudgmentEscalation(BaseModel):
    """One model-proposed severity escalation for a checklist item."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    check_id: RiskCheckId
    candidate_id: str | None = None
    verdict: Literal["flag", "veto"]
    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class RiskJudgment(BaseModel):
    """Structured output required from the model-judgment stage."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    collective_critiques: list[str] = Field(default_factory=list)
    candidate_critiques: dict[str, list[str]] = Field(default_factory=dict)
    escalations: list[JudgmentEscalation] = Field(default_factory=list)


_JUDGMENT_SYSTEM_PROMPT = """\
You are the Risk / Skeptic Agent on an investment-research desk. Three
trader agents proposed mean-reversion strategy candidates; deterministic
code has already computed the mechanical checklist results below. Your job
is adversarial review of what code cannot judge:

- CP-2 severity: does a disclosed parameter sweep look like overfitting?
- CP-8: are two candidates effectively the same hypothesis in disguise?
- CP-12: does a resubmission merely rename a previously vetoed idea?
- Economic plausibility: does the stated hypothesis explain the result?

Rules you must follow:
1. Ground every claim in the provided evidence; cite evidence IDs. Never
   invent numbers, runs, or metrics that are not in the input.
2. You may ESCALATE a check (flag or veto) with justification. You may
   never argue a deterministic result downward; do not try.
3. A suspiciously strong backtest is a reason for more scrutiny, not less.
4. Be terse and specific. One sentence per critique.
Return only the requested structured output.
"""


class RiskAgentImpl:
    """Deterministic-first collective reviewer for the settled trader batch."""

    agent_id = RISK_AGENT_ID

    def __init__(
        self,
        *,
        policy: RiskPolicy | None = None,
        model_client: ModelClient | None = None,
        metrics_sink: MetricsSink | None = None,
        audit_reader: RoundAuditReader | None = None,
        history_reader: RoundHistoryReader | None = None,
    ) -> None:
        self._policy = policy or RiskPolicy()
        self._model_client = model_client
        self._metrics_sink = metrics_sink
        self._audit_reader = audit_reader
        self._history_reader = history_reader

    async def review(self, request: RiskReviewRequest) -> RiskReviewResponse:
        candidates = [
            package
            for package in request.candidates
            if package.candidate_id is not None
        ]
        audit_entries = await self._load_audit_entries(request)
        history = await self._load_history(request)

        candidate_checks: dict[str, list[RiskCheckResult]] = {}
        for package in candidates:
            candidate_checks[str(package.candidate_id)] = [
                *self._within_trader_checks(package, audit_entries),
                *self._cross_trader_candidate_checks(package, candidates),
                *self._cross_round_candidate_checks(
                    package,
                    request,
                    history,
                ),
            ]
        round_checks = [
            self._check_multiple_comparison(request, candidates),
            self._check_lens_duplication(candidates),
            self._check_nothing_is_deleted(request, history),
        ]

        collective_critiques: list[str] = [
            (
                f"Excluded from review this round: {len(request.excluded_packages)} "
                "package(s) that settled without a risk-eligible candidate."
            )
        ] if request.excluded_packages else []

        judgment = await self._model_judgment(
            request=request,
            candidates=candidates,
            candidate_checks=candidate_checks,
            round_checks=round_checks,
        )
        if judgment is not None:
            collective_critiques.extend(judgment.collective_critiques)
            self._apply_escalations(
                judgment=judgment,
                candidate_checks=candidate_checks,
                round_checks=round_checks,
            )

        decisions = [
            self._decide(
                package=package,
                checks=candidate_checks[str(package.candidate_id)],
                critiques=(
                    judgment.candidate_critiques.get(
                        str(package.candidate_id), []
                    )
                    if judgment is not None
                    else []
                ),
            )
            for package in candidates
        ]
        blocked = any(
            result.verdict is RiskCheckVerdict.VETO
            for result in round_checks
        )
        return RiskReviewResponse(
            response_id=f"{request.request_id}.response",
            request_id=request.request_id,
            decisions=decisions,
            round_check_results=round_checks,
            collective_critiques=collective_critiques,
            blocked_progression=blocked,
            reviewed_at=datetime.now(timezone.utc),
            reviewer_card_version=RISK_AGENT_CARD_VERSION,
        )

    # ------------------------------------------------------------------
    # Level 1 — within-trader checks (per candidate)
    # ------------------------------------------------------------------

    def _within_trader_checks(
        self,
        package: TraderStrategyPackage,
        audit_entries: Sequence[BacktestRunLedgerEntry] | None,
    ) -> list[RiskCheckResult]:
        return [
            *self._check_trial_accounting(package, audit_entries),
            self._check_full_period_metrics(package),
            self._check_universe_trimming(package, audit_entries),
            self._check_canonical_metrics(package),
            self._check_baseline(package),
            self._check_test_set_lock(package),
        ]

    def _check_trial_accounting(
        self,
        package: TraderStrategyPackage,
        audit_entries: Sequence[BacktestRunLedgerEntry] | None,
    ) -> list[RiskCheckResult]:
        """CP-1 report-everything-tried and CP-2 best-of-N disclosure."""

        candidate_id = str(package.candidate_id)
        declared = package.additional_fields.get(DECLARED_RUN_COUNT_KEY, 1)
        declared = declared if isinstance(declared, int) and declared >= 1 else 1
        if audit_entries is None:
            return [
                self._unverifiable(
                    check_id,
                    candidate_id,
                    "round audit ledger is not resolvable in this "
                    "environment; trial accounting needs human review",
                )
                for check_id in (
                    RiskCheckId.REPORT_EVERYTHING_TRIED,
                    RiskCheckId.BEST_OF_N_DISCLOSURE,
                )
            ]

        trader_runs = [
            entry
            for entry in audit_entries
            if entry.trader_id is package.trader_id
        ]
        actual = len(trader_runs)
        evidence = [entry.ledger_entry_id for entry in trader_runs]
        results: list[RiskCheckResult] = []
        if actual > declared:
            results.append(
                RiskCheckResult(
                    check_id=RiskCheckId.REPORT_EVERYTHING_TRIED,
                    verdict=RiskCheckVerdict.VETO,
                    scope=RiskCheckScope.CANDIDATE,
                    candidate_id=candidate_id,
                    summary=(
                        f"Engine ledger records {actual} run(s) for "
                        f"{package.trader_id} this round but the package "
                        f"declares {declared}; undeclared trials are hidden "
                        "selection."
                    ),
                    evidence_ids=evidence,
                    deterministic=True,
                )
            )
        else:
            results.append(
                RiskCheckResult(
                    check_id=RiskCheckId.REPORT_EVERYTHING_TRIED,
                    verdict=RiskCheckVerdict.PASS,
                    scope=RiskCheckScope.CANDIDATE,
                    candidate_id=candidate_id,
                    summary=(
                        f"Declared trial count ({declared}) covers all "
                        f"{actual} ledger run(s) for {package.trader_id}."
                    ),
                    evidence_ids=evidence,
                    deterministic=True,
                )
            )

        effective_n = max(actual, declared)
        if actual > declared:
            best_of_n = RiskCheckResult(
                check_id=RiskCheckId.BEST_OF_N_DISCLOSURE,
                verdict=RiskCheckVerdict.VETO,
                scope=RiskCheckScope.CANDIDATE,
                candidate_id=candidate_id,
                summary=(
                    f"Candidate presented as best of {declared} while the "
                    f"ledger shows {actual} variants; undeclared sweep."
                ),
                evidence_ids=evidence,
                deterministic=True,
            )
        elif effective_n > self._policy.sweep_flag_threshold:
            best_of_n = RiskCheckResult(
                check_id=RiskCheckId.BEST_OF_N_DISCLOSURE,
                verdict=RiskCheckVerdict.FLAG,
                scope=RiskCheckScope.CANDIDATE,
                candidate_id=candidate_id,
                summary=(
                    f"Disclosed sweep of {effective_n} variants exceeds the "
                    f"{self._policy.sweep_flag_threshold}-variant threshold; "
                    "expect validation decay and report the full variant "
                    "table."
                ),
                evidence_ids=evidence,
                deterministic=True,
            )
        else:
            best_of_n = RiskCheckResult(
                check_id=RiskCheckId.BEST_OF_N_DISCLOSURE,
                verdict=RiskCheckVerdict.PASS,
                scope=RiskCheckScope.CANDIDATE,
                candidate_id=candidate_id,
                summary=(
                    f"Selection breadth of {effective_n} variant(s) is "
                    "declared and within policy."
                ),
                evidence_ids=evidence,
                deterministic=True,
            )
        results.append(best_of_n)
        return results

    def _check_full_period_metrics(
        self,
        package: TraderStrategyPackage,
    ) -> RiskCheckResult:
        """CP-3: headline metrics must include the held-out window."""

        candidate_id = str(package.candidate_id)
        result = package.backtest_result
        request = package.backtest_request
        problems: list[str] = []
        if result is None or result.status is not BacktestStatus.SUCCEEDED:
            problems.append("the backtest did not succeed")
        if request is None or request.plan.validation_split is None:
            problems.append("no code-owned validation split was applied")
        if result is not None and not result.out_of_sample_metrics:
            problems.append("no out-of-sample metrics were computed")
        evidence = [result.result_id] if result is not None else []
        if problems:
            return RiskCheckResult(
                check_id=RiskCheckId.FULL_PERIOD_METRICS,
                verdict=RiskCheckVerdict.VETO,
                scope=RiskCheckScope.CANDIDATE,
                candidate_id=candidate_id,
                summary=(
                    "Full-period evidence is incomplete: "
                    + "; ".join(problems)
                    + "."
                ),
                evidence_ids=evidence,
                deterministic=True,
            )
        return RiskCheckResult(
            check_id=RiskCheckId.FULL_PERIOD_METRICS,
            verdict=RiskCheckVerdict.PASS,
            scope=RiskCheckScope.CANDIDATE,
            candidate_id=candidate_id,
            summary=(
                "Backtest succeeded over the full requested window with a "
                "code-owned validation split and out-of-sample metrics."
            ),
            evidence_ids=evidence,
            deterministic=True,
        )

    def _check_universe_trimming(
        self,
        package: TraderStrategyPackage,
        audit_entries: Sequence[BacktestRunLedgerEntry] | None,
    ) -> RiskCheckResult:
        """CP-4: the traded universe must not shrink after seeing results."""

        candidate_id = str(package.candidate_id)
        if audit_entries is None:
            return self._unverifiable(
                RiskCheckId.NO_POST_HOC_UNIVERSE_TRIMMING,
                candidate_id,
                "round audit ledger unavailable; cross-run universe "
                "comparison needs human review",
            )
        trader_runs = sorted(
            (
                entry
                for entry in audit_entries
                if entry.trader_id is package.trader_id
                and entry.resolved_symbols
            ),
            key=lambda entry: entry.recorded_at,
        )
        if len(trader_runs) < 2:
            return RiskCheckResult(
                check_id=RiskCheckId.NO_POST_HOC_UNIVERSE_TRIMMING,
                verdict=RiskCheckVerdict.PASS,
                scope=RiskCheckScope.CANDIDATE,
                candidate_id=candidate_id,
                summary=(
                    "A single ledger run exists for this trader; no "
                    "post-hoc universe narrowing is possible."
                ),
                evidence_ids=[
                    entry.ledger_entry_id for entry in trader_runs
                ],
                deterministic=True,
            )
        first = set(trader_runs[0].resolved_symbols)
        last = set(trader_runs[-1].resolved_symbols)
        dropped = sorted(first - last)
        if dropped and last < first:
            return RiskCheckResult(
                check_id=RiskCheckId.NO_POST_HOC_UNIVERSE_TRIMMING,
                verdict=RiskCheckVerdict.FLAG,
                scope=RiskCheckScope.CANDIDATE,
                candidate_id=candidate_id,
                summary=(
                    "The traded universe narrowed across runs (dropped: "
                    + ", ".join(dropped)
                    + "); confirm the subset rule was declared ex ante."
                ),
                evidence_ids=[
                    trader_runs[0].ledger_entry_id,
                    trader_runs[-1].ledger_entry_id,
                ],
                deterministic=True,
            )
        return RiskCheckResult(
            check_id=RiskCheckId.NO_POST_HOC_UNIVERSE_TRIMMING,
            verdict=RiskCheckVerdict.PASS,
            scope=RiskCheckScope.CANDIDATE,
            candidate_id=candidate_id,
            summary="The traded universe did not narrow across ledger runs.",
            evidence_ids=[entry.ledger_entry_id for entry in trader_runs],
            deterministic=True,
        )

    def _check_canonical_metrics(
        self,
        package: TraderStrategyPackage,
    ) -> RiskCheckResult:
        """CP-5: every required metric reported, including the ugly ones."""

        candidate_id = str(package.candidate_id)
        result = package.backtest_result
        metrics = result.metrics if result is not None else {}
        missing = sorted(
            name
            for name in self._policy.required_metrics
            if metrics.get(name) is None
        )
        evidence = [result.result_id] if result is not None else []
        if missing:
            return RiskCheckResult(
                check_id=RiskCheckId.FULL_CANONICAL_METRIC_SET,
                verdict=RiskCheckVerdict.VETO,
                scope=RiskCheckScope.CANDIDATE,
                candidate_id=candidate_id,
                summary=(
                    "Canonical metrics are missing or null: "
                    + ", ".join(missing)
                    + "."
                ),
                evidence_ids=evidence,
                deterministic=True,
            )
        return RiskCheckResult(
            check_id=RiskCheckId.FULL_CANONICAL_METRIC_SET,
            verdict=RiskCheckVerdict.PASS,
            scope=RiskCheckScope.CANDIDATE,
            candidate_id=candidate_id,
            summary="All canonical metrics are present and non-null.",
            evidence_ids=evidence,
            deterministic=True,
        )

    def _check_baseline(
        self,
        package: TraderStrategyPackage,
    ) -> RiskCheckResult:
        """CP-6: same-terms benchmark computed by the same engine run."""

        candidate_id = str(package.candidate_id)
        request = package.backtest_request
        result = package.backtest_result
        benchmark = request.plan.benchmark if request is not None else None
        has_metrics = bool(result is not None and result.benchmark_metrics)
        evidence = [result.result_id] if result is not None else []
        if benchmark and has_metrics:
            return RiskCheckResult(
                check_id=RiskCheckId.SAME_TERMS_BASELINE,
                verdict=RiskCheckVerdict.PASS,
                scope=RiskCheckScope.CANDIDATE,
                candidate_id=candidate_id,
                summary=(
                    f"Benchmark '{benchmark}' was computed in the same "
                    "engine run under identical assumptions."
                ),
                evidence_ids=evidence,
                deterministic=True,
            )
        return RiskCheckResult(
            check_id=RiskCheckId.SAME_TERMS_BASELINE,
            verdict=RiskCheckVerdict.VETO,
            scope=RiskCheckScope.CANDIDATE,
            candidate_id=candidate_id,
            summary=(
                "No same-terms baseline: the plan lacks a benchmark or the "
                "engine produced no benchmark metrics."
            ),
            evidence_ids=evidence,
            deterministic=True,
        )

    def _check_test_set_lock(
        self,
        package: TraderStrategyPackage,
    ) -> RiskCheckResult:
        """CP-13: no evidence may touch data beyond the as-of boundary."""

        candidate_id = str(package.candidate_id)
        result = package.backtest_result
        ledger = result.ledger_entry if result is not None else None
        if ledger is None:
            return self._unverifiable(
                RiskCheckId.TEST_SET_LOCK,
                candidate_id,
                "no embedded run-ledger entry; lock compliance cannot be "
                "verified from the package alone",
            )
        as_of = package.as_of_date
        violations: list[str] = []
        if (
            ledger.resolved_end_time is not None
            and ledger.resolved_end_time.date() > as_of
        ):
            violations.append(
                "resolved data extends past the as-of date "
                f"({ledger.resolved_end_time.date().isoformat()} > "
                f"{as_of.isoformat()})"
            )
        split = ledger.additional_fields.get("validation_split")
        if isinstance(split, Mapping):
            end = _coerce_date(split.get("test_end_date"))
            if end is not None and end > as_of:
                violations.append(
                    "the validation split reaches past the as-of date"
                )
        if violations:
            return RiskCheckResult(
                check_id=RiskCheckId.TEST_SET_LOCK,
                verdict=RiskCheckVerdict.VETO,
                scope=RiskCheckScope.CANDIDATE,
                candidate_id=candidate_id,
                summary=(
                    "Test-set lock violation: " + "; ".join(violations) + "."
                ),
                evidence_ids=[ledger.ledger_entry_id],
                deterministic=True,
            )
        return RiskCheckResult(
            check_id=RiskCheckId.TEST_SET_LOCK,
            verdict=RiskCheckVerdict.PASS,
            scope=RiskCheckScope.CANDIDATE,
            candidate_id=candidate_id,
            summary=(
                "All resolved data and the validation split respect the "
                "as-of boundary."
            ),
            evidence_ids=[ledger.ledger_entry_id],
            deterministic=True,
        )

    # ------------------------------------------------------------------
    # Level 2 — cross-trader checks
    # ------------------------------------------------------------------

    def _cross_trader_candidate_checks(
        self,
        package: TraderStrategyPackage,
        candidates: Sequence[TraderStrategyPackage],
    ) -> list[RiskCheckResult]:
        return [self._check_borrowed_evidence(package, candidates)]

    def _check_borrowed_evidence(
        self,
        package: TraderStrategyPackage,
        candidates: Sequence[TraderStrategyPackage],
    ) -> RiskCheckResult:
        """CP-9: every cited run must belong to this candidate."""

        candidate_id = str(package.candidate_id)
        problems: list[str] = []
        result = package.backtest_result
        request = package.backtest_request
        if result is not None and result.candidate_id != package.candidate_id:
            problems.append(
                "the backtest result belongs to a different candidate"
            )
        if (
            result is not None
            and request is not None
            and result.request_id != request.request_id
        ):
            problems.append(
                "the backtest result does not answer this package's request"
            )
        ledger = result.ledger_entry if result is not None else None
        if ledger is not None and ledger.trader_id is not package.trader_id:
            problems.append("the run ledger names a different trader")

        foreign_run_ids = {
            other.backtest_result.result_id
            for other in candidates
            if other.candidate_id != package.candidate_id
            and other.backtest_result is not None
        }
        rule = package.candidate_rule
        cited = set(rule.specialty_evidence_ids) if rule is not None else set()
        borrowed = sorted(cited & foreign_run_ids)
        if borrowed:
            problems.append(
                "cited evidence resolves to another trader's runs: "
                + ", ".join(borrowed)
            )
        evidence = [result.result_id] if result is not None else []
        if problems:
            return RiskCheckResult(
                check_id=RiskCheckId.NO_BORROWED_EVIDENCE,
                verdict=RiskCheckVerdict.VETO,
                scope=RiskCheckScope.CANDIDATE,
                candidate_id=candidate_id,
                summary=(
                    "Evidence identity failure: " + "; ".join(problems) + "."
                ),
                evidence_ids=evidence,
                deterministic=True,
            )
        return RiskCheckResult(
            check_id=RiskCheckId.NO_BORROWED_EVIDENCE,
            verdict=RiskCheckVerdict.PASS,
            scope=RiskCheckScope.CANDIDATE,
            candidate_id=candidate_id,
            summary="All cited evidence resolves to this candidate's own runs.",
            evidence_ids=evidence,
            deterministic=True,
        )

    def _check_multiple_comparison(
        self,
        request: RiskReviewRequest,
        candidates: Sequence[TraderStrategyPackage],
    ) -> RiskCheckResult:
        """CP-7, emitted as FLAG so the disclosure must reach the memo."""

        declared_total = 0
        for package in candidates:
            declared = package.additional_fields.get(DECLARED_RUN_COUNT_KEY, 1)
            declared_total += (
                declared if isinstance(declared, int) and declared >= 1 else 1
            )
        return RiskCheckResult(
            check_id=RiskCheckId.MULTIPLE_COMPARISON_DISCLOSURE,
            verdict=RiskCheckVerdict.FLAG,
            scope=RiskCheckScope.ROUND,
            summary=(
                f"Multiple-comparison disclosure: {len(candidates)} "
                f"candidate(s) from parallel lenses "
                f"({len(request.excluded_packages)} package(s) excluded), "
                f"at least {declared_total} declared hypothesis test(s) "
                "against the same validation window this round. Reporting "
                "must present every candidate with its verdict, not only "
                "the winner."
            ),
            evidence_ids=[request.request_id],
            deterministic=True,
        )

    def _check_lens_duplication(
        self,
        candidates: Sequence[TraderStrategyPackage],
    ) -> RiskCheckResult:
        """CP-8 deterministic proxy: identical rules are one hypothesis."""

        duplicate_pairs: list[str] = []
        evidence: list[str] = []
        for index, first in enumerate(candidates):
            for second in candidates[index + 1:]:
                if first.candidate_rule is None or second.candidate_rule is None:
                    continue
                same_executor = (
                    first.candidate_rule.executor_id
                    == second.candidate_rule.executor_id
                )
                same_parameters = (
                    first.candidate_rule.parameters
                    == second.candidate_rule.parameters
                )
                if same_executor and same_parameters:
                    duplicate_pairs.append(
                        f"{first.candidate_id} ~ {second.candidate_id}"
                    )
                    for item in (first, second):
                        if item.backtest_result is not None:
                            evidence.append(item.backtest_result.result_id)
        if duplicate_pairs:
            return RiskCheckResult(
                check_id=RiskCheckId.LENS_DUPLICATION,
                verdict=RiskCheckVerdict.FLAG,
                scope=RiskCheckScope.ROUND,
                summary=(
                    "Candidate pairs share an executor and identical "
                    "parameters and count as one hypothesis, not "
                    "confirmation: " + "; ".join(duplicate_pairs) + "."
                ),
                evidence_ids=evidence,
                deterministic=True,
            )
        return RiskCheckResult(
            check_id=RiskCheckId.LENS_DUPLICATION,
            verdict=RiskCheckVerdict.PASS,
            scope=RiskCheckScope.ROUND,
            summary=(
                "No candidate pair shares an executor with identical "
                "parameters; lenses appear independent at rule level."
            ),
            evidence_ids=[],
            deterministic=True,
        )

    # ------------------------------------------------------------------
    # Level 3 — cross-round checks
    # ------------------------------------------------------------------

    def _cross_round_candidate_checks(
        self,
        package: TraderStrategyPackage,
        request: RiskReviewRequest,
        history: Sequence[Mapping[str, Any]] | None,
    ) -> list[RiskCheckResult]:
        return [
            self._check_validation_touch_budget(package, request),
            self._check_resurrection(package, request, history),
        ]

    def _check_validation_touch_budget(
        self,
        package: TraderStrategyPackage,
        request: RiskReviewRequest,
    ) -> RiskCheckResult:
        """CP-11: past the round budget, approval needs stability evidence."""

        candidate_id = str(package.candidate_id)
        if request.round_number <= self._policy.round_budget:
            return RiskCheckResult(
                check_id=RiskCheckId.VALIDATION_TOUCH_BUDGET,
                verdict=RiskCheckVerdict.PASS,
                scope=RiskCheckScope.CANDIDATE,
                candidate_id=candidate_id,
                summary=(
                    f"Round {request.round_number} is within the "
                    f"{self._policy.round_budget}-round validation-touch "
                    "budget."
                ),
                evidence_ids=[request.request_id],
                deterministic=True,
            )
        stability = package.additional_fields.get(STABILITY_EVIDENCE_KEY)
        if stability:
            return RiskCheckResult(
                check_id=RiskCheckId.VALIDATION_TOUCH_BUDGET,
                verdict=RiskCheckVerdict.FLAG,
                scope=RiskCheckScope.CANDIDATE,
                candidate_id=candidate_id,
                summary=(
                    f"Round {request.round_number} exceeds the "
                    f"{self._policy.round_budget}-round budget; stability "
                    "evidence was supplied and must appear in the memo."
                ),
                evidence_ids=[request.request_id],
                deterministic=True,
            )
        return RiskCheckResult(
            check_id=RiskCheckId.VALIDATION_TOUCH_BUDGET,
            verdict=RiskCheckVerdict.VETO,
            scope=RiskCheckScope.CANDIDATE,
            candidate_id=candidate_id,
            summary=(
                f"Round {request.round_number} exceeds the "
                f"{self._policy.round_budget}-round validation-touch budget "
                "and the candidate carries no parameter-stability evidence."
            ),
            evidence_ids=[request.request_id],
            deterministic=True,
        )

    def _check_resurrection(
        self,
        package: TraderStrategyPackage,
        request: RiskReviewRequest,
        history: Sequence[Mapping[str, Any]] | None,
    ) -> RiskCheckResult:
        """CP-12: vetoed ideas may return only with declared lineage."""

        candidate_id = str(package.candidate_id)
        if request.round_number <= 1:
            return RiskCheckResult(
                check_id=RiskCheckId.NO_COSMETIC_RESURRECTION,
                verdict=RiskCheckVerdict.PASS,
                scope=RiskCheckScope.CANDIDATE,
                candidate_id=candidate_id,
                summary="First round; no prior vetoes exist to resurrect.",
                evidence_ids=[request.request_id],
                deterministic=True,
            )
        if history is None:
            return self._unverifiable(
                RiskCheckId.NO_COSMETIC_RESURRECTION,
                candidate_id,
                "round history unavailable; resurrection screening needs "
                "human review",
            )
        rule = package.candidate_rule
        declared_parent = package.additional_fields.get(PARENT_STRATEGY_KEY)
        for summary in history:
            for vetoed in summary.get("vetoed", ()):
                same_name = (
                    rule is not None
                    and str(vetoed.get("strategy_name", "")).casefold()
                    == rule.strategy_name.casefold()
                )
                same_parameters = (
                    rule is not None
                    and vetoed.get("parameters") == rule.parameters
                )
                if (same_name or same_parameters) and not declared_parent:
                    return RiskCheckResult(
                        check_id=RiskCheckId.NO_COSMETIC_RESURRECTION,
                        verdict=RiskCheckVerdict.VETO,
                        scope=RiskCheckScope.CANDIDATE,
                        candidate_id=candidate_id,
                        summary=(
                            "Candidate matches previously vetoed strategy "
                            f"'{vetoed.get('candidate_id', 'unknown')}' "
                            "without declaring lineage or addressing the "
                            "original veto reasons."
                        ),
                        evidence_ids=[request.request_id],
                        deterministic=True,
                    )
        return RiskCheckResult(
            check_id=RiskCheckId.NO_COSMETIC_RESURRECTION,
            verdict=RiskCheckVerdict.PASS,
            scope=RiskCheckScope.CANDIDATE,
            candidate_id=candidate_id,
            summary=(
                "No undeclared match against previously vetoed strategies."
            ),
            evidence_ids=[request.request_id],
            deterministic=True,
        )

    def _check_nothing_is_deleted(
        self,
        request: RiskReviewRequest,
        history: Sequence[Mapping[str, Any]] | None,
    ) -> RiskCheckResult:
        """CP-10: round N must still see rounds 1..N-1 in the record."""

        if request.round_number <= 1:
            return RiskCheckResult(
                check_id=RiskCheckId.NOTHING_IS_DELETED,
                verdict=RiskCheckVerdict.PASS,
                scope=RiskCheckScope.ROUND,
                summary="First round; the research log starts here.",
                evidence_ids=[request.request_id],
                deterministic=True,
            )
        if history is None:
            return RiskCheckResult(
                check_id=RiskCheckId.NOTHING_IS_DELETED,
                verdict=RiskCheckVerdict.FLAG,
                scope=RiskCheckScope.ROUND,
                summary=(
                    "Round history is unavailable, so research-log "
                    "continuity cannot be verified; needs human review."
                ),
                evidence_ids=[request.request_id],
                deterministic=True,
                requires_human_review=True,
            )
        recorded = {
            summary.get("round_number")
            for summary in history
        }
        missing = sorted(
            round_number
            for round_number in range(1, request.round_number)
            if round_number not in recorded
        )
        if missing:
            return RiskCheckResult(
                check_id=RiskCheckId.NOTHING_IS_DELETED,
                verdict=RiskCheckVerdict.VETO,
                scope=RiskCheckScope.ROUND,
                summary=(
                    "Research-log continuity is broken; missing round "
                    "record(s): "
                    + ", ".join(str(item) for item in missing)
                    + "."
                ),
                evidence_ids=[request.request_id],
                deterministic=True,
            )
        return RiskCheckResult(
            check_id=RiskCheckId.NOTHING_IS_DELETED,
            verdict=RiskCheckVerdict.PASS,
            scope=RiskCheckScope.ROUND,
            summary="Every prior round remains in the research log.",
            evidence_ids=[request.request_id],
            deterministic=True,
        )

    # ------------------------------------------------------------------
    # Judgment stage
    # ------------------------------------------------------------------

    async def _model_judgment(
        self,
        *,
        request: RiskReviewRequest,
        candidates: Sequence[TraderStrategyPackage],
        candidate_checks: Mapping[str, Sequence[RiskCheckResult]],
        round_checks: Sequence[RiskCheckResult],
    ) -> RiskJudgment | None:
        if self._model_client is None or not candidates:
            return None
        workflow_id = candidates[0].lineage.workflow_id
        context = ModelRequestContext(
            agent_id=self.agent_id,
            operation="collective_risk_review",
            workflow_id=workflow_id,
            task_id=request.request_id,
        )
        started_at = datetime.now(timezone.utc)
        try:
            result = await self._model_client.generate_structured(
                system_prompt=_JUDGMENT_SYSTEM_PROMPT,
                user_prompt=self._judgment_prompt(
                    request=request,
                    candidates=candidates,
                    candidate_checks=candidate_checks,
                    round_checks=round_checks,
                ),
                response_model=RiskJudgment,
                context=context,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._record_model_call(
                context=context,
                status=ModelCallStatus.FAILED,
                started_at=started_at,
                error=exc,
            )
            return RiskJudgment(
                collective_critiques=[
                    "Model judgment was unavailable this round "
                    f"({type(exc).__name__}); deterministic checks stand "
                    "unassisted."
                ]
            )
        self._record_model_call(
            context=context,
            status=ModelCallStatus.SUCCEEDED,
            started_at=started_at,
            usage=result.usage,
        )
        output = result.output
        if isinstance(output, RiskJudgment):
            return output
        return RiskJudgment.model_validate(output)

    def _judgment_prompt(
        self,
        *,
        request: RiskReviewRequest,
        candidates: Sequence[TraderStrategyPackage],
        candidate_checks: Mapping[str, Sequence[RiskCheckResult]],
        round_checks: Sequence[RiskCheckResult],
    ) -> str:
        lines = [
            f"Round {request.round_number} review "
            f"(request {request.request_id}, as of "
            f"{request.as_of_date.isoformat()}).",
            "",
            "Deterministic round-level results:",
        ]
        for result in round_checks:
            lines.append(
                f"- {result.check_id}: {result.verdict} — {result.summary}"
            )
        for package in candidates:
            candidate_id = str(package.candidate_id)
            rule = package.candidate_rule
            result = package.backtest_result
            lines.extend(
                [
                    "",
                    f"Candidate {candidate_id} ({package.trader_id}):",
                    f"  hypothesis: {package.hypothesis or 'undeclared'}",
                    (
                        f"  rule: {rule.rule_summary} "
                        f"[executor {rule.executor_id}, "
                        f"parameters {dict(rule.parameters)}]"
                        if rule is not None
                        else "  rule: missing"
                    ),
                    (
                        f"  metrics: {dict(result.metrics)}"
                        if result is not None
                        else "  metrics: missing"
                    ),
                    (
                        f"  out-of-sample: {dict(result.out_of_sample_metrics)}"
                        if result is not None
                        else "  out-of-sample: missing"
                    ),
                ]
            )
            for check in candidate_checks.get(candidate_id, ()):
                lines.append(
                    f"  - {check.check_id}: {check.verdict} — {check.summary}"
                )
            interpretation = package.interpretation
            if interpretation is not None:
                lines.append(
                    "  trader self-assessment: "
                    + interpretation.out_of_sample_assessment
                )
        lines.extend(
            [
                "",
                "Escalate only with grounded justification; you cannot "
                "downgrade deterministic results.",
            ]
        )
        return "\n".join(lines)

    def _apply_escalations(
        self,
        *,
        judgment: RiskJudgment,
        candidate_checks: dict[str, list[RiskCheckResult]],
        round_checks: list[RiskCheckResult],
    ) -> None:
        """Append model escalations that raise severity; ignore the rest."""

        for escalation in judgment.escalations:
            verdict = (
                RiskCheckVerdict.VETO
                if escalation.verdict == "veto"
                else RiskCheckVerdict.FLAG
            )
            if escalation.candidate_id is not None:
                checks = candidate_checks.get(escalation.candidate_id)
                if checks is None:
                    continue
                current = max(
                    (
                        _SEVERITY_ORDER[check.verdict]
                        for check in checks
                        if check.check_id is escalation.check_id
                    ),
                    default=-1,
                )
                if _SEVERITY_ORDER[verdict] <= current:
                    continue
                checks.append(
                    RiskCheckResult(
                        check_id=escalation.check_id,
                        verdict=verdict,
                        scope=RiskCheckScope.CANDIDATE,
                        candidate_id=escalation.candidate_id,
                        summary=escalation.summary,
                        evidence_ids=escalation.evidence_ids,
                        deterministic=False,
                    )
                )
            else:
                current = max(
                    (
                        _SEVERITY_ORDER[check.verdict]
                        for check in round_checks
                        if check.check_id is escalation.check_id
                    ),
                    default=-1,
                )
                if _SEVERITY_ORDER[verdict] <= current:
                    continue
                round_checks.append(
                    RiskCheckResult(
                        check_id=escalation.check_id,
                        verdict=verdict,
                        scope=RiskCheckScope.ROUND,
                        summary=escalation.summary,
                        evidence_ids=escalation.evidence_ids,
                        deterministic=False,
                    )
                )

    # ------------------------------------------------------------------
    # Assembly helpers
    # ------------------------------------------------------------------

    def _decide(
        self,
        *,
        package: TraderStrategyPackage,
        checks: Sequence[RiskCheckResult],
        critiques: Sequence[str],
    ) -> RiskCandidateDecision:
        vetoed = any(
            check.verdict is RiskCheckVerdict.VETO for check in checks
        )
        flags = [
            check.summary
            for check in checks
            if check.verdict is RiskCheckVerdict.FLAG
        ]
        evidence = sorted(
            {
                evidence_id
                for check in checks
                for evidence_id in check.evidence_ids
            }
        )
        return RiskCandidateDecision(
            candidate_id=str(package.candidate_id),
            verdict=RiskVerdict.VETO if vetoed else RiskVerdict.APPROVE,
            check_results=list(checks),
            critiques=[critique for critique in critiques if critique.strip()],
            reporting_flags=flags,
            evidence_ids=evidence,
        )

    async def _load_audit_entries(
        self,
        request: RiskReviewRequest,
    ) -> Sequence[BacktestRunLedgerEntry] | None:
        reference = request.round_audit_summary_reference
        if self._audit_reader is None or reference is None:
            return None
        entries = await self._audit_reader.ledger_entries(reference=reference)
        return [
            entry
            for entry in entries
            if entry.round_number == request.round_number
        ]

    async def _load_history(
        self,
        request: RiskReviewRequest,
    ) -> Sequence[Mapping[str, Any]] | None:
        reference = request.round_history_reference
        if self._history_reader is None or reference is None:
            return None
        return list(
            await self._history_reader.prior_round_summaries(
                reference=reference
            )
        )

    @staticmethod
    def _unverifiable(
        check_id: RiskCheckId,
        candidate_id: str,
        reason: str,
    ) -> RiskCheckResult:
        return RiskCheckResult(
            check_id=check_id,
            verdict=RiskCheckVerdict.FLAG,
            scope=RiskCheckScope.CANDIDATE,
            candidate_id=candidate_id,
            summary=f"Unverifiable: {reason}.",
            evidence_ids=[],
            deterministic=True,
            requires_human_review=True,
        )

    def _record_model_call(
        self,
        *,
        context: ModelRequestContext,
        status: ModelCallStatus,
        started_at: datetime,
        usage: Any = None,
        error: Exception | None = None,
    ) -> None:
        if self._metrics_sink is None:
            return
        completed_at = datetime.now(timezone.utc)
        self._metrics_sink.record_model_call(
            ModelCallMetrics(
                context=context,
                status=status,
                started_at=started_at,
                completed_at=completed_at,
                latency_ms=max(
                    (completed_at - started_at).total_seconds() * 1000.0,
                    0.0,
                ),
                usage=usage,
                error_type=type(error).__name__ if error else None,
                error_message=str(error) or None if error else None,
            )
        )


def _coerce_date(value: Any) -> date | None:
    """Read a date that may arrive as a date or an ISO string.

    Ledger ``additional_fields`` survive a JSON round trip through graph
    state, so the same field is a ``date`` in-process and a string after
    checkpointing. A lock check that only understood one form would pass
    silently on the other.
    """

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def make_risk_review_node(agent: RiskAgentImpl):
    """Adapt a Risk agent to the graph's injected-node boundary.

    Returns a node suitable for ``ProductionNodeSet.risk_review``: it reads
    the prepared ``risk_review_request`` from state and returns the
    ``risk_review_response`` update the graph wrapper validates.
    """

    async def risk_review_node(
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        request = RiskReviewRequest.model_validate(
            state.get("risk_review_request")
        )
        response = await agent.review(request)
        return {"risk_review_response": response.model_dump(mode="json")}

    return risk_review_node


__all__ = [
    "DECLARED_RUN_COUNT_KEY",
    "PARENT_STRATEGY_KEY",
    "RISK_AGENT_ID",
    "RiskAgentImpl",
    "RiskJudgment",
    "JudgmentEscalation",
    "RiskPolicy",
    "RoundAuditReader",
    "RoundHistoryReader",
    "STABILITY_EVIDENCE_KEY",
    "make_risk_review_node",
]
