# Methodology: Reporting Agent & Memory Store

*Paper section — The Fractional AI Workforce | Prepared by Emma*

## 1. Role in the System

The Reporting Agent is the last node before the human Portfolio Manager's decision. Unlike the three traders, it proposes nothing, and unlike Risk, it judges nothing: its job is to assemble whatever survived Risk review into a comparison the PM can actually read, and to say so honestly when a candidate was vetoed rather than quietly omit it. The agent consumes the round's `RiskReviewResponse` together with the surviving `TraderStrategyPackage` objects and produces a `ReportingOutput` carrying a structured, deterministic cross-lens comparison and, optionally, a natural-language memo.

Consistent with the project's central design rule — that the numbers a human acts on must not be authored by the thing being judged — the Reporting Agent is explicitly instructed never to select a winner or make the final portfolio decision. That choice is reserved for the PM. The agent's own system prompt enforces this as a hard rule, not a convention left to the model's discretion.

## 2. Pipeline and the Propose/Compute Boundary

The same propose/compute boundary described in the Fundamental Trader section governs Reporting: the structured comparison is always computed deterministically, and only the memo's narrative text is optionally produced by a model, constrained to interpret that data rather than introduce anything new.

The pipeline for one round is:

- **Collect.** Take the surviving candidates named on the `RiskReviewResponse` — candidates Risk vetoed do not reach this stage.
- **Compare.** Build a per-candidate record (hypothesis, metrics, interpretation, strengths/weaknesses, risk verdict, risk critiques, reporting flags) plus the round-level collective critiques and required disclosures Risk attached.
- **Interpret (optional).** If a `ModelClient` is configured, generate a narrative strategy memo from the comparison; if not, the round proceeds with the structured comparison only — never a hard failure.
- **Construct.** Assemble the `ReportingOutput` the PM and the dashboard consume: output and request identifiers, the surviving-candidate list, the comparison, and the memo reference if one was generated.

The model boundary uses the same provider-neutral `ModelClient` protocol shared with Risk's optional judgment stage and the Technical Trader's structured calls. A `GeminiModelClient` adapter was implemented and verified end-to-end against the live provider (§4); the agent remains fully functional with `model_client` left unset, in which case the PM still receives the full comparison, just without narrative memo text.

## 3. Memo Generation and Prompt Design

The system prompt given to the model enforces four rules directly:

- Summarize and compare the surviving candidates.
- Clearly report material Risk flags and critiques.
- Do not invent evidence, metrics, or conclusions.
- Do not select a winner or make the final portfolio decision.

Two further rules were added after inspecting the first real, provider-generated memo rather than assumed in advance: the initial output was one dense, unbroken paragraph, and it restated exact metrics that the comparison table already displayed. The prompt was revised to require a short paragraph per candidate, separated by line breaks, followed by a separate paragraph for risk disclosures; and to explicitly instruct the model to interpret the numbers rather than restate them, since the exact figures are already rendered in a separate table. Both changes were verified by regenerating the memo and inspecting the result, not assumed to have worked.

## 4. Verification and Representative Result

| Check | Result | Basis |
| --- | --- | --- |
| Reporting Agent unit tests | 3 / 3 pass | Cross-lens comparison, output identifiers, and surviving-candidate propagation, run against a real `RiskReviewResponse`. |
| Memory Store unit tests | 5 / 5 pass | Empty-context bootstrap, record()/load_context() round-trip, multi-round aggregation, per-workflow isolation, and state surviving a fresh instance pointed at the same directory (simulating a process restart). |
| Manual end-to-end chain | Verified | Technical/Fundamental/Quant candidates (shared risk_fixtures builders) → real `RiskAgentImpl` → `ReportingAgentImpl`, reproduced on demand. |
| Live production run | 100% execution | Four-round run, 19 Aug 2026 (see the Risk & Evaluation methodology section): Reporting completed every round it was reached; N/A on risk-approval since Reporting reviews no candidates itself. |
| Local live pilot (dashboard) | Verified | `GeminiModelClient` wired into the Reporting node produced a real, provider-generated narrative memo for the round's approved Fundamental and Quant candidates, correctly grounded in Risk's verdicts and flags. |

A representative memo, generated against a real round with one Technical candidate excluded (no model provider configured for Technical Trader in that environment) and Fundamental and Quant candidates approved by Risk, correctly separated each candidate into its own paragraph, avoided restating the table's exact figures, surfaced Risk's audit-ledger and multiple-comparison disclosures in a dedicated closing paragraph, and — as instructed — did not select a winner between the two approved candidates.

