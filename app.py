"""
HarborClaim -- Insurance Claim Intake System (web UI).

Front end for the pipeline described in the Design Deliverable. Today this wires
one real stage -- the completeness checker from main.py -- behind a claim
submission form and a result view. The other stages (document storage, AI
extraction, AI summary, adjuster review, persistence, notifications) are stubbed
with clearly-labeled mock data so the UI and the pipeline shape are both real,
even though most of the pipeline behind them isn't built yet.

Run: uvicorn app:app --reload
"""

import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from main import check_claim, READY_FOR_REVIEW, NEEDS_INFORMATION

app = FastAPI(title="HarborClaim -- Claim Intake")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# In-memory claim store -- stands in for the real Claims Database (step 7 of
# the end-to-end build). Every claim keeps its full status history, not just
# its current status, so a later "how long has this been waiting" feature has
# something to read.
CLAIMS: dict[str, dict] = {}

DOCUMENT_OPTIONS = [
    "police_report.pdf",
    "photos.zip",
    "repair_estimate.pdf",
    "medical_report.pdf",
    "witness_statement.pdf",
]


@app.get("/")
def new_claim_form(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"document_options": DOCUMENT_OPTIONS}
    )


@app.post("/claims")
def submit_claim(
    policy_id: str = Form(""),
    incident_date: str = Form(""),
    description: str = Form(""),
    documents: list[str] = Form([]),
):
    claim_id = f"CLM-{uuid.uuid4().hex[:8].upper()}"
    claim = {
        "claim_id": claim_id,
        "policy_id": policy_id,
        "incident_date": incident_date,
        "description": description,
        "documents": documents,
    }

    result = check_claim(claim)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    CLAIMS[claim_id] = {
        "claim": claim,
        "status": result["status"],
        "missing": result["missing"],
        "history": [{"status": result["status"], "at": now}],
    }

    return RedirectResponse(url=f"/claims/{claim_id}", status_code=303)


@app.get("/claims/{claim_id}")
def view_claim(request: Request, claim_id: str):
    record = CLAIMS.get(claim_id)
    if record is None:
        return templates.TemplateResponse(
            request, "not_found.html", {"claim_id": claim_id}, status_code=404
        )

    return templates.TemplateResponse(
        request,
        "result.html",
        {
            "record": record,
            "READY_FOR_REVIEW": READY_FOR_REVIEW,
            "NEEDS_INFORMATION": NEEDS_INFORMATION,
        },
    )


@app.get("/claims")
def list_claims(request: Request):
    return templates.TemplateResponse(
        request, "list.html", {"claims": list(CLAIMS.values())}
    )
