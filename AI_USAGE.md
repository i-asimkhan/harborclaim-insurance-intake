# AI usage — Claim Completeness Checker

## Tool

Claude Code (Claude Sonnet 5), used per the assignment's "Build with Claude Code" step.

## Prompt used

The assignment's own starter prompt, as given in the take-home build packet:

> Build a tiny Python console claim-intake checker using only the standard library.
> Use fake claim JSON and mock document names. Validate required fields and return a
> review-ready status or a list of missing information. Do not approve or deny claims.
> Work only in this folder. Create main.py with a built-in demo, test_main.py using
> unittest, and a README. Test a normal input and a failure.

## What Claude Code built

- `main.py` — `check_claim(claim)`, which checks for `policy_id`, `incident_date`,
  `description` (non-blank strings) and `documents` (non-empty list), and returns
  `READY_FOR_REVIEW` or `NEEDS_INFORMATION` with the specific missing fields named.
  Includes a `run_demo()` with one complete and one incomplete fictional claim.
- `test_main.py` — 5 unit tests: complete claim, missing `incident_date`, missing
  `documents`, all fields missing at once, and a check that no coverage/payout word
  ever appears in the result.
- `README.md`, `.gitignore` — setup/run instructions, limitations, and standard
  excludes (`.env`, credentials, `__pycache__/`, build output).

## What I changed or verified myself

- Ran `python main.py` directly and confirmed the printed output matches the
  assignment's required example run exactly: a complete claim returns
  `READY_FOR_REVIEW`, and a claim with a blank `incident_date` returns
  `NEEDS_INFORMATION -- missing: incident_date`.
- Ran `python -m unittest -v` and confirmed all 5 tests pass.
- Read through `check_claim()` line by line and confirmed it never contains logic
  that could be mistaken for a coverage or payout decision — it only ever returns a
  completeness status, matching the scenario's requirement that the source claim and
  human adjuster stay authoritative.
- Confirmed no real customer data, credentials, or secrets appear anywhere in this
  folder — every claim ID, policy ID, and document name is fictional.

## Phase 5: the AI models inside the app (three agents)

Separate from the build tool above: these are the models HarborClaim itself calls, off by default.
Four agents share one harness: intake review (adjuster), Ask about this claim (adjuster), Ask a
question (claimant) and the request agent (drafts the adjuster's request to the claimant, which the
adjuster edits and sends). The prompts are in `PROMPTS.md`; the diagram and walk-through are in
`docs/design/AGENTIC-LAYER.md`.

- **Models:** `nvidia/nemotron-3.5-super-vl:free`, then `nvidia/nemotron-3-ultra-550b-a55b:free`
  as failover, via OpenRouter (free tier, $0), reasoning off, temperature 0. Chosen by testing:
  12 free models screened in 3 probe rounds (AGENTS.md section 11.4). An adjuster can put either
  first on the AI usage page.
- **Prompts:** `intake-v6`, `adjuster-v4`, `claimant-v3`, `request-v2` (`agents.py`; v5 for the golden-set table below). Every output goes through the code gate
  (`agent_gate.py`, rules G1-G9) before an adjuster sees it.
- **Golden-set eval, 2026-11-02** (`python scripts/eval_agents.py`; 6 fictional claims in
  `sample_data/golden/`; replies recorded in `tests/fixtures/ai/intake/` and replayed by the tests):

  | Prompt | Cases hold | Passed gate | Findings found | False findings | Policy violations |
  |---|---|---|---|---|---|
  | intake-v3 | 4/6 | 1/6 | 3/3 | 1 | 1 |
  | intake-v4 | 5/6 | 5/6 | 2/3 | 0 | 0 |
  | intake-v5 | **6/6** | 5/6 | **3/3** | **0** | **0** |

