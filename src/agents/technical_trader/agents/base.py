"""Small, replaceable agent abstraction shared by this subsystem."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import UTC, datetime
from math import isfinite
from time import perf_counter
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from ..execution import DEFAULT_MODEL_CALL_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS
from ..errors import (
    AgentOutputValidationError,
    ModelInvocationError,
    ModelTimeoutError,
    StrategyBoundaryError,
)
from ..model_client import (
    MetricsSink,
    ModelCallMetrics,
    ModelCallResult,
    ModelCallStatus,
    ModelClient,
    ModelRequestContext,
    ModelUsage,
    NullMetricsSink,
    StructuredOutputT,
)


InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT", bound=BaseModel)
logger = logging.getLogger(__name__)


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """Minimal async base class with provider-neutral structured generation.

    The abstraction intentionally owns only stable cross-agent concerns:
    identity, model dependency, structured-output validation, and error
    normalization. Orchestration and financial responsibilities remain outside
    this base so it can be replaced without a broad rewrite.
    """

    def __init__(
        self,
        *,
        agent_id: str,
        model_client: ModelClient,
        metrics_sink: MetricsSink | None = None,
        model_timeout_seconds: float = DEFAULT_MODEL_CALL_TIMEOUT_SECONDS,
    ) -> None:
        if not agent_id.strip():
            raise ValueError("agent_id must be non-empty")
        if (
            isinstance(model_timeout_seconds, bool)
            or not isinstance(model_timeout_seconds, (int, float))
            or not isfinite(model_timeout_seconds)
            or model_timeout_seconds <= 0
        ):
            raise ValueError("model_timeout_seconds must be a positive number")
        if model_timeout_seconds > MAX_TIMEOUT_SECONDS:
            raise ValueError(
                f"model_timeout_seconds cannot exceed "
                f"{MAX_TIMEOUT_SECONDS:g} seconds"
            )
        self._agent_id = agent_id.strip()
        self._model_client = model_client
        self._metrics_sink = (
            metrics_sink if metrics_sink is not None else NullMetricsSink()
        )
        self._model_timeout_seconds = model_timeout_seconds

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @abstractmethod
    async def run(self, request: InputT) -> OutputT:
        """Execute the agent against a validated request."""

    async def _generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredOutputT],
        context: ModelRequestContext,
    ) -> StructuredOutputT:
        started_at = datetime.now(UTC)
        started_clock = perf_counter()
        status = ModelCallStatus.FAILED
        usage: ModelUsage | None = None
        error_type: str | None = None
        error_message: str | None = None

        try:
            async with asyncio.timeout(self._model_timeout_seconds):
                call_result = await self._model_client.generate_structured(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_model=response_model,
                    context=context,
                )

            if not isinstance(call_result, ModelCallResult):
                raise AgentOutputValidationError(
                    f"{self.agent_id} model adapter returned "
                    f"{type(call_result).__name__}; expected ModelCallResult."
                )
            if not isinstance(call_result.usage, ModelUsage):
                raise AgentOutputValidationError(
                    f"{self.agent_id} model adapter returned invalid usage metadata."
                )
            usage = call_result.usage
            raw = call_result.output

            if isinstance(raw, response_model):
                status = ModelCallStatus.SUCCEEDED
                return raw

            if not isinstance(raw, (BaseModel, Mapping)):
                raise AgentOutputValidationError(
                    f"{self.agent_id} returned {type(raw).__name__}; expected "
                    f"{response_model.__name__} or a mapping."
                )

            payload: Any = (
                raw.model_dump(mode="python") if isinstance(raw, BaseModel) else raw
            )
            try:
                output = response_model.model_validate(payload)
            except StrategyBoundaryError:
                raise
            except ValidationError as exc:
                raise AgentOutputValidationError(
                    f"Invalid structured output from {self.agent_id}: {exc}",
                    raw_payload=payload,
                ) from exc

            status = ModelCallStatus.SUCCEEDED
            return output
        except TimeoutError as exc:
            status = ModelCallStatus.TIMED_OUT
            error_type = type(exc).__name__
            error_message = (
                f"Model call timed out after {self._model_timeout_seconds:g} seconds."
            )
            raise ModelTimeoutError(
                f"{self.agent_id}:{context.operation} {error_message}"
            ) from exc
        except asyncio.CancelledError as exc:
            status = ModelCallStatus.CANCELLED
            error_type = type(exc).__name__
            error_message = "Model call was cancelled."
            raise
        except (AgentOutputValidationError, StrategyBoundaryError) as exc:
            error_type = type(exc).__name__
            error_message = str(exc) or type(exc).__name__
            raise
        except ModelInvocationError as exc:
            error_type = type(exc).__name__
            error_message = str(exc) or type(exc).__name__
            raise
        except Exception as exc:
            error_type = type(exc).__name__
            error_message = str(exc) or type(exc).__name__
            raise ModelInvocationError(
                f"Model invocation failed for {self.agent_id}:{context.operation}: {exc}",
                raw_payload=getattr(exc, "raw_payload", None),
            ) from exc
        finally:
            completed_at = datetime.now(UTC)
            event = ModelCallMetrics(
                context=context,
                status=status,
                started_at=started_at,
                completed_at=completed_at,
                latency_ms=max(0.0, (perf_counter() - started_clock) * 1000),
                usage=usage,
                error_type=error_type,
                error_message=error_message,
            )
            try:
                self._metrics_sink.record_model_call(event)
            except Exception:
                # Operational instrumentation must not corrupt an analytical
                # result. Production sinks should enqueue synchronously and
                # monitor their own delivery failures.
                logger.exception(
                    "Metrics sink failed for model_call_id=%s",
                    context.model_call_id,
                )
