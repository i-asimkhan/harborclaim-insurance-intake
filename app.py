"""
HarborClaim -- Insurance Claim Intake System (web UI).

Front end for the pipeline described in the Design Deliverable. Every stage
is wired now: the completeness checker (main.py), input validation
(validation.py), document/evidence storage and a persistent claims database
(storage.py, SQLite), a MOCK fact extractor (extraction.py), a MOCK summary
generator (summary.py), adjuster review (a human decision), and a
notification stub (in-app + a MOCK "email" -- neither one sends anything
real). See MOCKS.md for exactly what's mocked and why.

Two account types, two completely separate login mechanisms -- see auth.py
and storage.py's module docstrings for why:
  - Claimants: sign in with Google (auth.py). First login *is* account
    creation. A claimant only ever sees their own claims.
  - Adjusters: a username and password provisioned by hand
    (storage.create_adjuster) at /adjuster/login. No Google involved, no
    sign-up form -- provisioning an adjuster is meant to happen only after
    a real state license is verified, outside this app entirely.

The two roles also never share a page. Every claimant-facing route lives
under /claims (or /, /notifications); every adjuster-facing route lives
under /adjuster/... There is no template, and no URL, that renders
differently depending on which role is looking at it -- a claimant session
grants zero access to any /adjuster/... route and vice versa, even for the
exact same claim_id. A browser can still hold both sessions at once
(different keys in the same cookie), but the pages themselves are entirely
separate code paths, not one shared view with role branches.

Run: uvicorn app:app --reload
"""

import html
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import storage
import agents
import ai_client
import consistency
import email_delivery
import privacy
from email_delivery import send_email
from auth import get_current_adjuster, get_current_user, router as auth_router
from extraction import extract_facts
from main import check_claim, READY_FOR_REVIEW, NEEDS_INFORMATION
from summary import generate_summary
from validation import (
    ALLOWED_EXTENSIONS,
    CLAIM_TYPES,
    DESCRIPTION_MAX_LENGTH,
    EARLIEST_INCIDENT_DATE,
    MAX_FILE_SIZE_BYTES,
    MAX_FILES,
    POLICY_ID_MAX_LENGTH,
    normalize_claim_type,
    validate_claim_fields,
    validate_claim_type,
    validate_files,
    validate_not_empty,
)

DECISIONS = ["APPROVED", "DECLINED", "NEEDS_MORE_REVIEW"]
FINAL_DECISIONS = {"APPROVED", "DECLINED"}
DECLINE_REASON_MIN_LENGTH = 10
DECISION_REASON_MAX_LENGTH = 1000


def _base_url(request: Request) -> str:
    """Absolute site address for links in emails. APP_BASE_URL (set on the hosted site, where
    the app sits behind a proxy) wins; locally the request's own address is right."""
    return (os.environ.get("APP_BASE_URL", "").strip() or str(request.base_url)).rstrip("/")


def _email_content(claim_id: str, heading: str, message: str, link: str, button: str) -> tuple[str, str]:
    """Plain-text and HTML versions of one notification email. Only the status message and
    the claim number go in -- no description, no document text."""
    text = "\n".join([message, "", f"Claim number: {claim_id}", f"{button}: {link}"])
    html = templates.get_template("email/notification.html").render(
        heading=heading, message=message, claim_id=claim_id, link=link, button=button,
    )
    return text, html


def _send_and_record(notification_id: int, to: str, subject: str, text: str, html: str) -> None:
    """Background task: send the email, then store what happened on its notification row."""
    storage.set_notification_delivery(notification_id, send_email(to, subject, text, html))


def _notify(claim_id: str, claimant_email: str, message: str, base_url: str,
            background: BackgroundTasks) -> None:
    """Record a notification on both channels (in-app and email).

    The in-app channel is a row the app shows. The email channel goes through
    email_delivery.send_email. When email is simulated the row is stored as such straight
    away; when it is real, the row is stored as "queued" and the send happens after the
    response has gone out (a background task), which then records "sent" or "failed" -- so the
    page never waits on Azure and always reports what really happened. A failed email never
    breaks the request: send_email can't raise. The email links to the claim and carries only
    the status message and the claim number.
    """
    storage.add_notification(claim_id, claimant_email, "in_app", message)
    subject = f"HarborClaim: update on claim {claim_id}"
    if email_delivery.provider() == email_delivery.SIMULATED:
        storage.add_notification(claim_id, claimant_email, "email", message)
        return
    text, html = _email_content(
        claim_id, "Claim update", message, f"{base_url}/claims/{claim_id}", "View your claim"
    )
    row_id = storage.add_notification(claim_id, claimant_email, "email", message, delivery="queued")
    background.add_task(_send_and_record, row_id, claimant_email, subject, text, html)


def _notify_adjusters(claim_id: str, claim_type: str, base_url: str, background: BackgroundTasks) -> None:
    """Email the adjusters' shared inbox (ADJUSTER_NOTIFY_EMAIL) that a claim is ready for
    review, after the response. Nothing happens when the setting is empty. Not logged as a
    notification row -- those belong to claimants -- and a failure is already logged by
    send_email."""
    to = os.environ.get("ADJUSTER_NOTIFY_EMAIL", "").strip()
    if not to:
        return
    message = f"A new {claim_type} claim is ready for review."
    text, html = _email_content(
        claim_id, "Ready for review", message, f"{base_url}/adjuster/claims/{claim_id}", "Open in review queue"
    )
    background.add_task(send_email, to, f"HarborClaim: claim {claim_id} ready for review", text, html)


def _start_intake_review(claim_id: str, background: BackgroundTasks) -> None:
    """Queue the AI intake review after the response (the email pattern). Nothing is queued when
    AI is off. The review only reads: it never changes the claim, its status or its routing."""
    if ai_client.enabled():
        background.add_task(agents.run_intake_review, claim_id)


