"""Dev-only fixtures and a runnable demo for the Quant Trader package.

Nothing in here is imported by ``agent.py``, ``strategy.py``, or
``discovery.py`` - it exists purely so the agent can be exercised end to
end against the static ETF workbook before the shared DataService and a
production ValidationSplitPolicy exist.
"""
