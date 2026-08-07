"""Retired dev-only stand-ins for the shared DataService / BacktestDataResolver.

Superseded. The real ``services.data_service.DataService`` now exists
(``YFinanceDataService`` / ``YFinanceBacktestDataResolver``, built on Yiran's
workstream) and ``examples/run_demo.py`` calls it directly as the primary
path. Quant Trader's own ``agent.py`` / ``strategy.py`` never depended on
anything in this file to begin with - both only depend on the
``DataService`` / ``BacktestDataResolver`` Protocols, not on where the bars
actually come from, so nothing there needed to change.

Everything below is commented out and kept only as documented fallbacks, in
the order they were actually tried during development, in case the shared
DataService is ever unavailable:

- **Fallback #0: yfinance (dev-only)** - the adapter this module used to run
  live before the shared DataService landed. Functionally identical to
  ``services.data_service.YFinanceDataService``.
- **Fallback #1: Financial Modeling Prep** - its ``historical-price-eod/full``
  endpoint needs a paid plan.
- **Fallback #2: Stooq** - its free CSV endpoint returns a 404 in practice for
  direct programmatic access, despite older documentation describing it as
  working.
- **Fallback #3: Alpha Vantage** - worked and has a real free tier, but that
  free tier only returns the most recent ~100 trading days per symbol
  (``outputsize=full`` is premium-only). This project's pair discovery needs
  at least ``MIN_HISTORY_DAYS`` (750) days of shared history to trust a
  correlation or fit a mean-reversion half-life, so 100 days isn't enough -
  it's kept here in case a paid Alpha Vantage plan is available later, or for
  a different use case that doesn't need deep history.
- **Fallback #4: static xlsx** - reads ``ETF_historical_prices.xlsx`` directly,
  no network calls at all; fully offline.

``DEFAULT_UNIVERSE`` and the yfinance fetch/cache helpers just below are kept
active (not commented out) since several of the fallback classes above still
reference them.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

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

# Used only when the mandate doesn't restrict `permitted_asset_universe`.
# Matches the 120 tickers in the original static xlsx fixture so the demo
# behaves the same way by default.
DEFAULT_UNIVERSE: tuple[str, ...] = (
    "AFK", "AIQ", "AMLP", "ARGT", "ARKX", "ASHR", "AWAY", "BETZ", "BND", "BNDX",
    "BOTZ", "CIBR", "COPX", "COW", "CPER", "DBA", "DBB", "DBC", "DRIV", "DXJ",
    "EMB", "ESPO", "EWA", "EWC", "EWJ", "EWT", "EWU", "EWY", "EWZS", "EZU",
    "FAN", "FHLC", "FINX", "FIW", "FXA", "FXB", "FXC", "FXE", "FXF", "FXY",
    "GDX", "HYG", "IAU", "ICLN", "IEF", "IEMG", "IGF", "IGV", "IHI", "IJH",
    "IJR", "ILF", "INDA", "IVV", "JEPI", "JEPQ", "JETS", "KRE", "KSA", "LIT",
    "LQD", "MCHI", "MOO", "MSOS", "MTUM", "MUB", "PALL", "PBJ", "PEJ", "PFF",
    "PICK", "PPLT", "QQQ", "RCTR", "REM", "REMX", "RYLD", "SCHD", "SEA", "SHY",
    "SIL", "SKYY", "SLV", "SMH", "SMIN", "SOXS", "SPLV", "SPXU", "SQQQ", "SVOL",
    "TAN", "TIP", "TLT", "TUR", "UDN", "UFO", "UNG", "URNM", "USO", "UUP",
    "VEA", "VNM", "VNQ", "VNQI", "VTV", "VXX", "WOOD", "XAR", "XBI", "XLB",
    "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLY", "XTN", "XYLD",
)


# Simple process-lifetime cache so the same symbol isn't re-fetched over the
# network multiple times in one run (discovery scans the whole universe,
# then the backtest engine resolves the same two tickers again).
_bar_cache: dict[tuple[str, date], tuple[PriceBar, ...]] = {}


def _fetch_symbol_bars(symbol: str, as_of_date: date) -> tuple[PriceBar, ...]:
    """Fetch and clean one symbol's daily OHLC history up to ``as_of_date``."""
    cache_key = (symbol, as_of_date)
    if cache_key in _bar_cache:
        return _bar_cache[cache_key]

    # yfinance's `end` is exclusive, so add a day to include as_of_date itself.
    history = yf.Ticker(symbol).history(
        end=as_of_date + timedelta(days=1),
        period="max",
        auto_adjust=True,
    )

    bars = []
    for timestamp, row in history.iterrows():
        row_date = timestamp.date()
        if row_date > as_of_date:
            continue
        try:
            open_, high, low, close = (
                float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]),
            )
        except (KeyError, ValueError, TypeError):
            continue
        if min(open_, high, low, close) <= 0:
            continue  # skip bad/non-positive rows rather than fabricate a bar

        # Clamp rather than drop on the rare OHLC rounding artifact, same
        # policy as the other adapters in this file.
        low = min(open_, high, low, close)
        high = max(open_, high, low, close)
        bars.append(PriceBar(
            symbol=symbol,
            timestamp=datetime.combine(row_date, datetime.min.time(), tzinfo=timezone.utc),
            open=open_,
            high=high,
            low=low,
            close=close,
        ))

    bars.sort(key=lambda bar: bar.timestamp)
    result = tuple(bars)
    _bar_cache[cache_key] = result
    return result

