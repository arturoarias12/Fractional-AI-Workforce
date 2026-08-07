"""End-to-end smoke test: Quant Trader against the shared DataService.

Run from the repository root (needs ``pip install -e .[quant-demo]``; no
API key required):

    python -m agents.quant_trader.examples.run_demo

This wires the real ``QuantTraderAgent`` and the real, shared
``DeterministicBacktestEngine`` to the project's shared ``services``
package (``services.data_service.YFinanceDataService`` /
``YFinanceBacktestDataResolver``) - the same DataService the other trader
agents call, instead of a Quant-Trader-only dev adapter. Quant Trader's
own code never talks to yfinance directly; it only calls
``data_service.fetch(data_request)`` on whatever ``DataService`` it is
handed, so this is purely a wiring change here in the demo entrypoint.

Everything Quant Trader used before the shared DataService existed -
its own yfinance/Stooq/FMP/Alpha Vantage/static-xlsx adapters - is kept
in ``static_data_service.py``, commented out, as documented fallbacks in
case the shared service is ever unavailable. See the commented import
block below and the "Fallback" swap-in block in ``main()``.

Note: the demo below restricts the mandate to a small ticker subset so it
runs quickly and stays polite to yfinance's unofficial, unauthenticated
endpoint. Widen ``permitted_asset_universe`` (or drop it entirely to scan
the full ``DEFAULT_UNIVERSE`` in ``static_data_service.py``) if you want a
bigger scan.
"""

from __future__ import annotations

import asyncio
from datetime import date

from protocols import PMMandate

from services import YFinanceBacktestDataResolver, YFinanceDataService

from tools import DeterministicBacktestEngine

from .. import QuantTraderAgent, QuantTraderRuntime, cross_asset_spread_executor
# Old process, kept as a fallback (Quant-Trader-only adapters, used before
# the shared services.data_service existed). All four are commented out in
# static_data_service.py itself, in the order they were actually tried:
# from .static_data_service import YFinanceDataResolver, YFinanceDataService  # dev-only yfinance adapter (superseded by services.data_service)
# from .static_data_service import FMPDataResolver, FMPDataService  # needs a paid FMP plan
# from .static_data_service import StooqDataResolver, StooqDataService  # endpoint 404s in practice
# from .static_data_service import AlphaVantageDataResolver, AlphaVantageDataService  # free tier too shallow (~100 days)
# from .static_data_service import StaticExcelDataResolver, StaticExcelDataService  # fully offline
from .validation_split import PercentileValidationSplitPolicy

DEMO_UNIVERSE = [
    "EWA", "EWC", "EWJ", "EWU", "QQQ", "IVV", "SCHD", "JEPI", "JEPQ", "XLK",
    "XLF", "XLE", "SMH", "GDX", "TLT",
]


async def main() -> None:
    # Primary path: the shared DataService (services.data_service), same as
    # the other trader agents use. Quant Trader's agent code only ever calls
    # data_service.fetch(data_request) - it has no idea yfinance is behind it.
    data_service = YFinanceDataService()
    backtest_engine = DeterministicBacktestEngine(
        data_resolver=YFinanceBacktestDataResolver(),
        strategy_executors=[cross_asset_spread_executor],
    )
    # Fallback (old process): Quant Trader's own dev-only adapters, kept in
    # static_data_service.py in case the shared DataService is unavailable.
    # Uncomment ONE pair and comment out the primary path above:
    # from .static_data_service import YFinanceDataResolver, YFinanceDataService
    # data_service = YFinanceDataService()
    # backtest_engine = DeterministicBacktestEngine(
    #     data_resolver=YFinanceDataResolver(),
    #     strategy_executors=[cross_asset_spread_executor],
    # )
    # ... or fully offline against the static xlsx fixture:
    # from .static_data_service import StaticExcelDataResolver, StaticExcelDataService
    # data_service = StaticExcelDataService()
    # backtest_engine = DeterministicBacktestEngine(
    #     data_resolver=StaticExcelDataResolver(),
    #     strategy_executors=[cross_asset_spread_executor],
    # )
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
        as_of_date=date.today(),
        investment_objective=(
            "Research-stage exploration of cross-asset mean-reversion "
            "strategies across the permitted ETF universe."
        ),
        permitted_asset_universe=DEMO_UNIVERSE,
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