# Why the page shows the template draft instead of an AI review, by the run's error type.
AI_UNAVAILABLE_REASONS = {
    "timeout": "the AI service didn't answer in time",
    "rate_limited": "the free AI service's request limit was reached",
    "http_error": "the AI service returned an error",
    "bad_response": "the AI service sent a reply that couldn't be read",
    "empty_reply": "the AI service sent an empty reply",
    "bad_config": "the AI settings are incomplete",
    "bad_output": "the AI's answer wasn't in the expected format",
    "tool_error": "a lookup failed during the review",
    "harness_error": "the review hit an internal error",
}


def _intake_stale_seconds() -> int:
    """How long a "running" intake review counts as in progress: the run's own timeout plus room
    to read the documents and check the answer. Older than that, it was lost (e.g. a restart)."""
    return ai_client.timeout_seconds() + 30


def _intake_review_view(claim_id: str) -> dict:
    """What the adjuster page shows for the AI intake review. Always from the latest *finished*
    run, so a re-run in progress never hides a result. The template draft stays the fallback."""
    run = storage.latest_finished_agent_run(claim_id, "intake")
    newest = storage.recent_agent_runs(claim_id, "intake", limit=1)
    running = storage.agent_run_in_progress(claim_id, "intake", _intake_stale_seconds())
    lost = bool(newest) and newest[0]["status"] == "running" and not running
    view = {"ai_on": ai_client.enabled(), "running": running, "run": None, "reason": None, "flagged": set()}

    if run and run["status"] in ("passed", "flagged") and run["output"]:
        view["run"] = run
        view["flagged"] = {r["where"] for r in (run["gate"] or {}).get("reasons", [])}
    elif running:
        pass
    elif lost:
        view["reason"] = "the last AI review didn't finish (the server may have restarted); re-run it"
    elif run:
        view["reason"] = AI_UNAVAILABLE_REASONS.get(run["error_type"], "the AI review was unavailable")
    elif not view["ai_on"]:
        view["reason"] = "AI review is off on this site"
    elif storage.agent_runs_today("intake") >= agents.CHARTERS["intake"].daily_limit():
        view["reason"] = "today's AI review limit is reached"
    else:
        view["reason"] = "no AI review has run for this claim yet"
    return view


def _ask_view(claim_id: str) -> dict:
    """The adjuster's last 5 questions about this claim, newest first, each with what to show:
    a cited AI answer, "not found", the fixed refusal, or why there was no answer."""
    items = []
    for run in storage.recent_agent_runs(claim_id, "adjuster", limit=5):
        out = run["output"] or {}
        if run["status"] == "refused" or out.get("refused"):
            kind = "refused"
        elif run["status"] == "running":
            kind = "running"
        elif run["status"] in ("passed", "flagged") and out.get("not_found"):
            kind = "not_found"
        elif run["status"] in ("passed", "flagged"):
            kind = "answer"
        else:
            kind = "unavailable"
        items.append({"run": run, "kind": kind,
                      "reason": AI_UNAVAILABLE_REASONS.get(run["error_type"], "the AI assistant was unavailable"),
                      "flagged": {r["where"] for r in (run["gate"] or {}).get("reasons", [])}})
    limit_reached = storage.agent_runs_today("adjuster") >= agents.CHARTERS["adjuster"].daily_limit()
    return {"ai_on": ai_client.enabled(), "limit_reached": limit_reached, "questions": items,
            "refusal": agents.ADJUSTER_REFUSAL, "not_found": agents.NOT_FOUND}


def _request_view(record: dict) -> dict:
    """The adjuster's "Request missing information" card: the draft to edit, and what was sent.

    The draft is the request agent's latest one when it passed the checks; otherwise the code
    template (from the completeness check alone), with the reason the AI draft isn't shown."""
    claim_id = record["claim"]["claim_id"]
    run = storage.latest_finished_agent_run(claim_id, "request")
    view = {"ai_on": ai_client.enabled(), "source": "template", "text": agents.template_request(record),
            "run": run, "note": None, "reasons": [],
            "limit_reached": storage.agent_runs_today("request") >= agents.CHARTERS["request"].daily_limit(),
            "sent": list(reversed(record["requests"])),
            "open": any(r["answered_at"] is None for r in record["requests"]),
            "final": bool(record["decisions"]) and record["decisions"][-1]["decision"] != "NEEDS_MORE_REVIEW"}
    if run is None:
        return view
    if run["status"] == "passed" and run["output"]:
        view.update(source="ai", text=agents.request_text(run["output"]))
    elif run["status"] == "flagged":
        view.update(note="The AI draft failed automated checks, so the template is shown instead.",
                    reasons=(run["gate"] or {}).get("reasons", []))
    else:
        view["note"] = "No AI draft: " + AI_UNAVAILABLE_REASONS.get(run["error_type"], "the AI assistant was unavailable") + "."
    return view


def _claimant_nav(claimant_email: str) -> dict:
    """Context for the claimant top nav's notification bell (_claimant_header.html).

    Every event is logged on both channels, so the bell counts and previews only
    the in_app rows -- one status change shows as one notification, not two.
    """
    in_app = [n for n in storage.list_notifications_for(claimant_email) if n["channel"] == "in_app"]
    return {
        "unread_count": sum(1 for n in in_app if not n["read_at"]),
        "notification_preview": in_app[:5],
        "help_on": _claimant_help_on(),
    }


def _claimant_help_on() -> bool:
    """The claimant assistant needs both switches: AI on, and AI_CLAIMANT_CHAT=true."""
    return ai_client.enabled() and agents.claimant_chat_enabled()


