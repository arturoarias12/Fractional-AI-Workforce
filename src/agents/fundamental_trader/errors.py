"""Domain exceptions exposed by the Fundamental Trader package."""

from __future__ import annotations


class FundamentalTraderError(Exception):
    """Base class for errors raised by this package."""


class MandateValidationError(FundamentalTraderError):
    """The normalized Portfolio Manager mandate is invalid."""


class DiscoveryError(FundamentalTraderError):
    """The category-deviation discovery stage could not produce a candidate."""


class ServiceContractError(FundamentalTraderError):
    """A shared service (DataService/BacktestEngine) violated its contract."""


class DataGapError(FundamentalTraderError):
    """Requested fundamental fields are not populated in ETF_info.xlsx.

    ``marketCap``, ``sector``, and ``industry`` are null/empty for all 120
    tickers in the current fixture (verified by inspection, not assumed from
    the spec). Any code path that would depend on those fields for this
    ETF-only universe should raise this instead of silently treating missing
    data as zero/false - see ``docs/fundamental_trader.md`` for the fuller
    write-up of this limitation.
    """
