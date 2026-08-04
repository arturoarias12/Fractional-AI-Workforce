"""Shared market-data helpers for trader agents and the backtest engine.

Same file on purpose (small prototype):

1. ``DataService`` / ``YFinanceDataService``
   ``fetch(DataRequest) -> DataResponse`` for Quant / Technical research.
2. ``YFinanceBacktestDataResolver``
   ``resolve(BacktestRequest) -> ResolvedBacktestData`` for the backtest engine.

Both paths download daily OHLC through the same yfinance helpers and return
the same ``PriceBar`` objects.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

import yfinance as yf

from protocols import (
    BacktestRequest,
    DataArtifact,
    DataCategory,
    DataProvenance,
    DataRequest,
    DataResponse,
)
from tools import PriceBar, ResolvedBacktestData

_LIMITATIONS = [
    "Data from yfinance (unofficial Yahoo Finance). Not a licensed feed.",
    "Prices are auto-adjusted; not true point-in-time as-of the mandate date.",
]


@runtime_checkable
class DataService(Protocol):
    async def fetch(self, request: DataRequest) -> DataResponse: ...


class YFinanceDataService:
    async def fetch(self, request: DataRequest) -> DataResponse:
        if not isinstance(request.asset_universe, list) or not request.asset_universe:
            raise ValueError("asset_universe must be a non-empty list of tickers")
        symbols = [str(s).upper().strip() for s in request.asset_universe if str(s).strip()]

        end = min(request.end_date or request.as_of_date, request.as_of_date)
        start = request.start_date or (end - timedelta(days=365 * 10))

        panel = await asyncio.to_thread(_download, symbols, start, end)

        now = datetime.now(timezone.utc)
        artifact = DataArtifact(
            artifact_id=f"{request.request_id}.prices",
            category=DataCategory.PRICE_VOLUME,
            description="Daily OHLCV from yfinance",
            data_reference=(
                f"yfinance::{','.join(sorted(panel))}::"
                f"{start.isoformat()}::{end.isoformat()}"
            ),
            schema_fields=["symbol", "timestamp", "open", "high", "low", "close"],
            asset_scope=sorted(panel),
            coverage_start=start,
            coverage_end=end,
            frequency=request.frequency or "daily",
            provenance=[
                DataProvenance(
                    provenance_id=f"{request.request_id}.provenance",
                    provider="yfinance",
                    source_reference="yahoo_finance",
                    retrieved_at=now,
                    point_in_time_verified=False,
                    effective_at=datetime.combine(
                        request.as_of_date, datetime.min.time(), tzinfo=timezone.utc
                    ),
                    notes=list(_LIMITATIONS),
                )
            ],
            analysis_payload=panel,
            limitations=list(_LIMITATIONS),
        )

        return DataResponse(
            response_id=f"{request.request_id}.response",
            request_id=request.request_id,
            lineage=request.lineage,
            as_of_date=request.as_of_date,
            complete=set(panel) == set(symbols),
            artifacts=[artifact] if panel else [],
            unavailable_fields=[] if panel else ["close"],
            limitations=list(_LIMITATIONS),
        )


class YFinanceBacktestDataResolver:
    async def resolve(self, request: BacktestRequest) -> ResolvedBacktestData:
        symbols = _symbols_from_backtest_request(request)
        if not symbols:
            raise ValueError(
                "BacktestRequest has no tickers in candidate.parameters "
                "(expected ticker_a/ticker_b/symbol/ticker)."
            )

        end = min(
            request.plan.requested_end_date or request.as_of_date,
            request.as_of_date,
        )
        start = request.plan.requested_start_date or (end - timedelta(days=365 * 10))

        panel = await asyncio.to_thread(_download, symbols, start, end)
        bars = tuple(
            bar
            for symbol in sorted(panel)
            for bar in panel[symbol]
        )
        if not bars:
            raise ValueError(f"No yfinance bars for {symbols} in {start}..{end}")

        reference = (
            f"yfinance::{','.join(sorted(panel))}::"
            f"{start.isoformat()}::{end.isoformat()}"
        )
        return ResolvedBacktestData(
            data_references=tuple(request.data_references) or (reference,),
            bars=bars,
        )


def _symbols_from_backtest_request(request: BacktestRequest) -> list[str]:
    params = request.candidate.parameters
    symbols: list[str] = []
    for key in ("ticker_a", "ticker_b", "symbol", "ticker"):
        value = params.get(key)
        if value:
            symbols.append(str(value).upper().strip())
    return list(dict.fromkeys(symbols))


def _download(
    symbols: list[str], start: date, end: date
) -> dict[str, tuple[PriceBar, ...]]:
    end_exclusive = (end + timedelta(days=1)).isoformat()
    start_s = start.isoformat()

    panel: dict[str, tuple[PriceBar, ...]] = {}
    for symbol in symbols:
        hist = yf.Ticker(symbol).history(
            start=start_s, end=end_exclusive, auto_adjust=True
        )
        bars = _to_bars(symbol, hist, end)
        if bars:
            panel[symbol] = bars
    return panel


def _to_bars(symbol: str, hist, end: date) -> tuple[PriceBar, ...]:
    if hist is None or hist.empty:
        return ()

    bars: list[PriceBar] = []
    for ts, row in hist.iterrows():
        day = ts.date()
        if day > end:
            continue
        open_, high, low, close = (
            float(row["Open"]),
            float(row["High"]),
            float(row["Low"]),
            float(row["Close"]),
        )
        if min(open_, high, low, close) <= 0:
            continue
        bars.append(
            PriceBar(
                symbol=symbol,
                timestamp=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
                open=open_,
                high=high,
                low=low,
                close=close,
            )
        )
    return tuple(bars)


__all__ = [
    "DataService",
    "YFinanceBacktestDataResolver",
    "YFinanceDataService",
]
