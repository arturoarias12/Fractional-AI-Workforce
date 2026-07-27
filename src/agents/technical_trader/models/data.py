"""Provisional shared Data Service request and response contracts."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from .common import (
    ExtensibleModel,
    NonEmptyStr,
    TaskLineage,
    TraderType,
)


class DataCategory(StrEnum):
    PRICE_VOLUME = "price_volume"
    ETF_METADATA = "etf_metadata"
    HOLDINGS_EXPOSURE = "holdings_exposure"
    MARKET_MACRO = "market_macro"
    NEWS_CONTEXT = "news_context"
    GOVERNANCE_CONTROVERSY = "governance_controversy"
    FACTOR_DATA = "factor_data"
    REFERENCE_RATES = "reference_rates"
    OTHER = "other"


class DataFieldRequirement(ExtensibleModel):
    name: NonEmptyStr
    purpose: NonEmptyStr
    required: bool = True
    point_in_time_required: bool = True
    publication_date_required: bool = False


class DataRequest(ExtensibleModel):
    """Trader-authored requirements wrapped in code-owned identifiers."""

    request_id: NonEmptyStr
    lineage: TaskLineage
    trader_type: TraderType
    as_of_date: date
    purpose: NonEmptyStr
    asset_universe: list[NonEmptyStr] | dict[str, Any] = Field(default_factory=list)
    categories: list[DataCategory] = Field(default_factory=list)
    fields: list[DataFieldRequirement] = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    frequency: NonEmptyStr | None = None
    provenance_required: bool = True

    @model_validator(mode="after")
    def validate_dates(self) -> "DataRequest":
        if self.end_date is not None and self.end_date > self.as_of_date:
            raise ValueError("Data request end_date cannot exceed as_of_date.")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("Data request start_date cannot exceed end_date.")
        return self


class DataProvenance(ExtensibleModel):
    provenance_id: NonEmptyStr
    provider: NonEmptyStr
    source_reference: NonEmptyStr
    retrieved_at: datetime
    effective_at: datetime | None = None
    published_at: datetime | None = None
    version: NonEmptyStr | None = None
    checksum: NonEmptyStr | None = None
    point_in_time_verified: bool
    notes: list[NonEmptyStr] = Field(default_factory=list)


class DataArtifact(ExtensibleModel):
    """An opaque data reference plus optional LLM-safe analytical payload."""

    artifact_id: NonEmptyStr
    category: DataCategory
    description: NonEmptyStr
    data_reference: NonEmptyStr
    schema_fields: list[NonEmptyStr] = Field(default_factory=list)
    asset_scope: list[NonEmptyStr] = Field(default_factory=list)
    coverage_start: date | None = None
    coverage_end: date | None = None
    frequency: NonEmptyStr | None = None
    provenance: list[DataProvenance] = Field(min_length=1)
    analysis_payload: Any | None = None
    limitations: list[NonEmptyStr] = Field(default_factory=list)


class DataResponse(ExtensibleModel):
    """Point-in-time research package returned by the shared Data Service."""

    response_id: NonEmptyStr
    request_id: NonEmptyStr
    lineage: TaskLineage
    as_of_date: date
    complete: bool
    artifacts: list[DataArtifact] = Field(default_factory=list)
    unavailable_fields: list[NonEmptyStr] = Field(default_factory=list)
    limitations: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_point_in_time_boundaries(self) -> "DataResponse":
        for artifact in self.artifacts:
            if (
                artifact.coverage_end is not None
                and artifact.coverage_end > self.as_of_date
            ):
                raise ValueError(
                    f"Artifact {artifact.artifact_id} exceeds response as_of_date."
                )
            for provenance in artifact.provenance:
                for timestamp_name in ("effective_at", "published_at"):
                    timestamp = getattr(provenance, timestamp_name)
                    if timestamp is not None and timestamp.date() > self.as_of_date:
                        raise ValueError(
                            f"{timestamp_name} for {provenance.provenance_id} "
                            "exceeds response as_of_date."
                        )
        return self

