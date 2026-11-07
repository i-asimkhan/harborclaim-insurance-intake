# HarborClaim — system design

High-level architecture for the Insurance Claim Intake System (Assignment 7, System Design
Studio), and the answer to the exercise's pressure test: what happens when an AI summary
disagrees with the source evidence or omits a fact.

- [`architecture.png`](architecture.png) — the components and how a claim moves between them.
  Drawn for the in-class Peer Clarification Round, before the instructor's reference
  architecture was shown.
- [`sequence-diagram.png`](sequence-diagram.png) — the same flow over time, with the
  missing-information branch.

## Components

Eight components. "Built" means it exists and is tested in this repo; "Mocked" means the stage
runs but stands in for the real thing (see `MOCKS.md`).

| # | Component | Responsibility | In this repo |
|---|---|---|---|
| 1 | Claimant | Submits claim details and supporting documents | Built — Google sign-in, sees only their own claims |
| 2 | Claim intake | Validates input, stores the claim and its files | Built — `app.py`, `validation.py`, `storage.py` |
| 3 | AI extractor | Pulls structured facts (dates, amounts, incident type) from documents. Never authoritative. | Mocked — `extraction.py`, regex only. The AI review reads the same text and cites it, but never writes facts |
| 4 | Completeness check | Returns `READY_FOR_REVIEW` or `NEEDS_INFORMATION` with the missing fields named. Deterministic. | Built — `main.py`; the standalone Assignment 7 version is `claim-intake-streamlit/logic.py` in the course submission |
| 5 | AI summary | Drafts a summary for the adjuster. A draft only. | **Built (Phase 5)** — the intake review agent (`agents.py`), checked by `agent_gate.py`; the template `summary.py` is the labelled fallback. Two more agents answer questions: adjuster (per claim) and claimant (own claims only) |
| 6 | Adjuster review | A human reads the summary *and* the source documents, then decides | Built — separate adjuster login, separation-of-duties check |
| 7 | Claims store | Claims, documents, status history, decisions, login audit trail | Built — SQLite (`storage.py`) |
| 8 | Claimant notification | Tells the claimant the status, or exactly what is missing | Mocked — logged on two channels, not sent |

Two rules hold across the whole design: the completeness check never approves, denies, or pays
a claim, and no AI output is ever the basis for a decision — a human adjuster decides, with the
source documents in front of them.

One difference between the sequence diagram and the build: the diagram generates a summary
only for `READY_FOR_REVIEW` claims. The build generates one for every claim, so an adjuster
also has a summary when a claim is incomplete.

## Pressure test

### When the AI summary disagrees with the source evidence

**The source documents win.** The summary is a draft for the adjuster, never the record and
never the basis for a decision.

Built today:

- The adjuster's claim page shows the summary, the full extracted-facts table (each fact with
  the document it came from), and the original documents together, so a contradiction is
  visible on one screen.
- The summary is labeled as an automated draft, not AI-generated.
- The current summary only restates fields already stored on the claim, so it cannot
  introduce a date, amount, or status that isn't in the record.

For the real AI summary (**built in Phase 5**, `agents.py` and `agent_gate.py`):

- Each sentence cites the document, page and a word-for-word quote (gate rules G2-G3).
- An automated check compares the summary's dates and amounts against the cited quotes and the
  tool results, and catches decision, coverage and payment wording (G4-G5) and injected
  instructions (G8). Any failure flags the review: the failing lines are marked, the reasons
  listed, and the label says "failed automated checks". Every run, flagged or not, is kept in
  the append-only `agent_runs` log. (Not built: recording the adjuster's resolution of a flag.)
- A citation does not fix a wrong sentence. If the source says $2,150 and the summary says
  $2,500, adding a reference to the source only makes the error easier to trace. The sentence
  has to be rewritten to match the source.

### When the AI summary omits a fact

**An omission must be visible, not silent.**

Built today:

- A missing field is named in the summary, not left blank — e.g. "incident reported
  [incident date not provided]", "Documents on file: none provided."
- If the extractor could not read a document, the summary says so and tells the adjuster to
  open the original file.
- The completeness check runs on the claim's own fields, independently of the summary. A
  missing required field produces `NEEDS_INFORMATION` regardless of what the summary says.
- The full extracted-facts table and document list are always shown next to the summary, so a
  fact the summary leaves out is still in front of the adjuster.

For the real AI summary (**built in Phase 5**):

- Code (`agent_gate.not_summarised`), not the model, lists every extracted amount and date that
  appears in no summary sentence or finding, under the review as "Not summarised -- listed by
  code, not the AI".
- What code can't catch is a *finding* the model never makes (a conflict it doesn't mention).
  That is measured by the golden set instead (`scripts/eval_agents.py`): the one model that
  missed most conflicts there was kept out of `AI_MODELS` (AGENTS.md section 11.4).