def _help_view(claimant_email: str) -> list[dict]:
    """The claimant's last 5 questions. Only an answer that passed the gate is shown; anything
    flagged or refused shows the fixed reply. No trace, gate reason or finding ever reaches here."""
    items = []
    for run in storage.recent_agent_runs_by(claimant_email, "claimant", limit=5):
        out = run["output"] or {}
        if run["status"] == "passed" and not out.get("refused") and isinstance(out.get("answer"), str):
            kind, text = "answer", out["answer"]
        elif run["status"] in ("refused", "flagged", "passed"):
            kind, text = "refused", agents.CLAIMANT_REFUSAL
        elif run["status"] == "running":
            kind, text = "running", "Answer in progress -- reload to see it."
        else:
            kind, text = "unavailable", "The assistant couldn't answer just now. Please try again later."
        items.append({"question": run["question"], "at": run["started_at"], "kind": kind, "text": text,
                      "model": run["model"]})
    return items


# Claimant view of extracted facts: one row per kind of fact, each distinct value
# shown once with every document it came from, instead of one table row per hit.
FACT_GROUPS = [
    ("incident_type", "What happened", "chat"),
    ("mentioned_amount", "Amounts mentioned", "money"),
    ("mentioned_date", "Dates mentioned", "calendar"),
]


def _amount_key(value: str) -> float:
    try:
        return float(value.replace("$", "").replace(",", ""))
    except ValueError:
        return 0.0


def _group_facts(facts: list[dict]) -> dict:
    groups = []
    for field, label, icon in FACT_GROUPS:
        values: dict[str, list[str]] = {}
        for f in facts:
            if f["field"] == field:
                sources = values.setdefault(f["value"], [])
                if f["source"] not in sources:
                    sources.append(f["source"])
        if not values:
            continue
        items = [{"value": v, "sources": src} for v, src in values.items()]
        if field == "mentioned_amount":
            items.sort(key=lambda i: _amount_key(i["value"]))
        elif field == "mentioned_date":
            items.sort(key=lambda i: i["value"])
        group_sources = []
        for item in items:
            group_sources += [s for s in item["sources"] if s not in group_sources]
        groups.append({"label": label, "icon": icon, "items": items, "sources": group_sources})
    unread = [f["source"] for f in facts if f["field"] == "document_not_processed"]
    return {"groups": groups, "unread_documents": unread}


def _group_notifications(rows: list[dict]) -> list[dict]:
    """One entry per event instead of one per channel row. _notify writes the
    same message on two channels back to back, so consecutive rows with the
    same claim and message (and a channel not already in the entry) are one
    event. Matching on adjacency, not exact timestamps: the two rows can land
    either side of a second boundary.
    """
    events: list[dict] = []
    for row in rows:
        last = events[-1] if events else None
        if (last and last["claim_id"] == row["claim_id"] and last["message"] == row["message"]
                and row["channel"] not in last["channels"]):
            last["channels"].append(row["channel"])
            last["unread"] = last["unread"] or not row["read_at"]
            if row["channel"] == "email":
                last["email_delivery"] = row["delivery"]
            continue
        events.append({
            "claim_id": row["claim_id"],
            "message": row["message"],
            "created_at": row["created_at"],
            "channels": [row["channel"]],
            "unread": not row["read_at"],
            "email_delivery": "simulated",
        })
        last = events[-1]
        if row["channel"] == "email":
            last["email_delivery"] = row["delivery"]
    for event in events:
        event["channels"].sort(key=lambda c: c != "in_app")  # in-app first
        if event["email_delivery"] == "queued" and _older_than(event["created_at"], QUEUED_STALE_MINUTES):
            event["email_delivery"] = "unconfirmed"
    return events


# A real send settles within seconds. A row still "queued" after this long was most likely cut
# off by a restart, so the page says "not confirmed" rather than claiming it is still sending.
QUEUED_STALE_MINUTES = 10


def _older_than(iso: str, minutes: int) -> bool:
    try:
        then = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return False
    return (datetime.now(timezone.utc) - then).total_seconds() > minutes * 60


QUEUE_VIEWS = {
    "all": "All claims",
    "awaiting": "Awaiting a decision",
    "waiting": "Waiting on claimant",
    "decided": "Decided",
}


def _open_findings(record: dict) -> list[str]:
    """What the review still has open: the code's consistency checks, plus the latest finished AI
    intake review's "worth checking" and "missing or unclear" items. Approving over any of them
    needs an explicit acknowledgement. The code checks count even when the AI is off."""
    findings = [c["finding"] for c in consistency.check(record)]
    run = storage.latest_finished_agent_run(record["claim"]["claim_id"], "intake")
    output = (run or {}).get("output") or {}
    if (run or {}).get("status") in ("passed", "flagged"):
        findings += [f.get("finding", "") for f in output.get("worth_checking") or [] if isinstance(f, dict)]
        findings += [m for m in output.get("missing_or_unclear") or [] if isinstance(m, str)]
    return [f for f in findings if f.strip()]


def _display_status(record: dict) -> str:
    """The one status a person should see for a claim: its latest decision once there is one,
    otherwise its intake status. claims.status stays the intake (completeness) status, which the
    queue and the bell filter on, so decisions are layered on top here instead of written into it.
    """
    return record["decisions"][-1]["decision"] if record["decisions"] else record["status"]


def _queue_category(record: dict) -> str:
    """Where a claim sits in the queue, by its *latest* decision: Approved or Declined
    finishes it, but "Needs more review" means the adjuster still has to act, so it stays
    with the claims awaiting a decision (the same rule as the bell, in storage).
    """
    latest = record["decisions"][-1]["decision"] if record["decisions"] else None
    if latest and latest != "NEEDS_MORE_REVIEW":
        return "decided"
    return "awaiting" if record["status"] == READY_FOR_REVIEW else "waiting"


def _order_queue(records: list[dict]) -> list[dict]:
    """Work first: claims awaiting a decision (oldest first, so nothing sits
    unnoticed), then claims waiting on the claimant, then decided ones (newest first).
    """
    buckets: dict[str, list[dict]] = {"awaiting": [], "waiting": [], "decided": []}
    for record in records:
        buckets[_queue_category(record)].append(record)
    filed = lambda r: r["history"][0]["at"]
    return (
        sorted(buckets["awaiting"], key=filed)
        + sorted(buckets["waiting"], key=filed, reverse=True)
        + sorted(buckets["decided"], key=filed, reverse=True)
    )


