"""
HarborClaim -- Insurance Claim Intake System (web UI).

Front end for the pipeline described in the Design Deliverable. Real stages
now: the completeness checker (main.py), document/evidence storage and a
persistent claims database (storage.py, SQLite), and adjuster review (a human
decision). AI extraction, AI summary, and notifications are still not built.

Two account types, two completely separate login mechanisms -- see auth.py
and storage.py's module docstrings for why:
  - Claimants: sign in with Google (auth.py). First login *is* account
    creation. A claimant only ever sees their own claims.
  - Adjusters: a username and password provisioned by hand
    (storage.create_adjuster) at /adjuster/login. No Google involved, no
    sign-up form -- provisioning an adjuster is meant to happen only after
    a real state license is verified, outside this app entirely.

A browser can hold both sessions at once (different keys in the same session
cookie), so one person can be signed in as a claimant and an adjuster
simultaneously, in the same tab.

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
from main import check_claim, READY_FOR_REVIEW, NEEDS_INFORMATION

DECISIONS = ["APPROVED", "DECLINED", "NEEDS_MORE_REVIEW"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
    yield


app = FastAPI(title="HarborClaim -- Claim Intake", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET_KEY", "dev-only-insecure-key-change-me"),
)
app.include_router(auth_router)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def _forbidden(message: str) -> HTMLResponse:
    return HTMLResponse(f"<h1>403 Forbidden</h1><p>{message}</p>", status_code=403)


def _can_view(record: dict, user: dict | None, adjuster: dict | None) -> bool:
    owns_it = user is not None and record["claim"]["claimant_email"] == user["email"]
    return owns_it or adjuster is not None


@app.get("/")
def home(
    request: Request,
    user: dict | None = Depends(get_current_user),
    adjuster: dict | None = Depends(get_current_adjuster),
):
    if user is None:
        return templates.TemplateResponse(request, "signed_out.html", {"adjuster": adjuster})
    return templates.TemplateResponse(request, "index.html", {"user": user, "adjuster": adjuster})


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

    claim_id = f"CLM-{uuid.uuid4().hex[:8].upper()}"

    # An empty <input type="file" multiple> still submits one UploadFile with
    # filename == "" -- drop those before they count as a real document.
    uploads = [f for f in files if f.filename]
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

    return RedirectResponse(url=f"/claims/{claim_id}", status_code=303)


@app.get("/claims/{claim_id}")
def view_claim(
    request: Request,
    claim_id: str,
    user: dict | None = Depends(get_current_user),
    adjuster: dict | None = Depends(get_current_adjuster),
):
    if user is None and adjuster is None:
        return RedirectResponse(url="/", status_code=303)

    record = storage.get_claim(claim_id)
    if record is None:
        return templates.TemplateResponse(
            request, "not_found.html", {"claim_id": claim_id}, status_code=404
        )
    if not _can_view(record, user, adjuster):
        return _forbidden("This claim belongs to a different account.")

    return templates.TemplateResponse(
        request,
        "result.html",
        {
            "record": record,
            "user": user,
            "adjuster": adjuster,
            "decisions": DECISIONS,
            "READY_FOR_REVIEW": READY_FOR_REVIEW,
            "NEEDS_INFORMATION": NEEDS_INFORMATION,
        },
    )


@app.post("/claims/{claim_id}/decision")
def record_decision(
    claim_id: str,
    decision: str = Form(...),
    adjuster: dict | None = Depends(get_current_adjuster),
):
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
    return RedirectResponse(url=f"/claims/{claim_id}", status_code=303)


@app.get("/claims/{claim_id}/documents/{filename}")
def download_document(
    claim_id: str,
    filename: str,
    user: dict | None = Depends(get_current_user),
    adjuster: dict | None = Depends(get_current_adjuster),
):
    if user is None and adjuster is None:
        return RedirectResponse(url="/", status_code=303)

    record = storage.get_claim(claim_id)
    if record is None or not _can_view(record, user, adjuster):
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
        {"claims": storage.list_claims_for(user["email"]), "user": user},
    )


@app.get("/adjuster")
def adjuster_queue(request: Request, adjuster: dict | None = Depends(get_current_adjuster)):
    if adjuster is None:
        return RedirectResponse(url="/adjuster/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "adjuster_queue.html",
        {"claims": storage.list_claims(), "adjuster": adjuster, "READY_FOR_REVIEW": READY_FOR_REVIEW},
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