# ---------------------------------------------------------------------------
# Fallback #0: dev-only yfinance adapter, used before the shared
# services.data_service.YFinanceDataService/YFinanceBacktestDataResolver
# existed. Superseded now that Quant Trader is wired to the real shared
# DataService in examples/run_demo.py - kept here, commented out, as the
# first fallback if the shared service is ever unavailable.
# ---------------------------------------------------------------------------

# class YFinanceDataService:
#     """Live yfinance adapter; satisfies ``quant_trader.services.DataService``."""

#     async def fetch(self, request: DataRequest) -> DataResponse:
#         universe = (
#             request.asset_universe
#             if isinstance(request.asset_universe, list) and request.asset_universe
#             else list(DEFAULT_UNIVERSE)
#         )

#         panel: dict[str, tuple[PriceBar, ...]] = {}
#         for symbol in universe:
#             bars = await asyncio.to_thread(_fetch_symbol_bars, symbol, request.as_of_date)
#             if bars:
#                 panel[symbol] = bars

#         retrieved_at = datetime.now(timezone.utc)
#         effective_at = datetime.combine(
#             request.as_of_date, datetime.min.time(), tzinfo=timezone.utc,
#         )
#         artifact = DataArtifact(
#             artifact_id=f"{request.request_id}.prices",
#             category=DataCategory.PRICE_VOLUME,
#             description="Daily OHLC close prices fetched live via yfinance.",
#             data_reference=f"yfinance::history::{request.as_of_date.isoformat()}",
#             schema_fields=["symbol", "timestamp", "open", "high", "low", "close"],
#             asset_scope=list(panel.keys()),
#             coverage_end=request.as_of_date,
#             frequency="daily",
#             provenance=[
#                 DataProvenance(
#                     provenance_id=f"{request.request_id}.provenance",
#                     provider="yfinance",
#                     source_reference="yfinance.Ticker.history",
#                     retrieved_at=retrieved_at,
#                     point_in_time_verified=True,
#                     effective_at=effective_at,
#                 ),
#             ],
#             analysis_payload=panel,
#             limitations=[
#                 "yfinance is an unofficial library that scrapes Yahoo Finance; "
#                 "no SLA and it can break without notice.",
#                 "Close price is auto-adjusted for splits/dividends; no separate "
#                 "unadjusted series is fetched.",
#                 "No survivorship-bias audit performed.",
#             ],
#         )

#         return DataResponse(
#             response_id=f"{request.request_id}.response",
#             request_id=request.request_id,
#             lineage=request.lineage,
#             as_of_date=request.as_of_date,
#             complete=bool(panel),
#             artifacts=[artifact] if panel else [],
#             unavailable_fields=[] if panel else request.required_fields,
#         )


