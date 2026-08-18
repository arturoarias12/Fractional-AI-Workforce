#!/usr/bin/env python3
"""Standalone entry point: run the Fundamental Trader demo from the repo root.

    python scripts/run_fundamental_trader_standalone.py

Thin wrapper around ``agents.fundamental_trader.examples.run_demo`` - see
that module's docstring for what it wires up and why. This script only
exists so the demo can be run as ``python scripts/...`` instead of
``python -m agents.fundamental_trader.examples.run_demo``, for anyone on
the team who finds that more natural.

Requires ``pip install -e .[fundamental-demo]`` and an ``ETF_info.xlsx``
copy at the repo root (or pass a path - see ``static_data_service.py``).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make the src layout importable when running this script directly, the
# same way tests/conftest.py does for pytest.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents.fundamental_trader.examples.run_demo import main  # noqa: E402

if __name__ == "__main__":
    asyncio.run(main())
