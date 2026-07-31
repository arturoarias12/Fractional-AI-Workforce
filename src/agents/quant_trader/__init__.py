"""Hireable Quant Trader: proposes cross-asset statistical strategies.

This is the "propose" half only - see ``docs/quant_trader.md`` at the repo
root for the full write-up. Evaluation stays with the shared, deterministic
``tools.backtest_engine``; this package's ``strategy.py`` only registers the
executor that engine calls to run a Quant Trader candidate.
"""

from .agent import QuantTraderAgent
from .discovery import PairEvidence, ProposedPair, propose_pairs
from .errors import DiscoveryError, MandateValidationError, QuantTraderError, ServiceContractError
from .runtime import QuantTraderRuntime, make_langgraph_node
from .services import BacktestEngine, DataService, ValidationSplitPolicy
from .strategy import (
    CROSS_ASSET_SPREAD_EXECUTOR_ID,
    PairSpreadParameters,
    PairSpreadSession,
    cross_asset_spread_executor,
)

__all__ = [
    "BacktestEngine",
    "CROSS_ASSET_SPREAD_EXECUTOR_ID",
    "DataService",
    "DiscoveryError",
    "MandateValidationError",
    "PairEvidence",
    "PairSpreadParameters",
    "PairSpreadSession",
    "ProposedPair",
    "QuantTraderAgent",
    "QuantTraderError",
    "QuantTraderRuntime",
    "ServiceContractError",
    "ValidationSplitPolicy",
    "cross_asset_spread_executor",
    "make_langgraph_node",
    "propose_pairs",
]
