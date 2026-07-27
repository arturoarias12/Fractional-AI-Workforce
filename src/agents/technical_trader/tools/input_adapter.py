"""Replaceable adapter from provisional Data Service payloads to OHLCV series."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import ValidationError

from ..errors import TechnicalAnalysisInputError
from ..models.data import DataCategory, DataResponse
from ..models.technical_analysis import PriceSeries


@runtime_checkable
class TechnicalAnalysisInputAdapter(Protocol):
    """Translate a shared-service response shape into agent-local models."""

    def extract(self, response: DataResponse) -> list[PriceSeries]:
        """Return validated point-in-time OHLCV series."""


class ArtifactPayloadTechnicalInputAdapter:
    """Default provisional adapter.

    A price/volume artifact may currently expose either one ``PriceSeries``, a
    mapping with ``bars``, or ``{"series": [...]}`` through
    ``DataArtifact.analysis_payload``. Replace this adapter when the Data
    Service contract is finalized; the analysis algorithms do not need to
    change.
    """

    def extract(self, response: DataResponse) -> list[PriceSeries]:
        series: list[PriceSeries] = []
        errors: list[str] = []

        for artifact in response.artifacts:
            if artifact.category is not DataCategory.PRICE_VOLUME:
                continue
            payload = artifact.analysis_payload
            if payload is None:
                errors.append(
                    f"{artifact.artifact_id}: missing analysis_payload"
                )
                continue

            candidates = self._payload_candidates(payload)
            for index, candidate in enumerate(candidates):
                if isinstance(candidate, PriceSeries):
                    series.append(candidate)
                    continue
                if not isinstance(candidate, Mapping):
                    errors.append(
                        f"{artifact.artifact_id}[{index}]: expected a mapping"
                    )
                    continue

                normalized: dict[str, Any] = dict(candidate)
                normalized.setdefault("artifact_id", artifact.artifact_id)
                normalized.setdefault("as_of_date", response.as_of_date)
                if artifact.frequency is not None:
                    normalized.setdefault("frequency", artifact.frequency)
                if "symbol" not in normalized and len(artifact.asset_scope) == 1:
                    normalized["symbol"] = artifact.asset_scope[0]

                try:
                    series.append(PriceSeries.model_validate(normalized))
                except ValidationError as exc:
                    errors.append(f"{artifact.artifact_id}[{index}]: {exc}")

        if not series:
            detail = "; ".join(errors) if errors else (
                "no price_volume artifact was returned"
            )
            raise TechnicalAnalysisInputError(
                "No valid OHLCV series was available for deterministic "
                f"technical analysis: {detail}"
            )
        return series

    @staticmethod
    def _payload_candidates(payload: Any) -> list[Any]:
        if isinstance(payload, PriceSeries):
            return [payload]
        if isinstance(payload, Mapping):
            nested = payload.get("series")
            if isinstance(nested, Sequence) and not isinstance(
                nested, (str, bytes)
            ):
                return list(nested)
            return [payload]
        if isinstance(payload, Sequence) and not isinstance(
            payload, (str, bytes)
        ):
            return list(payload)
        return [payload]
