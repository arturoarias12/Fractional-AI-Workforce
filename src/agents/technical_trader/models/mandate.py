"""Normalized Portfolio Manager mandate input contract."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import Field, field_validator, model_validator

from .common import ExtensibleModel, MandateReference, NonEmptyStr


FlexibleDetails = NonEmptyStr | dict[str, Any]
FlexibleCollection = list[NonEmptyStr] | dict[str, Any]


class PMMandate(ExtensibleModel):
    """Pre-normalized mandate accepted from the Portfolio Manager layer.

    Only identifiers, date, and objective are required. Known fields are typed,
    while additional teammate-defined fields are preserved through
    ``model_extra`` for forward compatibility. Unknown fields are not forwarded
    to specialist prompts automatically.
    """

    workflow_id: NonEmptyStr
    task_id: NonEmptyStr
    as_of_date: date
    investment_objective: NonEmptyStr

    risk_profile: FlexibleDetails | None = None
    investment_horizon: FlexibleDetails | None = None
    liquidity_requirements: FlexibleDetails | None = None
    permitted_asset_universe: FlexibleCollection = Field(default_factory=list)
    prohibited_assets: list[NonEmptyStr] = Field(default_factory=list)
    leverage_constraints: FlexibleDetails | None = None
    short_selling_constraints: FlexibleDetails | None = None
    risk_limits: dict[str, Any] = Field(default_factory=dict)
    market_context: FlexibleDetails | None = None
    prior_round_lessons: FlexibleCollection = Field(default_factory=list)
    rebalancing_preference: FlexibleDetails | None = None
    pm_notes: NonEmptyStr | list[NonEmptyStr] | None = None

    @field_validator(
        "permitted_asset_universe",
        "prohibited_assets",
        mode="after",
    )
    @classmethod
    def deduplicate_assets(
        cls,
        value: FlexibleCollection,
    ) -> FlexibleCollection:
        """Deduplicate list-form assets without changing input order."""

        if isinstance(value, dict):
            return value
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            key = item.casefold()
            if key not in seen:
                result.append(item)
                seen.add(key)
        return result

    @model_validator(mode="after")
    def flag_direct_asset_conflicts(self) -> "PMMandate":
        """Reject only unambiguous list-vs-list universe contradictions."""

        if isinstance(self.permitted_asset_universe, list):
            permitted = {item.casefold() for item in self.permitted_asset_universe}
            prohibited = {item.casefold() for item in self.prohibited_assets}
            overlap = permitted & prohibited
            if overlap:
                names = ", ".join(sorted(overlap))
                raise ValueError(
                    f"Assets cannot be both permitted and prohibited: {names}"
                )
        return self

    def reference(self) -> MandateReference:
        """Return the stable reference used by trader and handoff packages."""

        return MandateReference(
            workflow_id=self.workflow_id,
            task_id=self.task_id,
            as_of_date=self.as_of_date,
        )