## 5. Risk Analysis and Interpretation

Because the memo's narrative half is optionally model-authored, the primary risk is invented content — a model asserting a conclusion the underlying data does not support. This is mitigated three ways: the system prompt explicitly forbids inventing evidence, metrics, or conclusions; the structured comparison is always computed deterministically regardless of whether a memo is generated, so a PM's access to the actual numbers never depends on the narrative; and a missing or failed model client degrades the round to structured-comparison-only rather than blocking it, mirroring the same fail-open-on-narrative, fail-closed-on-data discipline Risk applies to its own optional model-judgment stage.

A second, more honest risk is that the formatting rules in §3 were arrived at by inspecting a handful of real generations and revising the prompt accordingly, not by evaluating a held-out set of rounds or multiple providers. The rules work for the cases observed; whether they generalize to less typical rounds — many more surviving candidates, a candidate with unusually long critiques — has not yet been tested.

## 6. Known Limitations and Assumptions

- `combination_logic_implemented` is currently always false: the agent does not synthesize a single recommended combination across surviving candidates. This is a deliberate consequence of §1, not an unfinished feature — that judgment is reserved for the PM.
- Only the Gemini adapter has been smoke-tested against a live provider for this agent. Unlike Technical Trader, OpenAI and Anthropic adapters for Reporting have not yet been verified end to end.
- Prompt formatting rules (§3) were tuned empirically over a small number of manual inspections, not validated against a systematic evaluation set.
- Reporting's field access is coupled to the exact shape of `RiskReviewResponse` and `TraderStrategyPackage`; a contract change on Risk's side that is not mirrored here would fail at the type boundary rather than silently — consistent with the project's fail-closed convention, but noted here as a coupling worth dedicated test coverage.
- The dashboard integration in §4 currently renders the structured comparison directly when no memo was generated, which is correct behavior, not an error — documented here because it can otherwise look like a missing feature.

## 7. The Memory Store

Memory is shared infrastructure rather than a hireable agent — the same category as the Data service and the deterministic backtest engine. It is documented here, alongside Reporting, because both were built by the same owner and neither appears in another section.

The `MemoryStore` protocol defines two operations: `record(MemoryRecord)`, which persists a round's results, critiques, and PM decision, and `load_context(workflow_id)`, which returns the accumulated `MemoryContext` — prior result references, prior critiques, prior PM decisions, and distilled lessons — for the next round. A single workflow can span multiple rounds whenever the PM requests another round, so `load_context` must fold together every prior round's record, not only the most recent one.

The current, live implementation is `FileBackedMemoryStore`: it persists every record to a JSON file per `workflow_id` on disk, rather than holding state only in the running process. This was a deliberate correction, not the original design — an earlier `InMemoryMemoryStore` (an in-process dictionary keyed by workflow ID) was the first implementation, and it satisfies the same `MemoryStore` protocol correctly on its own. It became a real bug once the live dashboard began launching each research round as a fresh subprocess: a purely in-process store loses everything the instant that process exits, so a PM's second "Request Another Round" would have started from a blank Memory rather than the prior round's actual lessons. `FileBackedMemoryStore` was built to close that gap, and both implementations now exist in the codebase — `InMemoryMemoryStore` remains valid for single-process use (e.g. the original multi-round test script), while `FileBackedMemoryStore` is what the live, subprocess-per-round dashboard pilot actually uses today, since only the file-backed version survives a round's subprocess exiting.

Both implementations satisfy the identical protocol, so nothing calling `load_context`/`record` needed to change when the live pilot switched from one to the other — the substitution is exactly what the protocol boundary was designed to allow.

Nine tests verify the two implementations together: the four shared behavioral properties (empty context before any round is recorded; `record()` returns the persisted record's identifier; `load_context()` aggregates results, critiques, PM decisions, and lessons across multiple recorded rounds, not just the latest; two different workflows never leak state into each other) are each verified against both `InMemoryMemoryStore` and `FileBackedMemoryStore`, plus one test specific to the file-backed store: state genuinely survives a fresh store instance being constructed against the same directory, directly simulating the subprocess-restart scenario that motivated building it.

**Known limitation:** `FileBackedMemoryStore` persists to a single machine's local filesystem — correct for the current single-machine demo, not yet a shared, multi-user, or hosted store.
