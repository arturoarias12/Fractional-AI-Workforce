"""Turns mandate fields into concrete rule-generation parameters.

Flagged gap this closes (raised during dashboard testing): Fundamental and
Quant Trader only ever read ``mandate.as_of_date``, ``permitted_asset_universe``,
and ``prohibited_assets``. Every other mandate field - ``risk_profile``,
``investment_horizon``, ``rebalancing_preference``, ``risk_limits``,
``leverage_constraints``, ``short_selling_constraints``, ``market_context``,
``pm_notes``, ``prior_round_lessons`` - was accepted, stored, and displayed,
but never changed what a trader actually did. This module is the one place
that mapping is defined, so both deterministic traders apply it identically
rather than drifting apart.

Design choice: every mapping below is a **stated, documented rule**, not a
model's interpretation. These traders are deterministic by design (no LLM
computes their strategy) - so "market_context" and "pm_notes" being free
text is a real limit: a keyword scan for "avoid/exclude/skip <TICKER>"
against the permitted universe is what a rule-based system can honestly do
with unstructured text, not a substitute for genuine language understanding.
That's stated here plainly rather than quietly overclaimed.

Each field's mapping, and why:

  * ``risk_profile`` -> ``entry_zscore_multiplier``. "Conservative" raises
    the bar for entering a position (require a larger deviation before
    trading - fewer, higher-conviction candidates); "aggressive" lowers it.
  * ``rebalancing_preference`` -> ``exit_zscore_multiplier``. "Low turnover"
    requires more reversion before exiting (hold longer, trade less);
    "high turnover" exits on a smaller recovery.
  * ``investment_horizon`` -> ``preferred_lookback_days``. Maps a stated or
    numeric horizon onto one of the three lookback windows the discovery
    scan already tries (20 / 40 / 90 trading days), rather than trying all
    three.
  * ``risk_limits`` (structured dict, e.g. ``{"max_drawdown": 0.15}``) ->
    ``max_drawdown_limit``, read directly (no keyword parsing needed - this
    field is always a dict). Used as a post-backtest screen: a candidate
    that breaches this is not proposed as eligible for Risk review.
  * ``leverage_constraints`` / ``short_selling_constraints`` -> validated,
    not mutated. Both traders are long-only and unlevered by design; if the
    mandate explicitly requires leverage or shorting, that is a real
    constraint violation, not something to silently ignore.
  * ``market_context`` / ``pm_notes`` / ``prior_round_lessons`` ->
    ``excluded_tickers``, via the keyword scan described above. A lesson or
    note can also be tagged for one specific agent
    (``"PIVOT[fundamental_trader_agent]: exclude XYZ"``) - untagged entries
    apply to every trader that reads this module; tagged entries apply only
    to the named agent. This is what gives the dashboard's Pivot action a
    real effect (see dashboard/app.py's staffing_dialog).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

DEFAULT_ENTRY_ZSCORE_MULTIPLIER = 1.0
DEFAULT_EXIT_ZSCORE_MULTIPLIER = 1.0

_CONSERVATIVE_TERMS = ("conservative", "cautious", "low risk", "low-risk", "defensive")
_MODERATE_TERMS = ("moderate", "balanced", "medium risk", "medium-risk", "neutral")
_AGGRESSIVE_TERMS = ("aggressive", "growth", "high risk", "high-risk", "opportunistic")

_LOW_TURNOVER_TERMS = ("low turnover", "low-turnover", "infrequent", "buy and hold", "buy-and-hold")
_HIGH_TURNOVER_TERMS = ("high turnover", "high-turnover", "frequent", "active trading")

_SHORT_HORIZON_TERMS = ("short term", "short-term", "short horizon")
_LONG_HORIZON_TERMS = ("long term", "long-term", "long horizon")

_EXCLUSION_PATTERN = re.compile(
    r"\b(?i:avoid|exclude|excluded|skip|vetoed|reject(?:ed)?)\b[^.\n]{0,40}?\b([A-Z][A-Z0-9]{0,4})\b"
)
_PIVOT_TAG_PATTERN = re.compile(r"^PIVOT\[(?P<agent_id>[a-z0-9_]+)\]:\s*(?P<body>.*)$")


@dataclass(frozen=True, slots=True)
class MandateDirectives:
    """Concrete, rule-generator-ready parameters resolved from a mandate."""

    entry_zscore_multiplier: float = DEFAULT_ENTRY_ZSCORE_MULTIPLIER
    exit_zscore_multiplier: float = DEFAULT_EXIT_ZSCORE_MULTIPLIER
    preferred_lookback_days: int | None = None
    excluded_tickers: frozenset[str] = frozenset()
    max_drawdown_limit: float | None = None
    constraint_violations: tuple[str, ...] = ()
    applied_notes: tuple[str, ...] = ()


def _as_text(value: Any) -> str:
    """Flatten a FlexibleDetails-typed field (str | dict | None) to text
    for keyword scanning. Dict values are joined; this is a scan, not a
    parse - see module docstring."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(str(v) for v in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return " ".join(_as_text(item) for item in value)
    return str(value)


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _resolve_risk_profile(risk_profile: Any) -> tuple[float, tuple[str, ...]]:
    text = _as_text(risk_profile)
    if not text:
        return DEFAULT_ENTRY_ZSCORE_MULTIPLIER, ()
    if _contains_any(text, _CONSERVATIVE_TERMS):
        return 1.3, (f"risk_profile ({text!r}) read as conservative: entry threshold raised 1.3x.",)
    if _contains_any(text, _MODERATE_TERMS):
        return (
            DEFAULT_ENTRY_ZSCORE_MULTIPLIER,
            (f"risk_profile ({text!r}) read as moderate: baseline entry threshold retained.",),
        )
    if _contains_any(text, _AGGRESSIVE_TERMS):
        return 0.75, (f"risk_profile ({text!r}) read as aggressive: entry threshold lowered 0.75x.",)
    return DEFAULT_ENTRY_ZSCORE_MULTIPLIER, (f"risk_profile ({text!r}) did not match a known term; no change applied.",)


