#!/usr/bin/env python3
"""Credential-safe preflight for the full local research-loop demo."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_local_environment(problems: list[str]) -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        problems.append(
            ".env exists, but python-dotenv is unavailable. Install the "
            "full demo with: pip install -e '.[full-demo]'"
        )
        return
    load_dotenv(env_path, override=False)


def _configured_path(environment_name: str, default_name: str) -> Path:
    raw_value = os.environ.get(environment_name, "").strip()
    path = Path(raw_value).expanduser() if raw_value else Path(default_name)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def _check_imports(problems: list[str]) -> None:
    required_modules = (
        "pydantic",
        "numpy",
        "pandas",
        "yfinance",
        "openpyxl",
        "langgraph",
        "aiosqlite",
    )
    missing = [
        module
        for module in required_modules
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        problems.append(
            "Missing Python dependencies: "
            + ", ".join(missing)
            + ". Install with: pip install -e '.[full-demo]'"
        )


def _check_model_configuration(problems: list[str]) -> None:
    provider = os.environ.get(
        "TECHNICAL_TRADER_MODEL_PROVIDER",
        "",
    ).strip().casefold()
    model = os.environ.get("TECHNICAL_TRADER_MODEL", "").strip()
    if provider not in {"openai", "anthropic"}:
        problems.append(
            "TECHNICAL_TRADER_MODEL_PROVIDER must be openai or anthropic."
        )
        return
    if not model:
        problems.append("TECHNICAL_TRADER_MODEL is not configured.")

    if provider == "openai":
        key_name = "OPENAI_API_KEY"
        sdk_name = "openai"
    else:
        key_name = "ANTHROPIC_API_KEY"
        sdk_name = "anthropic"
    if not os.environ.get(key_name, "").strip():
        problems.append(f"{key_name} is not configured.")
    if importlib.util.find_spec(sdk_name) is None:
        problems.append(
            f"The {sdk_name} SDK is not installed. Install with: "
            "pip install -e '.[full-demo]'"
        )


def _check_data(problems: list[str]) -> None:
    paths = {
        "ETF_HISTORICAL_PRICES_PATH": _configured_path(
            "ETF_HISTORICAL_PRICES_PATH",
            "ETF_historical_prices.xlsx",
        ),
        "ETF_INFO_PATH": _configured_path("ETF_INFO_PATH", "ETF_info.xlsx"),
    }
    for environment_name, path in paths.items():
        if not path.is_file():
            problems.append(
                f"{environment_name} does not point to a file: {path}"
            )


def main() -> int:
    problems: list[str] = []
    if sys.version_info < (3, 11):
        problems.append("Python 3.11 or newer is required.")

    _load_local_environment(problems)
    _check_imports(problems)
    _check_model_configuration(problems)
    _check_data(problems)

    if problems:
        print("Setup is not ready:")
        for problem in problems:
            print(f"- {problem}")
        return 1

    print("Setup is ready for a real full-loop run.")
    print("No API call was made and no credential value was displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