def _queue_matches(record: dict, query: str) -> bool:
    """Every word typed must appear somewhere in claim ID, claimant, policy or type."""
    claim = record["claim"]
    type_label = CLAIM_TYPES[claim["claim_type"]][0] if claim["claim_type"] in CLAIM_TYPES else claim["claim_type"]
    haystack = " ".join(
        [claim["claim_id"], claim["claimant_email"] or "", claim["policy_id"] or "", type_label]
    ).lower()
    return all(term in haystack for term in query.lower().split())


def _adjuster_nav() -> dict:
    """Context for the adjuster top nav's bell (_adjuster_header.html): the same
    live "needs attention" list the queue and /adjuster/notifications compute.
    """
    return {"needs_attention": storage.claims_needing_adjuster_attention()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
    demo_username = os.environ.get("DEMO_ADJUSTER_USERNAME")
    demo_password = os.environ.get("DEMO_ADJUSTER_PASSWORD")
    if demo_username and demo_password:
        if storage.get_adjuster(demo_username) is None:
            storage.create_adjuster(demo_username, "Demo Adjuster", password=demo_password)
        else:
            # Re-sync on every restart rather than only creating once -- lets
            # the demo password be rotated just by changing the App Service
            # setting and restarting, no shell or manual DB edit needed.
            storage.reset_adjuster_password(demo_username, demo_password)
    yield


app = FastAPI(title="HarborClaim -- Claim Intake", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET_KEY", "dev-only-insecure-key-change-me"),
)
app.include_router(auth_router)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["CLAIM_TYPES"] = CLAIM_TYPES
# Browser-side input limits on the claim form mirror validation.py's server-side
# ones, so both always agree. The server checks still run on every submission.
templates.env.globals["LIMITS"] = {
    "policy_id_max": POLICY_ID_MAX_LENGTH,
    "description_max": DESCRIPTION_MAX_LENGTH,
    "earliest_date": EARLIEST_INCIDENT_DATE.isoformat(),
    "max_files": MAX_FILES,
    "max_file_bytes": MAX_FILE_SIZE_BYTES,
    "extensions": sorted(ALLOWED_EXTENSIONS),
}
templates.env.globals["today_iso"] = lambda: date.today().isoformat()

STATIC_DIR = Path(__file__).parent / "static"


def static_url(path: str) -> str:
    """/static/<path>?v=<mtime>, so a browser never keeps using a stale cached
    stylesheet or script after the file changes (the dev server isn't restarted
    for CSS/JS edits, so this is computed per render, not once at startup)."""
    try:
        version = int((STATIC_DIR / path).stat().st_mtime)
    except OSError:
        version = 0
    return f"/static/{path}?v={version}"


def time_ago(iso: str) -> str:
    """"just now", "5 minutes ago", "yesterday", ... for an ISO timestamp; older
    than a week falls back to the date itself."""
    try:
        then = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso
    seconds = int((datetime.now(timezone.utc) - then).total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    return then.date().isoformat()


templates.env.globals["static_url"] = static_url
templates.env.filters["ago"] = time_ago

# What a person reads for a status or decision code. The codes stay in the data, the forms and
# the API; pages show these.
STATUS_LABELS = {
    "READY_FOR_REVIEW": "Ready for review",
    "NEEDS_INFORMATION": "Needs information",
    "NEEDS_MORE_REVIEW": "Needs more review",
    "APPROVED": "Approved",
    "DECLINED": "Declined",
}
templates.env.filters["status_label"] = lambda code: STATUS_LABELS.get(code, str(code).replace("_", " ").capitalize())


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> HTMLResponse:
    """Catches anything that isn't already a handled response. The traceback
    goes to the server console (uvicorn's own logging does this automatically
    when the exception propagates past this handler's logging call below) --
    never to the response body, the same "no stack traces to the user" rule
    a classmate's submission used for the same reason.
    """
    import logging
    logging.getLogger("uvicorn.error").exception("Unhandled error on %s %s", request.method, request.url.path)
    return HTMLResponse(
        "<h1>500 Something went wrong</h1><p>That wasn't supposed to happen. Nothing was leaked "
        "about what failed -- check the server console for the real error.</p>",
        status_code=500,
    )


def _forbidden(message: str) -> HTMLResponse:
    return HTMLResponse(f"<h1>403 Forbidden</h1><p>{message}</p>", status_code=403)


def _bad_request(errors: list[str]) -> HTMLResponse:
    # Messages can carry a filename the user chose, so they're escaped.
    items = "".join(f"<li>{html.escape(e)}</li>" for e in errors)
    return HTMLResponse(f"<h1>400 Invalid submission</h1><ul>{items}</ul>", status_code=400)


# ---------------------------------------------------------------------------
# Claimant-facing routes -- everything under /, /claims, /notifications.
# None of these ever accept an adjuster-only session as sufficient access.
# ---------------------------------------------------------------------------

@app.get("/")
def home(
    request: Request,
    user: dict | None = Depends(get_current_user),
    adjuster: dict | None = Depends(get_current_adjuster),
):
    if user is None:
        return templates.TemplateResponse(request, "signed_out.html", {"adjuster": adjuster})
    return templates.TemplateResponse(
        request,
        "index.html",
        {"user": user, "adjuster": adjuster, "active": "new", **_claimant_nav(user["email"])},
    )


@app.post("/claims")
async def submit_claim(
    request: Request,
    background: BackgroundTasks,
    policy_id: str = Form(""),
    incident_date: str = Form(""),
    description: str = Form(""),
    claim_type: str = Form(""),
    files: list[UploadFile] = File([]),
    user: dict | None = Depends(get_current_user),
):
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=303)

    # An empty <input type="file" multiple> still submits one UploadFile with
    # filename == "" -- drop those before they count as a real document.
    uploads = [f for f in files if f.filename]

    claim_type = normalize_claim_type(claim_type)
    errors = validate_claim_type(claim_type)
    errors += validate_claim_fields(policy_id, incident_date, description)
    errors += validate_not_empty(policy_id, incident_date, description, len(uploads))
    # Validate the uploads as one batch: validate_files' file-count limit only
    # works if it sees every file at once, not one single-file list per upload.
    files_and_sizes = []
    for upload in uploads:
        upload.file.seek(0, 2)  # seek to end to get size without reading content twice
        files_and_sizes.append((upload.filename, upload.file.tell()))
        upload.file.seek(0)
    errors.extend(validate_files(files_and_sizes))
    if errors:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "user": user,
                "adjuster": None,
                "active": "new",
                **_claimant_nav(user["email"]),
                "errors": errors,
                "form": {
                    "policy_id": policy_id,
                    "incident_date": incident_date,
                    "description": description,
                    "claim_type": claim_type,
                },
            },
            status_code=400,
        )

    claim_id = f"CLM-{uuid.uuid4().hex[:8].upper()}"
    document_names = [f.filename for f in uploads]

    claim = {
        "claim_id": claim_id,
        "policy_id": policy_id,
        "incident_date": incident_date,
        "description": description,
        "documents": document_names,
    }
    result = check_claim(claim)

    storage.create_claim(
        claim_id=claim_id,
        claimant_email=user["email"],
        policy_id=policy_id,
        incident_date=incident_date,
        description=description,
        status=result["status"],
        missing=result["missing"],
        claim_type=claim_type,
    )

    stored_documents = []
    for upload in uploads:
        content = await upload.read()
        stored_path = storage.save_uploaded_file(claim_id, upload.filename, content)
        # Record the name the file was actually saved under: a second "photo.jpg" is saved as
        # "photo-2.jpg", and every later lookup (downloads, citations) is by this name.
        storage.add_document(
            claim_id=claim_id,
            filename=stored_path.name,
            stored_path=stored_path,
            content_type=upload.content_type,
            size_bytes=len(content),
        )
        stored_documents.append(
            {"filename": stored_path.name, "stored_path": stored_path, "content_type": upload.content_type}
        )
    document_names = [d["filename"] for d in stored_documents]

    # Pipeline continues past the completeness check regardless of status --
    # even an incomplete claim gets whatever can be extracted from what it
    # does have, so an adjuster (or the claimant, on request) sees the same
    # draft a complete claim would get once the missing pieces arrive.
    facts = extract_facts(description, stored_documents)
    if facts:
        storage.add_facts(claim_id, facts)
    summary_text = generate_summary(
        {"policy_id": policy_id, "incident_date": incident_date, "description": description,
         "documents": document_names, "claim_type": claim_type},
        facts,
    )
    storage.add_summary(claim_id, summary_text)

    if result["status"] == NEEDS_INFORMATION:
        message = f"We still need: {', '.join(result['missing'])}. Please add these to your claim."
    else:
        message = "Your claim is complete and has been routed to an adjuster for review."
    base_url = _base_url(request)
    _notify(claim_id, user["email"], message, base_url, background)
    if result["status"] != NEEDS_INFORMATION:
        _notify_adjusters(claim_id, claim_type, base_url, background)
    _start_intake_review(claim_id, background)

    return RedirectResponse(url=f"/claims/{claim_id}", status_code=303)


