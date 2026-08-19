"""Demo-only wiring for the standalone Fundamental Trader.

Nothing in ``agent.py`` / ``strategy.py`` / ``rule_generator.py`` depends on
anything in this subpackage - it only exists to give ``run_demo.py`` (and
``scripts/run_fundamental_trader_standalone.py`` at the repo root) a
concrete ``DataService`` / ``ValidationSplitPolicy`` to inject.
"""
