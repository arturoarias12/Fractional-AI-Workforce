"""Turns a DataService response into the price panel discovery.py expects.

The shared DataService is still provisional (see
``docs/implementation_boundaries.md``), so this module is the one seam that
will need to change once its real payload format is finalized. Today it
expects each ``PRICE_VOLUME`` artifact's ``analysis_payload`` to be either:

  * a ``Mapping[str, Sequence[PriceBar]]`` (symbol -> bars), or
  * a flat ``Sequence[PriceBar]`` tagged with the artifact's own symbol
    (``artifact.asset_scope``), one artifact per symbol.

Both shapes are supported so a DataService implementation can choose
whichever is more natural for it without forcing every trader to agree on
one convention in advance.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Mapping, Sequence

from protocols import DataCategory, DataResponse
from tools import PriceBar

from .discovery import PricePanel


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
            symbols = artifact.asset_scope or [None] * 0
            for bar in payload:
                symbol = bar.symbol if isinstance(bar, PriceBar) else None
                if symbol is None and len(symbols) == 1:
                    symbol = symbols[0]
                if symbol is None:
                    continue
                panel[symbol].append(bar)

    return {symbol: tuple(bars) for symbol, bars in panel.items()}


__all__ = ["extract_price_panel"]
