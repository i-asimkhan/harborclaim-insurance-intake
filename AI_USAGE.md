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

## Phase 5: the AI model inside the app (intake review)

Separate from the build tool above: this is the model HarborClaim itself calls, off by default.

- **Model:** `nvidia/nemotron-3.5-super-vl:free` via OpenRouter (free tier, $0), reasoning off,
  temperature 0. Chosen by testing (AGENTS.md section 11.4, round 1 probe).
- **Prompt:** `intake-v6` (`agents.py`; v5 for the golden-set table below). Every output goes through the code gate
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
  rate-limited upstream on every call, so Nemotron is the only model for the demo.
