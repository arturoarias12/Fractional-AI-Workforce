"""Dev-only stand-ins for the shared DataService and BacktestEngine data resolver.

NOT the shared Data Service. ``services.data_service.DataService`` and
``tools.backtest_engine.BacktestDataResolver`` are provisional team-owned
boundaries (see ``docs/implementation_boundaries.md``); Yiran's workstream
owns the real implementation. This module exists only so Quant Trader can
be run and demonstrated end to end today, against the static
``ETF_historical_prices.xlsx`` file, with no live API calls. Swap it out
once the real Data Service lands - nothing in ``agent.py`` or
``strategy.py`` needs to change, since both only depend on the
``DataService`` / ``BacktestDataResolver`` Protocols.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd

from protocols import (
    BacktestRequest,
    DataArtifact,
    DataCategory,
    DataProvenance,
    DataRequest,
    DataResponse,
)
from tools import PriceBar, ResolvedBacktestData

DEFAULT_XLSX_PATH = Path("ETF_historical_prices.xlsx")


@lru_cache(maxsize=4)
def _load_workbook(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def _bars_for_symbol(
    df: pd.DataFrame, symbol: str, as_of_date: date,
) -> tuple[PriceBar, ...]:
    rows = df[(df["ticker"] == symbol) & (df["date"] <= as_of_date)]
    bars = []
    for row in rows.sort_values("date").itertuples(index=False):
        open_, high, low, close = float(row.open), float(row.high), float(row.low), float(row.close)
        if min(open_, high, low, close) <= 0:
            continue  # a handful of source rows have non-positive prices; skip rather than fabricate
        # The source workbook occasionally has OHLC rounding artifacts where
        # low/high don't quite bound open/close (e.g. around split adjustments).
        # PriceBar enforces strict OHLC consistency, so clamp rather than drop
        # the whole bar - this is a data-cleaning step specific to this static
        # demo fixture, not something the real DataService should need.
        low = min(open_, high, low, close)
        high = max(open_, high, low, close)
        bars.append(PriceBar(
            symbol=symbol,
            timestamp=datetime.combine(row.date, datetime.min.time(), tzinfo=timezone.utc),
            open=open_,
            high=high,
            low=low,
            close=close,
        ))
    return tuple(bars)


class StaticExcelDataService:
    """Reads the static ETF workbook; satisfies ``quant_trader.services.DataService``."""

    def __init__(self, xlsx_path: Path | str = DEFAULT_XLSX_PATH) -> None:
        self._xlsx_path = str(xlsx_path)

    async def fetch(self, request: DataRequest) -> DataResponse:
        df = _load_workbook(self._xlsx_path)
        universe = (
            request.asset_universe
            if isinstance(request.asset_universe, list) and request.asset_universe
            else sorted(df["ticker"].unique())
        )

        panel = {
            symbol: _bars_for_symbol(df, symbol, request.as_of_date)
            for symbol in universe
        }
        panel = {symbol: bars for symbol, bars in panel.items() if bars}

        retrieved_at = datetime.now(timezone.utc)
        effective_at = datetime.combine(
            request.as_of_date, datetime.min.time(), tzinfo=timezone.utc,
        )
        artifact = DataArtifact(
            artifact_id=f"{request.request_id}.prices",
            category=DataCategory.PRICE_VOLUME,
            description="Static daily OHLC close prices from ETF_historical_prices.xlsx.",
            data_reference=f"static_xlsx::{self._xlsx_path}::{request.as_of_date.isoformat()}",
            schema_fields=["symbol", "timestamp", "open", "high", "low", "close"],
            asset_scope=list(panel.keys()),
            coverage_end=request.as_of_date,
            frequency="daily",
            provenance=[
                DataProvenance(
                    provenance_id=f"{request.request_id}.provenance",
                    provider="static_local_file",
                    source_reference=self._xlsx_path,
                    retrieved_at=retrieved_at,
                    point_in_time_verified=True,
                    effective_at=effective_at,
                ),
            ],
            analysis_payload=panel,
            limitations=[
                "Static local file, not a live/licensed market-data provider.",
                "No survivorship-bias or corporate-action adjustment audit performed.",
            ],
        )

        return DataResponse(
            response_id=f"{request.request_id}.response",
            request_id=request.request_id,
            lineage=request.lineage,
            as_of_date=request.as_of_date,
            complete=bool(panel),
            artifacts=[artifact] if panel else [],
            unavailable_fields=[] if panel else request.required_fields,
        )


class StaticExcelDataResolver:
    """Satisfies ``tools.backtest_engine.BacktestDataResolver`` from the same file."""

    def __init__(self, xlsx_path: Path | str = DEFAULT_XLSX_PATH) -> None:
        self._xlsx_path = str(xlsx_path)

    async def resolve(self, request: BacktestRequest) -> ResolvedBacktestData:
        df = _load_workbook(self._xlsx_path)
        symbols = sorted({
            str(value) for key, value in request.candidate.parameters.items()
            if key in ("ticker_a", "ticker_b")
        })
        bars: list[PriceBar] = []
        for symbol in symbols:
            bars.extend(_bars_for_symbol(df, symbol, request.as_of_date))

        return ResolvedBacktestData(
            data_references=tuple(request.data_references),
            bars=tuple(bars),
        )


__all__ = ["StaticExcelDataResolver", "StaticExcelDataService"]
