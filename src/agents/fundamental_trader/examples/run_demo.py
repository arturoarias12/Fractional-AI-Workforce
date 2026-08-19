"""End-to-end smoke test: Fundamental Trader against the composite DataService.

Run from the repository root (needs ``pip install -e .[fundamental-demo]``;
no API key required, but ``ETF_info.xlsx`` must be present at the repo root
or passed explicitly):

    python -m agents.fundamental_trader.examples.run_demo

This wires the real ``FundamentalTraderAgent`` and the real, shared
``DeterministicBacktestEngine`` to:

  * ``services.data_service.YFinanceBacktestDataResolver`` for backtest
    price data, same as the other trader agents use.
  * ``FundamentalMetadataDataService`` (this package's own composite
    DataService) for the combined PRICE_VOLUME + ETF_METADATA fetch -
    the shared DataService doesn't serve ETF_METADATA yet, so this fills
    that gap locally until it does. See ``static_data_service.py``.

Fundamental Trader's own code never talks to yfinance or ETF_info.xlsx
directly; it only calls ``data_service.fetch(data_request)`` on whatever
``DataService`` it is handed, so swapping the shared DataService in later
(once it grows an ETF_METADATA path) is purely a wiring change here.

Note: this demo scans the full 120-ticker ``DEFAULT_UNIVERSE`` by default,
same fixture universe Quant Trader's demo uses. That means up to 120 live
yfinance calls per run, so it is noticeably slower than a small-subset scan.
Trim ``FULL_UNIVERSE`` below for a faster run.
"""

from __future__ import annotations

import asyncio
from datetime import date

from protocols import PMMandate

from services import YFinanceBacktestDataResolver  # noqa: F401 - kept for reference, not used below

from tools import DeterministicBacktestEngine

from .. import FundamentalTraderAgent, FundamentalTraderRuntime, category_deviation_executor
from agents.quant_trader.examples.static_data_service import DEFAULT_UNIVERSE  # full 120-ticker fixture universe
from .backtest_resolver import FundamentalBacktestDataResolver
from .static_data_service import FundamentalMetadataDataService
from .validation_split import PercentileValidationSplitPolicy

# Full 120-ticker universe. Swap in a shorter list here for a faster run.
FULL_UNIVERSE = list(DEFAULT_UNIVERSE)


async def main() -> None:
    data_service = FundamentalMetadataDataService()
    backtest_engine = DeterministicBacktestEngine(
        data_resolver=FundamentalBacktestDataResolver(),
        strategy_executors=[category_deviation_executor],
    )
    validation_split_policy = PercentileValidationSplitPolicy(train_fraction=0.8)

    agent = FundamentalTraderAgent(
        data_service=data_service,
        backtest_engine=backtest_engine,
        validation_split_policy=validation_split_policy,
    )
    runtime = FundamentalTraderRuntime(agent=agent)

    mandate = PMMandate(
        workflow_id="demo-workflow",
        task_id="demo-task",
        as_of_date=date.today(),
        investment_objective=(
            "Research-stage exploration of ETF category-benchmark deviation "
            "strategies across the permitted universe."
        ),
        permitted_asset_universe=FULL_UNIVERSE,
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
