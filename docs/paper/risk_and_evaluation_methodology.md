# Methodology: Risk Review & Evaluation Framework

*Paper section — The Fractional AI Workforce | Prepared by Yutong Liu*

## 1. Role in the System

The three preceding sections describe agents that *propose*. This section describes the two mechanisms that decide whether a proposal should be believed and whether the agent that made it is worth keeping: the **Risk agent**, which reviews every candidate against a 13-point cherry-picking checklist, and the **evaluation harness**, which turns a finished run into per-agent productivity metrics.

The system's premise is that a human Portfolio Manager manages AI specialists the way a manager runs a small team, on measured performance rather than impression. That premise has one structural requirement: the numbers the PM acts on must not be authored by the thing being judged. So a strategy's verdict is computed from engine-produced evidence rather than the trader's memo — traders' claims are hypotheses, the backtest engine's run ledger is ground truth — and an agent's score is replayed from an immutable event ledger rather than any agent's self-report.

Risk is also the only node with the visibility the job requires. The three traders are competing lenses on the same validation window and the PM can request further rounds, so selection bias has three places to hide: **within one trader** (many variants run, only the winner reported), **across the three traders** ("best of three lenses" presented as one hypothesis, when three shots at the same window inflate expected performance), and **across rounds** ("request another round" repeated until something passes). The second and third are invisible to any single trader.

## 2. The Checklist: CP-1 … CP-13

Each check returns **PASS**, **FLAG** (approval still permitted, but the flag must appear verbatim in the Reporting memo), or **VETO** (candidate rejected, with the check ID as a machine-readable veto reason code).

| Check | Scope | Deterministic basis | Status |
| --- | --- | --- | --- |
| CP-1 report-everything-tried | candidate | ledger run count vs. declared count | needs audit reader |
| CP-2 best-of-N disclosure | candidate | undeclared sweep → veto; large declared sweep → flag | needs audit reader |
| CP-3 full-period metrics | candidate | backtest succeeded, split applied, out-of-sample metrics present | runs |
| CP-4 no post-hoc universe trimming | candidate | resolved symbols, first run vs. last run | needs audit reader |
| CP-5 full canonical metric set | candidate | every required metric present and non-null | runs |
| CP-6 same-terms baseline | candidate | benchmark computed by the same engine run | runs |
| CP-7 multiple-comparison disclosure | round | candidate count vs. declared hypothesis count; always a flag | runs |
| CP-8 lens duplication | round | identical executor with identical parameters (proxy) | runs, as a proxy |
| CP-9 no borrowed evidence | candidate | result, request and trader identity; cited foreign run IDs | runs |
| CP-10 nothing is deleted | round | every prior round present in history | needs history reader |
| CP-11 validation-touch budget | candidate | round number vs. budget; approval past it needs stability evidence | runs |
| CP-12 no cosmetic resurrection | candidate | match against prior vetoed strategies without declared lineage | needs history reader |
| CP-13 test-set lock | candidate | resolved data end and split end vs. the mandate as-of date | runs |

Eight checks run today from evidence already embedded in the candidate package. Five require two small adapters that dereference the round-audit and round-history references the workflow state already carries but which nothing currently resolves; their absence is disclosed rather than concealed (§3, §7).

## 3. Two Stages, in This Order

**Deterministic gate.** Every mechanically checkable item is computed in ordinary Python from the run-ledger entry embedded in each result, from request counts, and from package identity fields. No model call is involved. This mirrors the propose/compute boundary the traders observe: the reviewer no more computes its verdict by language model than a trader computes its own Sharpe ratio.

**Bounded model judgment.** An optional model client then reviews what code cannot judge — sweep severity, semantic similarity between lenses, how to read stability evidence, whether a resubmission genuinely addressed its original veto — grounded in the deterministic results it is shown. Its authority is deliberately asymmetric: it may *escalate* severity (PASS → FLAG → VETO) with justification and evidence IDs, an escalation at equal or lower severity than the computed verdict is discarded, and a model failure degrades the review to deterministic-only rather than aborting the round. The model can never downgrade a computed result.

