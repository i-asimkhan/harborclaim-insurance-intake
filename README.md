# HarborClaim — Insurance Claim Intake System

USF FIN 6934 (AI in Finance), System Design Studio — Assignment 7. HarborClaim is a
fictional insurtech startup; this is my take-home build for its claim intake system.

## What this is

The minimum working example from the take-home spec: a claim completeness checker.
Given a fictional claim (policy ID, incident date, description, and a list of
supporting documents), it returns `READY_FOR_REVIEW` if everything required is
present, or `NEEDS_INFORMATION` naming exactly which fields are missing.

**It does not approve, decline, or pay a claim.** That decision — and any judgment
about coverage — stays with a human adjuster. This component only decides whether a
claim has enough information to reach that adjuster in the first place.

## Setup

No dependencies — standard library only. Requires Python 3.9+.

## Run it

```bash
python main.py
```

```
[CLM-1001] READY_FOR_REVIEW
{
  "status": "READY_FOR_REVIEW",
  "missing": []
}

[CLM-1002] NEEDS_INFORMATION -- missing: incident_date
{
  "status": "NEEDS_INFORMATION",
  "missing": [
    "incident_date"
  ]
}
```

## Test it

```bash
python -m unittest -v
```

5 tests: a complete claim, a claim missing `incident_date`, a claim missing
`documents`, a claim missing everything (confirms all missing fields are named at
once, not just the first one found), and a check that the result never contains a
coverage/payout word (`approve`, `deny`, `decline`, `pay`).

## What counts as "required"

- `policy_id`, `incident_date`, `description` — must be present and a non-blank string.
- `documents` — must be present and a non-empty list. Contents aren't validated (a
  document's name alone doesn't say whether it's the *right* document — see Limitations).

## Limitations (on purpose, for this minimum version)

- Field values aren't validated beyond "non-blank" — an `incident_date` of `"tbd"`
  passes. Real date parsing / format checking is a natural next step.
- `documents` only checks the list isn't empty; it doesn't check that the *right*
  documents were uploaded for the claim type (e.g., a police report for an auto claim).
- No persistence — this is a pure function over one claim at a time, not a service.
- No AI extraction or summarization — the full design calls for an AI step that pulls
  structured facts out of uploaded documents and drafts an adjuster summary, but the
  scenario is explicit that source documents stay authoritative over any AI output.
  This minimum build implements the deterministic completeness gate that decision
  would sit behind, not the AI step itself.

## Mocks

All claim data (`CLM-1001`, `CLM-1002`, policy IDs, document names) is fictional,
written for this demo. No real customer or policy data is used anywhere in this
folder.

---

## Optional stretch: web UI

Beyond the graded minimum above, this folder also has a small FastAPI web front end
(`app.py` + `templates/` + `static/`) so the completeness checker can be driven from a
browser instead of only the console demo. It's optional — the graded part is
`main.py`/`test_main.py` above, unchanged and untouched by any of this.

### Tech stack, and why

| Layer | What |
|---|---|
| Backend | FastAPI + Uvicorn |
| Templating | Jinja2 (server-rendered HTML, no JS framework) |
| Styling | Plain CSS (`static/style.css`), IBM Plex fonts |
| Testing | `pytest` + FastAPI's `TestClient` (`tests/test_app.py`) |
| State | In-memory dict (`app.CLAIMS`) — a stand-in for a real database, resets on restart |

**FastAPI + Jinja2 was picked over Flutter Web or a NestJS backend for a few concrete
reasons, not just "it's what was already installed":**

- **Same language as the logic it's wrapping.** `app.py` imports `check_claim`
  directly from `main.py` — no network call, no serialization boundary, no second
  language. A Flutter or separate-Node front end would need the backend turned into a
  JSON API first (a fine change, just extra work with no functional benefit yet).
- **Zero new tooling, originally.** This started inside the course's shared Python
  environment, where FastAPI/Jinja2/Uvicorn were already installed from an earlier
  class's agent app — only `python-multipart` (form parsing) and `pytest` were new.
  Now split out into this standalone repo with its own `requirements.txt`.
- **It's the industry default for exactly this kind of AI-adjacent backend.** FastAPI
  is the framework used across most real-world "wrap model logic in an API" work
  (OpenAI's own examples, Hugging Face inference endpoints, LangServe, vLLM's serving
  layer) — precisely because Python is the AI ecosystem's language, so the API layer
  and the model/data code share one process and one language.
- **NestJS is a backend peer to FastAPI, not an alternative to Jinja2/Flutter** — same
  job (routing, validation, async I/O), different language (TypeScript vs. Python).
  Picking it here would mean rewriting `check_claim()` in TypeScript for no gain, since
  nothing in this project needs Node's ecosystem specifically.
- **Flutter is a frontend peer to Jinja2, not to FastAPI** — it's a UI toolkit (Dart),
  not a backend. Using it would mean keeping FastAPI underneath (converted to return
  JSON instead of HTML) and rebuilding the 3 screens in Dart on top. Reasonable if this
  becomes a real mobile+web app later; not needed to satisfy the assignment.
- **Scaling profile is the same as the alternatives that matter here.** FastAPI and
  NestJS are both async, stateless-by-default, and scale horizontally the same way
  (more processes/containers behind a load balancer) — nothing is given up by choosing
  Python over Node for this.

### Set up the web UI

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Windows
# .venv/bin/pip install -r requirements.txt        # macOS/Linux
```

### Run the web UI

```bash
.venv/Scripts/python.exe -m uvicorn app:app --reload
```

Then open `http://127.0.0.1:8000/`. `--reload` isn't required, just convenient
during development.

### Test the web UI

```bash
.venv/Scripts/python.exe -m pytest tests/test_app.py -v
```

6 tests covering the form page, a complete-claim submission (redirects to
`READY_FOR_REVIEW`), an incomplete one (names the missing field), an unknown claim ID
(404), and the claims list (populated and empty states).

### What's real vs. stubbed

Only the completeness check is real logic. The full Design Deliverable calls for
seven more stages: document/evidence storage, an AI fact extractor, an AI summary
generator, an adjuster review step, a persistent claims database (replacing the
in-memory store this UI currently uses), a notification service, and finally wiring
all of it into one pipeline. None of those are built yet.