def _resolve_rebalancing_preference(preference: Any) -> tuple[float, tuple[str, ...]]:
    text = _as_text(preference)
    if not text:
        return DEFAULT_EXIT_ZSCORE_MULTIPLIER, ()
    if _contains_any(text, _LOW_TURNOVER_TERMS):
        return 1.5, (f"rebalancing_preference ({text!r}) read as low-turnover: exit threshold raised 1.5x (holds longer).",)
    if _contains_any(text, _HIGH_TURNOVER_TERMS):
        return 0.6, (f"rebalancing_preference ({text!r}) read as high-turnover: exit threshold lowered 0.6x (exits sooner).",)
    return DEFAULT_EXIT_ZSCORE_MULTIPLIER, (f"rebalancing_preference ({text!r}) did not match a known term; no change applied.",)


def _resolve_investment_horizon(horizon: Any) -> tuple[int | None, tuple[str, ...]]:
    text = _as_text(horizon)
    if not text:
        return None, ()
    if _contains_any(text, _SHORT_HORIZON_TERMS):
        return 20, (f"investment_horizon ({text!r}) read as short: preferred lookback set to 20 trading days.",)
    if _contains_any(text, _LONG_HORIZON_TERMS):
        return 90, (f"investment_horizon ({text!r}) read as long: preferred lookback set to 90 trading days.",)
    match = re.search(r"(\d+)\s*(day|week|month)", text.lower())
    if match:
        count, unit = int(match.group(1)), match.group(2)
        days = count * {"day": 1, "week": 7, "month": 30}[unit]
        preferred = 20 if days <= 30 else 90 if days >= 180 else 40
        return preferred, (f"investment_horizon ({text!r}) parsed as ~{days} days: preferred lookback set to {preferred}.",)
    return None, (f"investment_horizon ({text!r}) did not match a known term or duration; no change applied.",)


def _resolve_risk_limits(risk_limits: Mapping[str, Any] | None) -> tuple[float | None, tuple[str, ...]]:
    if not risk_limits:
        return None, ()
    limit = risk_limits.get("max_drawdown")
    if limit is None:
        return None, ()
    try:
        limit = float(limit)
    except (TypeError, ValueError):
        return None, (f"risk_limits.max_drawdown ({risk_limits.get('max_drawdown')!r}) is not numeric; ignored.",)
    return limit, (f"risk_limits.max_drawdown set to {limit:.0%}: candidates breaching this will not be proposed.",)