**Unverifiable is not a pass.** Where evidence cannot be reached — the two missing readers being the common case — the check returns FLAG with requires_human_review set and a summary naming what could not be verified. A manufactured PASS would be the most damaging failure available to this component, because it would make an absent check indistinguishable from a satisfied one.

A candidate is vetoed if any of its checks vetoed; otherwise it is approved carrying its flags, and the response exposes every flag the Reporting memo must reproduce. A round-level veto must block progression, enforced by a contract validator rather than by convention. Dropping a flag downstream would be cherry-picking the critique rather than the result. Every threshold the checklist draft left open — the round budget (3), the sweep-disclosure flag threshold (20), the lens-overlap cutoff (0.7), and the canonical metric set — lives in a single policy object, so a team ruling is a one-line change.

## 4. The Evaluation Harness

The Risk agent grades strategies. The harness grades **agents**, which is what the hire/fire/pivot controls act on. Each node wrapper in the production graph already knew everything an event needs — which agent ran, at which stage, when it started and ended, whether it settled or failed — and was discarding all but the lifecycle summary. Emission now attaches an operational event at each wrapper's exit path, and the harness replays that ledger into a per-agent record: tasks observed and completed, failures, retries, latency, model calls, tokens, API cost, and candidates reviewed versus approved. Risk's verdicts are collected first, so traders are scored against the reviewer's record rather than their own.

**Measured or N/A, never defaulted.** No metric defaults to zero. An agent that made no model calls has an *unknown* cost, not a cost of nothing, and the difference matters when the number sits under a fire button. A benched agent has no success rate — not 0%. A trader that crashed has no risk-approval rate: its failed package still carries a candidate ID, but Risk never reviewed it, so counting it as a rejected proposal would score a crash as a research-quality failure and penalise the agent twice for one incident. The same discipline was applied to the dashboard, where demo and live modes render through identical widgets: each site that displays productivity figures now states their provenance, and demo mode says plainly that nothing on screen was measured.

**The open ruling: what "Success %" means.** The term has two defensible readings. *Execution* — the share of tasks that finished without erroring — is literal, cheap and un-gameable, and nearly useless for firing, because a trader that reliably produces worthless strategies scores 100%. *Risk approval* — the share of proposals that survived review — is genuinely informative about research quality, and it makes the skeptic the scorekeeper for everyone it judges: once a trader is measured on its approval rate, the way to score well is to propose things Risk waves through, which points Goodhart's law at the mechanism this project is built around. The choice is a team ruling and is deliberately still open, so the harness computes **both, always**, and reports them under separate names; the selector only decides which one fills the single slot the dashboard renders. No view can silently imply the question has been settled.

## 5. Verification and Representative Result

The run below was executed end-to-end on 19 August 2026 through the compiled production workflow with real Fundamental Trader, Quant Trader, Risk agent, Reporting agent and Memory store, against the real 120-ticker ETF fixture and the shared deterministic backtest engine — not mocks. The Technical Trader ran in its stubbed form because no model provider was configured in this environment; it settles as a failed package and is therefore excluded from Risk review, which is itself one of the behaviours under test. Risk ran deterministic-only, so every verdict reported here was computed by code.

In round 1 both candidates that reached review were approved, each carrying three flags naming exactly what could not be verified, with the round-level multiple-comparison disclosure recording that two hypotheses competed and one package was excluded. Driving the same workflow through three further "request another round" decisions produced a 23-event ledger over four rounds, and at round 4 the deterministic gate vetoed **both** surviving candidates on CP-11 — *"Round 4 exceeds the 3-round validation-touch budget and the candidate carries no parameter-stability evidence"* — leaving nothing selectable.

