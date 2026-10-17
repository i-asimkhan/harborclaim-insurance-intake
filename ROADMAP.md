# HarborClaim roadmap

What's built, what's next, and why. Status key: `[ ]` not started · `[~]` in progress ·
`[x]` done.

## Principles

- **Primary stack: FastAPI + Jinja2.** The Assignment 7 build guide's own brief specifies a
  one-screen Streamlit app. This project keeps FastAPI + Jinja2 as the primary build instead,
  with the reasoning written out in README.md's "Tech stack, and why" section. The guide's
  literal, scored shape is still implemented in full, standalone, in
  `claim-intake-streamlit/` inside the [teacher-repo submission](https://github.com/adnanmasood/fintech-samples/pull/12).
- **`main.py` / `test_main.py`** (the graded minimum) stay untouched across every phase below.
- **Real AI (Phase 5) is last on purpose.** Everything else gets built on real infrastructure
  first; the two mocked intelligence stages are swapped for the real thing only once the rest
  of the product is solid.

## Current status

- Core completeness checker, FastAPI web app, two-role auth (claimant Google sign-in,
  adjuster provisioned credentials), persistent SQLite storage, document upload, a mocked
  extraction/summary pipeline, and a notification log are all built and tested (44 tests in
  `tests/test_app.py`, 5 in `test_main.py`, a Playwright suite in `tests/test_ui.py`).
- Deployed live at **[harborclaim-demo-2630.azurewebsites.net](https://harborclaim-demo-2630.azurewebsites.net)**
  (Azure App Service, Free F1 plan), deployed from this repo's `main` branch. Deployment is
  a **manual sync**, not automatic on push (`isManualIntegration: true`, no webhook): after
  pushing, run `az webapp deployment source sync --name harborclaim-demo-2630
  --resource-group harborclaim-rg` or click **Sync** in the portal's Deployment Center.
- Assignment 7's literal Streamlit minimum is built and submitted separately via
  [PR #12](https://github.com/adnanmasood/fintech-samples/pull/12) to the course's shared
  repo, standalone from this build (see `claim-intake-streamlit/` in that PR).
- Claim-type list for Phase 2 and email provider for Phase 3 are decided (see those phases
  below); not yet implemented.

Execution order: **Phase 0 (done) -> 1 -> 2 -> 3 -> 4 -> 5**.

---

## Phase 0 -- Close the spec-compliance gap [x] done

The Assignment 7 build guide specifies something materially smaller than the FastAPI build:
a one-screen Streamlit app (`app.py` + `logic.py` + `tests/test_logic.py`), no database, no
auth, no file uploads, `check_claim(claim)` returning `{status, missing}`, two screenshots
named `screenshots/normal.png` and `screenshots/failure.png`, and one required modification
(a next-step message when `description` is missing).

Submitted via the course's existing fork-and-PR-into-`student-projects/` workflow
(`CONTRIBUTING.md`), in a `claim-intake-streamlit/` subfolder alongside the FastAPI build
(avoids an `app.py` naming collision at the project folder's root) --
[PR #12](https://github.com/adnanmasood/fintech-samples/pull/12).

- [x] Tech-stack-decision documentation in README.md's "Tech stack, and why" section.
- [x] `logic.py` -- `check_claim(claim) -> {status, missing}`.
- [x] `app.py` -- one Streamlit screen per the guide's wireframes.
- [x] `tests/test_logic.py` -- the 8 cases from the build guide, 11/11 passing.
- [x] Required modification: human-readable next-step message when `description` is missing.
- [x] `screenshots/normal.png` and `screenshots/failure.png`, captured from the running app.
- [x] `README.md` and `AI_USAGE.md` for the subfolder.
- [x] `requirements.txt` pinned, `.gitignore` per the guide's list.
- [x] PR opened into `adnanmasood/fintech-samples`.

---

## Phase 1 -- Visual redesign (no backend changes)

Goal: stop looking like a built-for-tests demo and start looking like a real insurance
product.

- [ ] **Research pass first.** Pull reference screenshots from a handful of real claims-intake
      flows (Lemonade, Root, Progressive's claims portal, a couple of others) and note the
      patterns worth copying: centered single-column forms, a clear one-line value prop above
      the fold, progress/step indicators, trust signals near the submit button. Do this for
      both the claimant sign-in and the adjuster login -- they should stay deliberately
      different from each other (see README.md's "Claimant and adjuster pages are fully
      separate routes"), just each one good on its own terms.
- [ ] **Fix the table overflow bug.** Long values (claimant email, description, filenames)
      break out of `table.claims-table` / `table.facts-table` cells. Needs `table-layout:
      fixed`, explicit column widths, `overflow-wrap`/`word-break` on text cells, and probably
      truncation with a title-attribute tooltip for the longest fields.
- [ ] **Typography and spacing overhaul.** Current look (`static/style.css`) uses IBM Plex
      Sans/Mono on a fairly bare grid. Decide: keep IBM Plex but fix scale/weight/spacing, or
      swap to something more SaaS-standard (Inter, Geist). Either way: consistent heading
      scale, consistent button/badge sizing, more breathing room in cards.
- [ ] **Notifications as a top-nav item**, not a plain text link. A bell icon with an
      unread-count badge and a dropdown preview; clicking through still goes to the full
      `/notifications` page.
- [ ] Re-screenshot everything in `docs/screenshots/` once the redesign lands --
      `scripts/capture_screenshots.py` regenerates the set from a live instance.

---

## Phase 2 -- Claim type at intake

Goal: let a claimant say what kind of claim this is, and let that shape what's asked for.

- [x] **Claim-type list:** `auto`, `property`, `health`, `theft`, `liability`, `other`. Maps
      cleanly to the existing `sample_data/` document types (police report -> auto, repair
      estimate -> property, injury notes -> health, theft report -> theft).
- [ ] Add a `claim_type` field to the submission form using the list above.
- [ ] Per-type document hints in the UI (e.g. auto -> "attach a police report if you have
      one"; property -> "attach a repair estimate"). Hints only -- not a hard requirement,
      since `main.py`'s completeness rule (any non-empty `documents` list) can't change.
- [ ] Schema: add a `claim_type` column to the `claims` table (`storage.py`), migrate like the
      existing `claimant_email` migration pattern.
- [ ] **Constraint:** `main.py` / `test_main.py` stays untouched. Claim-type logic belongs in
      `app.py` / `validation.py` / the web layer, as an addition on top of `check_claim()`,
      never inside it.
- [ ] Decide whether claim type later feeds the mock extractor's keyword list
      (`extraction.py`'s `INCIDENT_KEYWORDS`) -- e.g. skip "theft" matching on a health claim.
      Nice-to-have, not required for this phase.

---

## Phase 3 -- Notifications, for real

- [ ] Notifications page polish: group by claim, relative timestamps ("2 hours ago"), clearer
      read/unread state than the current left-accent-bar treatment.
- [x] **Email provider: Azure Communication Services Email.** Same Azure subscription already
      in use for the Web App, no new third-party account, pay-as-you-go pricing is
      effectively free at this project's demo volume.
- [ ] **Real email delivery** for the `email` channel, behind a feature flag / env var so the
      simulated path still works without the provider configured. Needs an Email
      Communication Service + sender domain (or Azure's free `*.azurecomm.net` managed
      domain), a connection string held as another Azure app setting.
- [ ] In-app channel: still just a logged row for now, unless this phase also needs live
      updates (websocket/poll) instead of only-on-page-load.

---

## Phase 4 -- Azure production setup

- [ ] Flesh out Blob Storage, Document Intelligence, a queue, Key Vault, Azure SQL, and Entra
      ID for adjuster identity from a design into at least a partial build, starting with
      whichever piece Phase 5 needs first (likely Document Intelligence, since extraction is
      the first real-AI piece).
- [ ] Decide whether the Free F1 plan is enough once there's a queue + Document Intelligence
      in the mix, or whether this needs a paid tier -- F1 has no "Always On" and sleeps on
      idle, fine for a demo link but not for a queue worker.

### Long-term storage design (claims, documents, notifications)

The relational schema already in `storage.py` is the right shape -- the fix is swapping its
backend, not redesigning the data model.

- [ ] **Claims -> Azure SQL Database** (or Azure Database for PostgreSQL). SQLite is a single
      file on disk, which a redeploy, restart, or scaling to more than one instance can wipe
      or fragment -- fine for a demo, risky long-term. `list_claims_for(claimant_email)`
      already filters a claimant to only their own claims; that logic doesn't change. Mainly
      `storage.py`'s connection layer changes, to a real driver with a connection string held
      as another Azure app setting.
- [ ] **Documents -> Azure Blob Storage**, private container. Uploaded files currently land in
      `data/uploads/` on local disk, same durability problem as SQLite. The `documents` table
      already stores a path per file; that column starts holding a Blob reference instead,
      and downloads go through a short-lived signed URL instead of a local file read.
- [ ] **Notifications -> no schema change, just real delivery.** The `notifications` table
      already logs every event per claimant on two channels -- storage isn't the gap. See
      Phase 3 for the real email provider.
- [ ] **Net effect:** once the database and Blob Storage pieces land, nothing about how a
      claimant sees their own claim history changes from their side -- it already works via
      `claimant_email` filtering. What changes is durability: claims and documents survive
      restarts, redeploys, and scaling instead of depending on one server's local disk.

---

## Phase 5 -- Real AI (last on purpose)

Goal: replace the two mocked intelligence stages with the real thing, once everything else is
in better shape. See `MOCKS.md` for what's mocked today and why.

- [ ] **Extraction**: a document-AI step (Azure Document Intelligence fits the existing Azure
      direction) reading the actual uploaded file -- including images and scanned PDFs, not
      just the `.txt`/`.pdf` text layer `extraction.py` currently handles -- returning
      structured fields with confidence scores and page references, not a keyword hit.
- [ ] **Summary**: an LLM call grounded in the extracted facts and the retrieved document
      text, with inline citations back to the specific document and page a claim was drawn
      from, plus a way to flag when the generated text says something the source documents
      don't support.
- [ ] **Model/provider decision, not yet made.** Azure OpenAI is the natural fit given the
      deployment target.
- [x] **UI labeling: no blunt "MOCK" wording in the results views.** The results-page badges
      and tags now read `"Automated draft -- not AI-generated"`, `"Automated extraction --
      not AI"`, and `"Email (simulated)"` -- same honest disclosure as before, without the
      alarming-sounding word. `MOCKS.md`'s fuller documentation of what's mocked and why is
      unchanged.
