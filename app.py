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
import email_delivery
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


def _claimant_nav(claimant_email: str) -> dict:
    """Context for the claimant top nav's notification bell (_claimant_header.html).

    Every event is logged on both channels, so the bell counts and previews only
    the in_app rows -- one status change shows as one notification, not two.
    """
    in_app = [n for n in storage.list_notifications_for(claimant_email) if n["channel"] == "in_app"]
    return {
        "unread_count": sum(1 for n in in_app if not n["read_at"]),
        "notification_preview": in_app[:5],
    }


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
    return events


QUEUE_VIEWS = {
    "all": "All claims",
    "awaiting": "Awaiting a decision",
    "waiting": "Waiting on claimant",
    "decided": "Decided",
}


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
    items = "".join(f"<li>{e}</li>" for e in errors)
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
            "facts_view": _group_facts(record["facts"]),
            **_adjuster_nav(),
            "READY_FOR_REVIEW": READY_FOR_REVIEW,
            "NEEDS_INFORMATION": NEEDS_INFORMATION,
        },
    )


@app.post("/adjuster/claims/{claim_id}/decision")
def record_decision(request: Request, background: BackgroundTasks, claim_id: str, decision: str = Form(""), adjuster: dict | None = Depends(get_current_adjuster)):
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

    storage.add_decision(claim_id, decision, adjuster["username"])
    _notify(
        claim_id,
        record["claim"]["claimant_email"],
        f"An adjuster has recorded a decision on your claim: {decision.replace('_', ' ').title()}.",
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
