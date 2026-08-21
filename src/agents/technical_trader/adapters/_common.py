"""Shared helpers for Technical Trader model-provider adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from pydantic import BaseModel, ValidationError

from ..errors import StructuredOutputValidationError


DEFAULT_PROVIDER_TIMEOUT_SECONDS = 90.0
DEFAULT_PROVIDER_MAX_RETRIES = 0
PROVIDER_DEADLINE_HEADROOM_SECONDS = 5.0


def member(value: Any, name: str, default: Any = None) -> Any:
    """Read a field from either an SDK object or a mapping test double."""

    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def optional_nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def total_tokens(
    input_tokens: int | None,
    output_tokens: int | None,
    provider_total: Any = None,
) -> int | None:
    normalized_total = optional_nonnegative_int(provider_total)
    if normalized_total is not None:
        return normalized_total
    if input_tokens is None or output_tokens is None:
        return None
    return input_tokens + output_tokens


def schema_name(response_model: type[BaseModel]) -> str:
    name = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in response_model.__name__
    )
    return (name or "technical_trader_output")[:64]


def response_schema(response_model: type[BaseModel]) -> dict[str, Any]:
    if not isinstance(response_model, type) or not issubclass(
        response_model, BaseModel
    ):
        raise TypeError("response_model must be a Pydantic BaseModel type")
    return response_model.model_json_schema(mode="validation")


def strict_response_schema(response_model: type[BaseModel]) -> dict[str, Any]:
    """Build a provider-strict schema and reject every open object node."""

    schema = response_schema(response_model)

    def close(node: Any, path: str) -> None:
        if isinstance(node, list):
            for index, child in enumerate(node):
                close(child, f"{path}[{index}]")
            return
        if not isinstance(node, dict):
            return
        node.pop("default", None)
        properties = node.get("properties")
        is_object = node.get("type") == "object" or isinstance(
            properties, dict
        )
        if is_object:
            additional = node.get("additionalProperties")
            if not isinstance(properties, dict) and additional is not False:
                raise ValueError(
                    f"Strict structured output forbids an open object at {path}."
                )
            node["additionalProperties"] = False
            if isinstance(properties, dict):
                node["required"] = list(properties)
        for key, child in tuple(node.items()):
            close(child, f"{path}.{key}")

    close(schema, "$")
    return schema


def structured_json_instruction(response_model: type[BaseModel]) -> str:
    """Fallback instruction for providers running without native schemas."""

    return (
        "Return exactly one JSON object and no Markdown or commentary. "
        "The object will be validated locally against this JSON Schema:\n"
        + json.dumps(response_schema(response_model), sort_keys=True)
    )


def validate_json_output(
    raw_text: Any,
    response_model: type[BaseModel],
    *,
    provider: str,
) -> BaseModel:
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise RuntimeError(
            f"{provider} returned no structured JSON text. The response may "
            "have been refused or truncated."
        )
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise StructuredOutputValidationError(
            f"{provider} returned invalid JSON for "
            f"{response_model.__name__}: {exc}",
            raw_payload={"unparsed_text": raw_text[:12_000]},
        ) from exc
    try:
        return response_model.model_validate(parsed)
    except ValidationError as exc:
        raise StructuredOutputValidationError(
            f"{provider} output failed {response_model.__name__} validation: "
            f"{exc}",
            raw_payload=parsed,
        ) from exc


def sdk_version(distribution_name: str) -> str:
    try:
        return version(distribution_name)
    except PackageNotFoundError:
        return "not-installed"


def clean_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def opaque_context_id(*values: Any, prefix: str) -> str:
    """Return a stable, non-identifying provider-side correlation value."""

    material = "\x1f".join(str(value) for value in values).encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()
    return f"{prefix}-{digest[:40]}"


__all__ = [
    "clean_optional_string",
    "member",
    "opaque_context_id",
    "optional_nonnegative_int",
    "response_schema",
    "schema_name",
    "sdk_version",
    "structured_json_instruction",
    "strict_response_schema",
    "total_tokens",
    "validate_json_output",
]
