"""Registry-facing contract for a hireable Technical Trader."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from .common import ContractModel, NonEmptyStr


class DependencyConfirmationStatus(StrEnum):
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"


class AgentDependency(ContractModel):
    name: NonEmptyStr
    owner: NonEmptyStr
    contract: NonEmptyStr
    confirmation_status: DependencyConfirmationStatus
    required_to_run: bool = True
    notes: list[NonEmptyStr] = Field(default_factory=list)


class HireableTechnicalTraderCard(ContractModel):
    agent_id: Literal["technical_trader_agent"]
    display_name: Literal["Technical Trader Agent"]
    version: NonEmptyStr
    specialty: Literal["technical_trading"]
    hireable: Literal[True]
    implementation_status: Literal["adapter_integration_pending"]
    input_contract: Literal["PMMandate"]
    output_contract: Literal["TraderStrategyPackage"]
    capabilities: list[NonEmptyStr] = Field(min_length=1)
    owned_tools: list[NonEmptyStr] = Field(min_length=1)
    external_dependencies: list[AgentDependency] = Field(min_length=1)


def technical_trader_agent_card() -> HireableTechnicalTraderCard:
    return HireableTechnicalTraderCard(
        agent_id="technical_trader_agent",
        display_name="Technical Trader Agent",
        version="0.2.0",
        specialty="technical_trading",
        hireable=True,
        implementation_status="adapter_integration_pending",
        input_contract="PMMandate",
        output_contract="TraderStrategyPackage",
        capabilities=[
            "dynamic_technical_strategy_generation",
            "point_in_time_ohlcv_request",
            "support_resistance_detection",
            "head_and_shoulders_detection",
            "inverse_head_and_shoulders_detection",
            "deterministic_backtest_request",
            "deterministic_backtest_interpretation",
            "partial_failure_package",
        ],
        owned_tools=[
            "DeterministicTechnicalAnalysisToolkit.support_resistance",
            "DeterministicTechnicalAnalysisToolkit.head_and_shoulders",
        ],
        external_dependencies=[
            AgentDependency(
                name="model_client",
                owner="LLM adapter owner",
                contract="ModelClient",
                confirmation_status="provisional",
                notes=[
                    "Provider and model are intentionally replaceable.",
                    "Adapter must return structured output and usage metadata.",
                ],
            ),
            AgentDependency(
                name="data_service",
                owner="Data Service teammate",
                contract="DataService",
                confirmation_status="provisional",
                notes=[
                    "Must supply point-in-time OHLCV and provenance.",
                    "Final payload adapter remains to be confirmed.",
                ],
            ),
            AgentDependency(
                name="backtest_engine",
                owner="Backtest Engine teammate",
                contract="BacktestEngine",
                confirmation_status="provisional",
                notes=[
                    "Must execute candidate rules deterministically.",
                    "No engine implementation is bundled with this agent.",
                ],
            ),
            AgentDependency(
                name="graph_state",
                owner="State Graph and workflow owners",
                contract=(
                    "make_langgraph_node callable or optional single-node "
                    "LangGraph adapter"
                ),
                confirmation_status="provisional",
                required_to_run=False,
                notes=[
                    "State keys are configurable at adapter construction.",
                    (
                        "The Technical Trader agent does not define the "
                        "production topology."
                    ),
                    "The optional adapter supports langgraph>=1.2,<2.",
                ],
            ),
        ],
    )
