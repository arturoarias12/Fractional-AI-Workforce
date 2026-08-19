"""Environment-driven Technical Trader model-provider selection."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from math import isfinite
from typing import Any, cast

from ..execution import ExecutionPolicy
from ..model_client import ModelClient
from ._common import (
    DEFAULT_PROVIDER_MAX_RETRIES,
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    PROVIDER_DEADLINE_HEADROOM_SECONDS,
)
from .anthropic import AnthropicTechnicalModelClient
from .openai import OpenAIOutputMode, OpenAITechnicalModelClient


class TechnicalModelConfigurationError(ValueError):
    """Raised when production model-provider configuration is incomplete."""


class TechnicalModelProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


def _required(settings: Mapping[str, str], name: str) -> str:
    value = str(settings.get(name, "")).strip()
    if not value:
        raise TechnicalModelConfigurationError(
            f"Required environment variable {name} is not set."
        )
    return value


def _integer(
    settings: Mapping[str, str],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = str(settings.get(name, default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise TechnicalModelConfigurationError(
            f"{name} must be an integer."
        ) from exc
    if not minimum <= value <= maximum:
        raise TechnicalModelConfigurationError(
            f"{name} must be from {minimum} through {maximum}."
        )
    return value


def _positive_float(
    settings: Mapping[str, str],
    name: str,
    *,
    default: float,
) -> float:
    raw = str(settings.get(name, default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise TechnicalModelConfigurationError(
            f"{name} must be numeric."
        ) from exc
    if not isfinite(value) or value <= 0:
        raise TechnicalModelConfigurationError(
            f"{name} must be a positive finite number."
        )
    return value


def _boolean(
    settings: Mapping[str, str],
    name: str,
    *,
    default: bool,
) -> bool:
    raw = str(settings.get(name, str(default))).strip().casefold()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise TechnicalModelConfigurationError(
        f"{name} must be true/false, yes/no, on/off, or 1/0."
    )


def create_technical_model_client_from_env(
    *,
    execution_policy: ExecutionPolicy,
    environ: Mapping[str, str] | None = None,
    client: Any | None = None,
) -> ModelClient:
    """Create the selected provider adapter without changing agent code.

    Required variables are ``TECHNICAL_TRADER_MODEL_PROVIDER``,
    ``TECHNICAL_TRADER_MODEL``, and the selected provider's standard API-key
    variable. Importing the package never reads credentials; this explicit
    composition function does so only when called.
    """

    if not isinstance(execution_policy, ExecutionPolicy):
        raise TechnicalModelConfigurationError(
            "execution_policy must be an ExecutionPolicy instance."
        )
    model_call_timeout_seconds = (
        execution_policy.model_call_timeout_seconds
    )
    settings = os.environ if environ is None else environ
    raw_provider = _required(
        settings,
        "TECHNICAL_TRADER_MODEL_PROVIDER",
    ).casefold()
    try:
        provider = TechnicalModelProvider(raw_provider)
    except ValueError as exc:
        supported = ", ".join(item.value for item in TechnicalModelProvider)
        raise TechnicalModelConfigurationError(
            "TECHNICAL_TRADER_MODEL_PROVIDER must be one of: " + supported
        ) from exc

    model = _required(settings, "TECHNICAL_TRADER_MODEL")
    max_output_tokens = _integer(
        settings,
        "TECHNICAL_TRADER_MAX_OUTPUT_TOKENS",
        default=12_000,
        minimum=256,
        maximum=100_000,
    )
    timeout = _positive_float(
        settings,
        "TECHNICAL_TRADER_PROVIDER_TIMEOUT_SECONDS",
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    )
    retries = _integer(
        settings,
        "TECHNICAL_TRADER_PROVIDER_MAX_RETRIES",
        default=DEFAULT_PROVIDER_MAX_RETRIES,
        minimum=0,
        maximum=3,
    )
    provider_deadline_budget = (
        timeout * (1 + retries) + PROVIDER_DEADLINE_HEADROOM_SECONDS
    )
    if provider_deadline_budget >= model_call_timeout_seconds:
        raise TechnicalModelConfigurationError(
            "Technical model-provider timeout/retry budget must remain below "
            "the surrounding model-call deadline. Configured provider budget "
            f"is {provider_deadline_budget:g} seconds including "
            f"{PROVIDER_DEADLINE_HEADROOM_SECONDS:g} seconds of retry "
            f"headroom; model_call_timeout_seconds is "
            f"{model_call_timeout_seconds:g}."
        )

    if provider is TechnicalModelProvider.OPENAI:
        reasoning_effort = str(
            settings.get("TECHNICAL_TRADER_OPENAI_REASONING_EFFORT", "")
        ).strip() or None
        output_mode = str(
            settings.get(
                "TECHNICAL_TRADER_OPENAI_OUTPUT_MODE",
                "json_schema",
            )
        ).strip().casefold()
        if output_mode not in {"json_schema", "json_object"}:
            raise TechnicalModelConfigurationError(
                "TECHNICAL_TRADER_OPENAI_OUTPUT_MODE must be json_schema or "
                "json_object."
            )
        return OpenAITechnicalModelClient(
            api_key=_required(settings, "OPENAI_API_KEY"),
            model=model,
            reasoning_effort=reasoning_effort,
            max_output_tokens=max_output_tokens,
            sdk_timeout_seconds=timeout,
            max_retries=retries,
            output_mode=cast(OpenAIOutputMode, output_mode),
            client=client,
        )

    native_structured_outputs = _boolean(
        settings,
        "TECHNICAL_TRADER_ANTHROPIC_NATIVE_STRUCTURED_OUTPUTS",
        default=True,
    )
    return AnthropicTechnicalModelClient(
        api_key=_required(settings, "ANTHROPIC_API_KEY"),
        model=model,
        max_output_tokens=max_output_tokens,
        sdk_timeout_seconds=timeout,
        max_retries=retries,
        native_structured_outputs=native_structured_outputs,
        client=client,
    )


__all__ = [
    "TechnicalModelConfigurationError",
    "TechnicalModelProvider",
    "create_technical_model_client_from_env",
]