# class YFinanceDataResolver:
#     """Satisfies ``tools.backtest_engine.BacktestDataResolver`` from the live yfinance API."""

#     async def resolve(self, request: BacktestRequest) -> ResolvedBacktestData:
#         symbols = sorted({
#             str(value) for key, value in request.candidate.parameters.items()
#             if key in ("ticker_a", "ticker_b")
#         })
#         bars: list[PriceBar] = []
#         for symbol in symbols:
#             bars.extend(
#                 await asyncio.to_thread(_fetch_symbol_bars, symbol, request.as_of_date)
#             )

#         return ResolvedBacktestData(
#             data_references=tuple(request.data_references),
#             bars=tuple(bars),
#             point_in_time_verified=True,
#         )


# ---------------------------------------------------------------------------
# Fallback #1: Financial Modeling Prep. NOT used by default - its
# historical-price-eod/full endpoint needs a paid plan. Kept here in case a
# paid FMP key is available later; requires an FMP_API_KEY environment
# variable if uncommented.
# ---------------------------------------------------------------------------

# import os
#
# import requests
#
# FMP_BASE_URL = "https://financialmodelingprep.com/stable"
# FMP_API_KEY_ENV_VAR = "FMP_API_KEY"
#
#
# def _fmp_api_key() -> str:
#     api_key = os.environ.get(FMP_API_KEY_ENV_VAR)
#     if not api_key:
#         raise RuntimeError(
#             f"Set the {FMP_API_KEY_ENV_VAR} environment variable to a "
#             "Financial Modeling Prep API key (https://financialmodelingprep.com/) "
#             "before running against the FMP data adapter."
#         )
#     return api_key
#
#
# def _fetch_symbol_bars_fmp(symbol: str, as_of_date: date) -> tuple[PriceBar, ...]:
#     response = requests.get(
#         f"{FMP_BASE_URL}/historical-price-eod/full",
#         params={"symbol": symbol, "to": as_of_date.isoformat(), "apikey": _fmp_api_key()},
#         timeout=30,
#     )
#     response.raise_for_status()
#     payload = response.json()
#     rows = payload.get("historical", []) if isinstance(payload, dict) else payload
#     bars = []
#     for row in rows:
#         try:
#             row_date = date.fromisoformat(str(row["date"])[:10])
#         except (KeyError, ValueError):
#             continue
#         if row_date > as_of_date:
#             continue
#         open_, high, low, close = (
#             float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]),
#         )
#         if min(open_, high, low, close) <= 0:
#             continue
#         low = min(open_, high, low, close)
#         high = max(open_, high, low, close)
#         bars.append(PriceBar(
#             symbol=symbol,
#             timestamp=datetime.combine(row_date, datetime.min.time(), tzinfo=timezone.utc),
#             open=open_,
#             high=high,
#             low=low,
#             close=close,
#         ))
#     return tuple(sorted(bars, key=lambda bar: bar.timestamp))
#
#
# class FMPDataService:
#     """Live Financial Modeling Prep adapter; satisfies ``quant_trader.services.DataService``."""
#
#     async def fetch(self, request: DataRequest) -> DataResponse:
#         universe = (
#             request.asset_universe
#             if isinstance(request.asset_universe, list) and request.asset_universe
#             else list(DEFAULT_UNIVERSE)
#         )
#         panel: dict[str, tuple[PriceBar, ...]] = {}
#         for symbol in universe:
#             bars = await asyncio.to_thread(_fetch_symbol_bars_fmp, symbol, request.as_of_date)
#             if bars:
#                 panel[symbol] = bars
#         retrieved_at = datetime.now(timezone.utc)
#         effective_at = datetime.combine(
#             request.as_of_date, datetime.min.time(), tzinfo=timezone.utc,
#         )
#         artifact = DataArtifact(
#             artifact_id=f"{request.request_id}.prices",
#             category=DataCategory.PRICE_VOLUME,
#             description="Daily OHLC close prices fetched live from the Financial Modeling Prep API.",
#             data_reference=f"fmp::historical-price-eod::{request.as_of_date.isoformat()}",
#             schema_fields=["symbol", "timestamp", "open", "high", "low", "close"],
#             asset_scope=list(panel.keys()),
#             coverage_end=request.as_of_date,
#             frequency="daily",
#             provenance=[
#                 DataProvenance(
#                     provenance_id=f"{request.request_id}.provenance",
#                     provider="financial_modeling_prep",
#                     source_reference=f"{FMP_BASE_URL}/historical-price-eod/full",
#                     retrieved_at=retrieved_at,
#                     point_in_time_verified=True,
#                     effective_at=effective_at,
#                 ),
#             ],
#             analysis_payload=panel,
#             limitations=["Requires a paid FMP plan for this endpoint's historical depth."],
#         )
#         return DataResponse(
#             response_id=f"{request.request_id}.response",
#             request_id=request.request_id,
#             lineage=request.lineage,
#             as_of_date=request.as_of_date,
#             complete=bool(panel),
#             artifacts=[artifact] if panel else [],
#             unavailable_fields=[] if panel else request.required_fields,
#         )
#
#
# class FMPDataResolver:
#     """Satisfies ``tools.backtest_engine.BacktestDataResolver`` from the live FMP API."""
#
#     async def resolve(self, request: BacktestRequest) -> ResolvedBacktestData:
#         symbols = sorted({
#             str(value) for key, value in request.candidate.parameters.items()
#             if key in ("ticker_a", "ticker_b")
#         })
#         bars: list[PriceBar] = []
#         for symbol in symbols:
#             bars.extend(
#                 await asyncio.to_thread(_fetch_symbol_bars_fmp, symbol, request.as_of_date)
#             )
#         return ResolvedBacktestData(
#             data_references=tuple(request.data_references),
#             bars=tuple(bars),
#             point_in_time_verified=True,
#         )


