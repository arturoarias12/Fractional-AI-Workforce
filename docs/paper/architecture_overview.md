# The Fractional AI Workforce

*System Architecture Overview | Prepared by Aditi | The Fractional AI Workforce, Group 6*

## 1. The Idea, in Plain Terms

Most discussions of "AI agents" focus on whether an agent can complete a task. This project asks a different question: once you have a team of AI agents instead of one, how does a human actually manage them — decide who to trust, who to let go, and who to try differently — the way a manager runs a small team of people? The Fractional AI Workforce answers that question inside a concrete, testable setting: a solo investment researcher who "hires" a small staff of AI specialists to research trading strategies. The specific setting (finance) is a vehicle; the actual contribution is a management pattern — a dashboard and a set of productivity metrics that turn "which AI agent should I keep using" into a data-driven decision instead of a guess.

## 2. The System in One Paragraph

The Fractional AI Workforce is a Virtual Office in which a human Portfolio Manager (PM) delegates to five hireable specialist agents — three independent traders (Technical, Fundamental, Quant), a Risk/Skeptic agent, and a Reporting agent — that together propose, backtest, and critique trading strategies across a fixed 120-ETF universe. A real-time dashboard tracks each agent's real, measured productivity (cost, latency, success rate, veto rate), and that data — not subjective judgment — is the input to the PM's hire/fire/pivot decisions. That loop now runs for real, end to end: a human decision pauses and resumes the actual system, staffing changes have a real effect on the next round, and the data behind every metric is replayed from an event ledger rather than any agent's self-report.

## 3. The Architecture Decision: The Independent Trader Architecture

Two architectures were evaluated for how Technical, Fundamental, and Quant should relate to each other: the Independent Trader Architecture (adopted), where each trader owns the full propose-through-backtest pipeline for its own analytical lens, and a combined-strategy alternative, where three analysts feed a single combiner before backtesting. The independent design was chosen for three reasons: it keeps the hireable roster at exactly 5 agents, as the project brief requires; it makes every result attributable to a single agent, which the hire/fire/pivot thesis depends on; and the alternative's synthesis step — mechanically combining a technical, a fundamental, and a statistical signal into one rule — was a genuinely unsolved design problem the timeline could not safely absorb. One idea from that alternative was kept: the Data service pushes an initial point-in-time package to all three traders as soon as the PM sets the mandate, rather than each trader starting from nothing.

## 4. The Five Hireable Agents

| Agent | Lens / Job | Owner | Status |
| --- | --- | --- | --- |
| Technical Trader | Charts, volume, indicators (RSI, MACD, moving averages) | Arturo | Real when configured (OpenAI/Anthropic/Gemini adapters built); falls back to a labeled stub without credentials. Live-key smoke test completed — see the Technical Trader methodology section for the verified result. |
| Fundamental Trader | Fund-level fundamentals via ISSUER_SCALE_TIER heuristic (category-benchmark deviation) | Aditi | Built, tested, verified end-to-end |
| Quant Trader | Statistical anomalies — cross-asset mean-reversion pairs | Shaurya | Built, verified end-to-end |
| Risk / Skeptic Agent | 13-point cherry-picking checklist (CP-1–CP-13); can veto any candidate | Yutong | Built, verified against real candidates and a real 4-round run |
| Reporting Agent | Assembles the strategy memo from whatever survives Risk | Emma | Built, verified against real Risk output |

*Data service and the deterministic backtest engine are shared infrastructure — tools every trader calls — not hireable agents, which keeps the roster at 5 per the project brief.*

## 5. The Research Loop

PM → Data (initial push) → {Technical, Fundamental, Quant} in parallel → Risk → Reporting → PM decision (durable interrupt) → Memory → next round.

The PM sets the mandate — not just as-of date and universe, but risk profile, investment horizon, rebalancing preference, risk limits, and leverage/short constraints, all of which now have a real, documented effect on what each trader proposes (see §6). The Data service immediately pushes an initial data package to all three traders. Each trader independently proposes a rule using its own lens and tests it via the shared backtest engine. Risk reviews all three results together against its 13-point checklist and can veto any of them. Reporting writes up whatever survives. The PM's decision — Select, Reject, or Request Another Round — is a real pause-and-resume of the running system, not a script: the graph genuinely halts and waits for that decision, and Hire/Bench/Pivot choices made at that point carry into the next round. The outcome is written to a persistent Memory store that survives between rounds, closing the loop.

## 6. What Was Actually Fixed, Not Just Planned

