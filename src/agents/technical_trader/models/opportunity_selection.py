"""Technical-local LLM drafts using atomic opportunity references."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from protocols import ContractModel, NonEmptyStr

from ..parameter_limits import (
    MAX_RELATIVE_VOLUME_MULTIPLE,
    MAX_TECHNICAL_BUFFER_PERCENT,
    MIN_RELATIVE_VOLUME_MULTIPLE,
    MIN_TECHNICAL_BUFFER_PERCENT,
)


TARGET_TECHNICAL_SLEEVES = 10


class OpportunitySleeveParametersDraft(ContractModel):
    """Closed union of the numeric choices a Technical model may author.

    Every field is nullable so one strict provider schema can represent all
    registered sleeve families. Deterministic expansion rejects non-null
    fields that do not belong to the selected opportunity's executor.
    """

    entry_buffer_percent: float | None = Field(
        default=None,
        ge=MIN_TECHNICAL_BUFFER_PERCENT,
        le=MAX_TECHNICAL_BUFFER_PERCENT,
    )
    support_entry_floor_buffer_percent: float | None = Field(
        default=None,
        ge=MIN_TECHNICAL_BUFFER_PERCENT,
        le=MAX_TECHNICAL_BUFFER_PERCENT,
    )
    technical_invalidation_buffer_percent: float | None = Field(
        default=None,
        ge=MIN_TECHNICAL_BUFFER_PERCENT,
        le=MAX_TECHNICAL_BUFFER_PERCENT,
    )
    minimum_relative_volume: float | None = Field(
        default=None,
        ge=MIN_RELATIVE_VOLUME_MULTIPLE,
        le=MAX_RELATIVE_VOLUME_MULTIPLE,
    )
    breakout_buffer_percent: float | None = Field(
        default=None,
        ge=MIN_TECHNICAL_BUFFER_PERCENT,
        le=MAX_TECHNICAL_BUFFER_PERCENT,
    )

    def authored_mapping(self) -> dict[str, float]:
        """Return only fields actually selected for one executor family."""

        return self.model_dump(mode="python", exclude_none=True)


class TechnicalTransactionCostAssumptionsDraft(ContractModel):
    """Closed Technical-local execution assumptions accepted by the engine."""

    initial_capital: float = Field(default=100_000.0, gt=0.0)
    commission_bps: float = Field(default=0.0, ge=0.0, le=1_000.0)
    slippage_bps: float = Field(default=0.0, ge=0.0, le=1_000.0)
    fill_price_field: Literal["open", "close"] = "open"
    signal_delay_bars: int = Field(default=1, ge=1, le=20)
    liquidate_at_end: bool = True
    annualization_factor: int = Field(default=252, ge=1, le=366)


class TechnicalBacktestPlanSelectionDraft(ContractModel):
    """Only the cost/execution choices left to the Technical model."""

    transaction_cost_assumptions: TechnicalTransactionCostAssumptionsDraft


class OpportunitySleeveSelectionDraft(ContractModel):
    """One model-selected deterministic opportunity."""

    opportunity_ref: NonEmptyStr
    expected_return_rationale: NonEmptyStr
    parameters: OpportunitySleeveParametersDraft


class OpportunityPortfolioSelectionDraft(ContractModel):
    """Model-authored portfolio choices before deterministic expansion."""

    portfolio_target_gross_weight: float = Field(gt=0.0, le=1.0)
    omission_rationale: str = ""
    sleeves: list[OpportunitySleeveSelectionDraft] = Field(
        min_length=1,
        max_length=TARGET_TECHNICAL_SLEEVES,
    )

    @model_validator(mode="after")
    def validate_selection(self) -> "OpportunityPortfolioSelectionDraft":
        references = [sleeve.opportunity_ref for sleeve in self.sleeves]
        if len(references) != len(set(references)):
            raise ValueError("Opportunity references must be unique.")
        if (
            len(self.sleeves) < TARGET_TECHNICAL_SLEEVES
            and not self.omission_rationale.strip()
        ):
            raise ValueError(
                "omission_rationale is required when fewer than 10 ETFs "
                "are selected."
            )
        return self


class OpportunityCandidateRuleDraft(ContractModel):
    """Technical narrative plus atomic selections, without canonical IDs."""

    strategy_name: NonEmptyStr
    hypothesis: NonEmptyStr
    rule_summary: NonEmptyStr
    asset_eligibility_logic: NonEmptyStr
    signal_logic: NonEmptyStr
    position_logic: NonEmptyStr
    entry_logic: NonEmptyStr
    exit_logic: NonEmptyStr
    rebalancing_logic: NonEmptyStr
    portfolio: OpportunityPortfolioSelectionDraft
    required_data_fields: list[NonEmptyStr] = Field(default_factory=list)
    constraint_handling: list[NonEmptyStr] = Field(default_factory=list)
    implementation_notes: list[NonEmptyStr] = Field(default_factory=list)


class OpportunityCandidateProposalDraft(ContractModel):
    """Provider response expanded locally into CandidateProposalDraft."""

    rule: OpportunityCandidateRuleDraft
    backtest_plan: TechnicalBacktestPlanSelectionDraft
    mandate_constraint_mapping: list[NonEmptyStr] = Field(default_factory=list)
    known_constraint_violations: list[NonEmptyStr] = Field(default_factory=list)


__all__ = [
    "OpportunityCandidateProposalDraft",
    "OpportunityCandidateRuleDraft",
    "OpportunityPortfolioSelectionDraft",
    "OpportunitySleeveParametersDraft",
    "OpportunitySleeveSelectionDraft",
    "TARGET_TECHNICAL_SLEEVES",
    "TechnicalBacktestPlanSelectionDraft",
    "TechnicalTransactionCostAssumptionsDraft",
]