# ---------------------------------------------------------------------------
# Fallback #2: Stooq. NOT used by default - its free CSV endpoint returns a
# 404 in practice for direct programmatic access (confirmed against the
# live endpoint), despite older documentation describing it as working.
# Kept here in case that ever changes.
# ---------------------------------------------------------------------------

# import csv
# import io
#
# import requests
#
# STOOQ_BASE_URL = "https://stooq.com/q/d/l"
#
#
# def _stooq_symbol(symbol: str) -> str:
#     """Stooq needs a market suffix; assume US-listed unless one is already given."""
#     return symbol if "." in symbol else f"{symbol}.us"
#
#
# def _fetch_symbol_bars_stooq(symbol: str, as_of_date: date) -> tuple[PriceBar, ...]:
#     response = requests.get(
#         STOOQ_BASE_URL,
#         params={"s": _stooq_symbol(symbol), "i": "d"},
#         timeout=30,
#     )
#     response.raise_for_status()
#     text = response.text.strip()
#     if not text or "No data" in text.splitlines()[0]:
#         return ()
#     bars = []
#     reader = csv.DictReader(io.StringIO(text))
#     for row in reader:
#         try:
#             row_date = date.fromisoformat(row["Date"])
#         except (KeyError, ValueError):
#             continue
#         if row_date > as_of_date:
#             continue
#         try:
#             open_, high, low, close = (
#                 float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]),
#             )
#         except (KeyError, ValueError):
#             continue
#         if min(open_, high, low, close) <= 0:
#             continue
#         low = min(open_, high, low, close)
#         high = max(open_, high, low, close)
#         bars.append(PriceBar(
#             symbol=symbol,
#             timestamp=datetime.combine(row_date, datetime.min.time(), tzinfo=timezone.utc),
#             open=open_,
#             high=high,
#             low=low,
#             close=close,
#         ))
#     return tuple(sorted(bars, key=lambda bar: bar.timestamp))
#
#
# class StooqDataService:
#     """Live Stooq CSV adapter; satisfies ``quant_trader.services.DataService``."""
#
#     async def fetch(self, request: DataRequest) -> DataResponse:
#         universe = (
#             request.asset_universe
#             if isinstance(request.asset_universe, list) and request.asset_universe
#             else list(DEFAULT_UNIVERSE)
#         )
#         panel: dict[str, tuple[PriceBar, ...]] = {}
#         for symbol in universe:
#             bars = await asyncio.to_thread(_fetch_symbol_bars_stooq, symbol, request.as_of_date)
#             if bars:
#                 panel[symbol] = bars
#         retrieved_at = datetime.now(timezone.utc)
#         effective_at = datetime.combine(
#             request.as_of_date, datetime.min.time(), tzinfo=timezone.utc,
#         )
#         artifact = DataArtifact(
#             artifact_id=f"{request.request_id}.prices",
#             category=DataCategory.PRICE_VOLUME,
#             description="Daily OHLC close prices fetched live from Stooq's CSV download endpoint.",
#             data_reference=f"stooq::q_d_l::{request.as_of_date.isoformat()}",
#             schema_fields=["symbol", "timestamp", "open", "high", "low", "close"],
#             asset_scope=list(panel.keys()),
#             coverage_end=request.as_of_date,
#             frequency="daily",
#             provenance=[
#                 DataProvenance(
#                     provenance_id=f"{request.request_id}.provenance",
#                     provider="stooq",
#                     source_reference=STOOQ_BASE_URL,
#                     retrieved_at=retrieved_at,
#                     point_in_time_verified=True,
#                     effective_at=effective_at,
#                 ),
#             ],
#             analysis_payload=panel,
#             limitations=["Endpoint returned 404 in practice as of this project's testing."],
#         )
#         return DataResponse(
#             response_id=f"{request.request_id}.response",
#             request_id=request.request_id,
#             lineage=request.lineage,
#             as_of_date=request.as_of_date,
#             complete=bool(panel),
#             artifacts=[artifact] if panel else [],
#             unavailable_fields=[] if panel else request.required_fields,
#         )
#
#
# class StooqDataResolver:
#     """Satisfies ``tools.backtest_engine.BacktestDataResolver`` from the live Stooq API."""
#
#     async def resolve(self, request: BacktestRequest) -> ResolvedBacktestData:
#         symbols = sorted({
#             str(value) for key, value in request.candidate.parameters.items()
#             if key in ("ticker_a", "ticker_b")
#         })
#         bars: list[PriceBar] = []
#         for symbol in symbols:
#             bars.extend(
#                 await asyncio.to_thread(_fetch_symbol_bars_stooq, symbol, request.as_of_date)
#             )
#         return ResolvedBacktestData(
#             data_references=tuple(request.data_references),
#             bars=tuple(bars),
#             point_in_time_verified=True,
#         )


