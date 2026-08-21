"""OpenAI Responses API adapter for the Technical Trader."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

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
    schema_name,
    sdk_version,
    strict_response_schema,
    structured_json_instruction,
    total_tokens,
    validate_json_output,
)


OpenAIOutputMode = Literal["json_schema", "json_object"]


class OpenAITechnicalModelClient:
    """Implement the provider-neutral model contract with OpenAI.

    The default uses the Responses API JSON-schema format and then validates
    the returned JSON again with the original Pydantic model. ``json_object``
    remains available for a model/schema combination that cannot use native
    JSON Schema; local Pydantic validation is authoritative in both modes.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        reasoning_effort: str | None = None,
        max_output_tokens: int = 12_000,
        sdk_timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_PROVIDER_MAX_RETRIES,
        output_mode: OpenAIOutputMode = "json_schema",
        client: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must be non-empty")
        if not model.strip():
            raise ValueError("model must be non-empty")
        if reasoning_effort is not None and not reasoning_effort.strip():
            raise ValueError("reasoning_effort must be non-empty when supplied")
        if isinstance(max_output_tokens, bool) or max_output_tokens < 256:
            raise ValueError("max_output_tokens must be an integer of at least 256")
        if (
            isinstance(sdk_timeout_seconds, bool)
            or sdk_timeout_seconds <= 0
        ):
            raise ValueError("sdk_timeout_seconds must be positive")
        if isinstance(max_retries, bool) or not 0 <= max_retries <= 3:
            raise ValueError("max_retries must be an integer from 0 through 3")
        if output_mode not in {"json_schema", "json_object"}:
            raise ValueError("output_mode must be 'json_schema' or 'json_object'")

        self._model = model.strip()
        self._reasoning_effort = (
            None if reasoning_effort is None else reasoning_effort.strip()
        )
        self._max_output_tokens = int(max_output_tokens)
        self._output_mode: OpenAIOutputMode = output_mode
        self._minimum_model_call_timeout_seconds = (
            float(sdk_timeout_seconds) * (1 + int(max_retries))
            + PROVIDER_DEADLINE_HEADROOM_SECONDS
        )
        if client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "The OpenAI SDK is not installed. Install the repository "
                    "with: pip install -e \".[technical-models]\""
                ) from exc
            client = AsyncOpenAI(
                api_key=api_key,
                timeout=float(sdk_timeout_seconds),
                max_retries=int(max_retries),
            )
        self._client = client

    @property
    def model(self) -> str:
        return self._model

    @property
    def output_mode(self) -> OpenAIOutputMode:
        return self._output_mode

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
        schema = strict_response_schema(response_model)
        submitted_prompt = user_prompt
        if self._output_mode == "json_schema":
            output_format: dict[str, Any] = {
                "type": "json_schema",
                "name": schema_name(response_model),
                "schema": schema,
                "strict": True,
            }
        else:
            output_format = {"type": "json_object"}
            submitted_prompt = (
                f"{user_prompt}\n\n{structured_json_instruction(response_model)}"
            )

        request: dict[str, Any] = {
            "model": self._model,
            "instructions": system_prompt,
            "input": submitted_prompt,
            "max_output_tokens": self._max_output_tokens,
            "metadata": self._metadata(context),
            "store": False,
            "text": {"format": output_format},
        }
        if self._reasoning_effort is not None:
            request["reasoning"] = {"effort": self._reasoning_effort}

        response = await self._client.responses.create(**request)
        status = str(member(response, "status", "unknown"))
        if status != "completed":
            incomplete = member(response, "incomplete_details")
            reason = member(incomplete, "reason", "unknown")
            raise RuntimeError(
                f"OpenAI response status was {status}; reason: {reason}."
            )

        output = validate_json_output(
            member(response, "output_text"),
            response_model,
            provider="OpenAI",
        )
        return ModelCallResult(
            output=output,
            usage=self._usage(
                response,
                system_prompt_characters=len(system_prompt),
                user_prompt_characters=len(submitted_prompt),
            ),
        )

    @staticmethod
    def _metadata(context: ModelRequestContext) -> dict[str, str]:
        return {
            "agent_id": context.agent_id[:512],
            "operation": context.operation[:512],
            "model_call_id": context.model_call_id[:512],
            "attempt": str(context.attempt),
            "workflow_ref": opaque_context_id(
                context.workflow_id,
                prefix="workflow",
            ),
            "task_ref": opaque_context_id(context.task_id, prefix="task"),
        }

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
        if usage is None:
            return ModelUsage(
                usage_available=False,
                unavailable_reason=(
                    "OpenAI response did not include usage metadata."
                ),
                provider="openai",
                model=response_model,
                provider_request_id=request_id,
                provider_metadata={
                    "sdk_version": sdk_version("openai"),
                    "response_status": str(
                        member(response, "status", "unknown")
                    ),
                    "output_mode": self._output_mode,
                    "system_prompt_characters": system_prompt_characters,
                    "user_prompt_characters": user_prompt_characters,
                },
            )

        input_tokens = optional_nonnegative_int(
            member(usage, "input_tokens")
        )
        output_tokens = optional_nonnegative_int(
            member(usage, "output_tokens")
        )
        input_details = member(usage, "input_tokens_details")
        output_details = member(usage, "output_tokens_details")
        metadata: Mapping[str, Any] = {
            "sdk_version": sdk_version("openai"),
            "cached_input_tokens": optional_nonnegative_int(
                member(input_details, "cached_tokens")
            ),
            "reasoning_tokens": optional_nonnegative_int(
                member(output_details, "reasoning_tokens")
            ),
            "response_status": str(member(response, "status", "unknown")),
            "output_mode": self._output_mode,
            "system_prompt_characters": system_prompt_characters,
            "user_prompt_characters": user_prompt_characters,
        }
        return ModelUsage(
            provider="openai",
            model=response_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens(
                input_tokens,
                output_tokens,
                member(usage, "total_tokens"),
            ),
            provider_request_id=request_id,
            provider_metadata={
                key: value for key, value in metadata.items() if value is not None
            },
        )


__all__ = ["OpenAIOutputMode", "OpenAITechnicalModelClient"]