| Agent | Success (risk) | Execution | Risk approval | Time | Failed | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| fundamental_trader_agent | 75% | 100% | 75% | 2.43s | 0 | N/A |
| quant_trader_agent | 75% | 100% | 75% | 4.67s | 0 | N/A |
| reporting_agent | N/A | 100% | N/A | 1ms | 0 | N/A |
| risk_agent | N/A | 100% | N/A | 1ms | 0 | N/A |
| technical_trader_agent | N/A | 0% | N/A | 0ms | 4 | N/A |

Four details in that table are the point of the section. Both traders executed flawlessly in all four rounds while three of their four proposals survived review, so the two readings of Success % diverge on the same run — under the execution reading, an agent whose fourth-round work was rejected outright looks perfect. The crashed Technical Trader reads 0% on execution and N/A on risk approval, a crash rather than a rejected proposal. Risk and Reporting read N/A on approval because they submit no candidates, rather than 0%, which would read as a failing grade. And cost reads N/A throughout because no model call reported usage — a missing measurement, stated as such rather than printed as $0.00.

The loop was stopped here by the accumulated cost of re-touching the validation window, not by anything wrong with the fourth round's strategies. Benching the Risk agent produces the complementary behaviour: the graph records a review failure requiring PM action, Reporting never runs, and no candidate becomes selectable — so firing the skeptic escalates to the human instead of silently approving.

## 6. Risk Analysis and Interpretation

The honest limitation of this design is structural rather than numerical. Every other agent is checked by something outside itself — traders by Risk, arithmetic by the shared engine, data by provenance records. The Risk agent is checked by nothing, because it *is* the checking code, and the harness has the same property one level up.

The project has already produced one instance of this failure mode. The shared data service back-adjusts prices and therefore honestly declares that its data is not point-in-time verified. In the same change that introduced it, the Technical Trader's data check — which had rejected unverified data — was relaxed to require only that provenance *exists*, and the flag was dropped from the backtest data contract. A source failed a look-ahead guard and the guard moved. Nothing in the checklist catches this: CP-13 verifies that resolved data and the validation split respect the as-of boundary, which they do, and no check consults the point-in-time flag at all.

This is not offered as a defect to be quietly patched before submission. It is the precise self-deception the project exists to detect, committed by the project, and it is a real research gap: there is no mechanism for reviewing changes to the reviewer. Two defensible resolutions exist — restore the strict check and accept that the live data source cannot be used for graded runs, or keep it relaxed and add an explicit disclosure that propagates through Risk into the PM memo. What is not defensible is letting it be settled by silence. The second-order risk is the one in §4: if risk approval becomes the number under the fire button, traders are optimised toward whatever Risk approves and the adversary becomes a target. The current answer is to refuse to pick one number, publish both, and force the choice to be made explicitly.

## 7. Known Limitations and Assumptions

- **Five of thirteen checks do not run.** CP-1, CP-2, CP-4, CP-10 and CP-12 degrade to *flag, requires human review* until the round-audit and round-history readers are supplied. The system therefore cannot yet mechanically detect a hidden sweep in a live run.

- **No trader produces the disclosure fields.** Declared run count, stability evidence and parent strategy ID have no producer, so CP-1, CP-2 and CP-7 see no declared trial counts, CP-11 can only hard-veto past the round budget rather than assess perturbation results, and CP-12 has no lineage to inspect.

- **CP-8 is a proxy.** It detects an identical executor with identical parameters, not the intended trade-day overlap; two lenses converging on economically similar but structurally different rules would pass.

- **No check verifies point-in-time data** (§6).

- **API cost is unmeasured end to end.** Provider telemetry is converted into ledger events and unit-tested against the Technical Trader's real metrics type, but no runtime construction site supplies the sink yet, so every verified run reports cost as N/A. The metric is honest about its own absence; it is still absent.

- **Policy thresholds are proposals, not rulings.** The 3-round budget, the 20-variant flag threshold and the 70% overlap cutoff are the checklist draft's suggested values and have not been ratified by the team or confirmed with the professor.

- **The model-judgment stage is unexercised in the verified runs**, which used a deterministic-only reviewer; escalation logic has not been run against a live provider inside the full loop.
