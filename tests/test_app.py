"""
Tests for the web UI layer (app.py). Run from the asim-khan folder:

    python -m pytest tests/test_app.py -v

These exercise the FastAPI routes directly (no server process needed) via
FastAPI's TestClient, which wraps httpx. Each test resets app.CLAIMS first so
tests don't leak state into each other -- the in-memory store is a known
stand-in for a real database (see app.py's own comment on CLAIMS).
"""

import sys
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)


def setup_function(_):
    app_module.CLAIMS.clear()


def submit(**fields):
    # Built explicitly with urlencode(doseq=True) + a raw `content=` body,
    # rather than handing a list of tuples to `data=`, because this
    # environment's httpx variant (there are two packages installed --
    # httpx and httpx2 -- and TestClient resolves to httpx2 here) doesn't
    # form-encode a list-of-tuples the way classic httpx does; fields were
    # silently arriving empty on the server side. An explicit body sidesteps
    # that regardless of which httpx variant is actually in play.
    documents = fields.pop("documents", None) or []
    pairs = list(fields.items()) + [("documents", d) for d in documents]
    body = urlencode(pairs)
    return client.post(
        "/claims",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )


def test_homepage_shows_the_submission_form():
    response = client.get("/")
    assert response.status_code == 200
    assert "Submit a claim" in response.text
    assert 'action="/claims"' in response.text


def test_complete_claim_redirects_and_shows_ready_for_review():
    response = submit(
        policy_id="POL-48213",
        incident_date="2026-09-10",
        description="Rear-end collision in parking lot, minor bumper damage.",
        documents=["police_report.pdf"],
    )
    assert response.status_code == 303
    claim_url = response.headers["location"]

    result = client.get(claim_url)
    assert result.status_code == 200
    assert "READY_FOR_REVIEW" in result.text
    assert "NEEDS_INFORMATION" not in result.text


def test_incomplete_claim_names_the_missing_field():
    response = submit(
        policy_id="POL-77410",
        description="Kitchen fire, water damage.",
        documents=["photos.zip"],
    )
    claim_url = response.headers["location"]

    result = client.get(claim_url)
    assert "NEEDS_INFORMATION" in result.text
    assert "incident_date" in result.text


def test_unknown_claim_id_returns_404():
    response = client.get("/claims/CLM-DOESNOTEXIST")
    assert response.status_code == 404


def test_claims_list_shows_submitted_claims():
    submit(
        policy_id="POL-1",
        incident_date="2026-01-01",
        description="Minor claim.",
        documents=["report.pdf"],
    )
    response = client.get("/claims")
    assert response.status_code == 200
    assert "POL-1" in response.text


def test_claims_list_is_empty_state_when_nothing_submitted():
    response = client.get("/claims")
    assert "No claims submitted yet." in response.text
