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
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import storage
from auth import get_current_adjuster, get_current_user, router as auth_router
from extraction import extract_facts
from main import check_claim, READY_FOR_REVIEW, NEEDS_INFORMATION
from summary import generate_summary
from validation import validate_claim_fields, validate_files

DECISIONS = ["APPROVED", "DECLINED", "NEEDS_MORE_REVIEW"]


def _notify(claim_id: str, claimant_email: str, message: str) -> None:
    """Record a notification on both mock channels. See storage.add_notification
    -- neither channel actually delivers anything; this just logs that a real
    system would have, which is enough to demonstrate the pipeline stage
    without pretending to send real email.
    """
    storage.add_notification(claim_id, claimant_email, "in_app", message)
    storage.add_notification(claim_id, claimant_email, "email", message)


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
    demo_username = os.environ.get("DEMO_ADJUSTER_USERNAME")
    demo_password = os.environ.get("DEMO_ADJUSTER_PASSWORD")
    if demo_username and demo_password and storage.get_adjuster(demo_username) is None:
        storage.create_adjuster(demo_username, "Demo Adjuster", password=demo_password)
    yield


app = FastAPI(title="HarborClaim -- Claim Intake", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET_KEY", "dev-only-insecure-key-change-me"),
)
app.include_router(auth_router)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


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
        {"user": user, "adjuster": adjuster, "unread_count": storage.unread_notification_count_for(user["email"])},
    )


@app.post("/claims")
async def submit_claim(
    request: Request,
    policy_id: str = Form(""),
    incident_date: str = Form(""),
    description: str = Form(""),
    files: list[UploadFile] = File([]),
    user: dict | None = Depends(get_current_user),
):
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=303)

    # An empty <input type="file" multiple> still submits one UploadFile with
    # filename == "" -- drop those before they count as a real document.
    uploads = [f for f in files if f.filename]

    errors = validate_claim_fields(policy_id, incident_date, description)
    for upload in uploads:
        upload.file.seek(0, 2)  # seek to end to get size without reading content twice
        size = upload.file.tell()
        upload.file.seek(0)
        errors.extend(validate_files([(upload.filename, size)]))
    if errors:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "user": user,
                "adjuster": None,
                "unread_count": storage.unread_notification_count_for(user["email"]),
                "errors": errors,
                "form": {"policy_id": policy_id, "incident_date": incident_date, "description": description},
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
    )

    stored_documents = []
    for upload in uploads:
        content = await upload.read()
        stored_path = storage.save_uploaded_file(claim_id, upload.filename, content)
        storage.add_document(
            claim_id=claim_id,
            filename=upload.filename,
            stored_path=stored_path,
            content_type=upload.content_type,
            size_bytes=len(content),
        )
        stored_documents.append(
            {"filename": upload.filename, "stored_path": stored_path, "content_type": upload.content_type}
        )

    # Pipeline continues past the completeness check regardless of status --
    # even an incomplete claim gets whatever can be extracted from what it
    # does have, so an adjuster (or the claimant, on request) sees the same
    # draft a complete claim would get once the missing pieces arrive.
    facts = extract_facts(description, stored_documents)
    if facts:
        storage.add_facts(claim_id, facts)
    summary_text = generate_summary(
        {"policy_id": policy_id, "incident_date": incident_date, "description": description,
         "documents": document_names},
        facts,
    )
    storage.add_summary(claim_id, summary_text)

    if result["status"] == NEEDS_INFORMATION:
        message = f"We still need: {', '.join(result['missing'])}. Please add these to your claim."
    else:
        message = "Your claim is complete and has been routed to an adjuster for review."
    _notify(claim_id, user["email"], message)

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
            "unread_count": storage.unread_notification_count_for(user["email"]),
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
            "unread_count": storage.unread_notification_count_for(user["email"]),
        },
    )


@app.get("/notifications")
def notifications(request: Request, user: dict | None = Depends(get_current_user)):
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=303)

    items = storage.list_notifications_for(user["email"])
    storage.mark_notifications_read(user["email"])
    return templates.TemplateResponse(
        request,
        "notifications.html",
        {"notifications": items, "user": user, "unread_count": 0},
    )


# ---------------------------------------------------------------------------
# Adjuster-facing routes -- everything under /adjuster/... None of these
# ever accept a claimant session as sufficient access, even for a claim that
# session's own account filed.
# ---------------------------------------------------------------------------

@app.get("/adjuster")
def adjuster_queue(request: Request, adjuster: dict | None = Depends(get_current_adjuster)):
    if adjuster is None:
        return RedirectResponse(url="/adjuster/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "adjuster_queue.html",
        {
            "claims": storage.list_claims(),
            "needs_attention": storage.claims_needing_adjuster_attention(),
            "adjuster": adjuster,
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
            "READY_FOR_REVIEW": READY_FOR_REVIEW,
            "NEEDS_INFORMATION": NEEDS_INFORMATION,
        },
    )


@app.post("/adjuster/claims/{claim_id}/decision")
def record_decision(claim_id: str, decision: str = Form(...), adjuster: dict | None = Depends(get_current_adjuster)):
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
            "needs_attention": storage.claims_needing_adjuster_attention(),
            "recent_logins": storage.list_login_events()[:20],
        },
    )


@app.get("/adjuster/login")
def adjuster_login_form(request: Request, error: str | None = None):
    return templates.TemplateResponse(request, "adjuster_login.html", {"error": error})


@app.post("/adjuster/login")
def adjuster_login(request: Request, username: str = Form(...), password: str = Form(...)):
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
