# HarborClaim roadmap

Working doc for what's next. Decisions locked in on 2026-10-10:

- **Tech stack: keep FastAPI.** The build guide's own brief calls for Streamlit, but we're
  keeping FastAPI + Jinja2 as the primary stack for this project, documented with reasons (see
  Phase 0 below) rather than rebuilding everything to match the brief literally.
- **Completion and accuracy still matter.** Where the real build guide scores something
  specific that the FastAPI app doesn't present in that shape, we build the missing piece and
  add it -- we don't just document around the gap.
- **AI (Phase 5 below) stays last.** Everything else starts next session, in order.
- `main.py` / `test_main.py` (the graded minimum) stay untouched across every phase.

Status key: `[ ]` not started · `[~]` in progress · `[x]` done

Execution order for next session onward: **Phase 0 -> 1 -> 2 -> 3 -> 4 -> 5**. Phase 5 (AI) is
last on purpose, not by default.

- [x] **2026-10-11** -- README.md live-demo/Azure-deployment docs and this ROADMAP.md itself
      committed and pushed to `main` (`3f6d3bc`). Pre-Phase-0 housekeeping, not a roadmap item
      itself, but recorded here so a future session doesn't re-check it.

## Immediate priorities, in order (as of 2026-10-11)

These sit outside the Phase 0-5 structure below -- housekeeping/sequencing, not roadmap phases
-- but need to happen in this order before Phase 0's own PR goes out.

1. [x] Commit and push the README.md fixes and ROADMAP.md to the live repo. Done 2026-10-11,
       see the status line above (`3f6d3bc`, plus a follow-up `91f2e1a` for this file).
