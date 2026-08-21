# Independent QA Verification

**Commit under test:** `15e2cc6` · **Date:** 2026-08-21 · **Prepared by:** Yutong Liu

Every result below was produced from a **fresh `git clone` of this repository**,
set up by following `README.md` and `dashboard/README.md` literally, on macOS
with Python 3.14.4. No pre-existing working copy, no local state, no team
machine. This document exists so that the verification claims made in the paper
can be checked against a reproducible procedure rather than taken on trust.

Where something was not verified, it is labeled as not verified rather than
omitted.

---

## 1. Setup from a clean clone

| Step | Result |
| --- | --- |
| `pip install -e '.[full-demo,dev]'` | Succeeded |
| `pip install -r dashboard/requirements.txt` | Succeeded (Streamlit 1.62.0) |
| `python scripts/check_setup.py` (no key configured) | Correctly refused: `OPENAI_API_KEY is not configured` |
| `python -m pytest -q` | **111 passed** in 20.62s |

The 111-test figure supersedes the "91 automated tests" cited in the paper's
§1.7, which was accurate at an earlier commit.

---

## 2. The research loop, end to end

Run with the Technical Trader in its documented stub mode (no provider key), so
every result here was produced by deterministic code.

- **Round 1** completed and paused at the durable PM interrupt. Technical
  settled `failed` and was correctly excluded from Risk review; Fundamental and
  Quant completed and were risk-eligible; Risk reviewed and approved both;
  Reporting produced the structured comparison. Wall time 1.70s.
- **Resume with `reject`** completed and wrote a Memory record.
- **Resume with `request_another_round`** plus a staffing change ran round 2
  with only the active specialists — the benched Fundamental Trader did not run
  — and metrics accumulated across rounds (Technical `failed_count` reached 2;
  the operational-event ledger grew from 5 events to 11).

The durable interrupt, the hire/bench/pivot loop, and cross-round metric
accumulation are therefore real mechanisms rather than scripted UI states.

### Risk checks observed firing in a real round

CP-3, CP-5, CP-6, CP-9, CP-11, CP-12 and CP-13 returned **pass** against
engine-produced evidence. CP-7 returned its intended **flag** — multiple-comparison
disclosure, correctly counting two candidates from parallel lenses with one
package excluded. CP-8 and CP-10 passed. CP-1, CP-2 and CP-4 returned **flag /
requires human review**, reporting an unresolvable round-audit ledger, exactly
as documented in the Risk methodology section.

---

## 3. Fixes merged 2026-08-20, independently confirmed

**Empty `permitted_asset_universe`** (`db338d8`). The dashboard encodes its
default universe option as an empty list. Fed the byte-for-byte payload
`dashboard/app.py` writes for that option, the runner expands it to the full
offline panel — **exactly 120 ETFs**. The expansion was confirmed to run after
`_initialize_offline_data()`, so the panel is populated when the fix reads it.

**Session-scoped live mode** (`2d072e3`). Verified under genuine simultaneous
load rather than back-to-back runs: two workflows launched at the same instant
produced fully independent checkpoint databases, Memory stores and snapshots
under `dashboard/data/sessions/<workflow_id>/`, with no shared file and no
cross-referenced identifier in either direction.

---

## 4. Reproducibility note on the four-round result

The paper's four-round run — in which the deterministic Risk checklist vetoed
both surviving candidates at round 4 on CP-11, the validation-touch budget — was
executed on 2026-08-19 and is honestly reported. It **cannot be reproduced on
this commit.**

`scripts/run_full_research_loop_demo.py` compiled the workflow with
`max_rounds=5` at the time of that run. Commit `5bd98cb` (2026-08-20) changed it
to `max_rounds=3` to align the pilot with Risk's own three-round
validation-touch budget. That change is correct on its own terms; its side
effect is that the graph now stops at round 3, so a fourth round cannot be
entered and the CP-11 budget veto cannot be demonstrated end to end from a
clean clone today.

Driving this commit through the same sequence produces three rounds and a
17-event ledger, against the 23-event, four-round ledger the paper reports.
Readers reproducing the paper's headline result should expect this difference.

---

## 5. Scope — what this pass did **not** cover

Every run reported here used the Technical Trader stub, and **no result in this
document depended on a live provider call**. The following are therefore
unverified by this pass:

- the real Technical Trader's proposal quality;
- the Reporting Agent's optional Gemini narrative memo;
- the Risk agent's bounded model-judgment escalation stage, which was
  exercised deterministic-only throughout;
- any non-`N/A` API cost.

A teammate reported a successful live-key smoke test showing the Technical
Trader `Completed` and progressing through Risk and Reporting to the PM
decision. That report is credible and consistent with the code read here, but it
is a separate observation and not an independent reproduction.

## 6. Method

The dashboard was exercised through Streamlit's `AppTest` harness, which
executes `dashboard/app.py` and exposes its rendered elements, rather than by
reading the source alone. Concurrency was tested with two runner processes
launched simultaneously, not sequentially.
