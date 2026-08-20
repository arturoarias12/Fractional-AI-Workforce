"""Tests for mandate_directives.resolve_mandate_directives.

Uses a lightweight stand-in mandate object (not the full PMMandate pydantic
model) since resolve_mandate_directives only reads attributes via getattr -
this keeps these tests fast and focused on the resolution logic itself.
"""

from __future__ import annotations

from types import SimpleNamespace

from mandate_directives import resolve_mandate_directives


def _mandate(**overrides):
    defaults = dict(
        risk_profile=None,
        investment_horizon=None,
        leverage_constraints=None,
        short_selling_constraints=None,
        risk_limits={},
        market_context=None,
        prior_round_lessons=[],
        rebalancing_preference=None,
        pm_notes=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_defaults_are_neutral_when_nothing_is_set():
    directives = resolve_mandate_directives(_mandate(), agent_id="fundamental_trader_agent")

    assert directives.entry_zscore_multiplier == 1.0
    assert directives.exit_zscore_multiplier == 1.0
    assert directives.preferred_lookback_days is None
    assert directives.excluded_tickers == frozenset()
    assert directives.max_drawdown_limit is None
    assert directives.constraint_violations == ()


def test_conservative_risk_profile_raises_entry_threshold():
    mandate = _mandate(risk_profile="Please be conservative this round.")
    directives = resolve_mandate_directives(mandate, agent_id="fundamental_trader_agent")

    assert directives.entry_zscore_multiplier == 1.3
    assert any("conservative" in note for note in directives.applied_notes)


def test_aggressive_risk_profile_lowers_entry_threshold():
    mandate = _mandate(risk_profile={"tolerance": "aggressive"})
    directives = resolve_mandate_directives(mandate, agent_id="fundamental_trader_agent")

    assert directives.entry_zscore_multiplier == 0.75


def test_low_turnover_preference_raises_exit_threshold():
    mandate = _mandate(rebalancing_preference="low-turnover please")
    directives = resolve_mandate_directives(mandate, agent_id="fundamental_trader_agent")

    assert directives.exit_zscore_multiplier == 1.5


def test_short_horizon_prefers_short_lookback():
    mandate = _mandate(investment_horizon="short-term")
    directives = resolve_mandate_directives(mandate, agent_id="fundamental_trader_agent")

    assert directives.preferred_lookback_days == 20


def test_numeric_horizon_is_parsed():
    mandate = _mandate(investment_horizon="approximately 200 days")
    directives = resolve_mandate_directives(mandate, agent_id="fundamental_trader_agent")

    assert directives.preferred_lookback_days == 90


def test_risk_limits_max_drawdown_is_read_directly():
    mandate = _mandate(risk_limits={"max_drawdown": 0.12})
    directives = resolve_mandate_directives(mandate, agent_id="fundamental_trader_agent")

    assert directives.max_drawdown_limit == 0.12


def test_leverage_requirement_is_flagged_as_a_violation():
    mandate = _mandate(leverage_constraints="Leverage is mandatory, target 2x exposure.")
    directives = resolve_mandate_directives(mandate, agent_id="fundamental_trader_agent")

    assert len(directives.constraint_violations) == 1
    assert "leverage" in directives.constraint_violations[0].lower()


def test_short_requirement_is_flagged_as_a_violation():
    mandate = _mandate(short_selling_constraints="Must include short positions this round.")
    directives = resolve_mandate_directives(mandate, agent_id="fundamental_trader_agent")

    assert len(directives.constraint_violations) == 1
    assert "short" in directives.constraint_violations[0].lower()


def test_market_context_excludes_a_mentioned_ticker():
    mandate = _mandate(market_context="Avoid AWAY this round due to a pending delisting.")
    directives = resolve_mandate_directives(
        mandate, agent_id="fundamental_trader_agent", permitted_symbols=["AWAY", "PEJ", "XLY"],
    )

    assert directives.excluded_tickers == frozenset({"AWAY"})


def test_exclusion_outside_the_permitted_universe_is_ignored():
    """Avoids false positives: a capitalized word that isn't a real ticker
    in this universe should not silently exclude a symbol that happens to
    match the two-to-five-letter pattern."""
    mandate = _mandate(market_context="Please avoid ASAP delays this round.")
    directives = resolve_mandate_directives(
        mandate, agent_id="fundamental_trader_agent", permitted_symbols=["AWAY", "PEJ", "XLY"],
    )

    assert directives.excluded_tickers == frozenset()


def test_prior_round_lessons_exclude_a_vetoed_ticker():
    mandate = _mandate(prior_round_lessons=["Risk vetoed AWAY for insufficient trade count."])
    directives = resolve_mandate_directives(
        mandate, agent_id="fundamental_trader_agent", permitted_symbols=["AWAY", "PEJ"],
    )

    assert directives.excluded_tickers == frozenset({"AWAY"})


def test_pivot_tag_only_applies_to_the_named_agent():
    mandate = _mandate(
        prior_round_lessons=["PIVOT[fundamental_trader_agent]: exclude AWAY, try a different candidate."]
    )

    fundamental_directives = resolve_mandate_directives(
        mandate, agent_id="fundamental_trader_agent", permitted_symbols=["AWAY", "PEJ"],
    )
    quant_directives = resolve_mandate_directives(
        mandate, agent_id="quant_trader_agent", permitted_symbols=["AWAY", "PEJ"],
    )

    assert fundamental_directives.excluded_tickers == frozenset({"AWAY"})
    assert quant_directives.excluded_tickers == frozenset()


def test_untagged_lesson_applies_to_every_agent():
    mandate = _mandate(prior_round_lessons=["Team decided to avoid AWAY across all strategies."])

    fundamental_directives = resolve_mandate_directives(
        mandate, agent_id="fundamental_trader_agent", permitted_symbols=["AWAY", "PEJ"],
    )
    quant_directives = resolve_mandate_directives(
        mandate, agent_id="quant_trader_agent", permitted_symbols=["AWAY", "PEJ"],
    )

    assert fundamental_directives.excluded_tickers == frozenset({"AWAY"})
    assert quant_directives.excluded_tickers == frozenset({"AWAY"})
