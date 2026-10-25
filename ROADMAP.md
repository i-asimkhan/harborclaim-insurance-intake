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

## Final project deadline (FIN 6934)

HarborClaim is the owner's **FIN 6934 Final Project**: **40% of the course grade**,
**presented and submitted Tue Nov 10, 2026** (syllabus: "Final Project Presentation and
Submission"). Assigned 9/1; the syllabus gives no rubric, length or submission format.

**What else is due in the same window.** Assignment 2 (30%) is the PaymentCo 2030 team case:
memo due **Sun Nov 1**, board presentation **Tue Nov 3**, team meetups **Sat Oct 24 and Sat
Oct 31, 11 am**. That work comes first until Nov 3, so the real HarborClaim build window is
about **Nov 4–9**, plus spare evenings before.

### Plan to Nov 10

| When | HarborClaim work | Also that day |
|---|---|---|
| Thu Oct 22 – Fri Oct 23 | Owner decides on commit + push of the ~40 uncommitted files; Sync and smoke-test the live site | — |
| Sat Oct 24 | — | PaymentCo meetup, 11 am |
| Sun Oct 25 – Mon Oct 26 | Finish Phase 3 hosted rollout (Azure settings, `EMAIL_ENABLED=false` first, then on) | — |
| Tue Oct 27 | — | Class (PaymentCo Week 3) |
| Oct 28 – Nov 3 | Light only: approve Phase 5, model probe round 1 (free, ~12 requests); steps 5.1–5.2 (groundwork, harness, gate; no model calls) in spare evenings | PaymentCo memo (Nov 1), meetup (Oct 31), presentation (Nov 3) |
| Wed Nov 4 – Fri Nov 6 | Phase 5 core: 5.3 intake review agent, 5.4 golden set + first live runs, then 5.5 adjuster assistant if on track; 5.6 claimant assistant only if time remains | — |
| Sat Nov 7 | Code freeze; deploy; regenerate screenshots | — |
| Sun Nov 8 | Presentation slides + demo script; README final pass | — |
| Mon Nov 9 | Timed rehearsal on the live site; buffer for fixes | — |
| **Tue Nov 10** | **Present and submit** | — |

### Decisions needed from the owner

- [ ] **AI before Nov 10, or present with the labeled mocks?** Superseded by the Phase 5 plan
      (2026-10-24): three agents on one harness, intake review first. The mocks stay as the
      fallback behind an off-by-default flag, so whatever is built by Nov 9 is what's shown.
- [x] **New Azure resources for Phase 5**: none. Decided 2026-10-24: a free OpenRouter model
      instead of Azure OpenAI, $0 (Phase 5, step 5.0).
- [ ] **Phase 4 scope.** The full production setup (Azure SQL, Blob, queue, Key Vault, Entra)
      doesn't fit before Nov 10. Recommendation: build only what Phase 5 needs, and present
      the rest as the documented production design (the "Long-term storage design" below).
- [ ] **Phase 1b open items** (decision note, "Worth checking") only if time allows; the
      decision note is the better demo moment.
- [ ] **Confirm the final-project requirements** with the instructors: presentation length,
      what to submit (repo link, PR, slides, report), and where.

**For the Nov 10 presentation:** problem and users; live demo (claimant files, completeness
check, adjuster reviews and decides, claimant notified); architecture; what is AI and what is
labeled automation (`MOCKS.md`); responsible-AI choices (human decides, source documents
authoritative, honest labels); production roadmap (Phases 4–5).

## Current status

- Core completeness checker, FastAPI web app, two-role auth (claimant Google sign-in,
  adjuster provisioned credentials), persistent SQLite storage, document upload, a mocked
  extraction/summary pipeline, a notification log, claim type at intake, a redesigned
  claimant side and adjuster side, and email delivery behind an off-by-default flag are all
  built. **94 tests pass**: 74 in `tests/test_app.py`, 15 Playwright tests in
  `tests/test_ui.py`, 5 in `test_main.py`.
- **Everything since the Phase 2 commit is uncommitted and not deployed** (about 40 changed
  files: Phases 1, 1b and the first slice of 3). The live Azure site still runs the older
  build. Committing, pushing and the Azure Sync are the owner's call.
- Deployed live at **[harborclaim-demo-2630.azurewebsites.net](https://harborclaim-demo-2630.azurewebsites.net)**
  (Azure App Service, Free F1 plan), deployed from this repo's `main` branch. Deployment is
  a **manual sync**, not automatic on push (`isManualIntegration: true`, no webhook): after
  pushing, run `az webapp deployment source sync --name harborclaim-demo-2630
  --resource-group harborclaim-rg` or click **Sync** in the portal's Deployment Center.
- Assignment 7's literal Streamlit minimum is built and submitted separately via
  [PR #12](https://github.com/adnanmasood/fintech-samples/pull/12) to the course's shared
  repo, standalone from this build (see `claim-intake-streamlit/` in that PR).
- Phase 3 is built and working locally: real email through Azure Communication Services
  (proven with one real send), claim links and HTML design, an adjuster email, sending after
  the response, an on/off switch, and a self-refreshing bell. Left: seeing the decision and
  adjuster emails arrive, and switching it all on for the hosted site (see Phase 3).

Execution order: **Phase 0 (done) -> 1 (done) -> 2 (done) -> 1b (visual done; decision note
and "Worth checking" open) -> 3 (built locally; hosted rollout left) -> 5 (planned; the
agentic layer, see [`docs/design/AGENTS.md`](docs/design/AGENTS.md)) -> 4**. Phase 5 moved
ahead of Phase 4: HarborClaim is the final project (due Nov 10), and Phase 5 doesn't need any
Phase 4 piece. The new-session handoff summary is at the end of this file.

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

## Phase 1 -- Visual redesign (no backend changes) [x] done

Goal: stop looking like a built-for-tests demo and start looking like a real insurance
product.

- [x] **Research pass first.** Notes in `docs/design/RESEARCH.md`: Root, Progressive, State
      Farm and Lemonade on the claimant side; Guidewire ClaimCenter and Five Sigma on the
      adjuster side. Taken from public pages and docs rather than screenshots (the real flows
      sit behind policy logins, and Lemonade's page blocked automated fetches). Adopted: a
      value prop with an honest effort estimate, "how it works" steps, grouped form sections,
      trust signals by the submit button, a prominent claim number, queue count tiles, and a
      two-column review screen with a sticky decision rail. Not adopted, with reasons: one
      question per screen, invented phone numbers or testimonials, guest filing.
- [x] **Fix the table overflow bug.** The adjuster queue now uses a wider page
      (`.page.wide`, now 1120px), both claim tables use `table-layout: fixed` with per-table
      `<colgroup>` widths, cells wrap with `overflow-wrap: anywhere`, long emails and policy IDs
      truncate with the full value in a `title` tooltip, and dates show as `YYYY-MM-DD` with the
      full timestamp on hover. Checked in a real browser: the queue table now ends inside its
      card instead of running past it.
- [x] **Typography and spacing overhaul.** Decided: **Inter** for all interface text, **IBM
      Plex Mono** kept only for identifiers (claim IDs, policy numbers, filenames, status
      codes). `static/style.css` now runs on a type scale (`--text-xs` to `--text-lg`) and a
      4px spacing scale. Buttons have one height and three intents (primary, approve, decline,
      plus secondary), every badge is the same pill (`.lg` on result pages), and the inline
      per-template styles are gone. Also fixed along the way: the signed-out "Sign in with
      Google" link had no button styling at all (`a.primary` was never defined), the nav
      identity ran into the "Notifications" link, and the adjuster's light-blue primary
      button had white text at under 3:1 contrast (it now uses dark text).
- [x] **Notifications as a top-nav item**, not a plain text link. A bell icon with an
      unread-count badge and a dropdown preview; clicking through still goes to the full
      `/notifications` page. It's built on `<details>`, so it works with no script;
      `static/app.js` only adds click-outside and Escape to close it. Claimant side: the
      badge counts *events* (the in-app rows), so one status change shows as 1, not 2 as
      the old text-link badge did (it counted both channels). Opening the dropdown marks
      nothing read; only the full page does, as before. Adjuster side: the badge is the live
      "needs attention" count, on every adjuster page, including claim review, which had
      no notifications link before. Each role has its own header partial
      (`_claimant_header.html`, `_adjuster_header.html`), so no template branches on role.
      Tested in `tests/test_app.py` (2 tests) and `tests/test_ui.py` (1 browser test).
- [x] **Second pass: claimant side restyled after Lemonade's homepage** (see
      `docs/design/RESEARCH.md`, "Second pass"). Warm grays and one signature color, harbor
      coral (`#C93B25` for text and buttons, `#E8553D` for decoration only, both
      contrast-checked); Fraunces serif page titles; uppercase buttons with a soft glow;
      borderless cards; line-art illustrations drawn as inline SVG (`templates/_art.html`):
      a harbor scene, one icon per claim type, a lighthouse brand mark. The claim form is now
      a conversation: each section opens with a question in a chat bubble, and claim type is
      picture tiles instead of a dropdown. Still one page and one submit, so no flow or
      backend change. Warnings moved from orange-red to amber so they don't read as the
      brand color. The adjuster side keeps its dark enterprise look; it only gains the mark.
- [x] **Input validation tightened, browser and server.** Fixed a real bug: uploads were
      validated one file at a time, so the 10-file limit never triggered; regression test
      added (it fails on the old code). The form now enforces the same limits in the browser
      (`maxlength`, date `min`/`max`, `accept`, plus `static/claim_form.js` for file count,
      size and type), with values taken from `validation.py` so the two can't drift. The
      server still re-checks everything; a browser test with JavaScript off proves it.
      Blank fields stay allowed on purpose -- they're `NEEDS_INFORMATION`, not errors.
- [x] **Claimant claim page reworked** after review feedback ("too many rows with the same
      design"). Four visually distinct sections now: the outcome message (worded per state,
      including each decision) with a four-step progress tracker (Submitted, Completeness
      check, Adjuster review, Decision); "Your claim" as a three-fact strip, the description
      as a quote, and documents as file tiles; extracted facts as one row per kind (what
      happened, amounts, dates), each distinct value a single tag with its sources listed
      once (`app._group_facts`), instead of an 11-row table with duplicates; and the
      adjuster's draft summary collapsed by default, since it's written for the adjuster.
      Both "not AI" labels stay visible. The adjuster's own review page keeps the full table.
- [x] **Tests and screenshots have their own database.** `storage.DATA_DIR` now reads
      `HARBORCLAIM_DATA_DIR` (default: `data/`, unchanged). `tests/conftest.py` points it at a
      throwaway folder before anything imports `storage`, and the browser tests' live server
      inherits it; `scripts/capture_screenshots.py` does the same. Checked by fingerprinting
      `data/harborclaim.db` before and after a full test run plus a full screenshot run: byte
      for byte unchanged (it used to be wiped, which deleted the owner's claim once). Two
      tests guard it: one fails if tests ever resolve to the dev `data/` folder, one checks
      the default is still `data/`. No more backing up the database before running tests.
- [x] **Submit button stays off until the claim is complete** (`static/claim_form.js`).
      Five pills (claim type, policy ID, incident date, what happened, documents) turn green
      as each is filled in, a line names what's still needed, and the button enables only
      when all five are in. The date and policy ID must also be valid (a future date doesn't
      count), and the button locks on the first click so a double-click files one claim.
      This is a decision made after review: I'd recommended a live checklist that left the
      button on, because filing an incomplete claim is the assignment's core behavior
      (`NEEDS_INFORMATION`), but the rule that nothing is sent half-filled was preferred.
      **The cost:** the form can no longer produce a `NEEDS_INFORMATION` claim. The server
      is unchanged and still accepts partial claims from scripts and the seed data (and
      `main.py` still answers `NEEDS_INFORMATION`), except that a submission with nothing at
      all is rejected (`validation.validate_not_empty`). Screenshot 04 is captured by posting
      the form the way a script would. Without JavaScript the checklist is hidden and the
      form submits as before.
- [x] Re-screenshot everything in `docs/screenshots/` once the redesign lands --
      `scripts/capture_screenshots.py` regenerated all 13, plus a new
      `14-notification-bell-open.png`.

---

## Phase 1b -- Adjuster workflow and review screen [x] visual work done

The claimant side got a full design pass in Phase 1; this is the same pass for the
adjuster side, from a review of the screens (long fact table with duplicate rows, automated
output louder than the claim itself, queue ordered with decided claims first, one-click
final decisions, developer notes in the page copy). Visual work first; the two items that
change what the app computes or stores are listed separately and left unticked until
they're decided.

Visual and flow, no schema change:

- [x] **Review page:** extracted facts as grouped tags (one row per kind, each value once,
      sources listed once -- the claimant page's treatment, shared partial); automated cards
      quieter on the dark theme (a thin amber edge instead of a cream fill, tags unchanged,
      text contrast still tested).
- [x] **Decision confirm step:** choosing a decision opens a confirm dialog naming the
      claim and the decision; one send only, so a double-click can't record it twice.
- [x] **Queue:** work waiting first (awaiting a decision, oldest first; then waiting on
      claimant; then decided); the count tiles become the filters; search by claim ID,
      claimant, policy or type; the "Needs attention" card goes (the awaiting tile and the
      bell already say it).
- [x] **Copy and times:** developer notes out of the page text (they stay in the README),
      relative times everywhere ("2 hours ago", full timestamp on hover).

Built: the facts partial is shared with the claimant page (`_facts_groups.html`); the
confirm dialog is `static/review.js` (a native `<dialog>`; without JavaScript the buttons
post directly); queue ordering, filters and search are server-side in `app.py`
(`_order_queue`, `_queue_matches`, `?view=` and `?q=`), so they work without JavaScript and
storage is untouched. The "Needs attention" card is gone from the queue (its count is the
"Awaiting a decision" tile and the bell); the adjuster notifications page keeps its list.

Bugs the owner found while testing, fixed with regression tests:

- [x] **"Needs more review" dropped a claim off the adjuster's list.** Any decision was
      treated as final, so a claim marked "Needs More Review" left the awaiting count, the
      bell and the top of the queue even though the adjuster still owed a final decision.
      The rule now follows the claim's *latest* decision: Approved or Declined finishes it;
      "Needs more review" keeps it awaiting (`storage.claims_needing_adjuster_attention`,
      `app._queue_category`). The review page flags it, and the claimant's tracker shows
      "In progress / Not yet" rather than a finished decision.
- [x] **Blank adjuster login returned a raw JSON validation error.** FastAPI treats a blank
      required form field as missing and answers 422. The login (and the decision route)
      now default to `""` and handle blanks as normal pages; the login form also has
      `required` attributes. A blank attempt is never recorded as a login.
- [x] **Empty claims.** A completely empty submission is rejected server-side
      (`validation.validate_not_empty`), the button stays off until the claim is complete,
      and it locks on the first click so a double-click files one claim.
- [x] **Stale CSS after a deploy or edit.** Stylesheet and script links carry a version tag
      (`static_url()` in `app.py`, from the file's modified time), and icons have built-in
      sizes so a missing stylesheet can't make them huge.

Not started, needs a decision:

- [ ] **Decision note** (backend): a `note` column on `adjuster_decisions` with an in-place
      migration like Phase 2's `claim_type`; the decision route accepts it and a decline
      requires one; shown in the decision history and the claimant's notification.
- [ ] **"Worth checking" panel** -- moved into Phase 5: the intake review agent produces these
      findings (amount, date and claim-type mismatches, missing documents), each cited and
      checked by the gate. See Phase 5, step 5.3.
- [ ] **Claim timeline** on the review page, from the stored status history.
- [ ] **Search/filter beyond the basics** (date range, claim type) if the queue grows.

---

## Phase 2 -- Claim type at intake [x] done

Goal: let a claimant say what kind of claim this is, and let that shape what's asked for.

- [x] **Claim-type list:** `auto`, `property`, `health`, `theft`, `liability`, `other`. Maps
      cleanly to the existing `sample_data/` document types (police report -> auto, repair
      estimate -> property, injury notes -> health, theft report -> theft).
- [x] `claim_type` select on the submission form. A blank value becomes `other`, so scripts
      and older clients that never send the field still work; an unknown value is a `400`
      with the form re-shown, like the other validation errors.
- [x] Per-type document hints under the select, server-rendered and swapped on change. Hints
      only -- an auto claim with no police report is still `READY_FOR_REVIEW` (tested).
- [x] Schema: `claim_type TEXT NOT NULL DEFAULT 'other'`, with an in-place migration for
      existing databases (tested against a pre-claim-type database file). Shown on both claim
      pages, the claimant's list, and the adjuster queue.
- [x] The mock summary states the selected type on its own line, next to the incident types
      the extractor found in the text, so a mismatch (claimant picked Health, documents
      describe a collision) is visible side by side.
- [x] **Constraint held:** `main.py` / `test_main.py` untouched. The list and hints live in
      `validation.py`; `check_claim()` never sees the claim type.
- [x] Seed scenarios in `sample_data/claims.json` carry a claim type.
- [ ] Decide whether claim type later feeds the mock extractor's keyword list
      (`extraction.py`'s `INCIDENT_KEYWORDS`) -- e.g. skip "theft" matching on a health claim.
      Nice-to-have, not required for this phase.

---

## Phase 3 -- Notifications, for real [~] built and working locally; hosted rollout left

- [x] Notifications page polish. Each event shows **once**, with its channels as tags
      ("In-app", "Email (simulated)"), instead of one row per channel -- `_notify` logs every
      event on both channels, and the page used to list both rows as if they were two
      messages. Grouping is on the page only (`app._group_notifications`, consecutive rows
      with the same claim and message), so the stored log is unchanged. Relative timestamps
      ("2 hours ago", full timestamp on hover) here and in the bell; unread is a coral dot
      plus bold text instead of a filled background. Still open: grouping under per-claim
      headings, if the list gets long enough to need it.
- [x] **Email provider: Azure Communication Services Email.** Same Azure subscription already
      in use for the Web App, no new third-party account, pay-as-you-go pricing is
      effectively free at this project's demo volume.
- [~] **Real email delivery** for the `email` channel, behind a feature flag so the simulated
      path still works without the provider configured.
      **Built (first slice):** `email_delivery.py` with `EMAIL_PROVIDER` (`simulated` by
      default, or `acs`), `ACS_CONNECTION_STRING` and `EMAIL_SENDER_ADDRESS` as the settings
      (names only in the repo). `send_email()` returns `simulated`, `sent` or `failed` and
      never raises, so a failed email can't break filing a claim or recording a decision;
      errors are logged by type only, never with a connection string or body. The outcome is
      stored on the notification row (new `delivery` column, in-place migration like Phase
      2's) and the notifications page shows "Email sent", "Email failed" or "Email
      (simulated)" accordingly. The email carries only the status message and the claim
      number, no description or document text. Tested with a fake provider (default stays
      simulated and calls nothing; success; failure with no leak; misconfiguration; the
      migration). `MOCKS.md` and the README settings list are updated.
      **Still open, and these are outward-facing, so they need the owner:**
      - [x] Created the Azure resources in `harborclaim-rg`: Email Communication Service
            `harborclaim-email` with the free Azure managed domain, and Communication Service
            `harborclaim-comm` with that domain connected.
      - [x] `azure-communication-email==1.1.0` pinned in `requirements.txt`; `_send_via_acs`
            checked against the installed SDK (client, `begin_send`, message fields).
      - [x] First real send, locally (2026-10-18): a claim-filed email reached the owner's
            inbox and the row stored `sent`.
      - [x] Emails now carry a link to the claim (claimant: `/claims/<id>`, adjuster:
            `/adjuster/claims/<id>`) and a designed HTML version (`templates/email/`) next to
            the plain text. Links use `APP_BASE_URL`, or the request's own address locally.
      - [x] Adjuster email: `ADJUSTER_NOTIFY_EMAIL` (one inbox) is emailed when a claim is
            ready for review. Not logged as a notification row. Empty = nothing sent.
      - [x] Tests pin `EMAIL_PROVIDER=simulated` in `tests/conftest.py`, so a `.env` with real
            email on can't make the test suite send mail.
      - [ ] Decision email, adjuster email and the HTML design not yet seen in an inbox
            (waiting on Azure's sending limit to recover; one claim plus one decision sends
            three emails). Adjuster login for the decision: `local.reviewer`.
      - [ ] Hosted site: set the settings (`EMAIL_PROVIDER`, `ACS_CONNECTION_STRING`,
            `EMAIL_SENDER_ADDRESS`, `EMAIL_ENABLED`, `APP_BASE_URL`, `ADJUSTER_NOTIFY_EMAIL`)
            in the Azure Web App (start with `EMAIL_ENABLED=false`), push, Sync, smoke-test,
            then flip `EMAIL_ENABLED` to `true`. Also check `DEMO_ADJUSTER_USERNAME` and
            `DEMO_ADJUSTER_PASSWORD` exist there for the hosted adjuster login.
      - [x] Sending moved out of the request: the email row is stored as `queued`, the send
            runs as a FastAPI background task after the response, and records `sent` or
            `failed` (the page shows "Email sending" until then). Same for the adjuster email.
            A durable queue is still a Phase 4 matter: a background task is lost if the
            process restarts mid-send.
      - [x] `EMAIL_ENABLED=false` switch: keeps email simulated without removing the settings.
      - [x] Azure's free-domain sending limit was hit during testing (`429 TooManyRequests`);
            the log now records the status and code (no secrets). Wait out the limit and
            test sparingly.
- [x] In-app channel live updates: decided on plain polling, not websockets or push. The
      claimant's bell (`templates/_bell.html`) refreshes every 30 s while the tab is visible
      and the bell is closed, from `GET /notifications/bell` (`static/app.js`). Reasoning: a
      claim changes a few times over days, and the email reaches people who aren't on the
      site. The adjuster side has no bell, so nothing changed there. Seen working in a
      browser by the owner (2026-10-18).

---

## Phase 4 -- Azure production setup

- [ ] Flesh out Blob Storage, Document Intelligence, a queue, Key Vault, Azure SQL, and Entra
      ID for adjuster identity from a design into at least a partial build. Phase 5 needs none
      of them (it reads text PDFs with `pypdf`); Document Intelligence comes in only if
      scanned documents or photos need reading, and Key Vault is the natural next home for
      `OPENROUTER_API_KEY` and the other secrets.
- [ ] **Effect on the Phase 5 agents: none, by design.** Agents reach data only through
      `storage.py` (document text by claim and filename, not by path), and the intake review is
      a plain function of a claim ID that a queue worker can call instead of a background task.
      Swapping SQLite for Azure SQL and local uploads for Blob Storage changes `storage.py`
      only; `agent_runs` moves with the other tables. See AGENTS.md section 10.
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

## Phase 5 -- The agentic layer (real AI) [ ] planned, awaiting approval

Goal: three AI agents on one shared harness, each a draft-and-explain helper for a human,
none able to decide, pay or change a claim. **Full build reference:
[`docs/design/AGENTS.md`](docs/design/AGENTS.md)** (charters, tools, the gate, limits, labels,
storage, tests). HarborClaim is the final project (40%, due Nov 10), so this phase covers the
course outcome "build AI agents that automate financial workflows", not only the build
guide's optional bonus.

| Agent | Runs | Seen by | Job |
|---|---|---|---|
| 1. Intake review | Automatically, after each submit | Adjuster | Cited summary + "Worth checking" findings |
| 2. Adjuster assistant | When the adjuster asks | Adjuster | Answers about one claim's documents, with citations |
| 3. Claimant assistant | When the claimant asks | That claimant | Status, what's missing, which documents help |

Decisions already made (2026-10-18 to 10-24 planning sessions):

- **Agents, not a single summary call**, because it's the final project and outcome #2 is
  agents. One shared loop (the `analyst.py` pattern from Class 2), three charters.
- **The fixed parts stay fixed** (Class 7): `main.py` still routes; storing, extracting and the
  template draft still run in the request. Only the choice of checks, and answering questions,
  is agentic.
- **Read-only tools only; at most 3 model calls and 3 tool calls per run** (so the build guide's
  "three calls per request" holds under either reading); allowlist, argument checks and scope
  enforced in Python. No tool can approve, decline, pay, change status, or notify.
- **A deterministic gate (G1-G8)** checks every output before a human sees it: verbatim quotes,
  numbers tied to quotes, no decision/coverage/accusation phrases, claimant answers limited to
  their own claims, injected instructions flagged. Refusals are written by code, not the model.
- **Every guardrail is listed** in AGENTS.md section 8 (hard or soft, where enforced, which test
  proves it), and the terms are defined in section 0.
- **Design reviewed 2026-10-24** by an independent subagent against the real sample PDFs and the
  current code; its fixes are in AGENTS.md (section 14 lists them).
- **Provider: OpenRouter, one free model pinned by ID** (changed from Azure OpenAI on
  2026-10-24, owner's decision): $0, called with `httpx` (no OpenAI package or service), never the
  `openrouter/free` router. The model is chosen by testing (a probe, then a golden-set bake-off;
  AGENTS.md section 11.4). Document Intelligence not needed; Phase 4 is not a prerequisite.
- **Regex extraction stays** as the deterministic reference; its label stays "not AI".
- **Claimant pages never show AI findings or traces**; the claimant assistant has its own
  off-by-default switch (`AI_CLAIMANT_CHAT`).
- **Not agentic, on purpose:** routing, queue order, notifications, decisions, payments.

### Steps

Each step ends with the full suite passing (`python -m pytest -q`), the server restarted, and
the owner shown the result. Stop points marked **(demoable)** are complete projects if time
runs out.

**5.0 Before building** (owner)

- [x] Commit the uncommitted work first: done 2026-10-24, two local commits (`852e07b`,
      `7d1fe0c`), not pushed.
- [x] Provider and cost: OpenRouter, a free model, $0 (2026-10-24).
- [ ] Approve this plan.
- [ ] Owner puts `OPENROUTER_API_KEY` in `.env` (Claude never reads it). Other settings by name:
      `AI_PROVIDER`, `AI_ENABLED`, `AI_MODEL`, `AI_CLAIMANT_CHAT`, `AI_TIMEOUT_SECONDS`, and the
      per-agent daily limits. Check OpenRouter's current free rate limits.
- [ ] **Model probe, round 1** (AGENTS.md section 11.4): `scripts/model_probe.py` sends the same
      3 requests to each shortlisted free model (about 12 requests, $0; owner's go-ahead
      first), and the results pick the top two. Shortlist from the 2026-10-24 search:
      `google/gemma-4-31b-it:free`, `google/gemma-4-26b-a4b-it:free`,
      `nvidia/nemotron-3-super-120b-a12b:free`, `nvidia/nemotron-3.5-super-vl:free`.
- [x] Claimant assistant (5.6): decided 2026-10-24 to keep it, built last, after 5.5. The
      design review had recommended cutting it; it's the first thing dropped if time runs out.

**5.1 Groundwork** (no model call anywhere yet)

- [ ] Fix a bug the agents would inherit: two uploads with the same filename on one claim are
      stored as `name.pdf` and `name-2.pdf` on disk, but both rows keep the name `name.pdf`, so
      `get_document_path` always returns the first and the second file can't be opened.
      Store the de-duplicated name; regression test first.
- [ ] `extraction.py`: make the document reader public and page-aware, keeping `extract_facts`
      output identical; `storage.read_document_pages(claim_id, filename)` wraps it, so agents
      never handle file paths (ready for Blob Storage in Phase 4).
- [ ] `storage.py`: the `agent_runs` table (AGENTS.md section 10), its queries, `reset()`.
- [ ] `ai_client.py`: off by default, timeout, never raises; calls OpenRouter's
      `/chat/completions` endpoint with `httpx` (already in `requirements.txt`). No `openai`
      package, no new dependency.
- [ ] `tests/conftest.py`: pin `AI_PROVIDER`, `AI_ENABLED`, `AI_CLAIMANT_CHAT` to off.
- [ ] `.env.example` and README: the settings, names only.

**5.2 The shared harness, the tools and the gate** (fake client only)

- [ ] `agents.py`: the loop (AGENTS.md section 4): every tool call answered, allowlist,
      argument checks, 3 model calls and 3 tool calls (parallel calls counted), scope bound in
      Python, empty results valid, exceptions stop the run, per-agent daily limits, the trace,
      code-written refusals.
- [ ] `agent_tools.py`: the read-only tools for all three charters, deterministic Python.
- [ ] `agent_gate.py`: rules G1-G8 and the code-computed "Not summarised" / "Not read in full"
      lists.
- [ ] `tests/test_agents.py`: the offline tests in AGENTS.md section 11, using the real sample
      PDFs' text: limits, read-only proof, scope, one pass/fail per gate rule, the
      pressure-test case ($2,150 vs $2,500), the false-positive sentences, the injection
      document, `<script>` in model output.

- [ ] **Challenge 1 (independent subagent):** try to break the harness and gate before any agent
      is wired in: exceed the caps, call tools out of scope, slip invented numbers and quotes
      past G3/G4, false positives on G5, injection text. Every hole it finds becomes a failing
      test first, then a fix (AGENTS.md section 11.5).

**5.3 Agent 1: intake review** -- **(demoable)**

- [ ] Background task after `POST /claims` (the email pattern, a plain `def`); re-run button on
      the review page, refused only while a run is in progress; the page shows the latest
      finished run; a `running` row older than the timeout shows as unavailable.
- [ ] Adjuster review page: the "AI review" card (cited summary, "Worth checking", missing or
      unclear, not summarised, not read in full), the collapsible AI trace, the labels in
      AGENTS.md section 9, and the template card as the fallback. This builds Phase 1b's "Worth
      checking" panel.
- [ ] Claimant page unchanged (template draft only); a test proves no AI output reaches it.
- [ ] The build guide's three checks: normal, missing/ambiguous, injected model failure.

**5.4 Golden set, model bake-off and first live runs** (free quota; ask before each run)

- [ ] `sample_data/golden/`: six claims from new single-purpose `.txt` documents (AGENTS.md
      section 11), including the amount-conflict document for the pressure test.
- [ ] `scripts/eval_agents.py`: `--record` saves real responses to `tests/fixtures/ai/`; the
      default mode prints faithfulness, finding recall, false findings, violations and the
      not-summarised count.
- [ ] **Model bake-off, round 2:** `eval_agents.py --model` for the probe's top two models;
      pin the winner in `AI_MODEL`, record the runner-up as the fallback, both scorecards in
      `AI_USAGE.md`.
- [ ] First live run locally; fixtures replayed in the test suite; results, model, prompt
      version and one observed limitation recorded in `AI_USAGE.md`.

- [ ] **Challenge 2 (independent subagent):** review the live outputs, the chosen model's
      scorecard and the recorded fixtures; write new adversarial golden claims (injection
      variants, conflicting documents, near-miss quotes) and run them (free quota; owner's
      go-ahead). Findings recorded in `AI_USAGE.md`.

**5.5 Agent 2: adjuster assistant** -- **(demoable)**

- [ ] "Ask about this claim" form on the review page (`POST /adjuster/claims/{id}/ask`), three
      tools (`search_documents`, `read_document`, `get_intake_review`), last 5 questions with
      their traces, the "not in the records" answer, decision questions refused by code, 30
      questions per adjuster per day.
- [ ] Tests (fake client) and golden questions added to the eval.

**5.6 Agent 3: claimant assistant**

- [ ] `/help` page behind `AI_CLAIMANT_CHAT`, 20 questions per claimant per day, tools bound to
      the session email, fixed refusals for coverage/payout/decision questions.
- [ ] Tests: another claimant's claim ID returns "not found"; no facts, findings or traces ever
      appear; refusals.

**5.7 Documentation and screenshots**

- [ ] `MOCKS.md`, `docs/design/DESIGN.md` (components 3 and 5, pressure test marked built),
      README, `AI_USAGE.md`, new screenshots (AI review passed and flagged, trace open, both
      assistants, the fallback).

- [ ] **Challenge 3 (independent subagent), before code freeze:** a full review of Phase 5 as
      built against AGENTS.md: every guardrail in the register has its code and its test, labels
      are honest, claimant pages leak nothing, `main.py`/`test_main.py` untouched, no secrets in
      the repo. Blockers fixed before 5.8.

**5.8 Hosted rollout** (owner: outward-facing)

- [ ] Settings in the Azure Web App with `AI_ENABLED=false`, push, Sync, smoke test, then switch
      on. Claimant assistant on the hosted site only after the owner has tried it locally.

Timing follows "Plan to Nov 10" at the top of this file: 5.0-5.2 in spare evenings before
Nov 3 (no model calls, no cost), 5.3-5.4 on Nov 4-5, 5.5 on Nov 6, code freeze Nov 7 with
5.7-5.8. The claimant assistant (5.6) is the first thing cut if time runs short; 5.3 + 5.4
alone is a complete, demoable agentic project.

- [x] **UI labeling: no blunt "MOCK" wording in the results views.** The results-page badges
      and tags now read `"Automated draft -- not AI-generated"`, `"Automated extraction --
      not AI"`, and `"Email (simulated)"` -- same honest disclosure as before, without the
      alarming-sounding word. `MOCKS.md`'s fuller documentation of what's mocked and why is
      unchanged. Phase 5 changes a label only where AI really produced the content
      (AGENTS.md section 9).

---

## Handoff summary (read this first in a new session)

**What HarborClaim is.** An insurance claim intake system built for FIN 6934 (USF, AI in
Finance), Class 5 system-design studio, Assignment 7 -- and the owner's **Final Project**,
presented and submitted **Tue Nov 10, 2026** (see "Final project deadline" at the top). A claimant files a claim; a completeness
checker (`main.py`, the graded minimum) says `READY_FOR_REVIEW` or `NEEDS_INFORMATION`; mocked
extraction and summary stages produce a draft; a human adjuster reviews and records a decision;
the claimant is notified. Fictional demo data only. The owner is Asim Khan.

**How to run it locally**
- Run from this folder. Python is the shared venv at `claude-work/.venv`.
- Server: `python -m uvicorn app:app --port 8123`. **No `--reload`**: it didn't notice Python
  edits in this OneDrive folder and died mid-edit. Restart the server by hand after changing any
  `.py` file; templates and CSS/JS changes show on a refresh.
- Tests: `python -m pytest -q` from inside this folder (94 tests, about 45 s, includes the
  Playwright browser tests; `python -m playwright install chromium` once).
- Screenshots: `python scripts/capture_screenshots.py` regenerates all 14 in
  `docs/screenshots/` from a live instance.
- Tests and the screenshot script use a throwaway data folder (`HARBORCLAIM_DATA_DIR`, set in
  `tests/conftest.py` and at the top of the capture script), so they never touch `data/`. Safe
  to run while a dev server is up.
- A local adjuster: `python -c "import storage; print(storage.create_adjuster('local.reviewer', 'Local Reviewer'))"`
  prints a generated password. Demo claims: `python sample_data/seed_demo_data.py --reset --base-url http://127.0.0.1:8123`
  with the server running. Claimants sign in with real Google; the seeded claimants are fictional.

**Rules the owner set (keep following them)**
- Don't commit or push without asking. Deployment is a manual **Sync** in Azure's Deployment
  Center after pushing; pushing alone does not deploy.
- `main.py` and `test_main.py` stay untouched in every phase.
- Never read `.env` or Azure secrets. Setting names only, in docs.
- On product calls that cost something (a stricter form, a new Azure resource): recommend, then
  ask. The owner wants things to behave exactly as asked and has twice chosen the stricter form
  over a recommendation.

**Map of the code**
- `main.py` completeness checker; `validation.py` input rules, claim types, `validate_not_empty`;
  `storage.py` SQLite schema, in-place migrations, all queries; `auth.py` Google sign-in;
  `extraction.py` and `summary.py` the two mocked stages; `email_delivery.py` email behind a flag;
  `app.py` all routes plus the view helpers (`_group_facts`, `_group_notifications`,
  `_order_queue`, `static_url`, `time_ago`).
- `templates/`: claimant pages, adjuster pages, and partials (`_claimant_header`,
  `_adjuster_header`, `_facts_groups`, `_art` for the inline-SVG line art). No template branches
  on role; each role has its own pages.
- `static/`: `style.css` (design tokens; the adjuster dark theme is `body.adjuster-theme`),
  `claim_form.js` (readiness checklist, upload checks), `review.js` (decision confirm dialog),
  `app.js` (notification bell).
- `docs/design/`: `DESIGN.md` (architecture), `RESEARCH.md` (portal research, Lemonade pass).
  `MOCKS.md` says exactly what is mocked and why.

**Decisions already made, and why**
- FastAPI + Jinja2 is the primary build; the literal Streamlit minimum is a separate PR (Phase 0).
- Two roles with fully separate routes and separate login mechanisms (Google vs provisioned
  username/password); a claimant session never opens an adjuster page.
- Claimant side: Lemonade-inspired but its own (harbor coral, Fraunces titles, line art,
  conversational form). Adjuster side: deliberately plain and dark, a work tool.
- The claim form's submit button stays off until all five parts are in. The cost: the form can't
  produce `NEEDS_INFORMATION`; the server still accepts partial claims from scripts.
- "Needs more review" is not a final decision: it stays on the adjuster's list.
- Email: Azure Communication Services, behind a flag, simulated by default.
- Automated stages are always labelled ("Automated draft -- not AI-generated", "Automated
  extraction -- not AI", "Email (simulated)"). Keep that honesty when anything changes.

**Known gaps**
- `data/uploads/` holds about 1,000 orphan folders from test runs before the isolation change;
  harmless, safe to delete once the owner agrees.
- The local dev DB holds three empty claims from early testing; the owner hasn't said to delete
  them.
- Real email has never been run against Azure (Phase 3 open items).
- Policy IDs are free text: nothing checks they exist or belong to the claimant (idea: a policies
  table, Phase 4).
- Adjuster decisions carry no reason or note; there's no per-adjuster "seen" state.
- SQLite and local-disk uploads won't survive scaling or some redeploys (Phase 4).

**Next steps, in order**
1. Phase 1 is complete. Ask the owner whether to commit and push the uncommitted work, then Sync in Azure and smoke-test
   the live site (sign-in redirect, adjuster login, a claim end to end).
2. Finish Phase 3 with the owner: the Azure resource, the pinned package, a first real send.
3. Phase 5, the agentic layer: approve the plan (step 5.0), then build 5.1 onward. Full
   design in `docs/design/AGENTS.md`. Final project due Nov 10.
4. Phase 1b's decision note (schema change), if time allows.
5. Phase 4 (Azure storage and queue).
