"""End-to-end smoke test: Quant Trader against the static ETF workbook.

Run from the repository root (needs ``ETF_historical_prices.xlsx`` there,
and ``pip install -e .[quant-demo]``):

    python -m agents.quant_trader.examples.run_demo

This wires the real ``QuantTraderAgent`` and the real, shared
``DeterministicBacktestEngine`` together with dev-only static adapters (see
``static_data_service.py`` and ``validation_split.py``) so the whole
propose -> backtest -> interpret pipeline runs without any live API or a
finalized shared DataService.
"""

from __future__ import annotations

import asyncio
from datetime import date

from protocols import PMMandate

from tools import DeterministicBacktestEngine

from .. import QuantTraderAgent, QuantTraderRuntime, cross_asset_spread_executor
from .static_data_service import StaticExcelDataResolver, StaticExcelDataService
from .validation_split import PercentileValidationSplitPolicy


async def main() -> None:
    data_service = StaticExcelDataService()
    backtest_engine = DeterministicBacktestEngine(
        data_resolver=StaticExcelDataResolver(),
        strategy_executors=[cross_asset_spread_executor],
    )
    validation_split_policy = PercentileValidationSplitPolicy(train_fraction=0.8)

    agent = QuantTraderAgent(
        data_service=data_service,
        backtest_engine=backtest_engine,
        validation_split_policy=validation_split_policy,
    )
    runtime = QuantTraderRuntime(agent=agent)

    mandate = PMMandate(
        workflow_id="demo-workflow",
        task_id="demo-task",
        as_of_date=date(2026, 6, 29),
        investment_objective=(
            "Research-stage exploration of cross-asset mean-reversion "
            "strategies across the permitted ETF universe."
        ),
    )

    package = await runtime.research(mandate)

    print(f"status: {package.status.value}")
    print(f"eligible_for_risk_review: {package.eligible_for_risk_review}")
    if package.failures:
        for failure in package.failures:
            print(f"failure [{failure.stage}]: {failure.message}")
        return

    print(f"hypothesis: {package.hypothesis}")
    print(f"specialty_evidence: {package.specialty_evidence}")
    if package.candidate_rule:
        print(f"executor_id: {package.candidate_rule.executor_id}")
        print(f"parameters: {package.candidate_rule.parameters}")
    if package.backtest_result:
        print(f"train metrics: {package.backtest_result.metrics}")
        print(f"test metrics: {package.backtest_result.out_of_sample_metrics}")
    if package.interpretation:
        print(f"summary: {package.interpretation.summary}")


if __name__ == "__main__":
    asyncio.run(main())