# ---------------------------------------------------------------------------
# Fallback #3: Alpha Vantage. NOT used by default - its free tier only
# returns ~100 days of history per symbol (outputsize=full is premium-only),
# which is too little for this project's discovery.py to trust a
# correlation or half-life fit. Kept here in case a paid plan is available,
# or for a different use case that doesn't need deep history. Requires an
# ALPHA_VANTAGE_API_KEY environment variable if uncommented.
# ---------------------------------------------------------------------------

# ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
# ALPHA_VANTAGE_API_KEY_ENV_VAR = "ALPHA_VANTAGE_API_KEY"
# # Free tier: 5 requests/minute. Sleep this long between calls to stay under it.
# ALPHA_VANTAGE_MIN_SECONDS_BETWEEN_CALLS = 13.0
#
#
#
#
# # Simple process-lifetime cache so the same symbol isn't re-fetched over the
# # network multiple times in one run (discovery scans the whole universe,
# # then the backtest engine resolves the same two tickers again) - this also
# # directly protects the 25-requests/day free-tier budget.
# _bar_cache: dict[tuple[str, date], tuple[PriceBar, ...]] = {}
# _last_call_at: float | None = None
#
#
# def _alpha_vantage_api_key() -> str:
#     api_key = os.environ.get(ALPHA_VANTAGE_API_KEY_ENV_VAR)
#     if not api_key:
#         raise RuntimeError(
#             f"Set the {ALPHA_VANTAGE_API_KEY_ENV_VAR} environment variable to a free "
#             "Alpha Vantage API key (https://www.alphavantage.co/support/#api-key) "
#             "before running against the live Alpha Vantage data adapter."
#         )
#     return api_key
#
#
# def _respect_rate_limit() -> None:
#     """Sleep if needed so calls stay under 5/minute on the free tier."""
#     global _last_call_at
#     if _last_call_at is not None:
#         elapsed = time.monotonic() - _last_call_at
#         remaining = ALPHA_VANTAGE_MIN_SECONDS_BETWEEN_CALLS - elapsed
#         if remaining > 0:
#             time.sleep(remaining)
#     _last_call_at = time.monotonic()
#
#
# def _fetch_symbol_bars(symbol: str, as_of_date: date) -> tuple[PriceBar, ...]:
#     """Fetch and clean one symbol's daily OHLC history up to ``as_of_date``."""
#     cache_key = (symbol, as_of_date)
#     if cache_key in _bar_cache:
#         return _bar_cache[cache_key]
#
#     _respect_rate_limit()
#     response = requests.get(
#         ALPHA_VANTAGE_BASE_URL,
#         params={
#             "function": "TIME_SERIES_DAILY",
#             "symbol": symbol,
#             "outputsize": "full",
#             "apikey": _alpha_vantage_api_key(),
#         },
#         timeout=30,
#     )
#     response.raise_for_status()
#     payload = response.json()
#     rows = payload.get("Time Series (Daily)")
#     if not rows:
#         # Alpha Vantage reports errors inside a 200 OK body instead of an
#         # HTTP status code: "Error Message" for a bad symbol/function, "Note"
#         # once you've hit the daily/per-minute cap, "Information" for a bad
#         # or missing API key (or approaching the limit). Surface whichever
#         # one came back instead of silently treating this as "no data" -
#         # that message is almost always the real problem.
#         message = (
#             payload.get("Error Message")
#             or payload.get("Note")
#             or payload.get("Information")
#             or f"Unrecognized Alpha Vantage response shape: {payload!r}"
#         )
#         raise RuntimeError(f"Alpha Vantage returned no data for {symbol}: {message}")
#
#     bars = []
#     for row_date_str, values in rows.items():
#         try:
#             row_date = date.fromisoformat(row_date_str)
#         except ValueError:
#             continue
#         if row_date > as_of_date:
#             continue
#         try:
#             open_, high, low, close = (
#                 float(values["1. open"]), float(values["2. high"]),
#                 float(values["3. low"]), float(values["4. close"]),
#             )
#         except (KeyError, ValueError):
#             continue
#         if min(open_, high, low, close) <= 0:
#             continue  # skip bad/non-positive rows rather than fabricate a bar
#
#         # Clamp rather than drop on the rare OHLC rounding artifact, same
#         # policy as the other adapters in this file.
#         low = min(open_, high, low, close)
#         high = max(open_, high, low, close)
#         bars.append(PriceBar(
#             symbol=symbol,
#             timestamp=datetime.combine(row_date, datetime.min.time(), tzinfo=timezone.utc),
#             open=open_,
#             high=high,
#             low=low,
#             close=close,
#         ))
#
#     bars.sort(key=lambda bar: bar.timestamp)
#     result = tuple(bars)
#     _bar_cache[cache_key] = result
#     return result
#
#
# class AlphaVantageDataService:
#     """Live Alpha Vantage adapter; satisfies ``quant_trader.services.DataService``."""
#
#     async def fetch(self, request: DataRequest) -> DataResponse:
#         universe = (
#             request.asset_universe
#             if isinstance(request.asset_universe, list) and request.asset_universe
#             else list(DEFAULT_UNIVERSE)
#         )
#
#         panel: dict[str, tuple[PriceBar, ...]] = {}
#         for symbol in universe:
#             bars = await asyncio.to_thread(_fetch_symbol_bars, symbol, request.as_of_date)
#             if bars:
#                 panel[symbol] = bars
#
#         retrieved_at = datetime.now(timezone.utc)
#         effective_at = datetime.combine(
#             request.as_of_date, datetime.min.time(), tzinfo=timezone.utc,
#         )
#         artifact = DataArtifact(
#             artifact_id=f"{request.request_id}.prices",
#             category=DataCategory.PRICE_VOLUME,
#             description="Daily OHLC close prices fetched live from the Alpha Vantage API.",
#             data_reference=f"alpha_vantage::TIME_SERIES_DAILY::{request.as_of_date.isoformat()}",
#             schema_fields=["symbol", "timestamp", "open", "high", "low", "close"],
#             asset_scope=list(panel.keys()),
#             coverage_end=request.as_of_date,
#             frequency="daily",
#             provenance=[
#                 DataProvenance(
#                     provenance_id=f"{request.request_id}.provenance",
#                     provider="alpha_vantage",
#                     source_reference=ALPHA_VANTAGE_BASE_URL,
#                     retrieved_at=retrieved_at,
#                     point_in_time_verified=True,
#                     effective_at=effective_at,
#                 ),
#             ],
#             analysis_payload=panel,
#             limitations=[
#                 "Free-tier Alpha Vantage key: 25 requests/day, 5/minute; a large",
#                 "universe scan can exhaust the daily quota.",
#                 "TIME_SERIES_DAILY is unadjusted close, unlike the auto-adjusted",
#                 "series the earlier yfinance adapter used.",
#                 "No survivorship-bias or corporate-action adjustment audit performed.",
#             ],
#         )
#
#         return DataResponse(
#             response_id=f"{request.request_id}.response",
#             request_id=request.request_id,
#             lineage=request.lineage,
#             as_of_date=request.as_of_date,
#             complete=bool(panel),
#             artifacts=[artifact] if panel else [],
#             unavailable_fields=[] if panel else request.required_fields,
#         )
#
#
# class AlphaVantageDataResolver:
#     """Satisfies ``tools.backtest_engine.BacktestDataResolver`` from the live Alpha Vantage API."""
#
#     async def resolve(self, request: BacktestRequest) -> ResolvedBacktestData:
#         symbols = sorted({
#             str(value) for key, value in request.candidate.parameters.items()
#             if key in ("ticker_a", "ticker_b")
#         })
#         bars: list[PriceBar] = []
#         for symbol in symbols:
#             bars.extend(
#                 await asyncio.to_thread(_fetch_symbol_bars, symbol, request.as_of_date)
#             )
#
#         return ResolvedBacktestData(
#             data_references=tuple(request.data_references),
#             bars=tuple(bars),
#             point_in_time_verified=True,
#         )