@app.get("/claims/{claim_id}")
def view_claim(request: Request, claim_id: str, user: dict | None = Depends(get_current_user)):
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=303)

    record = storage.get_claim(claim_id)
    if record is None:
        return templates.TemplateResponse(
            request, "not_found.html", {"claim_id": claim_id}, status_code=404
        )
    if record["claim"]["claimant_email"] != user["email"]:
        return _forbidden("This claim belongs to a different account.")

    return templates.TemplateResponse(
        request,
        "claim_view.html",
        {
            "record": record,
            "user": user,
            "READY_FOR_REVIEW": READY_FOR_REVIEW,
            "NEEDS_INFORMATION": NEEDS_INFORMATION,
            "facts_view": _group_facts(record["facts"]),
            **_claimant_nav(user["email"]),
        },
    )


@app.post("/claims/{claim_id}/documents")
async def add_claim_documents(
    request: Request,
    background: BackgroundTasks,
    claim_id: str,
    note: str = Form(""),
    files: list[UploadFile] = File([]),
    user: dict | None = Depends(get_current_user),
):
    """The claimant's answer to a request for information: more documents and/or a note. The
    claim is checked again, and with new documents the AI intake review runs again, so the
    adjuster sees a review that includes them."""
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=303)
    record = storage.get_claim(claim_id)
    if record is None:
        return templates.TemplateResponse(request, "not_found.html", {"claim_id": claim_id}, status_code=404)
    if record["claim"]["claimant_email"] != user["email"]:
        return _forbidden("This claim belongs to a different account.")
    if record["decisions"] and record["decisions"][-1]["decision"] != "NEEDS_MORE_REVIEW":
        return _forbidden("This claim already has a final decision.")

    uploads = [f for f in files if f.filename]
    note = note.strip()
    errors = []
    if not uploads and not note:
        errors.append("Add at least one document or a note for your adjuster.")
    if len(note) > 1000:
        errors.append("The note can be at most 1,000 characters.")
    files_and_sizes = []
    for upload in uploads:
        upload.file.seek(0, 2)
        files_and_sizes.append((upload.filename, upload.file.tell()))
        upload.file.seek(0)
    errors += validate_files(files_and_sizes)
    if len(record["documents"]) + len(uploads) > MAX_FILES:
        errors.append(f"Too many files (max {MAX_FILES} per claim).")
    if errors:
        return _bad_request(errors)

    stored = []
    for upload in uploads:
        content = await upload.read()
        stored_path = storage.save_uploaded_file(claim_id, upload.filename, content)
        storage.add_document(claim_id=claim_id, filename=stored_path.name, stored_path=stored_path,
                             content_type=upload.content_type, size_bytes=len(content))
        stored.append({"filename": stored_path.name, "stored_path": stored_path, "content_type": upload.content_type})
    facts = extract_facts("", stored)
    if facts:
        storage.add_facts(claim_id, facts)

    record = storage.get_claim(claim_id)
    claim = record["claim"]
    result = check_claim({"claim_id": claim_id, "policy_id": claim["policy_id"], "incident_date": claim["incident_date"],
                          "description": claim["description"], "documents": claim["documents"]})
    storage.answer_info_requests(claim_id, note)
    storage.set_claim_status(claim_id, result["status"], result["missing"])
    if stored:
        storage.add_summary(claim_id, generate_summary(
            {"policy_id": claim["policy_id"], "incident_date": claim["incident_date"], "description": claim["description"],
             "documents": claim["documents"], "claim_type": claim["claim_type"]}, record["facts"]))

    base_url = _base_url(request)
    if result["status"] == NEEDS_INFORMATION:
        message = f"Thanks, we've added your update. We still need: {', '.join(result['missing'])}."
    else:
        message = "Thanks, we've added your update. Your claim is back with your adjuster for review."
        _notify_adjusters(claim_id, claim["claim_type"], base_url, background)
    _notify(claim_id, user["email"], message, base_url, background)
    if stored:
        _start_intake_review(claim_id, background)
    return RedirectResponse(url=f"/claims/{claim_id}", status_code=303)


