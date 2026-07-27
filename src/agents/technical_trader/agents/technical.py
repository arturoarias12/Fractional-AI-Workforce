"""Technical Trader Agent."""

from ..execution import ExecutionPolicy
from ..model_client import MetricsSink, ModelClient
from ..models.common import TraderType
from ..models.hireability import (
    HireableTechnicalTraderCard,
    technical_trader_agent_card,
)
from ..prompts import (
    TECHNICAL_LENS_REQUIREMENTS,
    TECHNICAL_TRADER_SYSTEM_PROMPT,
)
from ..services import BacktestEngine, DataService
from ..tools import (
    ArtifactPayloadTechnicalInputAdapter,
    DeterministicTechnicalAnalysisToolkit,
    TechnicalAnalysisInputAdapter,
    TechnicalAnalysisToolkit,
)
from .trader import TraderAgent


class TechnicalTraderAgent(TraderAgent):
    trader_type = TraderType.TECHNICAL

    def __init__(
        self,
        *,
        model_client: ModelClient,
        data_service: DataService,
        backtest_engine: BacktestEngine,
        technical_input_adapter: TechnicalAnalysisInputAdapter | None = None,
        technical_toolkit: TechnicalAnalysisToolkit | None = None,
        metrics_sink: MetricsSink | None = None,
        execution_policy: ExecutionPolicy | None = None,
    ) -> None:
        super().__init__(
            agent_id="technical_trader_agent",
            model_client=model_client,
            data_service=data_service,
            backtest_engine=backtest_engine,
            technical_input_adapter=(
                technical_input_adapter
                if technical_input_adapter is not None
                else ArtifactPayloadTechnicalInputAdapter()
            ),
            technical_toolkit=(
                technical_toolkit
                if technical_toolkit is not None
                else DeterministicTechnicalAnalysisToolkit()
            ),
            system_prompt=TECHNICAL_TRADER_SYSTEM_PROMPT,
            lens_requirements=TECHNICAL_LENS_REQUIREMENTS,
            metrics_sink=metrics_sink,
            execution_policy=execution_policy,
        )

    @property
    def capabilities(self) -> tuple[str, ...]:
        return (
            "technical_candidate_generation",
            "price_volume_data_request",
            "support_resistance_detection",
            "head_and_shoulders_detection",
            "inverse_head_and_shoulders_detection",
            "deterministic_backtest_interpretation",
        )

    @property
    def agent_card(self) -> HireableTechnicalTraderCard:
        """Return registry metadata without coupling to a registry implementation."""

        return technical_trader_agent_card()