A round of dashboard testing surfaced three real gaps between what the system was supposed to do and what it actually did. All three were found, fixed, and verified against the real system, not just described:

| Gap found | Fix |
| --- | --- |
| Only as-of date, universe, and prohibited assets affected trader behavior; every other mandate field was accepted and displayed but ignored. | Built a shared, documented resolver (`mandate_directives.py`) used by both deterministic traders: `risk_profile` tunes entry conviction, `rebalancing_preference` tunes exit patience, `investment_horizon` sets the lookback window, `risk_limits.max_drawdown` is a real post-backtest screen, leverage/short constraints are validated (not ignored), and `market_context`/`pm_notes`/`prior_round_lessons` exclude specific tickers via a stated keyword scan. |
| Hire/Bench worked, but "Pivot" was cosmetic — it mapped to the same status as Hire and only wrote a UI log line. | Pivot now tags a real, agent-scoped exclusion that rides into the next round's mandate, genuinely changing which candidate that specific agent proposes next. Verified end-to-end: pivoting an agent changes its output; other agents are unaffected. |
| Non-time productivity metrics (success rate, retries, failures) stayed N/A even after the evaluation harness was built. | Found the actual cause: the dashboard had a second, separate, incomplete metrics calculation that hardcoded `success_rate` to "N/A" unconditionally. Replaced it with the real, tested `evaluation.harness` module — one source of truth instead of two disagreeing ones. |

## 7. Verification Discipline

- 111 automated tests pass on `main` as of this writing (up from 91 at the time the mandate-directive fix first landed, as more agent and integration work merged in), including 20 covering the mandate-directive resolver and two full end-to-end proofs that a Pivot action and a risk-profile change each genuinely alter what a trader proposes — not just that the underlying resolver returns the right value in isolation.
- A representative live run drove the real system through four consecutive rounds (23 operational events), and the Risk agent's deterministic checklist correctly vetoed both surviving candidates at round 4 on CP-11 (the validation-touch budget) — a genuine veto produced by real code reviewing real results, not a scripted demo outcome.
- The dashboard was verified to launch cleanly from a completely fresh install, following its own README's setup instructions exactly, before any documentation claims were made about it.
- Every fix in §6 was verified against the real, shared 120-ETF dataset through the actual compiled production graph — not a mock — and confirmed that both real traders still pass Risk's unmodified checklist afterward.

## 8. Known Limitations (honest, not hidden)

- Technical Trader's live model call has been smoke-tested with real credentials against a real OpenAI model — see its methodology section's verified result (43.44% vs. a 39.57% executable benchmark over a 504-session held-out window). That result came from a controlled, Technical-only harness, not the full five-agent production graph; a separate integration run confirmed the same runtime completes correctly inside the compiled production graph alongside Fundamental and Quant Trader, but that run did not independently re-verify the backtest performance figures above.
- Five of the Risk agent's 13 checks (CP-1, CP-2, CP-4, CP-10, CP-12) require a round-audit and round-history reader that doesn't exist yet; they currently return a flag requiring human review rather than a computed verdict, and are honest about that rather than defaulting to pass.
- A data-provenance regression was found and documented, not silently patched: the shared data source's point-in-time verification was relaxed at some point, and no current check catches that specific class of regression. This is flagged as a genuine open question for the team, not resolved unilaterally.
- API cost is measured end-to-end in the metrics pipeline but has no live runtime source wired in yet, so it currently reports N/A rather than a number — stated as an absence, not printed as zero.
- The `risk_limits.max_drawdown` screen checks only the single top-ranked candidate per trader per round; a lower-ranked, compliant alternative is not automatically retried the same round.
- Memory and paused-round state persist to local files, not a shared or hosted store — correct for a single-machine demo, not yet a multi-user system.

## 9. Where This Leaves the Project

The engine of the system — the mechanism the entire hire/fire/pivot thesis depends on — is proven to work end-to-end, with real agents, real Risk review, real Reporting output, real Memory, and real staffing effects. Every agent has a completed methodology section. What remains is concentrated in a small number of well-understood, individually owned items (§8), plus assembling the individual methodology sections into one coherent final paper — which has not yet started, despite every section it depends on now existing. For a reader evaluating this as a portfolio artifact, the distinction that matters is between a demo that merely runs and a system whose behavior, including its failure modes, has been independently verified — this project has consistently aimed for the latter, including when that meant reporting a losing backtest or an unresolved regression rather than a cleaner story.