def _resolve_constraint_violations(
    leverage_constraints: Any, short_selling_constraints: Any,
) -> tuple[str, ...]:
    violations: list[str] = []
    leverage_text = _as_text(leverage_constraints).lower()
    if re.search(r"\b([2-9]|\d{2,})x\b|leverage\s*(required|mandatory|>\s*1)", leverage_text):
        violations.append(
            f"Mandate's leverage_constraints ({leverage_text!r}) appears to require leverage; "
            "this trader is unlevered by design (max gross exposure 1.0x)."
        )
    short_text = _as_text(short_selling_constraints).lower()
    if re.search(r"\b(require|must|mandatory)\b.{0,20}\bshort", short_text) or "short only" in short_text:
        violations.append(
            f"Mandate's short_selling_constraints ({short_text!r}) appears to require shorting; "
            "this trader is long-only by design."
        )
    return tuple(violations)


def _resolve_excluded_tickers(
    *,
    agent_id: str,
    market_context: Any,
    pm_notes: Any,
    prior_round_lessons: Any,
    permitted_symbols: Sequence[str] | None,
) -> tuple[frozenset[str], tuple[str, ...]]:
    universe = {s.upper() for s in permitted_symbols} if permitted_symbols else None
    excluded: set[str] = set()
    notes: list[str] = []

    def _scan(source_name: str, raw_entries: Sequence[str]) -> None:
        for entry in raw_entries:
            tag_match = _PIVOT_TAG_PATTERN.match(entry.strip())
            if tag_match:
                if tag_match.group("agent_id") != agent_id:
                    continue  # tagged for a different agent - not ours
                body = tag_match.group("body")
            else:
                body = entry
            for match in _EXCLUSION_PATTERN.finditer(body):
                symbol = match.group(1).upper()
                if universe is not None and symbol not in universe:
                    continue  # not a real ticker in this universe - avoid false positives
                excluded.add(symbol)
                notes.append(f"{source_name} excluded {symbol}: {entry.strip()!r}")

    market_context_text = _as_text(market_context)
    if market_context_text:
        _scan("market_context", [market_context_text])

    if isinstance(pm_notes, str):
        _scan("pm_notes", [pm_notes])
    elif isinstance(pm_notes, Sequence):
        _scan("pm_notes", [str(item) for item in pm_notes])

    if isinstance(prior_round_lessons, Sequence) and not isinstance(prior_round_lessons, (str, bytes)):
        _scan("prior_round_lessons", [str(item) for item in prior_round_lessons])
    elif isinstance(prior_round_lessons, Mapping):
        _scan("prior_round_lessons", [str(v) for v in prior_round_lessons.values()])

    return frozenset(excluded), tuple(notes)


def resolve_mandate_directives(
    mandate: Any,
    *,
    agent_id: str,
    permitted_symbols: Sequence[str] | None = None,
) -> MandateDirectives:
    """Resolve one trader's concrete parameters from a PMMandate.

    ``agent_id`` should be the same SpecialistId string used in
    ``active_specialists`` (e.g. ``"fundamental_trader_agent"``) - it scopes
    which tagged Pivot exclusions apply to this trader specifically.
    """

    entry_multiplier, risk_notes = _resolve_risk_profile(getattr(mandate, "risk_profile", None))
    exit_multiplier, rebalance_notes = _resolve_rebalancing_preference(
        getattr(mandate, "rebalancing_preference", None)
    )
    preferred_lookback, horizon_notes = _resolve_investment_horizon(
        getattr(mandate, "investment_horizon", None)
    )
    max_drawdown_limit, risk_limit_notes = _resolve_risk_limits(getattr(mandate, "risk_limits", None))
    constraint_violations = _resolve_constraint_violations(
        getattr(mandate, "leverage_constraints", None),
        getattr(mandate, "short_selling_constraints", None),
    )
    excluded_tickers, exclusion_notes = _resolve_excluded_tickers(
        agent_id=agent_id,
        market_context=getattr(mandate, "market_context", None),
        pm_notes=getattr(mandate, "pm_notes", None),
        prior_round_lessons=getattr(mandate, "prior_round_lessons", None),
        permitted_symbols=permitted_symbols,
    )

    all_notes = risk_notes + rebalance_notes + horizon_notes + risk_limit_notes + exclusion_notes

    return MandateDirectives(
        entry_zscore_multiplier=entry_multiplier,
        exit_zscore_multiplier=exit_multiplier,
        preferred_lookback_days=preferred_lookback,
        excluded_tickers=excluded_tickers,
        max_drawdown_limit=max_drawdown_limit,
        constraint_violations=constraint_violations,
        applied_notes=all_notes,
    )


__all__ = ["MandateDirectives", "resolve_mandate_directives"]