# ---------------------------------------------------------------------------
# Fallback #4: original static-xlsx implementation. Not used by default -
# kept here, commented out, in case you want to run fully offline with no
# network calls at all.
# To use it: uncomment this section, and in run_demo.py import
# StaticExcelDataService / StaticExcelDataResolver instead of the yfinance
# classes above (both satisfy the exact same Protocols).
# ---------------------------------------------------------------------------

# from functools import lru_cache
# from pathlib import Path
#
# import pandas as pd
#
# DEFAULT_XLSX_PATH = Path("ETF_historical_prices.xlsx")
#
#
# @lru_cache(maxsize=4)
# def _load_workbook(path: str) -> pd.DataFrame:
#     df = pd.read_excel(path)
#     df["date"] = pd.to_datetime(df["date"]).dt.date
#     return df
#
#
# def _bars_for_symbol(
#     df: pd.DataFrame, symbol: str, as_of_date: date,
# ) -> tuple[PriceBar, ...]:
#     rows = df[(df["ticker"] == symbol) & (df["date"] <= as_of_date)]
#     bars = []
#     for row in rows.sort_values("date").itertuples(index=False):
#         open_, high, low, close = float(row.open), float(row.high), float(row.low), float(row.close)
#         if min(open_, high, low, close) <= 0:
#             continue  # a handful of source rows have non-positive prices; skip rather than fabricate
#         # The source workbook occasionally has OHLC rounding artifacts where
#         # low/high don't quite bound open/close (e.g. around split adjustments).
#         # PriceBar enforces strict OHLC consistency, so clamp rather than drop
#         # the whole bar - this is a data-cleaning step specific to this static
#         # demo fixture, not something the real DataService should need.
#         low = min(open_, high, low, close)
#         high = max(open_, high, low, close)
#         bars.append(PriceBar(
#             symbol=symbol,
#             timestamp=datetime.combine(row.date, datetime.min.time(), tzinfo=timezone.utc),
#             open=open_,
#             high=high,
#             low=low,
#             close=close,
#         ))
#     return tuple(bars)
#
#
# class StaticExcelDataService:
#     """Reads the static ETF workbook; satisfies ``quant_trader.services.DataService``."""
#
#     def __init__(self, xlsx_path: Path | str = DEFAULT_XLSX_PATH) -> None:
#         self._xlsx_path = str(xlsx_path)
#
#     async def fetch(self, request: DataRequest) -> DataResponse:
#         df = _load_workbook(self._xlsx_path)
#         universe = (
#             request.asset_universe
#             if isinstance(request.asset_universe, list) and request.asset_universe
#             else sorted(df["ticker"].unique())
#         )
#
#         panel = {
#             symbol: _bars_for_symbol(df, symbol, request.as_of_date)
#             for symbol in universe
#         }
#         panel = {symbol: bars for symbol, bars in panel.items() if bars}
#
#         retrieved_at = datetime.now(timezone.utc)
#         effective_at = datetime.combine(
#             request.as_of_date, datetime.min.time(), tzinfo=timezone.utc,
#         )
#         artifact = DataArtifact(
#             artifact_id=f"{request.request_id}.prices",
#             category=DataCategory.PRICE_VOLUME,
#             description="Static daily OHLC close prices from ETF_historical_prices.xlsx.",
#             data_reference=f"static_xlsx::{self._xlsx_path}::{request.as_of_date.isoformat()}",
#             schema_fields=["symbol", "timestamp", "open", "high", "low", "close"],
#             asset_scope=list(panel.keys()),
#             coverage_end=request.as_of_date,
#             frequency="daily",
#             provenance=[
#                 DataProvenance(
#                     provenance_id=f"{request.request_id}.provenance",
#                     provider="static_local_file",
#                     source_reference=self._xlsx_path,
#                     retrieved_at=retrieved_at,
#                     point_in_time_verified=True,
#                     effective_at=effective_at,
#                 ),
#             ],
#             analysis_payload=panel,
#             limitations=[
#                 "Static local file, not a live/licensed market-data provider.",
#                 "No survivorship-bias or corporate-action adjustment audit performed.",
#             ],
#         )
#
#         return DataResponse(
#             response_id=f"{request.request_id}.response",
#             request_id=request.request_id,
#             lineage=request.lineage,
#             as_of_date=request.as_of_date,
#             complete=bool(panel),
#             artifacts=[artifact] if panel else [],
#             unavailable_fields=[] if panel else request.required_fields,
#         )
#
#
# class StaticExcelDataResolver:
#     """Satisfies ``tools.backtest_engine.BacktestDataResolver`` from the same file."""
#
#     def __init__(self, xlsx_path: Path | str = DEFAULT_XLSX_PATH) -> None:
#         self._xlsx_path = str(xlsx_path)
#
#     async def resolve(self, request: BacktestRequest) -> ResolvedBacktestData:
#         df = _load_workbook(self._xlsx_path)
#         symbols = sorted({
#             str(value) for key, value in request.candidate.parameters.items()
#             if key in ("ticker_a", "ticker_b")
#         })
#         bars: list[PriceBar] = []
#         for symbol in symbols:
#             bars.extend(_bars_for_symbol(df, symbol, request.as_of_date))
#
#         return ResolvedBacktestData(
#             data_references=tuple(request.data_references),
#             bars=tuple(bars),
#             point_in_time_verified=True,
#         )


__all__ = ["YFinanceDataResolver", "YFinanceDataService"]
