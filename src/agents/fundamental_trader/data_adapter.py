"""Turns a DataService response into the panels rule_generator.py expects.

Fundamental Trader consumes two artifact categories from one DataResponse:

  * ``PRICE_VOLUME`` - same shape as Technical/Quant Trader use, for
    backtesting the eventual rule.
  * ``ETF_METADATA`` - ``category`` and ``fundFamily`` per ticker, sourced
    from ``ETF_info.xlsx``. This category is not yet served by the shared
    ``services.data_service.YFinanceDataService`` (verified by inspection:
    that service only builds PRICE_VOLUME artifacts), so a DataService
    implementation handed to this trader must add it - see
    ``examples/static_data_service.py`` for the fixture-backed adapter used
    until a shared ETF_METADATA source exists.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from protocols import DataCategory, DataResponse
from tools import PriceBar

PricePanel = Mapping[str, Sequence[PriceBar]]


@dataclass(frozen=True, slots=True)
class ETFFundamentals:
    """The fund-level characteristics available for one ETF ticker.

    ``marketCap``, ``sector``, and ``industry`` are deliberately absent -
    they are null/empty for all 120 tickers in ``ETF_info.xlsx`` (a data
    gap, not an oversight; see ``docs/fundamental_trader.md``). Only the
    two fields that are actually populated are modeled here.
    """

    ticker: str
    category: str
    fund_family: str
    issuer_tier: str  # "major" | "boutique" - see rule_generator.classify_issuer_tier


FundamentalPanel = Mapping[str, ETFFundamentals]


def extract_price_panel(response: DataResponse) -> PricePanel:
    """Build ``{symbol: (PriceBar, ...)}`` from every PRICE_VOLUME artifact."""
    panel: dict[str, list[PriceBar]] = defaultdict(list)

    for artifact in response.artifacts:
        if artifact.category is not DataCategory.PRICE_VOLUME:
            continue
        payload = artifact.analysis_payload
        if payload is None:
            continue

        if isinstance(payload, Mapping):
            for symbol, bars in payload.items():
                panel[str(symbol)].extend(bars)
        elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
            symbols = artifact.asset_scope or []
            for bar in payload:
                symbol = bar.symbol if isinstance(bar, PriceBar) else None
                if symbol is None and len(symbols) == 1:
                    symbol = symbols[0]
                if symbol is None:
                    continue
                panel[symbol].append(bar)

    return {symbol: tuple(bars) for symbol, bars in panel.items()}


def extract_fundamental_panel(response: DataResponse) -> FundamentalPanel:
    """Build ``{ticker: ETFFundamentals}`` from every ETF_METADATA artifact.

    Expects each artifact's ``analysis_payload`` to be a
    ``Mapping[str, Mapping[str, str]]`` of
    ``{ticker: {"category": ..., "fund_family": ..., "issuer_tier": ...}}``,
    the shape produced by ``examples/static_data_service.py``.
    """
    panel: dict[str, ETFFundamentals] = {}

    for artifact in response.artifacts:
        if artifact.category is not DataCategory.ETF_METADATA:
            continue
        payload = artifact.analysis_payload
        if not isinstance(payload, Mapping):
            continue
        for ticker, fields in payload.items():
            if not isinstance(fields, Mapping):
                continue
            category = fields.get("category")
            fund_family = fields.get("fund_family")
            issuer_tier = fields.get("issuer_tier")
            if not category or not fund_family or not issuer_tier:
                continue  # incomplete record - skip rather than guess
            panel[str(ticker)] = ETFFundamentals(
                ticker=str(ticker),
                category=str(category),
                fund_family=str(fund_family),
                issuer_tier=str(issuer_tier),
            )

    return panel


__all__ = [
    "ETFFundamentals",
    "FundamentalPanel",
    "PricePanel",
    "extract_fundamental_panel",
    "extract_price_panel",
]
