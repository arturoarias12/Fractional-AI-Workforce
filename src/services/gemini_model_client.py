"""Gemini adapter for the provider-neutral ModelClient protocol.

Reads GEMINI_API_KEY (and optionally MODEL_NAME) from the environment, so
nothing about which provider is in use is hard-coded here beyond "this file
happens to call Gemini." Any agent that accepts a `model_client` can use
this without knowing it's Gemini underneath.

Notes:
- New GeminiModelClient implementing the ModelClient protocol,
  loading credentials from .env via python-dotenv
- Add google-genai and python-dotenv to pyproject.toml dependencies
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

from agents.technical_trader.model_client import (
    ModelCallResult,
    ModelRequestContext,
    ModelUsage,
    StructuredOutputT,
)

load_dotenv()

DEFAULT_MODEL_NAME = "gemini-2.5-flash"


class GeminiModelClient:
    """Calls the Gemini API and returns a validated structured output."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ["GEMINI_API_KEY"]
        self._model_name = (
            model_name or os.environ.get("MODEL_NAME") or DEFAULT_MODEL_NAME
        )
        self._client = genai.Client(api_key=self._api_key)

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredOutputT],
        context: ModelRequestContext,
    ) -> ModelCallResult[StructuredOutputT]:
        del context  # not sent to the provider; only used for local logging

        response = await self._client.aio.models.generate_content(
            model=self._model_name,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=response_model,
            ),
        )

        output = response.parsed
        if output is None:
            # Fall back to manual validation if the SDK couldn't auto-parse.
            output = response_model.model_validate_json(response.text)

        usage_meta = response.usage_metadata
        usage = ModelUsage(
            provider="gemini",
            model=self._model_name,
            input_tokens=getattr(usage_meta, "prompt_token_count", None),
            output_tokens=getattr(usage_meta, "candidates_token_count", None),
            total_tokens=getattr(usage_meta, "total_token_count", None),
        )

        return ModelCallResult(output=output, usage=usage)
