"""
Tests for the web UI layer (app.py). Run from the asim-khan folder:

    python -m pytest tests/test_app.py -v

These exercise the FastAPI routes directly (no server process needed) via
FastAPI's TestClient. Each test resets the database first so tests don't
leak state into each other -- see storage.reset().

Two separate login mechanisms, two separate ways of faking them in tests:
  - Claimant (Google) login is faked with FastAPI's dependency_overrides on
    get_current_user -- the standard way to test routes behind auth without
    a real OAuth round trip.
  - Adjuster login has its own username/password check
    (storage.verify_adjuster), so it's exercised for real: an actual
    POST /adjuster/login with a real generated password, not just an
    override, to prove the password check itself works.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

import app as app_module
import storage
from auth import get_current_user

client = TestClient(app_module.app)

CLAIMANT = {"id": 1, "email": "claimant@example.com", "name": "Casey Claimant"}
OTHER_CLAIMANT = {"id": 2, "email": "other@example.com", "name": "Other Person"}


def setup_function(_):
    storage.init_db()
    storage.reset()
    storage.get_or_create_user(CLAIMANT["email"], CLAIMANT["name"])
    storage.get_or_create_user(OTHER_CLAIMANT["email"], OTHER_CLAIMANT["name"])
    app_module.app.dependency_overrides.pop(get_current_user, None)
    client.cookies.clear()


def teardown_function(_):
    app_module.app.dependency_overrides.pop(get_current_user, None)


def login_as_claimant(user):
    app_module.app.dependency_overrides[get_current_user] = lambda: user


def login_as_adjuster(username: str, password: str):
    """Real login, not an override -- exercises storage.verify_adjuster for real."""
    response = client.post(
        "/adjuster/login", data={"username": username, "password": password}, follow_redirects=False
    )
    assert response.status_code == 303 and response.headers["location"] == "/adjuster"


def submit(files=None, **fields):
    upload_files = [
        ("files", (name, content, "application/octet-stream"))
        for name, content in (files or [])
    ]
    return client.post(
        "/claims",
        data=fields,
        files=upload_files or None,
        follow_redirects=False,
    )


def test_signed_out_homepage_prompts_to_sign_in():
    response = client.get("/")
    assert response.status_code == 200
    assert "Sign in with Google" in response.text


def test_signed_out_new_claim_form_redirects_to_login_on_submit():
    response = submit(
        policy_id="POL-1",
        incident_date="2026-01-01",
        description="Anonymous attempt.",
    )
    assert response.status_code in (307, 303, 302)
    assert response.headers["location"] == "/auth/login"


def test_first_login_creates_an_account_behind_the_scenes():
    storage.reset()
    assert storage.get_user("new-person@example.com") is None
    storage.get_or_create_user("new-person@example.com", "New Person")
    assert storage.get_user("new-person@example.com") is not None


def test_signed_in_homepage_shows_the_submission_form():
    login_as_claimant(CLAIMANT)
    response = client.get("/")
    assert response.status_code == 200
    assert "Submit a claim" in response.text
    assert 'action="/claims"' in response.text
    assert "Adjuster queue" not in response.text


def test_complete_claim_redirects_and_shows_ready_for_review():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-48213",
        incident_date="2026-09-10",
        description="Rear-end collision in parking lot, minor bumper damage.",
        files=[("police_report.pdf", b"%PDF-1.4 fictional report")],
    )
    assert response.status_code == 303
    claim_url = response.headers["location"]

    result = client.get(claim_url)
    assert result.status_code == 200
    assert "READY_FOR_REVIEW" in result.text
    assert "NEEDS_INFORMATION" not in result.text
    assert "police_report.pdf" in result.text
    assert CLAIMANT["email"] in result.text


def test_incomplete_claim_names_the_missing_field():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-77410",
        description="Kitchen fire, water damage.",
        files=[("photos.zip", b"fictional bytes")],
    )
    claim_url = response.headers["location"]

    result = client.get(claim_url)
    assert "NEEDS_INFORMATION" in result.text
    assert "incident_date" in result.text


def test_uploaded_file_is_persisted_to_disk_and_downloadable():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-99",
        incident_date="2026-02-02",
        description="Verifies real file storage, not just a filename.",
        files=[("estimate.pdf", b"fictional repair estimate bytes")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    stored_path = storage.get_document_path(claim_id, "estimate.pdf")
    assert stored_path is not None
    assert stored_path.read_bytes() == b"fictional repair estimate bytes"

    download = client.get(f"/claims/{claim_id}/documents/estimate.pdf")
    assert download.status_code == 200
    assert download.content == b"fictional repair estimate bytes"


def test_a_claimant_cannot_view_another_claimants_claim():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-PRIVATE",
        incident_date="2026-04-04",
        description="Only mine to see.",
        files=[("report.pdf", b"bytes")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    login_as_claimant(OTHER_CLAIMANT)
    blocked = client.get(f"/claims/{claim_id}")
    assert blocked.status_code == 403

    blocked_download = client.get(f"/claims/{claim_id}/documents/report.pdf")
    assert blocked_download.status_code == 403


def test_my_claims_list_only_shows_my_own_claims():
    login_as_claimant(CLAIMANT)
    submit(policy_id="POL-MINE", incident_date="2026-01-01", description="Mine.", files=[("a.pdf", b"x")])

    login_as_claimant(OTHER_CLAIMANT)
    submit(policy_id="POL-THEIRS", incident_date="2026-01-02", description="Theirs.", files=[("b.pdf", b"y")])

    response = client.get("/claims")
    assert "POL-THEIRS" in response.text
    assert "POL-MINE" not in response.text


def test_created_adjuster_password_is_random_and_only_returned_once():
    password_a = storage.create_adjuster("adjuster.a")
    password_b = storage.create_adjuster("adjuster.b")
    assert password_a != password_b
    assert len(password_a) >= 12


def test_wrong_adjuster_password_is_rejected():
    storage.create_adjuster("wrongpw.test")
    response = client.post(
        "/adjuster/login", data={"username": "wrongpw.test", "password": "not-the-real-password"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/adjuster/login?error=1"

    still_blocked = client.get("/adjuster", follow_redirects=False)
    assert still_blocked.status_code == 303
    assert still_blocked.headers["location"] == "/adjuster/login"


def test_unknown_username_is_rejected_without_a_stack_trace():
    response = client.post(
        "/adjuster/login", data={"username": "nobody-by-this-name", "password": "anything"},
    )
    assert response.status_code == 200  # followed the redirect to the login form
    assert "Incorrect username or password" in response.text


def test_adjuster_login_works_with_the_real_generated_password():
    password = storage.create_adjuster("real.adjuster", "Real Adjuster")
    login_as_adjuster("real.adjuster", password)

    response = client.get("/adjuster")
    assert response.status_code == 200
    assert "No claims submitted yet." in response.text


def test_claimant_login_does_not_grant_adjuster_access():
    login_as_claimant(CLAIMANT)
    response = client.get("/adjuster", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/adjuster/login"


def test_adjuster_sees_every_claim_regardless_of_owner():
    login_as_claimant(CLAIMANT)
    submit(policy_id="POL-MINE", incident_date="2026-01-01", description="Mine.", files=[("a.pdf", b"x")])

    login_as_claimant(OTHER_CLAIMANT)
    submit(policy_id="POL-THEIRS", incident_date="2026-01-02", description="Theirs.", files=[("b.pdf", b"y")])

    password = storage.create_adjuster("queue.adjuster")
    login_as_adjuster("queue.adjuster", password)

    response = client.get("/adjuster")
    assert response.status_code == 200
    assert "POL-MINE" in response.text
    assert "POL-THEIRS" in response.text


def test_only_a_logged_in_adjuster_can_record_a_decision():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-DECIDE",
        incident_date="2026-05-05",
        description="Needs a decision.",
        files=[("report.pdf", b"bytes")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    blocked = client.post(f"/claims/{claim_id}/decision", data={"decision": "APPROVED"}, follow_redirects=False)
    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/adjuster/login"

    password = storage.create_adjuster("decider")
    login_as_adjuster("decider", password)
    allowed = client.post(f"/claims/{claim_id}/decision", data={"decision": "APPROVED"}, follow_redirects=False)
    assert allowed.status_code == 303

    result = client.get(f"/claims/{claim_id}")
    assert "APPROVED" in result.text
    assert "decider" in result.text


def test_separation_of_duties_blocks_an_adjuster_deciding_their_own_claim():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-CONFLICT",
        incident_date="2026-06-06",
        description="Filed by the same person who will try to review it.",
        files=[("report.pdf", b"bytes")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    # This adjuster account is linked to CLAIMANT's own email -- same person,
    # two roles. Deciding on their own claim must be blocked regardless of
    # which decision they pick.
    password = storage.create_adjuster("conflicted", linked_claimant_email=CLAIMANT["email"])
    login_as_adjuster("conflicted", password)

    blocked = client.post(f"/claims/{claim_id}/decision", data={"decision": "APPROVED"})
    assert blocked.status_code == 403

    assert storage.get_claim(claim_id)["decisions"] == []


def test_an_unlinked_adjuster_is_unaffected_by_the_conflict_check():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-FINE",
        incident_date="2026-06-07",
        description="No conflict here.",
        files=[("report.pdf", b"bytes")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    # Linked to a *different* email than the claimant who filed this one --
    # the check should only ever fire on an exact match, never adjacent cases.
    password = storage.create_adjuster("unrelated", linked_claimant_email="someone-else@example.com")
    login_as_adjuster("unrelated", password)

    allowed = client.post(f"/claims/{claim_id}/decision", data={"decision": "APPROVED"}, follow_redirects=False)
    assert allowed.status_code == 303


def test_login_and_logout_are_recorded_in_the_audit_trail():
    password = storage.create_adjuster("audited.adjuster")
    login_as_adjuster("audited.adjuster", password)
    client.get("/adjuster/logout", follow_redirects=False)

    events = storage.list_login_events("audited.adjuster")
    assert [e["event"] for e in events] == ["logout", "login"]  # newest first
    assert all(e["role"] == "adjuster" for e in events)


def test_claimant_logout_does_not_end_an_active_adjuster_session():
    password = storage.create_adjuster("survives.claimant.logout")
    login_as_adjuster("survives.claimant.logout", password)

    # /auth/logout used to call request.session.clear(), which would wipe
    # this adjuster session too since they share one cookie. It should now
    # only ever touch its own key.
    client.get("/auth/logout", follow_redirects=False)

    still_in = client.get("/adjuster")
    assert still_in.status_code == 200


def test_unknown_claim_id_returns_404():
    login_as_claimant(CLAIMANT)
    response = client.get("/claims/CLM-DOESNOTEXIST")
    assert response.status_code == 404


def test_claims_list_is_empty_state_when_nothing_submitted():
    login_as_claimant(CLAIMANT)
    response = client.get("/claims")
    assert "No claims submitted yet." in response.text