@app.get("/claims/{claim_id}/documents/{filename}")
def download_document(claim_id: str, filename: str, user: dict | None = Depends(get_current_user)):
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=303)

    record = storage.get_claim(claim_id)
    if record is None or record["claim"]["claimant_email"] != user["email"]:
        return _forbidden("This document belongs to a different account's claim.")

    path = storage.get_document_path(claim_id, filename)
    if path is None:
        return RedirectResponse(url=f"/claims/{claim_id}", status_code=303)
    return FileResponse(path, filename=filename)


@app.get("/claims")
def list_claims(request: Request, user: dict | None = Depends(get_current_user)):
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "list.html",
        {
            "claims": storage.list_claims_for(user["email"]),
            "user": user,
            "active": "claims",
            **_claimant_nav(user["email"]),
        },
    )


@app.get("/notifications/bell")
def notification_bell(request: Request, user: dict | None = Depends(get_current_user)):
    """Just the bell, for static/app.js to poll. 204 (not a redirect) when signed out, so the
    script quietly stops instead of swapping a login page into the nav."""
    if user is None:
        return Response(status_code=204)
    response = templates.TemplateResponse(request, "_bell.html", _claimant_nav(user["email"]))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/notifications")
def notifications(request: Request, user: dict | None = Depends(get_current_user)):
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=303)

    items = storage.list_notifications_for(user["email"])
    storage.mark_notifications_read(user["email"])
    return templates.TemplateResponse(
        request,
        "notifications.html",
        {"events": _group_notifications(items), "user": user, **_claimant_nav(user["email"])},
    )


@app.get("/help")
def claimant_help(request: Request, user: dict | None = Depends(get_current_user)):
    """The claimant assistant: questions about the signed-in claimant's own claims only."""
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=303)
    if not _claimant_help_on():
        return RedirectResponse(url="/claims", status_code=303)
    left = agents.claimant_questions_left(user["email"])
    return templates.TemplateResponse(
        request, "help.html",
        {"user": user, "questions": _help_view(user["email"]), "limit_reached": left == 0,
         "questions_left": left, "active": "help", **_claimant_nav(user["email"])},
    )


@app.post("/help")
def claimant_ask(question: str = Form(""), user: dict | None = Depends(get_current_user)):
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=303)
    question = question.strip()
    if question and _claimant_help_on():
        agents.ask_claimant(user["email"], question)
    return RedirectResponse(url="/help", status_code=303)


# ---------------------------------------------------------------------------
# Adjuster-facing routes -- everything under /adjuster/... None of these
# ever accept a claimant session as sufficient access, even for a claim that
# session's own account filed.
# ---------------------------------------------------------------------------

@app.get("/adjuster")
def adjuster_queue(
    request: Request,
    view: str = "all",
    q: str = "",
    adjuster: dict | None = Depends(get_current_adjuster),
):
    if adjuster is None:
        return RedirectResponse(url="/adjuster/login", status_code=303)

    if view not in QUEUE_VIEWS:
        view = "all"
    query = q.strip()
    ordered = _order_queue(storage.list_claims())
    counts = {key: 0 for key in QUEUE_VIEWS}
    for record in ordered:
        counts["all"] += 1
        counts[_queue_category(record)] += 1
    shown = [
        r for r in ordered
        if (view == "all" or _queue_category(r) == view) and (not query or _queue_matches(r, query))
    ]

    return templates.TemplateResponse(
        request,
        "adjuster_queue.html",
        {
            "claims": shown,
            "total": counts["all"],
            "counts": counts,
            "views": QUEUE_VIEWS,
            "view": view,
            "q": query,
            "adjuster": adjuster,
            "active": "queue",
            **_adjuster_nav(),
            "READY_FOR_REVIEW": READY_FOR_REVIEW,
        },
    )


@app.get("/adjuster/claims/{claim_id}")
def adjuster_view_claim(request: Request, claim_id: str, adjuster: dict | None = Depends(get_current_adjuster)):
    if adjuster is None:
        return RedirectResponse(url="/adjuster/login", status_code=303)

    record = storage.get_claim(claim_id)
    if record is None:
        return templates.TemplateResponse(
            request, "not_found.html", {"claim_id": claim_id}, status_code=404
        )

    return templates.TemplateResponse(
        request,
        "adjuster_claim_view.html",
        {
            "record": record,
            "adjuster": adjuster,
            "decisions": DECISIONS,
            "display_status": _display_status(record),
            "open_findings": _open_findings(record),
            "code_checks": consistency.check(record),
            "facts_view": _group_facts(record["facts"]),
            "ai_review": _intake_review_view(claim_id),
            "ai_ask": _ask_view(claim_id),
            "info_request": _request_view(record),
            **_adjuster_nav(),
            "READY_FOR_REVIEW": READY_FOR_REVIEW,
            "NEEDS_INFORMATION": NEEDS_INFORMATION,
        },
    )


