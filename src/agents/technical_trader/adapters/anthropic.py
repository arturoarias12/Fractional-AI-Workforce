"""Anthropic Messages API adapter for the Technical Trader."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel

from ..model_client import ModelCallResult, ModelRequestContext, ModelUsage
from ._common import (
    DEFAULT_PROVIDER_MAX_RETRIES,
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    PROVIDER_DEADLINE_HEADROOM_SECONDS,
    clean_optional_string,
    member,
    opaque_context_id,
    optional_nonnegative_int,
    response_schema,
    sdk_version,
    structured_json_instruction,
    total_tokens,
    validate_json_output,
)


SchemaTransform = Callable[[dict[str, Any]], dict[str, Any]]


class AnthropicTechnicalModelClient:
    """Implement the provider-neutral model contract with Anthropic.

    Native structured outputs are enabled by default. The Anthropic SDK's
    schema transformer removes unsupported grammar constraints before the
    request, while the original Pydantic model remains the authoritative local
    validator. Prompt-only JSON can be enabled explicitly for a model that
    does not support native structured outputs.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_output_tokens: int = 12_000,
        sdk_timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_PROVIDER_MAX_RETRIES,
        native_structured_outputs: bool = True,
        client: Any | None = None,
        schema_transform: SchemaTransform | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must be non-empty")
        if not model.strip():
            raise ValueError("model must be non-empty")
        if isinstance(max_output_tokens, bool) or max_output_tokens < 256:
            raise ValueError("max_output_tokens must be an integer of at least 256")
        if (
            isinstance(sdk_timeout_seconds, bool)
            or sdk_timeout_seconds <= 0
        ):
            raise ValueError("sdk_timeout_seconds must be positive")
        if isinstance(max_retries, bool) or not 0 <= max_retries <= 3:
            raise ValueError("max_retries must be an integer from 0 through 3")
        if not isinstance(native_structured_outputs, bool):
            raise ValueError("native_structured_outputs must be a boolean")

        self._model = model.strip()
        self._max_output_tokens = int(max_output_tokens)
        self._native_structured_outputs = native_structured_outputs
        self._minimum_model_call_timeout_seconds = (
            float(sdk_timeout_seconds) * (1 + int(max_retries))
            + PROVIDER_DEADLINE_HEADROOM_SECONDS
        )
        if native_structured_outputs and schema_transform is None:
            try:
                from anthropic import transform_schema
            except ImportError as exc:
                raise RuntimeError(
                    "Anthropic native structured outputs require the SDK's "
                    "schema transformer. Install the repository with "
                    'pip install -e ".[technical-models]" or inject an '
                    "explicit schema_transform for a test client."
                ) from exc
            schema_transform = transform_schema
        if client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:
                raise RuntimeError(
                    "The Anthropic SDK with structured-output support is not "
                    "installed. Install the repository with: "
                    "pip install -e \".[technical-models]\""
                ) from exc
            client = AsyncAnthropic(
                api_key=api_key,
                timeout=float(sdk_timeout_seconds),
                max_retries=int(max_retries),
            )

        self._client = client
        self._schema_transform = schema_transform or (lambda schema: schema)

    @property
    def model(self) -> str:
        return self._model

    @property
    def native_structured_outputs(self) -> bool:
        return self._native_structured_outputs

    @property
    def minimum_model_call_timeout_seconds(self) -> float:
        """Smallest surrounding deadline that preserves all SDK attempts."""

        return self._minimum_model_call_timeout_seconds

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        context: ModelRequestContext,
    ) -> ModelCallResult[Any]:
        schema = response_schema(response_model)
        submitted_prompt = user_prompt
        request: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_output_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": submitted_prompt}],
            "metadata": {
                "user_id": opaque_context_id(
                    context.workflow_id,
                    context.task_id,
                    context.model_call_id,
                    prefix="technical-trader",
                )
            },
        }
        if self._native_structured_outputs:
            request["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": self._schema_transform(schema),
                }
            }
        else:
            submitted_prompt = (
                f"{user_prompt}\n\n{structured_json_instruction(response_model)}"
            )
            request["messages"] = [
                {"role": "user", "content": submitted_prompt}
            ]

        response = await self._client.messages.create(**request)
        stop_reason = str(member(response, "stop_reason", "unknown"))
        if stop_reason != "end_turn":
            raise RuntimeError(
                "Anthropic response did not complete normally; stop_reason="
                f"{stop_reason}."
            )

        content = member(response, "content", ()) or ()
        text_blocks = [
            str(member(block, "text"))
            for block in content
            if member(block, "type") == "text"
            and isinstance(member(block, "text"), str)
        ]
        output = validate_json_output(
            "".join(text_blocks),
            response_model,
            provider="Anthropic",
        )
        return ModelCallResult(
            output=output,
            usage=self._usage(
                response,
                system_prompt_characters=len(system_prompt),
                user_prompt_characters=len(submitted_prompt),
            ),
        )

    def _usage(
        self,
        response: Any,
        *,
        system_prompt_characters: int,
        user_prompt_characters: int,
    ) -> ModelUsage:
        usage = member(response, "usage")
        request_id = clean_optional_string(member(response, "id"))
        response_model = (
            clean_optional_string(member(response, "model")) or self._model
        )
        mode = (
            "json_schema" if self._native_structured_outputs else "prompt_json"
        )
        if usage is None:
            return ModelUsage(
                usage_available=False,
                unavailable_reason=(
                    "Anthropic response did not include usage metadata."
                ),
                provider="anthropic",
                model=response_model,
                provider_request_id=request_id,
                provider_metadata={
                    "sdk_version": sdk_version("anthropic"),
                    "stop_reason": str(
                        member(response, "stop_reason", "unknown")
                    ),
                    "output_mode": mode,
                    "system_prompt_characters": system_prompt_characters,
                    "user_prompt_characters": user_prompt_characters,
                },
            )

        uncached_input = optional_nonnegative_int(
            member(usage, "input_tokens")
        )
        cache_creation = optional_nonnegative_int(
            member(usage, "cache_creation_input_tokens")
        )
        cache_read = optional_nonnegative_int(
            member(usage, "cache_read_input_tokens")
        )
        input_parts = (uncached_input, cache_creation, cache_read)
        normalized_input = (
            sum(value or 0 for value in input_parts)
            if any(value is not None for value in input_parts)
            else None
        )
        output_tokens = optional_nonnegative_int(
            member(usage, "output_tokens")
        )
        metadata: Mapping[str, Any] = {
            "sdk_version": sdk_version("anthropic"),
            "uncached_input_tokens": uncached_input,
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read,
            "stop_reason": str(member(response, "stop_reason", "unknown")),
            "service_tier": clean_optional_string(
                member(response, "service_tier")
            ),
            "output_mode": mode,
            "system_prompt_characters": system_prompt_characters,
            "user_prompt_characters": user_prompt_characters,
        }
        return ModelUsage(
            provider="anthropic",
            model=response_model,
            input_tokens=normalized_input,
            output_tokens=output_tokens,
            total_tokens=total_tokens(normalized_input, output_tokens),
            provider_request_id=request_id,
            provider_metadata={
                key: value for key, value in metadata.items() if value is not None
            },
        )


__all__ = ["AnthropicTechnicalModelClient", "SchemaTransform"]
