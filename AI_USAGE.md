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