@app.post("/adjuster/claims/{claim_id}/intake-review")
def rerun_intake_review(claim_id: str, background: BackgroundTasks,
                        adjuster: dict | None = Depends(get_current_adjuster)):
    """Re-run the AI intake review. Refused (a plain redirect back) while one is in progress or
    when AI is off. It only reads the claim; nothing about the claim changes."""
    if adjuster is None:
        return RedirectResponse(url="/adjuster/login", status_code=303)
    if storage.get_claim(claim_id) is None:
        return RedirectResponse(url="/adjuster", status_code=303)
    if not storage.agent_run_in_progress(claim_id, "intake", _intake_stale_seconds()):
        _start_intake_review(claim_id, background)
    return RedirectResponse(url=f"/adjuster/claims/{claim_id}", status_code=303)


@app.post("/adjuster/claims/{claim_id}/ask")
def ask_about_claim(claim_id: str, question: str = Form(""),
                    adjuster: dict | None = Depends(get_current_adjuster)):
    """Answer one adjuster question about this claim (waits for the answer, then back to the page).
    Read-only; decision and coverage questions get the fixed refusal from code, no model call."""
    if adjuster is None:
        return RedirectResponse(url="/adjuster/login", status_code=303)
    if storage.get_claim(claim_id) is None:
        return RedirectResponse(url="/adjuster", status_code=303)
    question = question.strip()
    if question and ai_client.enabled():
        agents.ask_adjuster(claim_id, adjuster["username"], question)
    return RedirectResponse(url=f"/adjuster/claims/{claim_id}#ask", status_code=303)


def _conflict_of_interest(adjuster: dict, record: dict) -> bool:
    """Separation of duties: an adjuster linked to the claimant who filed this claim can't act on it."""
    return bool(adjuster["linked_claimant_email"]) and adjuster["linked_claimant_email"] == record["claim"]["claimant_email"]


@app.post("/adjuster/claims/{claim_id}/request/draft")
def draft_request(claim_id: str, adjuster: dict | None = Depends(get_current_adjuster)):
    """Ask the request agent for a draft (waits for it, up to a minute). Drafting changes nothing."""
    if adjuster is None:
        return RedirectResponse(url="/adjuster/login", status_code=303)
    if storage.get_claim(claim_id) is None:
        return RedirectResponse(url="/adjuster", status_code=303)
    if ai_client.enabled():
        agents.draft_info_request(claim_id, adjuster["username"])
    return RedirectResponse(url=f"/adjuster/claims/{claim_id}#request", status_code=303)


@app.post("/adjuster/claims/{claim_id}/request/send")
def send_info_request(request: Request, background: BackgroundTasks, claim_id: str, message: str = Form(""),
                      source: str = Form(""), adjuster: dict | None = Depends(get_current_adjuster)):
    """The one action in the agentic workflow, and a human takes it: the adjuster's edited request
    goes to the claimant, and the claim waits on them (NEEDS_INFORMATION) until they answer."""
    if adjuster is None:
        return RedirectResponse(url="/adjuster/login", status_code=303)
    record = storage.get_claim(claim_id)
    if record is None:
        return RedirectResponse(url="/adjuster", status_code=303)
    if _conflict_of_interest(adjuster, record):
        return _forbidden("Separation of duties: this adjuster account is linked to the claimant who filed this claim.")
    message = message.strip().replace("\r\n", "\n")
    if not message or len(message) > 2000:
        return _bad_request(["The request needs a message of at most 2,000 characters."])
    view = _request_view(record)
    if view["final"]:
        return _forbidden("A final decision is already recorded on this claim.")
    # Recorded honestly: whether the text an adjuster sends came from the AI draft, and whether
    # they changed it. The source is checked against the server's own draft, not trusted from the form.
    ai_drafted = source == "ai" and view["source"] == "ai"
    storage.add_info_request(claim_id, message, adjuster["username"],
                             run_id=view["run"]["id"] if ai_drafted else None, ai_drafted=ai_drafted,
                             edited=message != view["text"].strip())
    missing = [m for m in record["missing"] if m != "adjuster_request"] + ["adjuster_request"]
    storage.set_claim_status(claim_id, NEEDS_INFORMATION, missing)
    _notify(claim_id, record["claim"]["claimant_email"],
            "Your adjuster has asked for more information to continue reviewing your claim. "
            "See the request on your claim page.", _base_url(request), background)
    return RedirectResponse(url=f"/adjuster/claims/{claim_id}#request", status_code=303)


@app.get("/adjuster/ai")
def adjuster_ai_settings(request: Request, adjuster: dict | None = Depends(get_current_adjuster)):
    """Which approved model answers first, and today's AI usage against the daily limits."""
    if adjuster is None:
        return RedirectResponse(url="/adjuster/login", status_code=303)
    return templates.TemplateResponse(
        request, "adjuster_ai.html",
        {"adjuster": adjuster, "active": "ai", "ai_on": ai_client.enabled(), "models": agents.model_order(),
         "chosen": storage.get_ai_setting("model"), "usage": agents.usage_today(),
         "claimant_chat": agents.claimant_chat_enabled(), "data_policy": privacy.data_policy(),
         "free_tier": [m for m in agents.model_order() if privacy.is_free_tier(m)], **_adjuster_nav()},
    )


