"""Shared point-in-time Data Service request and response contracts."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from .common import ExtensibleModel, NonEmptyStr, SpecialistId, TaskLineage


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
    request_id: NonEmptyStr
    lineage: TaskLineage
    trader_id: SpecialistId
    as_of_date: date
    purpose: NonEmptyStr
    asset_universe: list[NonEmptyStr] | dict[str, Any] = Field(
        default_factory=list
    )
    categories: list[DataCategory] = Field(default_factory=list)
    fields: list[DataFieldRequirement] = Field(default_factory=list)
    required_fields: list[NonEmptyStr] = Field(default_factory=list)
    optional_fields: list[NonEmptyStr] = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    frequency: NonEmptyStr | None = None
    provenance_required: bool = True
    additional_fields: dict[str, Any] = Field(default_factory=dict)

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
        if not self.required_fields:
            object.__setattr__(
                self,
                "required_fields",
                [field.name for field in self.fields if field.required],
            )
        if not self.optional_fields:
            object.__setattr__(
                self,
                "optional_fields",
                [field.name for field in self.fields if not field.required],
            )
        return self


class DataProvenance(ExtensibleModel):
    provenance_id: NonEmptyStr
    provider: NonEmptyStr
    source_reference: NonEmptyStr
    retrieved_at: datetime
    point_in_time_verified: bool
    effective_at: datetime | None = None
    published_at: datetime | None = None
    version: NonEmptyStr | None = None
    checksum: NonEmptyStr | None = None
    notes: list[NonEmptyStr] = Field(default_factory=list)


class DataArtifact(ExtensibleModel):
    artifact_id: NonEmptyStr
    category: DataCategory = DataCategory.OTHER
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

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_adapter_payload(cls, value: Any) -> Any:
        if isinstance(value, dict):
            normalized = dict(value)
            if (
                "analysis_payload" not in normalized
                and "adapter_payload" in normalized
            ):
                normalized["analysis_payload"] = normalized["adapter_payload"]
            return normalized
        return value

    @property
    def adapter_payload(self) -> Any | None:
        """Compatibility view of the former payload field name."""

        return self.analysis_payload


class DataResponse(ExtensibleModel):
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
                    f"Artifact {artifact.artifact_id} exceeds response "
                    "as_of_date."
                )
            for provenance in artifact.provenance:
                for name in ("effective_at", "published_at"):
                    timestamp = getattr(provenance, name)
                    if (
                        timestamp is not None
                        and timestamp.date() > self.as_of_date
                    ):
                        raise ValueError(
                            f"{name} for {provenance.provenance_id} exceeds "
                            "response as_of_date."
                        )
        return self
