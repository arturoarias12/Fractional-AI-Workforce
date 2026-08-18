"""Acceptance tests for the Fundamental Trader.

Uses small, synthetic, hand-built price/metadata fixtures rather than the
real 120-ticker ETF_info.xlsx / ETF_historical_prices.xlsx files, so these
tests are hermetic, fast, and deterministic. The real files were used for
a manual offline end-to-end run during development (see
docs/fundamental_trader.md) - these tests exercise the same code paths at
a scale suited to CI.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

from protocols import (
    BacktestRequest,
    DataArtifact,
    DataCategory,
    DataProvenance,
    DataRequest,
    DataResponse,
    PMMandate,
)
from tools import DeterministicBacktestEngine, PriceBar, ResolvedBacktestData

from agents.fundamental_trader import (
    FundamentalTraderAgent,
    FundamentalTraderRuntime,
    category_deviation_executor,
    classify_issuer_tier,
)
from agents.fundamental_trader.data_adapter import ETFFundamentals
from agents.fundamental_trader.rule_generator import propose_category_deviations


def _build_bars(symbol: str, closes: list[float], start: date) -> tuple[PriceBar, ...]:
    bars = []
    for i, close in enumerate(closes):
        day = start + timedelta(days=i)
        bars.append(PriceBar(
            symbol=symbol,
            timestamp=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
            open=close, high=close, low=close, close=close,
        ))
    return tuple(bars)


def _synthetic_panel() -> dict[str, tuple[PriceBar, ...]]:
    """Two major-tier benchmark peers tracking together, one boutique-tier
    ticker in the same category that has recently diverged sharply -
    exactly the pattern propose_category_deviations should catch.
    """
    start = date(2023, 1, 2)
    n = 260  # a bit over a trading year

    base = 100.0
    peer_a_closes: list[float] = []
    peer_b_closes: list[float] = []
    boutique_closes: list[float] = []
    price = base
    for i in range(n):
        drift = 0.0005 * (i % 7 - 3)  # small shared wiggle so peers correlate
        price = price * (1 + drift)
        peer_a_closes.append(price * 1.0)
        peer_b_closes.append(price * 1.01)
        if i < n - 20:
            boutique_closes.append(price * 0.99)
        else:
            # sharp recent divergence in the final 20 trading days
            gap = 0.01 * (i - (n - 20))
            boutique_closes.append(price * (0.99 - gap))

    return {
        "MAJA": _build_bars("MAJA", peer_a_closes, start),
        "MAJB": _build_bars("MAJB", peer_b_closes, start),
        "BOUT": _build_bars("BOUT", boutique_closes, start),
    }


def _synthetic_fundamentals() -> dict[str, ETFFundamentals]:
    return {
        "MAJA": ETFFundamentals(ticker="MAJA", category="Test Category", fund_family="iShares", issuer_tier="major"),
        "MAJB": ETFFundamentals(ticker="MAJB", category="Test Category", fund_family="Vanguard", issuer_tier="major"),
        "BOUT": ETFFundamentals(ticker="BOUT", category="Test Category", fund_family="ARK ETF Trust", issuer_tier="boutique"),
    }


class _FakeDataService:
    def __init__(self, panel, fundamentals) -> None:
        self._panel = panel
        self._fundamentals = fundamentals

    async def fetch(self, request: DataRequest) -> DataResponse:
        now = datetime.now(timezone.utc)
        price_artifact = DataArtifact(
            artifact_id=f"{request.request_id}.prices",
            category=DataCategory.PRICE_VOLUME,
            description="Synthetic test prices",
            data_reference="fixture::prices",
            asset_scope=sorted(self._panel),
            provenance=[DataProvenance(
                provenance_id=f"{request.request_id}.prices.prov",
                provider="fixture", source_reference="synthetic",
                retrieved_at=now, point_in_time_verified=True,
            )],
            analysis_payload=dict(self._panel),
        )
        meta_payload = {
            t: {"category": f.category, "fund_family": f.fund_family, "issuer_tier": f.issuer_tier}
            for t, f in self._fundamentals.items()
        }
        meta_artifact = DataArtifact(
            artifact_id=f"{request.request_id}.meta",
            category=DataCategory.ETF_METADATA,
            description="Synthetic test metadata",
            data_reference="fixture::metadata",
            asset_scope=sorted(meta_payload),
            provenance=[DataProvenance(
                provenance_id=f"{request.request_id}.meta.prov",
                provider="fixture", source_reference="synthetic",
                retrieved_at=now, point_in_time_verified=True,
            )],
            analysis_payload=meta_payload,
        )
        return DataResponse(
            response_id=f"{request.request_id}.response",
            request_id=request.request_id,
            lineage=request.lineage,
            as_of_date=request.as_of_date,
            complete=True,
            artifacts=[price_artifact, meta_artifact],
        )


class _FakeBacktestResolver:
    def __init__(self, panel) -> None:
        self._panel = panel

    async def resolve(self, request: BacktestRequest) -> ResolvedBacktestData:
        params = request.candidate.parameters
        symbols = [params["ticker"]] + list(params.get("benchmark_tickers", []))
        bars = tuple(bar for s in symbols if s in self._panel for bar in self._panel[s])
        return ResolvedBacktestData(data_references=("fixture",), bars=bars)


class _EmptyDataService:
    async def fetch(self, request: DataRequest) -> DataResponse:
        return DataResponse(
            response_id=f"{request.request_id}.response",
            request_id=request.request_id,
            lineage=request.lineage,
            as_of_date=request.as_of_date,
            complete=False,
            artifacts=[],
            unavailable_fields=["close", "category"],
        )


def _build_mandate(universe: list[str]) -> PMMandate:
    return PMMandate(
        workflow_id="test-workflow",
        task_id="test-task",
        as_of_date=date(2023, 12, 1),
        investment_objective="Unit test of Fundamental Trader category-deviation logic.",
        permitted_asset_universe=universe,
    )


def test_classify_issuer_tier_splits_major_and_boutique() -> None:
    assert classify_issuer_tier("iShares") == "major"
    assert classify_issuer_tier("Vanguard") == "major"
    assert classify_issuer_tier("ARK ETF Trust") == "boutique"
    assert classify_issuer_tier("Some Fund Family Not In The List") == "boutique"


def test_propose_category_deviations_finds_the_planted_divergence() -> None:
    panel = _synthetic_panel()
    fundamentals = _synthetic_fundamentals()

    proposals = propose_category_deviations(panel, fundamentals, top_n=3)

    assert proposals, "expected at least one candidate from the planted divergence"
    best = proposals[0]
    assert best.ticker == "BOUT"
    assert set(best.benchmark_tickers) == {"MAJA", "MAJB"}
    assert best.evidence.current_zscore < 0  # BOUT drifted below its benchmark


def test_agent_run_produces_eligible_package_for_a_real_divergence() -> None:
    panel = _synthetic_panel()
    fundamentals = _synthetic_fundamentals()

    agent = FundamentalTraderAgent(
        data_service=_FakeDataService(panel, fundamentals),
        backtest_engine=DeterministicBacktestEngine(
            data_resolver=_FakeBacktestResolver(panel),
            strategy_executors=[category_deviation_executor],
        ),
        validation_split_policy=_FixedPercentileSplit(0.97),
    )
    runtime = FundamentalTraderRuntime(agent=agent)

    mandate = _build_mandate(["MAJA", "MAJB", "BOUT"])
    package = asyncio.run(runtime.research(mandate))

    assert package.status.value == "completed"
    assert package.eligible_for_risk_review is True
    assert package.candidate_rule is not None
    assert package.candidate_rule.executor_id == "fundamental_trader.category_benchmark_deviation.v1"
    assert package.backtest_result is not None
    assert package.interpretation is not None
    # The documented data-gap limitation must always surface to Risk.
    assert any(
        "ISSUER_SCALE_TIER" in risk for risk in package.interpretation.overfitting_risks
    )


def test_agent_run_settles_failed_package_on_empty_data() -> None:
    agent = FundamentalTraderAgent(
        data_service=_EmptyDataService(),
        backtest_engine=DeterministicBacktestEngine(
            data_resolver=_FakeBacktestResolver({}),
            strategy_executors=[category_deviation_executor],
        ),
        validation_split_policy=_FixedPercentileSplit(0.85),
    )
    runtime = FundamentalTraderRuntime(agent=agent)

    mandate = _build_mandate(["MAJA", "MAJB", "BOUT"])
    package = asyncio.run(runtime.research(mandate))

    assert package.status.value == "failed"
    assert package.eligible_for_risk_review is False
    assert package.failures
    assert package.failures[0].stage == "fundamental_trader.data_service"


class _FixedPercentileSplit:
    """Minimal ValidationSplitPolicy for tests - avoids importing the demo module."""

    def __init__(self, train_fraction: float) -> None:
        self._train_fraction = train_fraction

    def resolve(self, *, task, plan, data_response):
        from agents.fundamental_trader.data_adapter import extract_price_panel
        from protocols import ValidationSplit

        panel = extract_price_panel(data_response)
        all_dates = sorted({
            bar.timestamp.date() for bars in panel.values() for bar in bars
        })
        split_index = int(len(all_dates) * self._train_fraction)
        split_index = min(max(split_index, 1), len(all_dates) - 1)
        return ValidationSplit(
            test_start_date=all_dates[split_index],
            test_end_date=all_dates[-1],
        )