- **One observed limitation:** the model adds extra findings that the documents don't support
  (date conflict case: a second "difference" built on a quote that isn't in the notes). The gate
  catches it and the review is shown as "failed automated checks", so nothing unverified is
  labelled as checked, but the adjuster sees a flagged review instead of a clean one. It also
  never called a tool in 23 live runs: the prefetched documents were always enough.
- **What I verified myself:** each change to the prompt or gate was made from a recorded live
  reply, with a failing test first; the gate was never loosened for document quotes.
- **Challenge 2, 2026-11-02:** an independent subagent wrote 5 adversarial claims and ran them
  live. It found 3 gate holes (an obeyed injection, nonsense type mismatches, dates in words),
  all fixed with tests; details in AGENTS.md section 14. Replay of all 11 cases: 9/11 hold, the 2
  misses are false type mismatches the gate now flags. Backup models (two Gemma) were
  rate-limited upstream on every call, so Nemotron was the only model at that point.
- **Probe round 3 and model bake-off, 2026-11-06** (golden set, 11 cases, intake-v6):

  | Model | Cases hold | Conflicts found | Policy violations (all flagged by the gate) | Decision |
  |---|---|---|---|---|
  | `nemotron-3-ultra-550b-a55b:free` | 8/11 | 9/9 | 3 | Second in `AI_MODELS` |
  | `nemotron-3.5-lightning:free` | 5/11 | 2/9 | 1 | Out: its misses pass the gate silently |

  Gemma was rate-limited again and XingChen leaked its reasoning into answers. The bar: 7/11 and
  every miss caught by the gate.
- **First live try of the claimant assistant, 2026-11-04:** two harmless answers ("I can help you
  check your claims") were replaced by the fixed reply because gate rule C read the verb "check"
  as a payment check. Narrowed with tests; the claimant prompt now names the New claim link.

## Adjuster review fixes, 2026-11-06 (PR #3)

**Tool:** Claude Code (Claude Opus 5.5). **Prompt:** the owner reviewed the adjuster page for one
real-looking claim (CLM-6AD24F55: filed as Auto, notes describing a slip-and-fall, two decisions
8 seconds apart, the description "ggregrrg3wt3g3") and asked Claude Code to review what it showed,
then to "fix all of these one by one". Claude Code listed 14 problems; each became one commit with
its own tests, in `tests/test_review_fixes.py`.

### What Claude Code built

| # | Problem on the page | Change | Commit |
|---|---|---|---|
| 1 | Badge said Ready for review after a Needs more review decision | Badge shows the latest decision; `claims.status` stays the intake status the queue filters on | `c57aa3e` |
| 2 | Two identical decisions 8 s apart | A repeat of the latest decision records nothing and sends nothing | `6e7e511` |
| 3 | A final decision could be overwritten by a direct POST | Refused on the server, as are decisions on incomplete claims | `6e7e511` |
| 4 | No reason recorded with a decision | `reason` column; a decline needs one (10+ characters) and the claimant is told it; exact times in the history | `48136ba` |
| 5 | Claim data, including health details, went to free-tier models | `privacy.py`: emails, phones, SSNs and card numbers redacted from sources; `AI_DATA_POLICY` setting | `64ab31c` |
| 6 | "Needs more review" emailed the claimant | Only Approved and Declined notify | `08a8830` |
| 7 | Approve was one click away with findings open | Approving needs "I've checked the open findings"; the count is recorded | `aaf81ac` |
| 8 | Info-request template asked an "Auto" slip-and-fall claimant for a police report | Template and request agent ask to confirm type and date, and for documents that fit what the notes describe (`request-v2`) | `ce61110` |
| 9 | "What is this about?" got "Not found", labelled "checked against the documents" | Broad questions answered from the sources (`adjuster-v3`); not-found has its own label | `f9ea98c` |
| 10 | "claim form, p. 1" three times under one sentence | One citation per source and page, linked to the document page | `c77aa62` |
| 11 | "Not summarised listed by code, not the AI": a bare date | "Dates and amounts the summary doesn't mention", each with the line it came from | `2955d07` |
| 12 | Raw codes such as `NEEDS_MORE_REVIEW` on the pages | Plain labels everywhere; codes stay in the data | `c322b9d` |
| 13 | Intake accepted "ggregrrg3wt3g3" as a description | At least 3 real words, making up at least half of the text | `424eeaa` |
| 14 | The type mismatch was left to the AI | `consistency.py`: claim type vs. described incidents, incident date vs. document dates, by code; counted as open findings | `34e3b8a` |

- **`privacy.py`** runs when the agents' sources are built (`agent_tools.claim_scope`), so the
  model and the gate read the same redacted text and quote checks still line up. Card numbers are
  removed only if they pass the Luhn checksum, so long policy and claim numbers stay.
- **`AI_DATA_POLICY`:** `test` (default, unchanged behaviour: any configured model, fictional claims
  only) or `production` (`:free` models and `openrouter/free` refused; OpenRouter asked for
  providers that don't collect prompts). The AI usage page shows which is active.
- **`consistency.py`** works from the keyword scan's facts, so it flags a mismatch even when AI is
  off or the AI review failed its checks.

### What was verified

- **By tests (Claude Code ran them):** 377 tests pass (`python -m pytest -q`), browser tests
  included. Five commits (`c57aa3e`, `6e7e511`, `48136ba`, `64ab31c`, `aaf81ac`) were also run on
  their own in a separate git worktree, without the Phase 5.7 work that was still uncommitted.
  `main.py` and `test_main.py` (the graded minimum) are unchanged. Both GitHub checks on PR #3 pass.
- **A data-loss risk caught in review:** `init_db` dropped `adjuster_decisions` whenever its columns
  changed, so adding `reason` would have wiped every recorded decision. It now drops a table only
  when a required column is missing; a test builds the old table, runs `init_db` twice and checks
  the decision survives.
- **First live run, 2026-11-08:** `scripts/eval_agents.py` covers only the intake agent, so the
  request agent and both assistants were run against the real model in the app. That found four
  bugs the recorded-reply tests had missed, all fixed with tests in `eb34db2`:
  - the model passed a claim number to tools that take no arguments, and every such call was
    refused (those tools now ignore stray arguments);
  - the request agent skipped its tools and drafted a request that named nothing (it must now look
    first, and an empty draft falls back to the standard request);
  - an empty adjuster answer passed the checks (gate rule G1 now rejects it);
  - the claimant assistant replied "I'll check" instead of answering (`claimant-v3`).
- **Still open:** asked for the repair estimate total, the adjuster assistant (`adjuster-v4`) read
  the estimate and still answered "not found".

### Checked by the owner

To be ticked by the owner. Claude Code can't confirm these on the owner's behalf.

- [ ] Read the PR #3 diff
- [ ] Saw the 14 fixes on the local site (port 8123)
- [ ] Ran the test suite locally
- [ ] Ran `request-v2` and `adjuster-v4` live

### Known limits

- **The keyword scan misses negation.** "No injuries were reported" still counts as bodily
  injury, so `consistency.py` can flag a type mismatch on such a phrase. It flags; it never decides.
- **The description rule is a heuristic.** It stops a keyboard mash, but any three real words pass.
  It doesn't judge whether a description is true or complete.
- **Redaction is pattern-based.** Names, addresses and medical details are not removed. Real claims
  need `AI_DATA_POLICY=production`, a paid no-retention model, and a provider agreement covering
  retention and health data.
