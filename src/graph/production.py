"""Executable LangGraph topology for the parallel-trader research loop.

The topology owns coordination only. Agent reasoning, model providers, data,
backtesting, Risk judgment, Reporting, Memory, and persistence are injected
through explicit node boundaries.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from protocols import (
    AgentExecutionState,
    AgentLifecycleRecord,
    ConstraintCheckStatus,
    MandateConstraintAssessment,
    PMDecision,
    PMDecisionType,
    PMMandate,
    ReportingOutput,
    ReportingRequest,
    RiskReviewRequest,
    RiskReviewResponse,
    RunStatus,
    SpecialistId,
    TRADER_IDS,
    TaskLineage,
    TraderFailure,
    TraderStrategyPackage,
)

from .nodes import (
    FUNDAMENTAL_TRADER_NODE,
    GraphNode,
    MEMORY_READ_NODE,
    MEMORY_WRITE_NODE,
    PM_DECISION_NODE,
    PM_INTAKE_NODE,
    PREPARE_PM_REVIEW_NODE,
    PREPARE_REPORTING_NODE,
    PREPARE_ROUND_NODE,
    QUANT_TRADER_NODE,
    REPORTING_NODE,
    RISK_NODE,
    TECHNICAL_TRADER_NODE,
    TRADER_JOIN_NODE,
    TRADER_NODE_IDS,
)
from .routing import PostDecisionRoute, route_after_pm_decision
from .state import WorkflowInput, WorkflowState
from .workflow import planned_workflow


PRODUCTION_GRAPH_NAME = "fractional_ai_workforce_research"
PORTFOLIO_MANAGER_ID = "portfolio_manager"

_TRADER_OUTPUT_KEYS: dict[SpecialistId, str] = {
    SpecialistId.TECHNICAL_TRADER: "technical_trader_package",
    SpecialistId.FUNDAMENTAL_TRADER: "fundamental_trader_package",
    SpecialistId.QUANT_TRADER: "quant_trader_package",
}
_TRADER_NODE_NAMES: dict[SpecialistId, str] = {
    SpecialistId.TECHNICAL_TRADER: TECHNICAL_TRADER_NODE,
    SpecialistId.FUNDAMENTAL_TRADER: FUNDAMENTAL_TRADER_NODE,
    SpecialistId.QUANT_TRADER: QUANT_TRADER_NODE,
}


class GraphAssemblyError(RuntimeError):
    """Raised when injected nodes or state violate orchestration contracts."""


@dataclass(frozen=True, slots=True)
class ProductionNodeSet:
    """Agent/service nodes required by the production topology."""

    memory_read: GraphNode
    pm_intake: GraphNode
    technical_trader: GraphNode
    fundamental_trader: GraphNode
    quant_trader: GraphNode
    risk_review: GraphNode
    reporting: GraphNode
    memory_write: GraphNode
    pm_decision: GraphNode | None = None

    def trader_node(self, trader_id: SpecialistId) -> GraphNode:
        return {
            SpecialistId.TECHNICAL_TRADER: self.technical_trader,
            SpecialistId.FUNDAMENTAL_TRADER: self.fundamental_trader,
            SpecialistId.QUANT_TRADER: self.quant_trader,
        }[trader_id]


def compile_production_workflow(
    nodes: ProductionNodeSet,
    *,
    checkpointer: Any,
    max_rounds: int,
    name: str = PRODUCTION_GRAPH_NAME,
) -> Any:
    """Compile the current PM → traders → Risk → Reporting → PM loop.

    A checkpointer is mandatory because the default PM decision node uses a
    durable human interrupt. The graph does not select a persistence backend;
    integration supplies one appropriate for the runtime environment.
    """

    if checkpointer is None:
        raise GraphAssemblyError(
            "The production workflow requires an injected checkpointer for "
            "durable PM review and resume."
        )
    if (
        isinstance(max_rounds, bool)
        or not isinstance(max_rounds, int)
        or max_rounds < 1
    ):
        raise GraphAssemblyError("max_rounds must be a positive integer.")

    # LangGraph intentionally accepts several callable signatures. Keeping the
    # builder dynamic avoids coupling injected project nodes to its broad
    # internal StateNode union while our own GraphNode boundary stays strict.
    builder: Any = StateGraph(
        state_schema=WorkflowState,
        input_schema=WorkflowInput,
    )
    builder.add_node(MEMORY_READ_NODE, nodes.memory_read)
    builder.add_node(PM_INTAKE_NODE, nodes.pm_intake)
    builder.add_node(
        PREPARE_ROUND_NODE,
        _make_prepare_round_node(max_rounds),
    )

    for trader_id in TRADER_IDS:
        builder.add_node(
            _TRADER_NODE_NAMES[trader_id],
            _wrap_trader_node(
                trader_id=trader_id,
                node=nodes.trader_node(trader_id),
            ),
        )

    builder.add_node(TRADER_JOIN_NODE, _prepare_risk_review)
    builder.add_node(RISK_NODE, _wrap_risk_node(nodes.risk_review))
    builder.add_node(PREPARE_REPORTING_NODE, _prepare_reporting)
    builder.add_node(REPORTING_NODE, _wrap_reporting_node(nodes.reporting))
    builder.add_node(PREPARE_PM_REVIEW_NODE, _prepare_pm_review)
    builder.add_node(
        PM_DECISION_NODE,
        nodes.pm_decision or human_pm_decision_node,
    )
    builder.add_node(MEMORY_WRITE_NODE, nodes.memory_write)

    builder.add_edge(START, MEMORY_READ_NODE)
    builder.add_edge(MEMORY_READ_NODE, PM_INTAKE_NODE)
    builder.add_edge(PM_INTAKE_NODE, PREPARE_ROUND_NODE)
    for trader_node in TRADER_NODE_IDS:
        builder.add_edge(PREPARE_ROUND_NODE, trader_node)
    builder.add_edge(list(TRADER_NODE_IDS), TRADER_JOIN_NODE)
    builder.add_edge(TRADER_JOIN_NODE, RISK_NODE)
    builder.add_conditional_edges(
        RISK_NODE,
        _route_after_risk,
        {
            "prepare_reporting": PREPARE_REPORTING_NODE,
            "human_review": PREPARE_PM_REVIEW_NODE,
        },
    )
    builder.add_edge(PREPARE_REPORTING_NODE, REPORTING_NODE)
    builder.add_edge(REPORTING_NODE, PREPARE_PM_REVIEW_NODE)
    builder.add_edge(PREPARE_PM_REVIEW_NODE, PM_DECISION_NODE)
    builder.add_edge(PM_DECISION_NODE, MEMORY_WRITE_NODE)
    builder.add_conditional_edges(
        MEMORY_WRITE_NODE,
        _route_after_memory_write,
        {
            PostDecisionRoute.WRITE_MEMORY_AND_START_NEXT_ROUND: (
                PM_INTAKE_NODE
            ),
            PostDecisionRoute.WRITE_MEMORY_AND_FINISH: END,
        },
    )

    compiled = builder.compile(checkpointer=checkpointer, name=name)
    _assert_compiled_topology_matches_blueprint(compiled)
    return compiled


def _make_prepare_round_node(max_rounds: int) -> GraphNode:
    def prepare_round(state: Mapping[str, Any]) -> Mapping[str, Any]:
        return _prepare_round(state, max_rounds=max_rounds)

    return prepare_round


def _prepare_round(
    state: Mapping[str, Any],
    *,
    max_rounds: int,
) -> dict[str, Any]:
    mandate = _mandate_from_state(state)
    round_number = _positive_round_number(state.get("round_number", 0)) + 1
    if "active_specialists" in state:
        try:
            active_specialists = tuple(
                str(SpecialistId(item))
                for item in state["active_specialists"]
            )
        except (TypeError, ValueError) as exc:
            raise GraphAssemblyError(
                "active_specialists contains an unknown agent identifier."
            ) from exc
    else:
        active_specialists = tuple(
            str(specialist_id) for specialist_id in SpecialistId
        )

    lifecycle = {
        str(trader_id): _lifecycle(
            agent_name=str(trader_id),
            current_state=(
                AgentExecutionState.ASSIGNED
                if trader_id in {
                    SpecialistId(item) for item in active_specialists
                }
                else AgentExecutionState.IDLE
            ),
            current_task=f"{mandate.task_id}.round-{round_number}",
            input_reference={
                "mandate_task_id": mandate.task_id,
                "round_number": round_number,
            },
            next_step=_TRADER_NODE_NAMES[trader_id],
        )
        for trader_id in TRADER_IDS
    }
    trader_branches = {
        str(trader_id): {
            "trader_id": str(trader_id),
            "active": str(trader_id) in active_specialists,
            "status": (
                RunStatus.PENDING.value
                if str(trader_id) in active_specialists
                else RunStatus.CANCELLED.value
            ),
            "failures": (),
        }
        for trader_id in TRADER_IDS
    }
    return {
        "workflow_id": mandate.workflow_id,
        "run_id": _run_id_from_state(state, mandate.workflow_id),
        "round_number": round_number,
        "max_rounds": max_rounds,
        "as_of_date": mandate.as_of_date.isoformat(),
        "pm_mandate": mandate.model_dump(mode="json"),
        "active_specialists": active_specialists,
        "technical_trader_package": None,
        "fundamental_trader_package": None,
        "quant_trader_package": None,
        "trader_branches": trader_branches,
        "trader_packages": {},
        "risk_review_request": None,
        "risk_review_response": None,
        "risk_failure": None,
        "surviving_candidate_ids": (),
        "reporting_request": None,
        "reporting_output": None,
        "reporting_failure": None,
        "pm_decision": None,
        "pending_human_action": None,
        "memory_record_id": None,
        "agent_lifecycle": lifecycle,
        "cancellation_requested": False,
    }


def _wrap_trader_node(
    *,
    trader_id: SpecialistId,
    node: GraphNode,
) -> GraphNode:
    output_key = _TRADER_OUTPUT_KEYS[trader_id]
    node_name = _TRADER_NODE_NAMES[trader_id]

    async def wrapped(state: Mapping[str, Any]) -> Mapping[str, Any]:
        mandate = _mandate_from_state(state)
        round_number = _positive_round_number(state.get("round_number", 1))
        if not _agent_is_active(state, trader_id):
            return {
                output_key: None,
                "trader_branches": {
                    str(trader_id): {
                        "trader_id": str(trader_id),
                        "active": False,
                        "status": RunStatus.CANCELLED.value,
                        "failures": (),
                    }
                },
                "agent_lifecycle": {
                    str(trader_id): _lifecycle(
                        agent_name=str(trader_id),
                        current_state=AgentExecutionState.IDLE,
                        current_task=None,
                        next_step=TRADER_JOIN_NODE,
                        additional_fields={"staffing_status": "benched"},
                    )
                },
            }

        started_at = _utc_now()
        try:
            raw_update = await _invoke_node(node, state)
            if output_key not in raw_update:
                raise GraphAssemblyError(
                    f"{node_name} must return state key {output_key!r}."
                )
            package = TraderStrategyPackage.model_validate(
                raw_update[output_key]
            )
            _validate_package_identity(package, mandate, trader_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            package = _failed_trader_package(
                trader_id=trader_id,
                mandate=mandate,
                round_number=round_number,
                stage=node_name,
                exc=exc,
            )

        completed_at = _utc_now()
        lifecycle_state = (
            AgentExecutionState.FAILED
            if package.status is RunStatus.FAILED
            else AgentExecutionState.COMPLETED
        )
        error_message = None
        if lifecycle_state is AgentExecutionState.FAILED:
            error_message = (
                package.failures[0].message
                if package.failures
                else "Trader package settled as failed without diagnostics."
            )
        package_json = package.model_dump(mode="json")
        return {
            output_key: package_json,
            "trader_branches": {
                str(trader_id): {
                    "trader_id": str(trader_id),
                    "active": True,
                    "lineage": package.lineage.model_dump(mode="json"),
                    "status": package.status.value,
                    "package": package_json,
                    "failures": tuple(
                        failure.model_dump(mode="json")
                        for failure in package.failures
                    ),
                }
            },
            "agent_lifecycle": {
                str(trader_id): _lifecycle(
                    agent_name=str(trader_id),
                    current_state=lifecycle_state,
                    current_task=package.lineage.task_id,
                    input_reference={
                        "mandate_task_id": mandate.task_id,
                        "round_number": round_number,
                    },
                    output_reference={
                        "package_id": package.package_id,
                        "status": package.status.value,
                        "eligible_for_risk_review": (
                            package.eligible_for_risk_review
                        ),
                    },
                    start_time=started_at,
                    end_time=completed_at,
                    next_step=TRADER_JOIN_NODE,
                    error_message=error_message,
                    additional_fields={
                        "result_status": package.status.value,
                    },
                )
            },
        }

    return wrapped


def _prepare_risk_review(state: Mapping[str, Any]) -> dict[str, Any]:
    mandate = _mandate_from_state(state)
    round_number = _positive_round_number(state.get("round_number", 1))
    packages: dict[str, TraderStrategyPackage] = {}
    candidates: list[TraderStrategyPackage] = []
    excluded: list[TraderStrategyPackage] = []

    for trader_id in TRADER_IDS:
        raw_package = state.get(_TRADER_OUTPUT_KEYS[trader_id])
        if raw_package is None:
            continue
        package = TraderStrategyPackage.model_validate(raw_package)
        _validate_package_identity(package, mandate, trader_id)
        packages[str(trader_id)] = package
        if package.eligible_for_risk_review:
            candidates.append(package)
        else:
            excluded.append(package)

    request = RiskReviewRequest(
        request_id=f"{mandate.task_id}.round-{round_number}.risk",
        mandate_task_id=mandate.task_id,
        as_of_date=mandate.as_of_date,
        round_number=round_number,
        candidates=candidates,
        excluded_packages=excluded,
        round_audit_summary_reference=state.get(
            "round_audit_summary_reference"
        ),
        provenance_record_ids=list(state.get("provenance_record_ids", ())),
        candidate_memo_references=dict(
            state.get("candidate_memo_references", {})
        ),
        round_history_reference=state.get("round_history_reference"),
        canonical_universe_id=state.get("canonical_universe_id"),
        evaluation_policy_id=state.get("evaluation_policy_id"),
    )
    risk_state = (
        AgentExecutionState.ASSIGNED
        if _agent_is_active(state, SpecialistId.RISK)
        else AgentExecutionState.IDLE
    )
    return {
        "trader_packages": {
            key: package.model_dump(mode="json")
            for key, package in packages.items()
        },
        "risk_review_request": request.model_dump(mode="json"),
        "agent_lifecycle": {
            str(SpecialistId.RISK): _lifecycle(
                agent_name=str(SpecialistId.RISK),
                current_state=risk_state,
                current_task=request.request_id,
                input_reference={
                    "candidate_count": len(candidates),
                    "excluded_package_count": len(excluded),
                    "round_number": round_number,
                },
                next_step=RISK_NODE,
                additional_fields={
                    "staffing_status": (
                        "active"
                        if risk_state is AgentExecutionState.ASSIGNED
                        else "benched"
                    )
                },
            )
        },
    }


def _wrap_risk_node(node: GraphNode) -> GraphNode:
    async def wrapped(state: Mapping[str, Any]) -> Mapping[str, Any]:
        request = RiskReviewRequest.model_validate(
            state.get("risk_review_request")
        )
        started_at = _utc_now()
        if not _agent_is_active(state, SpecialistId.RISK):
            message = (
                "Risk Agent is benched; progression requires explicit PM "
                "review and no Risk bypass is implied."
            )
            return {
                "risk_review_response": None,
                "risk_failure": _failure_record(
                    error_type="AgentInactive",
                    message=message,
                    stage=RISK_NODE,
                    requires_human_action=True,
                ),
                "agent_lifecycle": {
                    str(SpecialistId.RISK): _lifecycle(
                        agent_name=str(SpecialistId.RISK),
                        current_state=AgentExecutionState.FAILED,
                        current_task=request.request_id,
                        input_reference={"request_id": request.request_id},
                        start_time=started_at,
                        end_time=_utc_now(),
                        next_step=PREPARE_PM_REVIEW_NODE,
                        error_message=message,
                        additional_fields={"staffing_status": "benched"},
                    )
                },
            }

        try:
            raw_update = await _invoke_node(node, state)
            if "risk_review_response" not in raw_update:
                raise GraphAssemblyError(
                    "Risk node must return state key "
                    "'risk_review_response'."
                )
            response = RiskReviewResponse.model_validate(
                raw_update["risk_review_response"]
            )
            _validate_risk_response(request, response)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = _bounded_exception_message(exc)
            return {
                "risk_review_response": None,
                "risk_failure": _failure_record(
                    error_type=type(exc).__name__,
                    message=message,
                    stage=RISK_NODE,
                    requires_human_action=True,
                ),
                "agent_lifecycle": {
                    str(SpecialistId.RISK): _lifecycle(
                        agent_name=str(SpecialistId.RISK),
                        current_state=AgentExecutionState.FAILED,
                        current_task=request.request_id,
                        input_reference={"request_id": request.request_id},
                        start_time=started_at,
                        end_time=_utc_now(),
                        next_step=PREPARE_PM_REVIEW_NODE,
                        error_message=message,
                    )
                },
            }

        return {
            "risk_review_response": response.model_dump(mode="json"),
            "risk_failure": None,
            "surviving_candidate_ids": response.approved_candidate_ids(),
            "agent_lifecycle": {
                str(SpecialistId.RISK): _lifecycle(
                    agent_name=str(SpecialistId.RISK),
                    current_state=AgentExecutionState.COMPLETED,
                    current_task=request.request_id,
                    input_reference={"request_id": request.request_id},
                    output_reference={
                        "response_id": response.response_id,
                        "approved_candidate_ids": list(
                            response.approved_candidate_ids()
                        ),
                        "blocked_progression": response.blocked_progression,
                    },
                    start_time=started_at,
                    end_time=_utc_now(),
                    next_step=PREPARE_REPORTING_NODE,
                )
            },
        }

    return wrapped


def _prepare_reporting(state: Mapping[str, Any]) -> dict[str, Any]:
    mandate = _mandate_from_state(state)
    risk_response = RiskReviewResponse.model_validate(
        state.get("risk_review_response")
    )
    packages = {
        key: TraderStrategyPackage.model_validate(value)
        for key, value in dict(state.get("trader_packages", {})).items()
    }
    candidates_by_id = {
        package.candidate_id: package
        for package in packages.values()
        if package.candidate_id is not None
    }
    approved_ids = risk_response.approved_candidate_ids()
    missing = set(approved_ids) - set(candidates_by_id)
    if missing:
        raise GraphAssemblyError(
            "Risk approved candidate IDs absent from trader packages: "
            + ", ".join(sorted(missing))
        )
    request = ReportingRequest(
        request_id=f"{risk_response.request_id}.reporting",
        mandate_task_id=mandate.task_id,
        surviving_candidates=[
            candidates_by_id[candidate_id]
            for candidate_id in approved_ids
        ],
        risk_response=risk_response,
    )
    reporting_state = (
        AgentExecutionState.ASSIGNED
        if _agent_is_active(state, SpecialistId.REPORTING)
        else AgentExecutionState.IDLE
    )
    return {
        "reporting_request": request.model_dump(mode="json"),
        "agent_lifecycle": {
            str(SpecialistId.REPORTING): _lifecycle(
                agent_name=str(SpecialistId.REPORTING),
                current_state=reporting_state,
                current_task=request.request_id,
                input_reference={
                    "risk_response_id": risk_response.response_id,
                    "surviving_candidate_ids": list(approved_ids),
                },
                next_step=REPORTING_NODE,
                additional_fields={
                    "staffing_status": (
                        "active"
                        if reporting_state is AgentExecutionState.ASSIGNED
                        else "benched"
                    )
                },
            )
        },
    }


def _wrap_reporting_node(node: GraphNode) -> GraphNode:
    async def wrapped(state: Mapping[str, Any]) -> Mapping[str, Any]:
        request = ReportingRequest.model_validate(
            state.get("reporting_request")
        )
        started_at = _utc_now()
        if not _agent_is_active(state, SpecialistId.REPORTING):
            message = (
                "Reporting Agent is benched; PM review will receive the "
                "validated Risk response without a generated report."
            )
            return {
                "reporting_output": None,
                "reporting_failure": _failure_record(
                    error_type="AgentInactive",
                    message=message,
                    stage=REPORTING_NODE,
                    requires_human_action=True,
                ),
                "agent_lifecycle": {
                    str(SpecialistId.REPORTING): _lifecycle(
                        agent_name=str(SpecialistId.REPORTING),
                        current_state=AgentExecutionState.FAILED,
                        current_task=request.request_id,
                        input_reference={"request_id": request.request_id},
                        start_time=started_at,
                        end_time=_utc_now(),
                        next_step=PREPARE_PM_REVIEW_NODE,
                        error_message=message,
                        additional_fields={"staffing_status": "benched"},
                    )
                },
            }

        try:
            raw_update = await _invoke_node(node, state)
            if "reporting_output" not in raw_update:
                raise GraphAssemblyError(
                    "Reporting node must return state key 'reporting_output'."
                )
            output = ReportingOutput.model_validate(
                raw_update["reporting_output"]
            )
            if output.request_id != request.request_id:
                raise GraphAssemblyError(
                    "Reporting output request_id does not match its request."
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = _bounded_exception_message(exc)
            return {
                "reporting_output": None,
                "reporting_failure": _failure_record(
                    error_type=type(exc).__name__,
                    message=message,
                    stage=REPORTING_NODE,
                    requires_human_action=True,
                ),
                "agent_lifecycle": {
                    str(SpecialistId.REPORTING): _lifecycle(
                        agent_name=str(SpecialistId.REPORTING),
                        current_state=AgentExecutionState.FAILED,
                        current_task=request.request_id,
                        input_reference={"request_id": request.request_id},
                        start_time=started_at,
                        end_time=_utc_now(),
                        next_step=PREPARE_PM_REVIEW_NODE,
                        error_message=message,
                    )
                },
            }

        return {
            "reporting_output": output.model_dump(mode="json"),
            "reporting_failure": None,
            "agent_lifecycle": {
                str(SpecialistId.REPORTING): _lifecycle(
                    agent_name=str(SpecialistId.REPORTING),
                    current_state=AgentExecutionState.COMPLETED,
                    current_task=request.request_id,
                    input_reference={"request_id": request.request_id},
                    output_reference={"output_id": output.output_id},
                    start_time=started_at,
                    end_time=_utc_now(),
                    next_step=PREPARE_PM_REVIEW_NODE,
                )
            },
        }

    return wrapped


def _pm_review_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    workflow_id = str(state.get("workflow_id", "")).strip()
    if not workflow_id:
        raise GraphAssemblyError("PM review requires workflow_id.")
    surviving_ids = tuple(state.get("surviving_candidate_ids", ()))
    round_number = _positive_round_number(state.get("round_number", 1))
    max_rounds = _positive_limit(state.get("max_rounds"))
    allowed_decisions = [
        decision.value
        for decision in PMDecisionType
        if not (
            (
                decision is PMDecisionType.REQUEST_ANOTHER_ROUND
                and round_number >= max_rounds
            )
            or (
                decision is PMDecisionType.SELECT
                and not surviving_ids
            )
        )
    ]
    return {
        "schema_version": "0.1.0",
        "action": "portfolio_manager_decision_required",
        "workflow_id": workflow_id,
        "round_number": round_number,
        "max_rounds": max_rounds,
        "surviving_candidate_ids": list(surviving_ids),
        "reporting_output": state.get("reporting_output"),
        "risk_failure": state.get("risk_failure"),
        "reporting_failure": state.get("reporting_failure"),
        "allowed_decisions": allowed_decisions,
    }


def _prepare_pm_review(state: Mapping[str, Any]) -> dict[str, Any]:
    request_payload = _pm_review_payload(state)
    now = _utc_now()
    return {
        "pending_human_action": request_payload,
        "agent_lifecycle": {
            PORTFOLIO_MANAGER_ID: _lifecycle(
                agent_name=PORTFOLIO_MANAGER_ID,
                current_state=AgentExecutionState.WAITING_FOR_REVIEW,
                current_task=(
                    f"{request_payload['workflow_id']}.round-"
                    f"{request_payload['round_number']}.pm-review"
                ),
                input_reference={
                    "surviving_candidate_ids": request_payload[
                        "surviving_candidate_ids"
                    ],
                },
                start_time=now,
                next_step=PM_DECISION_NODE,
            )
        },
    }


def human_pm_decision_node(state: Mapping[str, Any]) -> Mapping[str, Any]:
    """Pause on a persisted checkpoint and validate the PM resume payload."""

    workflow_id = str(state.get("workflow_id", "")).strip()
    surviving_ids = tuple(state.get("surviving_candidate_ids", ()))
    round_number = _positive_round_number(state.get("round_number", 1))
    max_rounds = _positive_limit(state.get("max_rounds"))
    request_payload = dict(
        state.get("pending_human_action") or _pm_review_payload(state)
    )
    while True:
        resumed = interrupt(request_payload)
        if isinstance(resumed, Mapping) and "pm_decision" in resumed:
            resumed = resumed["pm_decision"]
        try:
            decision = PMDecision.model_validate(resumed)
            _validate_pm_decision(
                decision=decision,
                workflow_id=workflow_id,
                surviving_ids=surviving_ids,
                round_number=round_number,
                max_rounds=max_rounds,
            )
        except (ValidationError, GraphAssemblyError) as exc:
            request_payload = {
                **request_payload,
                "validation_error": _bounded_exception_message(exc),
            }
            continue
        break
    now = _utc_now()
    return {
        "pm_decision": decision.model_dump(mode="json"),
        "pending_human_action": None,
        "agent_lifecycle": {
            PORTFOLIO_MANAGER_ID: _lifecycle(
                agent_name=PORTFOLIO_MANAGER_ID,
                current_state=AgentExecutionState.COMPLETED,
                current_task=decision.decision_id,
                input_reference={
                    "surviving_candidate_ids": list(surviving_ids),
                },
                output_reference={
                    "decision": decision.decision.value,
                    "selected_candidate_id": (
                        decision.selected_candidate_id
                    ),
                },
                start_time=now,
                end_time=now,
                next_step=MEMORY_WRITE_NODE,
            )
        },
    }


def _route_after_risk(state: Mapping[str, Any]) -> str:
    if state.get("risk_review_response") is not None:
        return "prepare_reporting"
    return "human_review"


def _route_after_memory_write(
    state: Mapping[str, Any],
) -> PostDecisionRoute:
    decision = PMDecision.model_validate(state.get("pm_decision"))
    route = route_after_pm_decision(decision)
    if (
        route is PostDecisionRoute.WRITE_MEMORY_AND_START_NEXT_ROUND
        and _positive_round_number(state.get("round_number", 1))
        >= _positive_limit(state.get("max_rounds"))
    ):
        # The normal PM validator prevents this state. If an injected PM node
        # violates the contract, terminate safely rather than crashing after
        # Memory has already recorded the decision.
        return PostDecisionRoute.WRITE_MEMORY_AND_FINISH
    return route


def _assert_compiled_topology_matches_blueprint(compiled: Any) -> None:
    """Fail compilation if the public blueprint drifts from LangGraph."""

    blueprint = planned_workflow()
    drawable = compiled.get_graph()
    actual_nodes = {
        str(node_id)
        for node_id in drawable.nodes
        if str(node_id) not in {START, END}
    }
    expected_nodes = set(blueprint.node_ids)
    actual_edges = {
        (str(edge.source), str(edge.target))
        for edge in drawable.edges
        if str(edge.source) != START and str(edge.target) != END
    }
    expected_edges = {
        (edge.source, edge.target)
        for edge in blueprint.edges
    }
    if actual_nodes != expected_nodes or actual_edges != expected_edges:
        missing_nodes = sorted(expected_nodes - actual_nodes)
        unexpected_nodes = sorted(actual_nodes - expected_nodes)
        missing_edges = sorted(expected_edges - actual_edges)
        unexpected_edges = sorted(actual_edges - expected_edges)
        raise GraphAssemblyError(
            "The executable graph and framework-neutral workflow blueprint "
            "have drifted; "
            f"missing_nodes={missing_nodes}, "
            f"unexpected_nodes={unexpected_nodes}, "
            f"missing_edges={missing_edges}, "
            f"unexpected_edges={unexpected_edges}."
        )


async def _invoke_node(
    node: GraphNode,
    state: Mapping[str, Any],
) -> Mapping[str, Any]:
    result = node(state)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, Mapping):
        raise GraphAssemblyError(
            "Injected graph nodes must return a mapping state update."
        )
    return result


def _agent_is_active(
    state: Mapping[str, Any],
    agent_id: SpecialistId,
) -> bool:
    active = state.get("active_specialists")
    if active is None:
        return True
    try:
        normalized = {SpecialistId(item) for item in active}
    except (TypeError, ValueError) as exc:
        raise GraphAssemblyError(
            "active_specialists contains an unknown agent identifier."
        ) from exc
    return agent_id in normalized


def _mandate_from_state(state: Mapping[str, Any]) -> PMMandate:
    try:
        return PMMandate.model_validate(state.get("pm_mandate"))
    except ValidationError as exc:
        raise GraphAssemblyError(
            f"Graph state contains an invalid pm_mandate: {exc}"
        ) from exc


def _run_id_from_state(
    state: Mapping[str, Any],
    workflow_id: str,
) -> str:
    raw_run_id = state.get("run_id")
    if raw_run_id is None:
        return workflow_id
    run_id = str(raw_run_id).strip()
    if not run_id:
        raise GraphAssemblyError("run_id must be non-empty when supplied.")
    return run_id


def _validate_package_identity(
    package: TraderStrategyPackage,
    mandate: PMMandate,
    trader_id: SpecialistId,
) -> None:
    if package.trader_id is not trader_id:
        raise GraphAssemblyError(
            f"{trader_id} returned a package for {package.trader_id}."
        )
    if package.lineage.workflow_id != mandate.workflow_id:
        raise GraphAssemblyError(
            "Trader package workflow lineage does not match the mandate."
        )
    if package.mandate_reference != mandate.reference():
        raise GraphAssemblyError(
            "Trader package mandate reference does not match graph mandate."
        )


def _validate_risk_response(
    request: RiskReviewRequest,
    response: RiskReviewResponse,
) -> None:
    if response.request_id != request.request_id:
        raise GraphAssemblyError(
            "Risk response request_id does not match its request."
        )
    expected = {
        package.candidate_id
        for package in request.candidates
        if package.candidate_id is not None
    }
    actual = {decision.candidate_id for decision in response.decisions}
    if expected != actual:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise GraphAssemblyError(
            "Risk must return exactly one verdict per eligible candidate; "
            f"missing={missing}, unexpected={unexpected}."
        )


def _validate_pm_decision(
    *,
    decision: PMDecision,
    workflow_id: str,
    surviving_ids: tuple[str, ...],
    round_number: int,
    max_rounds: int,
) -> None:
    if decision.workflow_id != workflow_id:
        raise GraphAssemblyError(
            "PM decision workflow_id does not match graph workflow_id."
        )
    if (
        decision.decision is PMDecisionType.SELECT
        and decision.selected_candidate_id not in surviving_ids
    ):
        raise GraphAssemblyError(
            "PM may select only a Risk-approved surviving candidate."
        )
    if (
        decision.decision is PMDecisionType.REQUEST_ANOTHER_ROUND
        and round_number >= max_rounds
    ):
        raise GraphAssemblyError(
            "The configured round limit has been reached; another round "
            "cannot be requested."
        )


def _failed_trader_package(
    *,
    trader_id: SpecialistId,
    mandate: PMMandate,
    round_number: int,
    stage: str,
    exc: Exception,
) -> TraderStrategyPackage:
    lineage = TaskLineage(
        workflow_id=mandate.workflow_id,
        task_id=(
            f"{mandate.task_id}.round-{round_number}."
            f"{str(trader_id)}"
        ),
        parent_task_id=mandate.task_id,
        source_task_id=mandate.task_id,
    )
    return TraderStrategyPackage(
        package_id=f"{lineage.task_id}.package",
        trader_id=trader_id,
        lineage=lineage,
        mandate_reference=mandate.reference(),
        status=RunStatus.FAILED,
        constraint_assessment=MandateConstraintAssessment(
            status=ConstraintCheckStatus.NOT_EVALUATED,
            requires_risk_validation=True,
        ),
        failures=[
            TraderFailure(
                stage=stage,
                message=_bounded_exception_message(exc),
                retryable=isinstance(exc, (TimeoutError, ConnectionError)),
            )
        ],
        eligible_for_risk_review=False,
    )


def _failure_record(
    *,
    error_type: str,
    message: str,
    stage: str,
    requires_human_action: bool,
) -> dict[str, Any]:
    return {
        "error_type": error_type,
        "message": message,
        "stage": stage,
        "requires_human_action": requires_human_action,
        "occurred_at": _utc_now().isoformat(),
    }


def _lifecycle(
    *,
    agent_name: str,
    current_state: AgentExecutionState,
    current_task: str | None,
    input_reference: dict[str, Any] | None = None,
    output_reference: dict[str, Any] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    next_step: str | None = None,
    error_message: str | None = None,
    additional_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return AgentLifecycleRecord(
        agent_name=agent_name,
        current_state=current_state,
        current_task=current_task,
        input=input_reference,
        output=output_reference,
        start_time=start_time,
        end_time=end_time,
        next_step=next_step,
        error_message=error_message,
        additional_fields=additional_fields or {},
    ).model_dump(mode="json")


def _bounded_exception_message(exc: Exception) -> str:
    detail = " ".join(str(exc).split())
    message = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    return message[:1000]


def _positive_round_number(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GraphAssemblyError(
            "round_number must be a non-negative integer before preparation."
        )
    return value


def _positive_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GraphAssemblyError("max_rounds must be a positive integer.")
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "GraphAssemblyError",
    "PRODUCTION_GRAPH_NAME",
    "ProductionNodeSet",
    "compile_production_workflow",
    "human_pm_decision_node",
]
