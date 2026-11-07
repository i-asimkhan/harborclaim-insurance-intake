# Demo claim: rear-end collision (fictional)

A realistic auto claim for trying the AI review end to end. All names, plates, report numbers
and businesses are made up. Rebuild the PDFs with `python sample_data/demo/make_demo_pdfs.py`.

## Fill in the claim form

| Field | Value |
|---|---|
| Claim type | Auto |
| Policy ID | HC-AUTO-5318 |
| Incident date | 2026-10-27 |
| Description | Another driver rear-ended my 2021 Honda Civic while I was stopped at a red light on Harbor Avenue at Palm Street on 2026-10-27. The rear bumper, trunk lid and left tail lamp are damaged. The body shop quoted $3,250.00 to repair it. |
| Files | `bayport_police_report.pdf`, `bayshore_repair_estimate.pdf` |

## What the AI review should find

- **Amount difference:** the description says $3,250.00 but the estimate totals $3,486.40.
- No date conflict (report and description both say 2026-10-27; the estimate's 2026-10-29 is
  when it was written, not a conflict) and no type mismatch.
- Possibly missing: photos of the damage (the officer took some; none are attached).

## Questions to ask in "Ask about this claim"

| Question | Expected |
|---|---|
| What does the repair estimate total? | $3,486.40, cited to the estimate |
| Who was cited, and for what? | Sam Ortiz (Vehicle 2), following too closely, cited to the report |
| Were there any injuries? | None reported at the scene, cited |
| What colour was the tow truck? | "Not found in this claim's records." |
| Should I approve this claim? | Fixed refusal, "not AI-generated", no model call |
