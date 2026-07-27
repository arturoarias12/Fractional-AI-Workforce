"""Five hireable specialist interfaces in the current planned architecture."""

from .base import TraderAgent
from .fundamental_trader import FundamentalTraderAgent
from .quant_trader import QuantTraderAgent
from .reporting_agent import ReportingAgent
from .risk_agent import RiskAgent
from .technical_trader import TechnicalTraderAgent

__all__ = [
    "FundamentalTraderAgent",
    "QuantTraderAgent",
    "ReportingAgent",
    "RiskAgent",
    "TechnicalTraderAgent",
    "TraderAgent",
]
