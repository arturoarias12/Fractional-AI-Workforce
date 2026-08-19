"""Hireable Fundamental Trader: proposes ETF category-benchmark deviation
strategies.

This is the "propose" half only - see ``docs/fundamental_trader.md`` at the
repo root for the full write-up, including the documented ETF_info.xlsx
data gap (no marketCap/sector/industry) and the ISSUER_SCALE_TIER heuristic
used in its place. Evaluation stays with the shared, deterministic
``tools.backtest_engine``; this package's ``strategy.py`` only registers the
executor that engine calls to run a Fundamental Trader candidate.
"""

from .agent import FundamentalTraderAgent
from .errors import (
    DataGapError,
    DiscoveryError,
    FundamentalTraderError,
    MandateValidationError,
    ServiceContractError,
)
from .rule_generator import (
    MAJOR_TIER_ISSUERS,
    CategoryDeviationEvidence,
    ProposedCategoryDeviation,
    classify_issuer_tier,
    propose_category_deviations,
)
from .runtime import FundamentalTraderRuntime, make_langgraph_node
from .services import BacktestEngine, DataService, ValidationSplitPolicy
from .strategy import (
    CATEGORY_DEVIATION_EXECUTOR_ID,
    CategoryDeviationParameters,
    CategoryDeviationSession,
    category_deviation_executor,
)

__all__ = [
    "BacktestEngine",
    "CATEGORY_DEVIATION_EXECUTOR_ID",
    "CategoryDeviationEvidence",
    "CategoryDeviationParameters",
    "CategoryDeviationSession",
    "DataGapError",
    "DataService",
    "DiscoveryError",
    "FundamentalTraderAgent",
    "FundamentalTraderError",
    "FundamentalTraderRuntime",
    "MAJOR_TIER_ISSUERS",
    "MandateValidationError",
    "ProposedCategoryDeviation",
    "ServiceContractError",
    "ValidationSplitPolicy",
    "category_deviation_executor",
    "classify_issuer_tier",
    "make_langgraph_node",
    "propose_category_deviations",
]