2. [x] **Rename the teacher-repo submission folder to `asim-khan`.** Done 2026-10-11 as a pure
       rename (49 files, 0 content changes) from
       `student-projects/harborclaim-insurance-intake-b41f7e2c/` to
       `student-projects/asim-khan/`, matching the other students' naming convention. Originally
       opened as its own PR (#10), then consolidated into #11, then #11 got accidentally
       auto-closed by GitHub (see item 3's note) -- final home is **PR #12**.
3. [x] **Start Phase 0.** Done 2026-10-11, consolidated with item 2 into a single PR --
       [**PR #12**](https://github.com/adnanmasood/fintech-samples/pull/12), two clean commits
       (`ad617f7` rename, `13a1715` Phase 0 addition), one descriptive PR body covering both.
       (History: opened separately as #10 + #11, consolidated into #11 alone, then renaming
       #11's source branch via GitHub's branch-rename API deleted the old ref, which GitHub
       read as "head branch deleted" and auto-closed #11 -- not recoverable via reopen. #12 is
       the same two commits, opened fresh from the renamed branch; #10 and #11 both carry
       comments pointing to it.) Adds `claim-intake-streamlit/`: `logic.py`, `app.py`,
       `tests/test_logic.py` (11/11 passing, the 8 build-guide-page-8 cases plus
       boundary/modification tests), real `screenshots/normal.png` + `failure.png` captured
       from the actual running app via a headless-Chromium session, `README.md`,
       `AI_USAGE.md`, `requirements.txt` (`streamlit==1.65.0`), `.gitignore`,
       `data/sample_claims.py`. Top-level README.md got a pointer to the subfolder; the "why
       FastAPI over the brief's Streamlit ask" reasoning itself is still a placeholder there --
       see the open question below, that one needs your voice.
4. [x] **Reset the stale `usf-fintech/` local clone.** Done 2026-10-11 -- confirmed the diff
       matched the known-stale state exactly (same 12 modified files, same untracked clutter),
       then `git checkout .` + `git clean -fd .`. Clean now.

---

## Phase 0 -- Close the spec-compliance gap (start here next session)

On 2026-10-10 the actual Assignment 7 build guide was read at full size for the first time.
Full transcription: `../teacher-notes/assignment-7-build-guide.md`. It specifies something
materially smaller and different from the FastAPI build: a one-screen Streamlit app
(`app.py` + `logic.py` + `tests/test_logic.py`), no database, no auth, no file uploads,
`check_claim(claim)` returning `{status, missing}` (a dict -- this resolves the old tuple-vs-dict
question from the course handoff; dict was already correct), two screenshots named exactly
`screenshots/normal.png` and `screenshots/failure.png`, and a specific required "small
modification" (a next-step message when `description` is missing).

**Where it goes -- corrected from an earlier version of this doc.** The guide's own page 9 says
to push an individually-owned repo named `usf-fintech-claim-intake`. That's not actually
necessary: `CONTRIBUTING.md` in the teacher's shared repo documents the fork-and-PR-into-
`student-projects/` workflow as the real submission mechanism, two classmates used it before us,
and the instructor already **merged PR #5** into
`student-projects/harborclaim-insurance-intake-b41f7e2c/`. A merge is stronger evidence than a
line in a slide deck. No new repo needed -- a new PR into that same, already-accepted folder.

**The one real wrinkle: a filename collision.** The existing submission folder already has an
`app.py` at its root (the FastAPI app). The guide's `app.py` is the Streamlit screen. These
can't share a root. Plan: put the compliant minimum in its own clearly named subfolder inside
the same project folder --
`student-projects/harborclaim-insurance-intake-b41f7e2c/claim-intake-streamlit/` -- so it stays
"one project folder" per `CONTRIBUTING.md`'s own rule, with its own `app.py`, `logic.py`,
`tests/test_logic.py`, `data/`, `screenshots/`, `README.md`, `AI_USAGE.md`. The top-level
README explains the relationship and the tech-stack decision below.

### Action items

- [ ] **Write the tech-stack-decision documentation.** Extend the existing "Tech stack, and
      why" section of the main `README.md` (it already argues FastAPI vs. Flutter/NestJS) to
      also address: the brief specified Streamlit; we kept FastAPI for the primary build for
      [reasons -- draft together next session: same-language reuse of `main.py`, the two-role
      auth/separation-of-duties design that a bare Streamlit screen can't express, etc.]; the
      `claim-intake-streamlit/` subfolder exists specifically to satisfy the brief's literal,
      scored shape without abandoning the larger build.
- [ ] **Build `logic.py`.** `check_claim` can likely be copied near-verbatim from `main.py` --
      the interface already matches (`{status, missing}`, same field order).
- [ ] **Build `app.py`.** One Streamlit screen: form in, result out, per the guide's page 2
      wireframes (normal case, failure case).
- [ ] **Build `tests/test_logic.py`.** The exact 8 cases from the guide's page 8, already
      transcribed in `teacher-notes/assignment-7-build-guide.md`.
- [ ] **Make the one required modification**: a human-readable next-step message when
      `description` is missing, kept test-covered -- the guide specifies this exact change, so
      no need to invent a different one.
- [ ] **Capture `screenshots/normal.png` and `screenshots/failure.png`** from the running
      Streamlit app.
- [ ] **Write the subfolder's own `README.md` and `AI_USAGE.md`**, matching the guide's
      required shape (setup/run/test commands, normal/failure examples, limits; prompts used,
      the modification, actual verification).
- [ ] **`requirements.txt`** pinned to the installed Streamlit version; **`.gitignore`** per the
      guide's list.
- [ ] **Open a new PR** into `adnanmasood/fintech-samples`, adding only this subfolder --
      same pattern as PR #5, scoped narrowly so it's easy to review.

---

## Phase 1 -- Visual redesign (no backend changes)

Goal: stop looking like a built-for-tests demo and start looking like a real insurance product.

- [ ] **Research pass first.** Before redesigning, pull reference screenshots from a handful of
      real claims-intake flows (e.g. Lemonade, Root, Progressive's claims portal, a couple of
      others) and note the patterns worth copying: centered single-column forms, a clear one-line
      value prop above the fold, progress/step indicators, trust signals near the submit button.
      Do this for **both** the claimant sign-in and the adjuster login -- they should still look
      deliberately different from each other (that's a real requirement, see
      `README.md`'s "Claimant and adjuster pages are fully separate routes"), just each one good
      on its own terms.
- [ ] **Fix the table overflow bug.** Long values (claimant email, description, filenames) break
      out of `table.claims-table` / `table.facts-table` cells right now. Needs `table-layout:
      fixed`, explicit column widths, `overflow-wrap`/`word-break` on text cells, and probably
      truncation with a title-attribute tooltip for the longest fields (description, email).
- [ ] **Typography and spacing overhaul.** Current look (`static/style.css`) uses IBM Plex Sans/
      Mono on a fairly bare grid. Decide: keep IBM Plex but fix scale/weight/spacing, or swap to
      something more SaaS-standard (Inter, Geist, etc.). Either way: consistent heading scale,
      consistent button/badge sizing, more breathing room in cards.
- [ ] **Notifications as a top-nav item**, not a plain text link. A bell icon with an unread-count
      badge and a dropdown preview is the common pattern; clicking through still goes to the full
      `/notifications` page.
- [ ] Re-screenshot everything in `docs/screenshots/` once the redesign lands -- the current set
      documents the *old* look.

---

## Phase 2 -- Claim type at intake

Goal: let a claimant say what kind of claim this is, and let that shape what's asked for.

- [x] **Claim-type list decided, 2026-10-11:** `auto`, `property`, `health`, `theft`,
      `liability`, `other` -- confirmed, no longer a guess. Maps cleanly to the existing
      `sample_data/` document types (police report -> auto, repair estimate -> property,
      injury notes -> health, theft report -> theft).
- [ ] Add a `claim_type` field to the submission form using the list above.
- [ ] Per-type document hints in the UI (e.g. auto -> "attach a police report if you have one";
      property -> "attach a repair estimate"). Hints only at first -- not a hard requirement,
      since `main.py`'s completeness rule (any non-empty `documents` list) can't change.
- [ ] Schema: add a `claim_type` column to the `claims` table (`storage.py`), migrate like the
      existing `claimant_email` migration pattern.
- [ ] **Constraint to hold the line on:** `main.py` / `test_main.py` is the graded minimum and
      must not change. Claim-type logic belongs in `app.py` / `validation.py` / the web layer, as
      an *addition* on top of `check_claim()`, never inside it.
- [ ] Decide whether claim type later feeds the mock extractor's keyword list (`extraction.py`'s
      `INCIDENT_KEYWORDS`) -- e.g. skip "theft" matching on a health claim. Nice-to-have, not
      required for this phase.

---

## Phase 3 -- Notifications, for real

- [ ] Notifications page polish: group by claim, relative timestamps ("2 hours ago"), clearer
      read/unread state than the current left-accent-bar treatment.
- [x] **Email provider decided, 2026-10-11: Azure Communication Services Email.** You asked for
      "any free provider" -- picked ACS over SendGrid/SES because it's the same Azure portal and
      subscription (Azure for Students) you're already using for the Web App, no new third-party
      account, and pay-as-you-go pricing is fractions of a cent per email at demo volume
      (effectively free for this project's scale). Setup, when this phase starts: provision an
      Email Communication Service + a verified sender domain (or use Azure's free
      `*.azurecomm.net` managed domain to skip DNS verification entirely for a demo), get a
      connection string, wire the send call behind a feature flag / env var so the mock `in_app`
      path still works without it configured.
- [ ] **Real email delivery** for the `email` channel, behind a feature flag / env var so the mock
      path still exists for anyone running this without the provider configured. Needs: the ACS
      connection string as another Azure app setting (same Credential-Materialization caution as
      the Google secrets -- I can wire the code, but moving the real connection string into Azure
      settings will hit the same sandbox block the Google secrets did, so that step will need to
      be yours).
- [ ] In-app channel: still just a logged row for now, unless we decide this phase also needs
      live updates (websocket/poll) instead of only-on-page-load.

---

## Phase 4 -- Azure production setup

- [x] **Re-read the teacher material we hadn't read yet.** Done 2026-10-10 -- see Phase 0
      above and `../teacher-notes/assignment-7-build-guide.md`. Turned out to be the Assignment
      7 build guide itself (not separate Azure setup notes as assumed) -- the "many other notes"
      were the exact data contract, test cases, and submission rubric, not infrastructure docs.
- [ ] Flesh out the Q3 peer-panel answer (Blob Storage, Document Intelligence, a queue, Key Vault,
      Azure SQL, Entra ID for adjuster identity) from a design into at least a partial build,
      starting with whichever piece Phase 5 needs first (likely Document Intelligence, since
      extraction is the first real-AI piece).
- [ ] Decide whether the Free F1 plan is enough once there's a queue + Document Intelligence in
      the mix, or whether this needs a paid tier -- F1 has no "Always On" and sleeps on idle,
      which is fine for a demo link but not for a queue worker.

### Long-term storage design (claims, documents, notifications)

Discussed 2026-10-10. The point of this section: the relational schema already in `storage.py`
is the right shape -- the fix is swapping its backend, not redesigning the data model.

- [ ] **Claims -> Azure SQL Database** (or Azure Database for PostgreSQL). SQLite is a single
      file on disk, which a redeploy, restart, or scaling to more than one instance can wipe or
      fragment -- fine for a demo, risky long-term. `list_claims_for(claimant_email)` already
      filters a claimant to only their own claims; that logic doesn't change. Mainly
      `storage.py`'s connection layer changes, from `sqlite3.connect()` to a real driver with a
      connection string held as another Azure app setting, same pattern as the Google secrets.
- [ ] **Documents -> Azure Blob Storage**, private container. Uploaded files currently land in
      `data/uploads/` on local disk, same durability problem as SQLite. The `documents` table
      already stores a path per file; that column starts holding a Blob reference instead of a
      local filesystem path, and downloads go through a short-lived signed URL instead of a
      local file read.
- [ ] **Notifications -> no schema change, just real delivery.** The `notifications` table
      already logs every event per claimant on two channels -- storage isn't the gap. The `email`
      channel is a logged row today, not an actually sent email; that's Phase 3's job (a real
      provider). The `in_app` channel could later get live updates (websocket or short poll)
      instead of only refreshing on page load -- nice-to-have, not broken today.
- [ ] **Net effect:** once Phase 4's database and Blob Storage pieces land, nothing about how a
      claimant sees their own claim history changes from their side -- it already works via
      `claimant_email` filtering. What changes is durability: their claims and documents survive
      restarts, redeploys, and scaling instead of depending on one server's local disk.

---

## Phase 5 -- Real AI (last on purpose)

Goal: replace the two mocked intelligence stages with the real thing, once everything else is in
better shape. This phase is **parked, not forgotten** -- it's here so it has a slot instead of
living only in `MOCKS.md`'s "what a real version would need" section.

- [ ] **Extraction**: a document-AI step (Azure Document Intelligence is the natural fit given the
      Azure direction) reading the actual uploaded file -- including images and scanned PDFs, not
      just the `.txt`/`.pdf` text layer `extraction.py` currently handles -- returning structured
      fields with confidence scores and page references, not a keyword hit.
- [ ] **Summary**: an LLM call grounded in the extracted facts and the retrieved document text,
      with inline citations back to the specific document and page a claim was drawn from, plus a
      way to flag when the generated text says something the source documents don't support (the
      exact failure mode the Design Deliverable's own pressure test asks about -- see Q6 in
      `../class-6-algorithms-fraud-responsible-ai/peer-panel-answers.md` for the worked example of
      this exact failure).
- [ ] **Model/provider decision, not yet made.** The Class 4 `.env`'s `OPENAI_API_KEY` is dead
      (needs a new key if we go that route). Azure OpenAI is the other natural fit given the
      deployment target. Worth deciding this alongside Phase 4's Azure work rather than in
      isolation.
- [x] **Labeling decided and shipped, 2026-10-11 -- option (c).** You called it: the badges
      shouldn't say the blunt word "MOCK" in the results UI. Reworded in place, same honest
      meaning, just not alarming-sounding: `"MOCK -- not AI-generated"` ->
      `"Automated draft -- not AI-generated"`, `"MOCK -- plain regex, not AI"` ->
      `"Automated extraction -- not AI"`, and the notification channel tag `"MOCK EMAIL"` ->
      `"Email (simulated)"`. Badge styling (muted amber, `.mock-tag`) left as-is -- it already
      wasn't alarming, just the word choice was. `MOCKS.md`'s fuller documentation of what's
      mocked and why is untouched -- this only changed the short in-UI badge text, not the
      honest-disclosure substance. Updated `tests/test_app.py` and `tests/test_ui.py` to match;
      38/38 + 5/5 passing.

---

## Open questions -- all resolved 2026-10-11

All five were live at once in the same session; none remain open as of this writing.

1. ~~Phase 0's exact wording for "why we kept FastAPI"~~ **Resolved:** the decision itself was
   never in question -- see the "Tech stack, and why" section's new "assignment brief's own
   stack choice" note in the teacher-repo submission's README (added via PR #12).
2. ~~Phase 5's labeling question (MOCK wording/styling)~~ **Resolved:** option (c), shipped --
   see Phase 5 above.
3. ~~Phase 2's exact claim-type list~~ **Resolved:** `auto`/`property`/`health`/`theft`/
   `liability`/`other`, confirmed -- see Phase 2 above.
4. ~~Phase 3's email provider choice~~ **Resolved:** Azure Communication Services Email --
   see Phase 3 above.
5. ~~Verify how the Azure demo actually auto-deploys~~ **Resolved** via
   `az webapp deployment source show` (not the portal): `isGitHubAction: false`,
   `isManualIntegration: true`, watching `i-asimkhan/harborclaim-insurance-intake` branch
   `main`. Confirmed: it's Azure App Service's own Kudu/SCM webhook-based continuous
   deployment, not GitHub Actions -- every push to `main` triggers a redeploy automatically,
   nothing to configure on the GitHub side.
