"""Technical Trader Agent."""

from collections.abc import Sequence

from protocols import SpecialistId

from ..benchmark import BenchmarkSelectionPolicy
from ..execution import ExecutionPolicy
from ..model_client import MetricsSink, ModelClient
from ..prompts import (
    TECHNICAL_LENS_REQUIREMENTS,
    TECHNICAL_TRADER_SYSTEM_PROMPT,
)
from ..services import BacktestEngine, DataService, ValidationSplitPolicy
from ..tools import (
    ArtifactPayloadTechnicalInputAdapter,
    DeterministicTechnicalAnalysisToolkit,
    TechnicalAnalysisInputAdapter,
    TechnicalAnalysisToolkit,
)
from .trader import StagedTraderAgent


class TechnicalTraderAgent(StagedTraderAgent):
    trader_id = SpecialistId.TECHNICAL_TRADER

    def __init__(
        self,
        *,
        model_client: ModelClient,
        data_service: DataService,
        backtest_engine: BacktestEngine,
        available_executors: Sequence[str],
        validation_split_policy: ValidationSplitPolicy | None = None,
        technical_input_adapter: TechnicalAnalysisInputAdapter | None = None,
        technical_toolkit: TechnicalAnalysisToolkit | None = None,
        benchmark_selection_policy: BenchmarkSelectionPolicy | None = None,
        metrics_sink: MetricsSink | None = None,
        execution_policy: ExecutionPolicy | None = None,
    ) -> None:
        super().__init__(
            agent_id="technical_trader_agent",
            model_client=model_client,
            data_service=data_service,
            backtest_engine=backtest_engine,
            available_executors=available_executors,
            validation_split_policy=validation_split_policy,
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
            benchmark_selection_policy=benchmark_selection_policy,
            metrics_sink=metrics_sink,
            execution_policy=execution_policy,
        )

    @property
    def capabilities(self) -> tuple[str, ...]:
        return (
            "technical_candidate_generation",
            "technical_candidate_self_review",
            "multi_asset_portfolio_generation",
            "price_volume_data_request",
            "support_resistance_detection",
            "head_and_shoulders_detection",
            "inverse_head_and_shoulders_detection",
            "moving_average_analysis",
            "relative_volume_analysis",
            "deterministic_backtest_interpretation",
            "deterministic_benchmark_fallback_selection",
        )
