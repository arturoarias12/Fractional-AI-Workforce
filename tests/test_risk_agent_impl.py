"""Acceptance tests for the collective Risk / Skeptic Agent.

Each test builds settled trader packages the way the graph delivers them and
asserts the checklist verdicts (CP-1..CP-13) the implementation must produce,
including the planted cherry-picking case from the QA workstream: an
undeclared 50-variant sweep must draw a CP-1/CP-2 veto.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from agents.risk_agent_impl import (
    DECLARED_RUN_COUNT_KEY,
    JudgmentEscalation,
    RiskAgentImpl,
    RiskJudgment,
    STABILITY_EVIDENCE_KEY,
    make_risk_review_node,
)
from protocols import (
    RiskCheckId,
    RiskCheckVerdict,
    RiskReviewRequest,
    RiskReviewResponse,
    RiskVerdict,
    SpecialistId,
)
from risk_fixtures import (
    AS_OF,
    CLEAN_METRICS,
    ScriptedModelClient,
    StaticAuditReader,
    StaticHistoryReader,
    WORKFLOW_ID,
    build_package,
    build_request,
    checks_by_id,
    decision_for,
    single_run_entries,
    three_clean_candidates,
    undeclared_sweep_entries,
)


def review(agent: RiskAgentImpl, request: RiskReviewRequest):
    return asyncio.run(agent.review(request))


def test_clean_batch_approves_every_candidate():
    response = review(RiskAgentImpl(), build_request(three_clean_candidates()))

    assert len(response.decisions) == 3
    assert all(
        decision.verdict is RiskVerdict.APPROVE
        for decision in response.decisions
    )
    assert not response.blocked_progression
    assert set(response.approved_candidate_ids()) == {
        "cand-technical",
        "cand-fundamental",
        "cand-quant",
    }


def test_unverifiable_audit_checks_flag_for_human_review():
    response = review(RiskAgentImpl(), build_request(three_clean_candidates()))

    decision = decision_for(response, "cand-quant")
    trial_checks = checks_by_id(
        decision.check_results,
        RiskCheckId.REPORT_EVERYTHING_TRIED,
    )
    assert trial_checks[0].verdict is RiskCheckVerdict.FLAG
    assert trial_checks[0].requires_human_review
    assert any("Unverifiable" in flag for flag in decision.reporting_flags)


def test_multiple_comparison_disclosure_always_reaches_reporting():
    response = review(RiskAgentImpl(), build_request(three_clean_candidates()))

    disclosure = checks_by_id(
        response.round_check_results,
        RiskCheckId.MULTIPLE_COMPARISON_DISCLOSURE,
    )[0]
    assert disclosure.verdict is RiskCheckVerdict.FLAG
    assert disclosure.summary in response.required_reporting_flags()


def test_planted_undeclared_sweep_draws_cp1_cp2_veto():
    """The QA planted fixture: best of 50 reported as a single hypothesis."""

    candidates = three_clean_candidates()
    agent = RiskAgentImpl(
        audit_reader=StaticAuditReader(
            [*single_run_entries(candidates[:2]), *undeclared_sweep_entries()]
        ),
    )
    response = review(
        agent,
        build_request(candidates, audit_reference="audit-round-1"),
    )

    quant_decision = decision_for(response, "cand-quant")
    assert quant_decision.verdict is RiskVerdict.VETO
    assert RiskCheckId.REPORT_EVERYTHING_TRIED in (
        quant_decision.veto_reason_codes
    )
    assert RiskCheckId.BEST_OF_N_DISCLOSURE in quant_decision.veto_reason_codes
    for honest in ("cand-technical", "cand-fundamental"):
        assert decision_for(response, honest).verdict is RiskVerdict.APPROVE


def test_declared_large_sweep_is_flagged_not_vetoed():
    candidates = [
        build_package(
            candidate_id="cand-quant",
            trader_id=SpecialistId.QUANT_TRADER,
            additional_fields={DECLARED_RUN_COUNT_KEY: 50},
        )
    ]
    agent = RiskAgentImpl(
        audit_reader=StaticAuditReader(undeclared_sweep_entries()),
    )
    response = review(
        agent,
        build_request(candidates, audit_reference="audit-round-1"),
    )

    decision = decision_for(response, "cand-quant")
    assert decision.verdict is RiskVerdict.APPROVE
    sweep_check = checks_by_id(
        decision.check_results,
        RiskCheckId.BEST_OF_N_DISCLOSURE,
    )[0]
    assert sweep_check.verdict is RiskCheckVerdict.FLAG
    assert any("50" in flag for flag in decision.reporting_flags)


def test_missing_canonical_metric_vetoes():
    package = build_package(
        candidate_id="cand-technical",
        trader_id=SpecialistId.TECHNICAL_TRADER,
        metrics={**CLEAN_METRICS, "sharpe_ratio": None},
    )
    response = review(RiskAgentImpl(), build_request([package]))

    decision = decision_for(response, "cand-technical")
    assert decision.verdict is RiskVerdict.VETO
    assert RiskCheckId.FULL_CANONICAL_METRIC_SET in decision.veto_reason_codes


def test_missing_baseline_vetoes():
    package = build_package(
        candidate_id="cand-technical",
        trader_id=SpecialistId.TECHNICAL_TRADER,
        benchmark=None,
        benchmark_metrics={},
    )
    response = review(RiskAgentImpl(), build_request([package]))

    decision = decision_for(response, "cand-technical")
    assert RiskCheckId.SAME_TERMS_BASELINE in decision.veto_reason_codes


def test_data_past_as_of_boundary_vetoes_test_set_lock():
    package = build_package(
        candidate_id="cand-technical",
        trader_id=SpecialistId.TECHNICAL_TRADER,
        ledger_resolved_end=datetime.combine(
            AS_OF + timedelta(days=30),
            datetime.min.time(),
            tzinfo=timezone.utc,
        ),
    )
    response = review(RiskAgentImpl(), build_request([package]))

    decision = decision_for(response, "cand-technical")
    assert decision.verdict is RiskVerdict.VETO
    assert RiskCheckId.TEST_SET_LOCK in decision.veto_reason_codes


def test_test_set_lock_survives_a_json_round_trip():
    """Graph state is JSON, so split dates reach Risk as ISO strings."""

    # The only lock violation here lives in the split field, which is the
    # branch that reads ledger additional_fields.
    package = build_package(
        candidate_id="cand-technical",
        trader_id=SpecialistId.TECHNICAL_TRADER,
        validation_split_end=AS_OF + timedelta(days=30),
    )
    round_tripped = RiskReviewRequest.model_validate(
        build_request([package]).model_dump(mode="json")
    )
    ledger = round_tripped.candidates[0].backtest_result.ledger_entry
    assert isinstance(
        ledger.additional_fields["validation_split"]["test_end_date"],
        str,
    )

    response = review(RiskAgentImpl(), round_tripped)
    decision = decision_for(response, "cand-technical")
    assert RiskCheckId.TEST_SET_LOCK in decision.veto_reason_codes


def test_round_budget_requires_stability_evidence():
    history = StaticHistoryReader(
        [
            {"round_number": 1, "vetoed": []},
            {"round_number": 2, "vetoed": []},
            {"round_number": 3, "vetoed": []},
        ]
    )
    agent = RiskAgentImpl(history_reader=history)

    exhausted = build_package(
        candidate_id="cand-technical",
        trader_id=SpecialistId.TECHNICAL_TRADER,
    )
    response = review(
        agent,
        build_request(
            [exhausted],
            round_number=4,
            history_reference="history-ref",
        ),
    )
    decision = decision_for(response, "cand-technical")
    assert RiskCheckId.VALIDATION_TOUCH_BUDGET in decision.veto_reason_codes

    stabilized = build_package(
        candidate_id="cand-technical",
        trader_id=SpecialistId.TECHNICAL_TRADER,
        additional_fields={
            STABILITY_EVIDENCE_KEY: {"parameter_perturbation_pct": 20},
        },
    )
    response = review(
        agent,
        build_request(
            [stabilized],
            round_number=4,
            history_reference="history-ref",
        ),
    )
    assert (
        decision_for(response, "cand-technical").verdict is RiskVerdict.APPROVE
    )


def test_cosmetic_resurrection_of_vetoed_strategy_vetoes():
    package = build_package(
        candidate_id="cand-technical-v2",
        trader_id=SpecialistId.TECHNICAL_TRADER,
        parameters={"lookback": 20, "z_entry": 1.5},
    )
    agent = RiskAgentImpl(
        history_reader=StaticHistoryReader(
            [
                {
                    "round_number": 1,
                    "vetoed": [
                        {
                            "candidate_id": "cand-technical",
                            "strategy_name": "renamed-differently",
                            "parameters": {"lookback": 20, "z_entry": 1.5},
                            "veto_reason_codes": ["CP-2"],
                        }
                    ],
                }
            ]
        ),
    )
    response = review(
        agent,
        build_request(
            [package],
            round_number=2,
            history_reference="history-ref",
        ),
    )

    decision = decision_for(response, "cand-technical-v2")
    assert RiskCheckId.NO_COSMETIC_RESURRECTION in decision.veto_reason_codes


def test_identical_rules_across_lenses_flag_duplication():
    shared = {"lookback": 20, "z_entry": 1.5}
    candidates = [
        build_package(
            candidate_id="cand-technical",
            trader_id=SpecialistId.TECHNICAL_TRADER,
            parameters=shared,
        ),
        build_package(
            candidate_id="cand-quant",
            trader_id=SpecialistId.QUANT_TRADER,
            parameters=shared,
        ),
    ]
    response = review(RiskAgentImpl(), build_request(candidates))

    duplication = checks_by_id(
        response.round_check_results,
        RiskCheckId.LENS_DUPLICATION,
    )[0]
    assert duplication.verdict is RiskCheckVerdict.FLAG
    assert "cand-technical ~ cand-quant" in duplication.summary


def test_borrowed_evidence_from_another_lens_vetoes():
    borrower = build_package(
        candidate_id="cand-technical",
        trader_id=SpecialistId.TECHNICAL_TRADER,
        extra_evidence_ids=("cand-quant.result",),
    )
    owner = build_package(
        candidate_id="cand-quant",
        trader_id=SpecialistId.QUANT_TRADER,
    )
    response = review(RiskAgentImpl(), build_request([borrower, owner]))

    decision = decision_for(response, "cand-technical")
    assert RiskCheckId.NO_BORROWED_EVIDENCE in decision.veto_reason_codes
    assert decision_for(response, "cand-quant").verdict is RiskVerdict.APPROVE


def test_model_judgment_can_escalate_but_never_downgrade():
    judgment = RiskJudgment(
        collective_critiques=["Both lenses rely on one regime."],
        candidate_critiques={
            "cand-technical": ["Hypothesis does not explain 2018 drawdown."],
        },
        escalations=[
            JudgmentEscalation(
                check_id=RiskCheckId.LENS_DUPLICATION,
                candidate_id=None,
                verdict="veto",
                summary=(
                    "The two candidates trade the same signal with cosmetic "
                    "parameter changes; they are one hypothesis."
                ),
            ),
            # An equal-or-lower severity proposal must be ignored rather than
            # soften the standing round verdict.
            JudgmentEscalation(
                check_id=RiskCheckId.MULTIPLE_COMPARISON_DISCLOSURE,
                candidate_id=None,
                verdict="flag",
                summary="Redundant disclosure suggestion.",
            ),
        ],
    )
    client = ScriptedModelClient(judgment)
    response = review(
        RiskAgentImpl(model_client=client),
        build_request(three_clean_candidates()),
    )

    duplication_results = checks_by_id(
        response.round_check_results,
        RiskCheckId.LENS_DUPLICATION,
    )
    assert any(
        result.verdict is RiskCheckVerdict.VETO and not result.deterministic
        for result in duplication_results
    )
    assert response.blocked_progression
    assert (
        len(
            checks_by_id(
                response.round_check_results,
                RiskCheckId.MULTIPLE_COMPARISON_DISCLOSURE,
            )
        )
        == 1
    )
    technical = decision_for(response, "cand-technical")
    assert technical.critiques == ["Hypothesis does not explain 2018 drawdown."]
    assert client.contexts[0].workflow_id == WORKFLOW_ID


def test_model_failure_degrades_to_deterministic_review():
    class FailingModelClient:
        async def generate_structured(self, **kwargs):
            raise TimeoutError("provider timeout")

    response = review(
        RiskAgentImpl(model_client=FailingModelClient()),
        build_request(three_clean_candidates()),
    )

    assert len(response.decisions) == 3
    assert any(
        "Model judgment was unavailable" in critique
        for critique in response.collective_critiques
    )


def test_impl_satisfies_the_risk_agent_protocol():
    from agents import RiskAgent

    assert isinstance(RiskAgentImpl(), RiskAgent)


def test_graph_node_adapter_round_trips_state():
    request = build_request(three_clean_candidates())
    node = make_risk_review_node(RiskAgentImpl())
    update = asyncio.run(
        node({"risk_review_request": request.model_dump(mode="json")})
    )

    response = RiskReviewResponse.model_validate(
        update["risk_review_response"]
    )
    assert response.request_id == request.request_id
    assert len(response.decisions) == 3
