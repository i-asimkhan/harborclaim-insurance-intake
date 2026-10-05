# What's mocked in HarborClaim, and why

This project mixes real infrastructure (database, auth, file storage) with deliberately
fake stand-ins for the two stages the assignment explicitly says don't need to be real
("Runtime AI and cloud deployment are not required"). This file is the single place that
says, plainly, which is which -- so nobody mistakes a mock for the real thing while
reading the code or clicking through the app.

**All data is fictional.** Every claim, policy number, dollar amount, and sample document
in this project is made up for the class. Nothing here is a real claims system.

## The three mocked stages

| Stage | File | What it actually does | What it is NOT doing |
|---|---|---|---|
| Fact extraction | `extraction.py` | Reads real text (the claim description, plus the real text layer of uploaded `.txt`/`.pdf` files via `pypdf`), then finds dollar amounts, dates, and a fixed list of incident keywords with plain regular expressions. | No model call. No NLP library. No inference beyond a literal regex match. Can't read images, zips, or any format besides `.txt`/`.pdf`. |
| Summary generation | `summary.py` | Assembles a paragraph from fields already on the claim plus whatever extraction found, using a fixed string template. | No model call. Generates nothing that isn't a direct restatement of data already stored and visible on the same page -- it cannot "hallucinate" a fact, because it has no way to introduce one that isn't already in the database. |
| Notifications | `storage.add_notification` / `app._notify` | Writes a row to the `notifications` table on two "channels" (`in_app`, `email`) every time a claim's status changes or an adjuster decides on it. | No SMTP call, no email provider, no push service. The `email` channel is a label on a database row, not a sent message -- see the "📧 MOCK EMAIL" tag on the notifications page. |

## Why mocks instead of nothing

Early in this project these three stages simply didn't exist -- the pipeline stopped at
the completeness checker. Comparing against classmates' submissions to the same
assignment showed a better pattern: build the stage as an honest, clearly-labeled mock
so the *pipeline* is real even though the *intelligence* isn't. A classmate's loan-review
submission uses the identical approach for the same two slots (regex-based "mock document
AI," a hand-written risk formula instead of a model, and a mock notification outbox) --
this project's version follows that same shape, adapted to SQLite instead of a JSON file.

## Why mocks instead of a real LLM call

Mainly scope and cost control for a class project, but also a real design point: the
Design Deliverable's own pressure test asks what happens when an AI summary conflicts
with the source documents. The honest answer for a real AI summary is "sometimes, and you
need a way to catch it." The honest answer for *this* mock summary is that it structurally
can't conflict -- every sentence it writes is a direct copy of a field already stored and
shown on the same page, so there's nothing in it a reviewer can't verify in five seconds
against the claim detail and document list sitting right above it. That's a real
limitation (it can't actually read and interpret a document the way a human or an LLM
could), not a solved problem -- see "What a real version would need" below.

## What's real, for contrast

Everything these three mocks sit on top of is real, not mocked: the completeness checker
(`main.py`, the graded minimum), file storage (`storage.save_uploaded_file`, real bytes on
disk), the SQLite database (survives a server restart, verified by actually restarting
the server mid-session), Google sign-in for claimants and provisioned credentials for
adjusters (`auth.py`), the separation-of-duties check, and the login audit trail. None of
those are placeholders standing in for something not yet built.

## What a real version of each mock would need

- **Extraction**: an LLM or a document-AI service (e.g. a vision-capable model, or a
  service like Azure Document Intelligence) reading the actual uploaded file -- including
  images and scanned PDFs, not just `.txt`/`.pdf` text layers -- and returning structured
  fields with confidence scores, not just a keyword hit.
- **Summary**: an LLM call grounded in the extracted facts and the retrieved document
  text, with inline citations back to the specific document and page a claim was drawn
  from, plus a way to flag when the generated text says something the source documents
  don't support -- the exact failure mode the Design Deliverable's pressure test asks
  about.
- **Notifications**: a real email provider (e.g. SendGrid, SES) for the email channel, and
  a push/websocket mechanism for the in-app channel to update live instead of only on
  page load.

## Sample documents for trying this yourself

`sample_data/` has a handful of fictional claim documents (PDFs) written so the mock
extractor actually finds something in them -- dollar amounts, dates, incident keywords.
Upload one when filing a test claim to see the extraction/summary pipeline do something
other than return an empty table. See `sample_data/README.md` for what's in each one.
