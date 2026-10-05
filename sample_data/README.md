# Sample claim documents and demo data

Six fictional PDF documents, written so the mock fact extractor (`extraction.py`)
finds something real when you upload one -- dollar amounts, an ISO-format date
(`YYYY-MM-DD`, the only date shape the regex matches), and an incident keyword --
plus `claims.json` (five full claim scenarios and three validation-failure cases) and
`seed_demo_data.py`, which turns that data into a populated, running system with one
command.

## The documents

| File | Triggers `incident_type` | Mentions |
|---|---|---|
| `police_report_sample.pdf` | Collision | `$1,850.00`, `2026-09-10`, `2026-09-11` |
| `repair_estimate_sample.pdf` | (amounts/dates only) | `$2,400.00`, `$640.00`, `$1,200.00`, `$4,240.00`, `2026-09-12`, `2026-10-12` |
| `water_damage_notes_sample.pdf` | Water damage | `$3,100.00`, `2026-08-21`, `2026-08-20` |
| `theft_report_sample.pdf` | Theft | `$2,950.00`, `2026-09-02`, `2026-08-30`, `2026-09-01` |
| `vandalism_report_sample.pdf` | Vandalism | `$5,600.00`, `2026-09-15`, `2026-09-14` |
| `injury_claim_notes_sample.pdf` | Bodily injury | `$1,450.00`, `2026-09-18`, `2026-09-17` |

## `claims.json`

Two sections:

- **`scenarios`** (5) -- real claims to seed, covering every system state on
  purpose: a straightforward complete claim later **APPROVED**, a complete
  claim later **DECLINED** (proving the decision is a genuine independent
  judgment call, not predetermined by completeness), a complete claim routed
  **NEEDS_MORE_REVIEW** (the third outcome, not just a binary), one
  **NEEDS_INFORMATION** claim missing its incident date, and one
  **NEEDS_INFORMATION** claim missing documents entirely (the other way a
  claim can be incomplete). Three different fictional claimants, one of whom
  files twice, so "My Claims" has more than one entry to look at.
- **`validation_failures`** (3) -- input that must *never* become a stored
  claim: a policy ID over the length limit, a future incident date, a
  disallowed file type. `seed_demo_data.py` submits these too and fails
  loudly if one is ever accepted instead of rejected.

## Seed a running instance

```bash
# Server must already be running separately:
.venv/Scripts/python.exe -m uvicorn app:app --port 8123

# Then, from another terminal:
.venv/Scripts/python.exe sample_data/seed_demo_data.py --reset
```

This makes **real HTTP requests** against the live server -- every seeded
claim genuinely passes through `POST /claims` (completeness check,
`validation.py`, `extraction.py`, `summary.py`, the notification stub) and
every decision genuinely passes through `POST /adjuster/claims/{id}/decision`
(including the separation-of-duties check), exactly as a real browser
submission would. Nothing is inserted directly into the database. Login is
by injected, properly-signed session cookie (same technique as
`tests/test_ui.py` and the documentation screenshots) rather than five real
Google sign-ins or a password you'd have to remember between runs -- that's
what makes `--reset` safe to run repeatedly.

The script prints a result line per scenario (claim ID, actual vs. expected
status, decision) and confirms each validation-failure case was genuinely
rejected, not silently accepted. To browse the result: provision your own
adjuster login (`storage.create_adjuster('your.username', 'Your Name')`) --
the seed script's own adjuster session was cookie-injected, so there's no
real password for it to hand you. The seeded claimant emails are fictional
(`@example.com`) and can't actually complete real Google sign-in; use the
same cookie-injection technique if you need to view a seeded claimant's own
pages directly.

## Try a single document by hand

Run the app, sign in, go to **Submit a claim**, attach one of the PDFs above.
After submitting, open the claim -- the **Extracted facts** table shows what
the regex found in that file, and the **Adjuster summary** restates it in a
sentence. Both are tagged `MOCK` on the page; see `../MOCKS.md`.

All names, report numbers, policy numbers, and amounts are invented for this
class project -- none of these are real documents or real people, and the
"FICTIONAL DOCUMENT -- CLASSROOM USE ONLY" stamp is printed on every page for
exactly that reason.
