# Phase 1 research pass: real claims portals

Notes behind the Phase 1 visual redesign (see `ROADMAP.md`). The aim was to find patterns
real insurers and claims platforms use, then decide which ones fit HarborClaim. The claimant
side and the adjuster side were researched separately because they're meant to stay
different from each other (README: "Claimant and adjuster pages are fully separate routes").

**Method and limits.** These notes come from the insurers' public claims pages and, for the
adjuster side, from public documentation and vendor reviews. No screenshots were captured:
the claimant flows sit behind a policy login, Lemonade's claims page returned `403` to an
automated fetch, and adjuster workbenches (Guidewire ClaimCenter, Five Sigma) aren't public.
Lemonade's notes rely on secondary sources for that reason, and those sources describe
its *quote* funnel more than its claims flow. Researched October 2026.

## Claimant side

| Source | What it does | Pattern |
|---|---|---|
| [Root, claims page](https://joinroot.com/claims) | Headline "File a claim online or in the Root app", with "It takes about 3 minutes" directly under it. Three illustrated steps (answer questions, photograph the damage, Root contacts you), then a separate "What's next?" block. "File a claim" CTA repeated at the top and bottom. Says it emails the claimant at each step and status is always visible in the app. | One-line value prop + a time cost above the fold; numbered steps; tells you what happens *after* submitting; status updates at every step. |
| [Progressive, report a claim online](https://www.progressive.com/claims/online-claims/) | Log in, or continue as a guest. **Claim type first** (accident, glass, theft/vandalism, fire, weather), then date and location, then vehicles and people. Review before submit. Confirmation shows a **claim number**, followed by a secure link to upload photos and documents. "Track your claim online" lists what's visible afterwards: status, rep contact, payments, messaging. | Claim type as the first question; event before parties; review step; claim number front and center on the confirmation; tracking described as a feature. |
| [State Farm, auto claims](https://www.statefarm.com/claims/auto.html) | Start a claim online, in the app, or by phone around the clock. After filing, the account or app lets you check status, upload documents, message the claims team, and **get notifications**. | Notifications listed as part of the claim-tracking surface, next to status and documents. |
| Lemonade ([Invision on Lemonade's microcopy](https://invisionapp.com/blog/microcopy-best-practices), [claims page](https://www.lemonade.com/nl/en/claims)) | Conversational, one-question-per-screen, warm microcopy. Documented for the quote funnel; the claims flow starts from a "File a Claim" button and a free-text "what happened". | Plain-language labels and a friendly tone. One-question-per-screen is **not** adopted here (see below). |

### What HarborClaim takes from this

1. **Value prop and time cost above the fold** (Root). The signed-out page leads with a
   one-line promise and an honest effort estimate: four fields and your documents.
2. **"How it works" steps on the signed-out page** (Root, Progressive): tell us what happened,
   attach documents, get an instant completeness check, then an adjuster reviews.
3. **Grouped form sections** instead of a multi-screen wizard: "1 · About the incident"
   (claim type first, like Progressive) and "2 · Supporting documents". A real wizard would
   be a backend and flow change, which Phase 1 rules out, and with four fields the form fits
   on one screen anyway.
4. **Trust signals next to the submit button**: what happens next, who can see the documents,
   and that no coverage or payout decision is made at this step.
5. **Claim number prominent on the result page** (Progressive's confirmation), with the status
   badge beside it rather than buried in the card.
6. **Notifications as part of tracking** (Root, State Farm): a bell with an unread count in
   the top nav, not a plain text link.

## Adjuster side

| Source | What it shows | Pattern |
|---|---|---|
| Guidewire ClaimCenter ([application guide, Claim Summary screens](https://pdfcoffee.com/cc-appguide-pdf-free.html); [Olos release notes](https://docs.guidewire.com/cloud/olos/whatsnew/topics/cc-release_highlights.html)) | A **Desktop** of the adjuster's own work (activities, claims), a **Claim Summary** screen that gathers incident data, exposures, reserves and pending activities in one place, and a "Basics" section at the top of the summary overview. Newer releases add generative claim summarization as an early-access feature. | A work queue as the landing page; one summary screen with the basics first; actions ("activities") kept separate from read-only facts. |
| Five Sigma / Clive ([rfp.wiki vendor review](https://www.rfp.wiki/vendors/five-sigma)) | A "unified claim file" that consolidates notes, documents, communications and activity, plus task alerts so adjusters don't jump between systems. | One claim file screen; alerts surfaced where the adjuster already works. |
| Enterprise sign-in conventions (general) | Staff portals use a plain, narrow sign-in card, no marketing copy, and an authorized-use notice. | Stay deliberately unlike the consumer page. |

### What HarborClaim takes from this

1. **Queue as the Desktop.** Count tiles above the table (claims awaiting a decision, needing
   information from the claimant, decided), so the workload reads at a glance.
2. **Claim review as a two-column summary screen** on the wide page: the claim basics, the
   automated draft and the extracted facts on the left, and the **decision panel in a right
   rail** that sticks while scrolling. The decision no longer sits below a long facts table.
3. **Decision buttons that look different**: approve in green, decline in the warning color,
   "needs more review" as a neutral secondary button. All three were identical blue before.
4. **Adjuster bell = live "needs attention" count**, with the waiting claims as its dropdown
   preview. This matches what `/adjuster/notifications` already computes; there's still no
   per-adjuster "seen" state (README and `storage.claims_needing_adjuster_attention`).
5. **Adjuster login stays a narrow, dark, enterprise-style card** with an authorized-use
   notice. That notice is accurate: every sign-in is already written to the login audit log.

## Second pass: Lemonade's homepage

Lemonade's site blocks automated fetches, but it loaded in a headless browser, so this pass
is from its live homepage (screens and computed styles), October 2026:

- **One loud color, used sparingly.** Warm gray text (`#4a4a4a`) on white and `#f7f7f7`
  bands; hot pink appears only on the call to action (with a soft glow), the rating stars
  and a chat bubble.
- **A serif headline** (Merriweather, 55px, regular weight) over a sans body (Lato). The
  serif is what makes it feel human rather than like software.
- **Grayscale line-art illustrations** (houses, a car, a pet, a person on a bench) as the
  signature visual.
- **Space**: a centered single-column hero, borderless cards with large radii and soft
  shadows, alternating background bands.
- **Chat as a motif**: phone mockups with message bubbles.
- **Short, warm copy**: "Instant everything. Incredible prices. Big heart."

**Adopted for the claimant side:** all of the above, translated rather than copied: harbor
coral instead of Lemonade's pink, Fraunces instead of Merriweather, HarborClaim's own
harbor and lighthouse line art, and the claim form written as a conversation (questions in
bubbles, claim-type picture tiles) while staying one page with one submit.
**Not adopted:** the pink and the script logo (too close to Lemonade's identity), and the
testimonials, star ratings and press logos (fake trust signals in a demo). The adjuster side
stays deliberately plain: it's a work tool, not a consumer page.

## Not adopted, and why

- **One question per screen (Lemonade).** Considered again in the second pass and still not
  adopted: the conversational form keeps the feel without the extra clicks. It suits a long
  quote funnel, but HarborClaim's form has four fields. Splitting it up would add clicks without reducing effort, and it would mean
  changing the flow, which Phase 1 excludes.
- **Phone number, office hours, ratings badges, testimonials (Progressive, Root).** HarborClaim
  is a fictional demo, and invented contact details or social proof would be fake trust signals.
- **Guest filing without an account (Progressive).** Every claim is deliberately tied to a
  signed-in account (README, "Accounts and privacy").