@app.post("/adjuster/ai/model")
def adjuster_choose_model(model: str = Form(""), adjuster: dict | None = Depends(get_current_adjuster)):
    if adjuster is None:
        return RedirectResponse(url="/adjuster/login", status_code=303)
    if model not in ai_client.configured_models():
        return _forbidden("That model isn't on the approved list (AI_MODELS).")
    storage.set_ai_setting("model", model, adjuster["username"])
    return RedirectResponse(url="/adjuster/ai", status_code=303)


@app.post("/adjuster/claims/{claim_id}/decision")
def record_decision(request: Request, background: BackgroundTasks, claim_id: str, decision: str = Form(""),
                    reason: str = Form(""), acknowledge: str = Form(""),
                    adjuster: dict | None = Depends(get_current_adjuster)):
    if adjuster is None:
        return RedirectResponse(url="/adjuster/login", status_code=303)

    record = storage.get_claim(claim_id)
    if record is None:
        return RedirectResponse(url="/adjuster", status_code=303)
    if decision not in DECISIONS:
        return _forbidden("Not a recognized decision.")

    # Separation of duties: an adjuster account linked to a claimant email
    # (create_adjuster's linked_claimant_email) can never decide on a claim
    # filed by that same email. This is a conflict-of-interest control, not
    # an ownership check -- an adjuster with no linked claimant account has
    # nothing to conflict with and isn't affected by this at all.
    if adjuster["linked_claimant_email"] and adjuster["linked_claimant_email"] == record["claim"]["claimant_email"]:
        return _forbidden(
            "Separation of duties: this adjuster account is linked to the claimant who filed this claim."
        )

    # The page hides the buttons in these cases, but the server is what enforces them.
    if record["status"] != READY_FOR_REVIEW:
        return _forbidden("Decisions open once the claim is complete.")
    latest = record["decisions"][-1]["decision"] if record["decisions"] else None
    if latest in FINAL_DECISIONS:
        return _forbidden("A final decision is already recorded on this claim.")
    if decision == latest:
        # A repeat (a double click, a resubmitted form) adds no row and sends no second notice.
        return RedirectResponse(url=f"/adjuster/claims/{claim_id}", status_code=303)

    # An adverse decision needs a recorded reason, and the claimant is told it.
    reason = reason.strip().replace("\r\n", "\n")
    if decision == "DECLINED" and len(reason) < DECLINE_REASON_MIN_LENGTH:
        return _bad_request([f"A decline needs a written reason (at least {DECLINE_REASON_MIN_LENGTH} "
                             "characters). It's recorded with the decision and sent to the claimant."])
    if len(reason) > DECISION_REASON_MAX_LENGTH:
        return _bad_request([f"The reason can be at most {DECISION_REASON_MAX_LENGTH:,} characters."])

    open_findings = _open_findings(record)
    if decision == "APPROVED" and open_findings and acknowledge != "yes":
        count = len(open_findings)
        return _bad_request([f"{count} review finding{'s are' if count != 1 else ' is'} still open. Tick "
                             "\"I've checked the open findings\" to approve anyway; the approval records it."])

    storage.add_decision(claim_id, decision, adjuster["username"], reason, open_findings=len(open_findings))
    # Only a final decision goes to the claimant. "Needs more review" is the adjuster's own marker
    # for a closer look; emailing it would tell the claimant nothing they can act on.
    if decision in FINAL_DECISIONS:
        _notify(
            claim_id,
            record["claim"]["claimant_email"],
            f"An adjuster has recorded a decision on your claim: {decision.replace('_', ' ').title()}."
            + (f" Reason: {reason}" if reason else ""),
            _base_url(request),
            background,
        )
    return RedirectResponse(url=f"/adjuster/claims/{claim_id}", status_code=303)


@app.get("/adjuster/claims/{claim_id}/documents/{filename}")
def adjuster_download_document(claim_id: str, filename: str, adjuster: dict | None = Depends(get_current_adjuster)):
    if adjuster is None:
        return RedirectResponse(url="/adjuster/login", status_code=303)

    record = storage.get_claim(claim_id)
    if record is None:
        return _forbidden("No such claim.")

    path = storage.get_document_path(claim_id, filename)
    if path is None:
        return RedirectResponse(url=f"/adjuster/claims/{claim_id}", status_code=303)
    return FileResponse(path, filename=filename)


@app.get("/adjuster/notifications")
def adjuster_notifications(request: Request, adjuster: dict | None = Depends(get_current_adjuster)):
    if adjuster is None:
        return RedirectResponse(url="/adjuster/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "adjuster_notifications.html",
        {
            "adjuster": adjuster,
            **_adjuster_nav(),
            "recent_logins": storage.list_login_events()[:20],
        },
    )


@app.get("/adjuster/login")
def adjuster_login_form(request: Request, error: str | None = None):
    return templates.TemplateResponse(request, "adjuster_login.html", {"error": error})


@app.post("/adjuster/login")
def adjuster_login(request: Request, username: str = Form(""), password: str = Form("")):
    # FastAPI treats a blank required form field as missing and answers with a raw JSON
    # 422, so both default to "" and a blank submit is handled here, as a normal login
    # page message. (The form's own `required` attributes catch it in the browser first.)
    if not username.strip() or not password:
        return RedirectResponse(url="/adjuster/login?error=empty", status_code=303)
    adjuster = storage.verify_adjuster(username, password)
    if adjuster is None:
        # Same generic error whether the username doesn't exist or the
        # password is wrong -- distinguishing them would let someone probe
        # for valid adjuster usernames one guess at a time.
        return RedirectResponse(url="/adjuster/login?error=1", status_code=303)

    request.session["adjuster_username"] = adjuster["username"]
    storage.record_login_event("adjuster", adjuster["username"], "login")
    return RedirectResponse(url="/adjuster", status_code=303)


@app.get("/adjuster/logout")
def adjuster_logout(request: Request):
    username = request.session.pop("adjuster_username", None)
    if username:
        storage.record_login_event("adjuster", username, "logout")
    return RedirectResponse(url="/", status_code=303)
