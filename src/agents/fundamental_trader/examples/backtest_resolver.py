"""Backtest data resolver for Fundamental Trader candidates.

The shared ``services.data_service.YFinanceBacktestDataResolver`` only
looks for a fixed set of single-ticker parameter keys (``ticker_a``,
``ticker_b``, ``symbol``, ``ticker`` - verified by reading its source).
Fundamental Trader's candidates carry a ``ticker`` *and* a
``benchmark_tickers`` list, and that list is invisible to the shared
resolver as written today - it would silently backtest against only the
main ticker's bars and the strategy session would never see its
benchmark peers' history, quietly breaking the category-deviation signal
without raising an error.

``FundamentalBacktestDataResolver`` wraps the shared yfinance download
helper and additionally resolves every symbol in ``benchmark_tickers``.
This is a Fundamental-Trader-owned seam, not a modification to Yiran's
shared ``services`` module - flagged for Workstream #3 integration so the
shared resolver can grow a general "extra symbol keys" hook instead of
every trader needing its own wrapper long-term.
"""

from __future__ import annotations

from datetime import timedelta

from protocols import BacktestRequest

from services.data_service import _download  # reuses the shared yfinance helper

from tools import PriceBar, ResolvedBacktestData


def _symbols_from_backtest_request(request: BacktestRequest) -> list[str]:
    params = request.candidate.parameters
    symbols: list[str] = []
    for key in ("ticker_a", "ticker_b", "symbol", "ticker"):
        value = params.get(key)
        if value:
            symbols.append(str(value).upper().strip())
    benchmark = params.get("benchmark_tickers") or []
    symbols.extend(str(s).upper().strip() for s in benchmark if s)
    return list(dict.fromkeys(symbols))


class FundamentalBacktestDataResolver:
    """Like ``YFinanceBacktestDataResolver``, but also resolves benchmark_tickers."""

    async def resolve(self, request: BacktestRequest) -> ResolvedBacktestData:
        symbols = _symbols_from_backtest_request(request)
        if not symbols:
            raise ValueError(
                "BacktestRequest has no tickers in candidate.parameters "
                "(expected ticker/benchmark_tickers for Fundamental Trader)."
            )

        end = min(
            request.plan.requested_end_date or request.as_of_date,
            request.as_of_date,
        )
        start = request.plan.requested_start_date or (end - timedelta(days=365 * 10))

        import asyncio
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


__all__ = ["FundamentalBacktestDataResolver"]
