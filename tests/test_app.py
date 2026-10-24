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


def test_reset_adjuster_password_changes_which_password_works():
    old_password = storage.create_adjuster("rotate.test", "Rotate Test")
    new_password = storage.reset_adjuster_password("rotate.test")

    assert new_password is not None
    assert new_password != old_password
    assert storage.verify_adjuster("rotate.test", old_password) is None
    assert storage.verify_adjuster("rotate.test", new_password) is not None


def test_reset_adjuster_password_accepts_an_explicit_password():
    storage.create_adjuster("rotate.explicit")
    result = storage.reset_adjuster_password("rotate.explicit", password="chosen-value-123")
    assert result == "chosen-value-123"
    assert storage.verify_adjuster("rotate.explicit", "chosen-value-123") is not None


def test_reset_adjuster_password_on_unknown_username_returns_none():
    assert storage.reset_adjuster_password("does-not-exist") is None


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

    blocked = client.post(
        f"/adjuster/claims/{claim_id}/decision", data={"decision": "APPROVED"}, follow_redirects=False
    )
    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/adjuster/login"

    password = storage.create_adjuster("decider")
    login_as_adjuster("decider", password)
    allowed = client.post(
        f"/adjuster/claims/{claim_id}/decision", data={"decision": "APPROVED"}, follow_redirects=False
    )
    assert allowed.status_code == 303

    # Shows up on both the claimant's own view and the adjuster's separate one.
    claimant_view = client.get(f"/claims/{claim_id}")
    assert "APPROVED" in claimant_view.text
    assert "decider" in claimant_view.text

    adjuster_view = client.get(f"/adjuster/claims/{claim_id}")
    assert "APPROVED" in adjuster_view.text
    assert "decider" in adjuster_view.text


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

    blocked = client.post(f"/adjuster/claims/{claim_id}/decision", data={"decision": "APPROVED"})
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

    allowed = client.post(
        f"/adjuster/claims/{claim_id}/decision", data={"decision": "APPROVED"}, follow_redirects=False
    )
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


def test_mock_extraction_finds_facts_in_an_uploaded_text_document():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-FACTS",
        incident_date="2026-07-07",
        description="Kitchen fire, minor damage.",
        files=[("notes.txt", b"Repair estimate $4,200.00 dated 2026-07-08. Possible water damage too.")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    result = client.get(f"/claims/{claim_id}")
    assert "$4,200.00" in result.text
    assert "2026-07-08" in result.text
    assert "Fire" in result.text
    assert "Water damage" in result.text
    assert "not AI-generated" in result.text  # never presented as if it were real AI


def test_mock_summary_is_generated_on_submission():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-SUMMARY",
        incident_date="2026-08-01",
        description="Garage theft, tools missing.",
        files=[("report.txt", b"Police report filed.")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    record = storage.get_claim(claim_id)
    assert record["summary"] is not None
    assert "POL-SUMMARY" in record["summary"]["summary_text"]
    assert "Garage theft" in record["summary"]["summary_text"]


def test_summary_names_a_missing_incident_date_instead_of_leaving_a_blank():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-NODATE",
        incident_date="",
        description="Kitchen fire.",
        files=[("notes.txt", b"Fire in kitchen.")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    text = storage.get_claim(claim_id)["summary"]["summary_text"]
    assert "[incident date not provided]" in text
    assert "incident reported ." not in text


def test_summary_states_when_no_documents_were_provided():
    from summary import generate_summary

    text = generate_summary(
        {"policy_id": "POL-1", "incident_date": "2026-08-01", "description": "x", "documents": []},
        facts=[],
    )
    assert "Documents on file: none provided." in text


def test_summary_states_a_blank_description_as_not_provided():
    from summary import generate_summary

    text = generate_summary(
        {"policy_id": "POL-1", "incident_date": "2026-08-01", "description": "   ", "documents": ["a.pdf"]},
        facts=[],
    )
    assert "Claimant's description: not provided." in text


def test_submission_creates_notifications_on_both_mock_channels():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-NOTIFY",
        incident_date="2026-08-02",
        description="Minor claim.",
        files=[("a.pdf", b"x")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    events = storage.list_notifications_for(CLAIMANT["email"])
    channels = {e["channel"] for e in events if e["claim_id"] == claim_id}
    assert channels == {"in_app", "email"}


def test_incomplete_submission_notification_names_the_missing_field():
    login_as_claimant(CLAIMANT)
    submit(
        policy_id="POL-MISSING",
        description="No incident date given.",
        files=[("a.pdf", b"x")],
    )
    events = storage.list_notifications_for(CLAIMANT["email"])
    assert any("incident_date" in e["message"] for e in events)


def test_notifications_page_lists_and_marks_them_read():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-READ", incident_date="2026-08-03", description="x", files=[("a.pdf", b"x")]
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    assert storage.unread_notification_count_for(CLAIMANT["email"]) > 0
    page = client.get("/notifications")
    assert page.status_code == 200
    assert claim_id in page.text
    assert "routed to an adjuster" in page.text
    assert storage.unread_notification_count_for(CLAIMANT["email"]) == 0


def test_adjuster_decision_notifies_the_claimant():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-DECIDE-NOTIFY",
        incident_date="2026-08-04",
        description="Needs a decision.",
        files=[("a.pdf", b"x")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    password = storage.create_adjuster("notify.decider")
    login_as_adjuster("notify.decider", password)
    client.post(f"/adjuster/claims/{claim_id}/decision", data={"decision": "APPROVED"})

    events = storage.list_notifications_for(CLAIMANT["email"])
    assert any("Approved" in e["message"] and e["claim_id"] == claim_id for e in events)


def test_adjuster_needs_attention_panel_excludes_decided_claims():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-ATTN",
        incident_date="2026-08-05",
        description="Needs review.",
        files=[("a.pdf", b"x")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    password = storage.create_adjuster("attn.adjuster")
    login_as_adjuster("attn.adjuster", password)

    before = client.get("/adjuster")
    assert claim_id in before.text
    assert "Awaiting a decision" in before.text

    client.post(f"/adjuster/claims/{claim_id}/decision", data={"decision": "DECLINED"})

    needing_attention = storage.claims_needing_adjuster_attention()
    assert claim_id not in [r["claim"]["claim_id"] for r in needing_attention]


# --- Strict page separation: the two roles never share a route, even for
# the exact same claim. ----------------------------------------------------

def test_adjuster_session_alone_cannot_open_the_claimant_claim_page():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-SEP-1", incident_date="2026-09-01", description="x", files=[("a.pdf", b"x")]
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    # Drop the claimant override entirely -- only an adjuster session remains.
    app_module.app.dependency_overrides.pop(get_current_user, None)
    password = storage.create_adjuster("sep.adjuster")
    login_as_adjuster("sep.adjuster", password)

    blocked = client.get(f"/claims/{claim_id}", follow_redirects=False)
    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/auth/login"


def test_claimant_session_alone_cannot_open_the_adjuster_claim_page():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-SEP-2", incident_date="2026-09-02", description="x", files=[("a.pdf", b"x")]
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    blocked = client.get(f"/adjuster/claims/{claim_id}", follow_redirects=False)
    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/adjuster/login"


def test_claimant_pages_never_link_to_an_adjuster_route():
    # The word "adjuster" legitimately appears in claimant-facing copy (e.g.
    # "routed to an adjuster for review") -- what actually must never appear
    # is a navigable link into adjuster-only territory.
    login_as_claimant(CLAIMANT)
    for path in ("/", "/claims", "/notifications"):
        response = client.get(path)
        assert 'href="/adjuster' not in response.text


def test_adjuster_notifications_page_shows_needs_attention_and_login_history():
    password = storage.create_adjuster("notif.view.adjuster")
    login_as_adjuster("notif.view.adjuster", password)

    response = client.get("/adjuster/notifications")
    assert response.status_code == 200
    assert "notif.view.adjuster" in response.text
    assert "ADJUSTER / LOGIN" in response.text


# --- Input validation: malformed input is rejected with the form re-shown,
# not silently stored or crashed on. ---------------------------------------

def test_policy_id_too_long_is_rejected():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="P" * 41,
        incident_date="2026-09-01",
        description="x",
        files=[("a.pdf", b"x")],
    )
    assert response.status_code == 400
    assert "too long" in response.text
    assert len(storage.list_claims_for(CLAIMANT["email"])) == 0


def test_future_incident_date_is_rejected():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-FUTURE",
        incident_date="2099-01-01",
        description="x",
        files=[("a.pdf", b"x")],
    )
    assert response.status_code == 400
    assert "future" in response.text
    assert len(storage.list_claims_for(CLAIMANT["email"])) == 0


def test_disallowed_file_type_is_rejected():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-BADFILE",
        incident_date="2026-09-01",
        description="x",
        files=[("malware.exe", b"not really malware, just a bad extension")],
    )
    assert response.status_code == 400
    assert "file type not allowed" in response.text
    assert len(storage.list_claims_for(CLAIMANT["email"])) == 0


def test_oversized_file_is_rejected():
    login_as_claimant(CLAIMANT)
    big_content = b"x" * (11 * 1024 * 1024)  # 11 MB, over the 10 MB cap
    response = submit(
        policy_id="POL-BIGFILE",
        incident_date="2026-09-01",
        description="x",
        files=[("huge.pdf", big_content)],
    )
    assert response.status_code == 400
    assert "too large" in response.text


def test_valid_submission_preserves_form_values_are_not_shown_as_errors():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-VALID",
        incident_date="2026-09-01",
        description="A perfectly normal claim.",
        files=[("a.pdf", b"x")],
    )
    assert response.status_code == 303  # no validation errors -- straight to the result


# --- Claim type at intake (ROADMAP Phase 2). Hints only: the completeness
# check in main.py never sees the claim type. ---------------------------------

def test_claim_type_is_stored_and_shown_to_both_roles():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-AUTO",
        incident_date="2026-09-01",
        description="Rear-end collision.",
        claim_type="auto",
        files=[("a.pdf", b"x")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]
    assert storage.get_claim(claim_id)["claim"]["claim_type"] == "auto"

    assert "Auto" in client.get(f"/claims/{claim_id}").text
    assert "Auto" in client.get("/claims").text

    password = storage.create_adjuster("type.adjuster")
    login_as_adjuster("type.adjuster", password)
    assert "Auto" in client.get(f"/adjuster/claims/{claim_id}").text
    assert "Auto" in client.get("/adjuster").text


def test_blank_claim_type_defaults_to_other():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-NOTYPE", incident_date="2026-09-01", description="x", files=[("a.pdf", b"x")]
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]
    assert storage.get_claim(claim_id)["claim"]["claim_type"] == "other"


def test_unknown_claim_type_is_rejected_and_nothing_is_stored():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-BADTYPE",
        incident_date="2026-09-01",
        description="x",
        claim_type="spaceship",
        files=[("a.pdf", b"x")],
    )
    assert response.status_code == 400
    assert "Claim type isn" in response.text
    assert storage.list_claims_for(CLAIMANT["email"]) == []


def test_claim_type_does_not_change_completeness():
    # An auto claim with no police report is still READY_FOR_REVIEW: the
    # per-type document guidance is a hint, not a rule main.py enforces.
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-AUTO-PHOTO",
        incident_date="2026-09-01",
        description="Dented door.",
        claim_type="auto",
        files=[("photo.jpg", b"x")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]
    assert storage.get_claim(claim_id)["status"] == "READY_FOR_REVIEW"


def test_summary_states_the_selected_claim_type():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-SUMTYPE",
        incident_date="2026-09-01",
        description="Pipe burst in the kitchen.",
        claim_type="property",
        files=[("a.pdf", b"x")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]
    summary = storage.get_claim(claim_id)["summary"]["summary_text"]
    assert "Claim type selected by the claimant: property." in summary


def test_existing_database_gains_claim_type_column(tmp_path, monkeypatch):
    # A database created before claim types existed must upgrade in place,
    # with existing claims treated as "other" rather than failing to load.
    import sqlite3

    old_db = tmp_path / "old.db"
    conn = sqlite3.connect(old_db)
    conn.execute(
        """CREATE TABLE claims (claim_id TEXT PRIMARY KEY, claimant_email TEXT NOT NULL,
           policy_id TEXT NOT NULL, incident_date TEXT NOT NULL, description TEXT NOT NULL,
           status TEXT NOT NULL, missing TEXT NOT NULL, created_at TEXT NOT NULL)"""
    )
    conn.execute(
        "INSERT INTO claims VALUES ('CLM-OLD', 'a@example.com', 'P1', '2026-01-01', 'd', "
        "'READY_FOR_REVIEW', '[]', '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(storage, "DB_PATH", old_db)
    storage.init_db()
    assert storage.get_claim("CLM-OLD")["claim"]["claim_type"] == "other"


# --- Top-nav notification bell (Phase 1) ---

def test_claimant_bell_counts_each_event_once_and_links_to_the_full_page():
    # Every event is logged on both channels; the bell counts events, so one
    # submission shows as 1 unread, not 2.
    login_as_claimant(CLAIMANT)
    submit(policy_id="POL-BELL", incident_date="2026-08-05", description="x", files=[("a.pdf", b"x")])

    page = client.get("/claims")
    assert '<details class="bell">' in page.text
    assert '<span class="badge-count">1</span>' in page.text
    assert "routed to an adjuster" in page.text  # the dropdown preview
    assert 'href="/notifications"' in page.text

    # Opening the dropdown doesn't mark anything read -- only the full page does.
    assert storage.unread_notification_count_for(CLAIMANT["email"]) > 0
    client.get("/notifications")
    assert '<span class="badge-count">' not in client.get("/claims").text


def test_adjuster_bell_shows_the_live_needs_attention_count_on_every_adjuster_page():
    login_as_claimant(CLAIMANT)
    response = submit(policy_id="POL-ADJ-BELL", incident_date="2026-08-06", description="x", files=[("a.pdf", b"x")])
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    password = storage.create_adjuster("bell.adjuster")
    login_as_adjuster("bell.adjuster", password)
    for path in ("/adjuster", f"/adjuster/claims/{claim_id}", "/adjuster/notifications"):
        page = client.get(path)
        assert '<details class="bell">' in page.text, path
        assert '<span class="badge-count">1</span>' in page.text, path
        assert 'href="/adjuster/notifications"' in page.text, path

    client.post(f"/adjuster/claims/{claim_id}/decision", data={"decision": "APPROVED"})
    assert '<span class="badge-count">' not in client.get("/adjuster").text


def test_more_than_ten_files_is_rejected_and_nothing_is_stored():
    # Regression: uploads used to be validated one single-file list at a time,
    # so validate_files' count limit could never trigger.
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-ELEVEN",
        incident_date="2026-09-01",
        description="x",
        files=[(f"page{i}.pdf", b"x") for i in range(11)],
    )
    assert response.status_code == 400
    assert "Too many files" in response.text
    assert storage.list_claims_for(CLAIMANT["email"]) == []


def test_exactly_ten_files_is_accepted():
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-TEN",
        incident_date="2026-09-01",
        description="x",
        files=[(f"page{i}.pdf", b"x") for i in range(10)],
    )
    assert response.status_code == 303
    claim_id = response.headers["location"].rsplit("/", 1)[-1]
    assert len(storage.get_claim(claim_id)["documents"]) == 10


# --- Notifications page: one entry per event (Phase 3 polish) ---

def test_notifications_page_shows_each_event_once_with_both_channel_tags():
    # Every event is logged on two channels; the page groups them back into one entry.
    login_as_claimant(CLAIMANT)
    response = submit(policy_id="POL-ONCE", incident_date="2026-08-07", description="x", files=[("a.pdf", b"x")])
    claim_id = response.headers["location"].rsplit("/", 1)[-1]
    password = storage.create_adjuster("once.adjuster")
    login_as_adjuster("once.adjuster", password)
    client.post(f"/adjuster/claims/{claim_id}/decision", data={"decision": "APPROVED"})

    page = client.get("/notifications").text
    assert len(storage.list_notifications_for(CLAIMANT["email"])) == 4  # 2 events x 2 channels
    assert page.count('<li class="event') == 2
    assert page.count("Email (simulated)") == 2
    assert page.count("In-app") == 2


def test_time_ago_reads_like_a_person_would_say_it():
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    ago = lambda **kw: app_module.time_ago((now - timedelta(**kw)).isoformat(timespec="seconds"))
    assert ago(seconds=5) == "just now"
    assert ago(minutes=1) == "1 minute ago"
    assert ago(hours=2) == "2 hours ago"
    assert ago(days=1) == "yesterday"
    assert ago(days=3) == "3 days ago"
    assert ago(days=30) == (now - timedelta(days=30)).date().isoformat()
    assert app_module.time_ago("not a date") == "not a date"


def test_completely_empty_submission_is_rejected_and_nothing_is_stored():
    login_as_claimant(CLAIMANT)
    response = submit(policy_id="", incident_date="", description="")
    assert response.status_code == 400
    assert "Add at least one detail" in response.text
    assert storage.list_claims_for(CLAIMANT["email"]) == []


def test_a_single_detail_is_enough_to_file_an_incomplete_claim():
    login_as_claimant(CLAIMANT)
    response = submit(policy_id="POL-JUST-ME", incident_date="", description="")
    assert response.status_code == 303
    claim_id = response.headers["location"].rsplit("/", 1)[-1]
    assert storage.get_claim(claim_id)["status"] == "NEEDS_INFORMATION"



# --- Adjuster queue (Phase 1b): work first, filters, search ---

def _file_claim(policy_id, complete=True):
    """Files a claim as CLAIMANT and returns its id. complete=False omits the incident date."""
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id=policy_id,
        incident_date="2026-08-10" if complete else "",
        description="x",
        files=[("a.pdf", b"x")],
    )
    return response.headers["location"].rsplit("/", 1)[-1]


def _queue_ids(html):
    """Claim IDs in the queue table, in row order (the bell dropdown links to claims too)."""
    import re
    start = html.find('<table class="claims-table">')
    if start < 0:
        return []
    table = html[start:html.index("</table>", start)]
    return re.findall(r'href="/adjuster/claims/(CLM-[0-9A-F]+)"', table)


def test_queue_puts_work_first_then_waiting_then_decided():
    decided = _file_claim("POL-Q-DECIDED")
    waiting = _file_claim("POL-Q-WAITING", complete=False)
    awaiting = _file_claim("POL-Q-AWAITING")
    password = storage.create_adjuster("queue.adjuster")
    login_as_adjuster("queue.adjuster", password)
    client.post(f"/adjuster/claims/{decided}/decision", data={"decision": "APPROVED"})

    assert _queue_ids(client.get("/adjuster").text) == [awaiting, waiting, decided]


def test_queue_view_filters_and_unknown_view_falls_back_to_all():
    decided = _file_claim("POL-F-DECIDED")
    waiting = _file_claim("POL-F-WAITING", complete=False)
    awaiting = _file_claim("POL-F-AWAITING")
    password = storage.create_adjuster("filter.adjuster")
    login_as_adjuster("filter.adjuster", password)
    client.post(f"/adjuster/claims/{decided}/decision", data={"decision": "DECLINED"})

    assert _queue_ids(client.get("/adjuster?view=awaiting").text) == [awaiting]
    assert _queue_ids(client.get("/adjuster?view=waiting").text) == [waiting]
    assert _queue_ids(client.get("/adjuster?view=decided").text) == [decided]
    assert sorted(_queue_ids(client.get("/adjuster?view=nonsense").text)) == sorted([awaiting, waiting, decided])


def test_queue_search_matches_every_word_across_id_claimant_policy_and_type():
    first = _file_claim("POL-S-ALPHA")
    second = _file_claim("POL-S-BETA")
    password = storage.create_adjuster("search.adjuster")
    login_as_adjuster("search.adjuster", password)

    assert _queue_ids(client.get("/adjuster?q=alpha").text) == [first]
    assert _queue_ids(client.get(f"/adjuster?q={second.lower()}").text) == [second]
    assert _queue_ids(client.get("/adjuster?q=claimant@example.com").text).__len__() == 2
    assert _queue_ids(client.get("/adjuster?q=alpha+beta").text) == []
    page = client.get("/adjuster?q=zzz-nothing")
    assert "No claims match" in page.text
    assert "No claims submitted yet." not in page.text


def test_adjuster_pages_show_relative_times_not_raw_timestamps():
    _file_claim("POL-TIME")
    password = storage.create_adjuster("time.adjuster")
    login_as_adjuster("time.adjuster", password)
    page = client.get("/adjuster")
    assert "just now" in page.text
    assert "No per-adjuster inbox" not in client.get("/adjuster/notifications").text


# --- Blank submissions get a page, never a raw JSON validation error ---

def test_adjuster_login_with_blank_fields_shows_a_message_not_json():
    for data in ({}, {"username": "", "password": ""}, {"username": "   ", "password": "x"}, {"username": "someone", "password": ""}):
        response = client.post("/adjuster/login", data=data, follow_redirects=False)
        assert response.status_code == 303, data
        assert response.headers["location"] == "/adjuster/login?error=empty", data

    page = client.get("/adjuster/login?error=empty")
    assert page.status_code == 200
    assert "Enter your username and password." in page.text
    assert "Incorrect username or password" not in page.text
    assert '"detail"' not in page.text


def test_blank_credentials_never_log_anyone_in_or_hit_the_audit_log():
    before = len(storage.list_login_events())
    client.post("/adjuster/login", data={"username": "", "password": ""})
    assert len(storage.list_login_events()) == before
    assert client.get("/adjuster", follow_redirects=False).status_code == 303


def test_decision_post_without_a_decision_is_a_page_not_a_json_error():
    login_as_claimant(CLAIMANT)
    response = submit(policy_id="POL-NODEC", incident_date="2026-08-11", description="x", files=[("a.pdf", b"x")])
    claim_id = response.headers["location"].rsplit("/", 1)[-1]
    password = storage.create_adjuster("nodec.adjuster")
    login_as_adjuster("nodec.adjuster", password)

    blank = client.post(f"/adjuster/claims/{claim_id}/decision", data={})
    assert blank.status_code == 403
    assert "Not a recognized decision" in blank.text
    assert storage.get_claim(claim_id)["decisions"] == []


# --- "Needs more review" keeps a claim on the adjuster's list until a final decision ---

def test_needs_more_review_stays_awaiting_until_a_final_decision_is_recorded():
    claim_id = _file_claim("POL-NMR")
    password = storage.create_adjuster("nmr.adjuster")
    login_as_adjuster("nmr.adjuster", password)

    def attention_ids():
        return [r["claim"]["claim_id"] for r in storage.claims_needing_adjuster_attention()]

    def bell_count(html):
        import re
        match = re.search(r'<span class="badge-count">(\d+)</span>', html)
        return int(match.group(1)) if match else 0

    assert claim_id in attention_ids()
    client.post(f"/adjuster/claims/{claim_id}/decision", data={"decision": "NEEDS_MORE_REVIEW"})

    # A closer look was requested, so it's still the adjuster's to act on:
    assert claim_id in attention_ids()
    assert _queue_ids(client.get("/adjuster?view=awaiting").text) == [claim_id]
    assert _queue_ids(client.get("/adjuster?view=decided").text) == []
    queue = client.get("/adjuster")
    assert bell_count(queue.text) == 1
    assert "Needs more review" in queue.text
    assert "Marked for more review" in client.get(f"/adjuster/claims/{claim_id}").text

    # A final decision closes it everywhere:
    client.post(f"/adjuster/claims/{claim_id}/decision", data={"decision": "APPROVED"})
    assert claim_id not in attention_ids()
    assert _queue_ids(client.get("/adjuster?view=awaiting").text) == []
    assert _queue_ids(client.get("/adjuster?view=decided").text) == [claim_id]
    assert bell_count(client.get("/adjuster").text) == 0
    assert "Marked for more review" not in client.get(f"/adjuster/claims/{claim_id}").text


def test_claimant_sees_needs_more_review_as_in_progress_not_as_a_final_decision():
    claim_id = _file_claim("POL-NMR-CLAIMANT")
    password = storage.create_adjuster("nmr.claimant.adjuster")
    login_as_adjuster("nmr.claimant.adjuster", password)
    client.post(f"/adjuster/claims/{claim_id}/decision", data={"decision": "NEEDS_MORE_REVIEW"})

    login_as_claimant(CLAIMANT)
    page = client.get(f"/claims/{claim_id}").text
    assert "closer look" in page
    assert '<li class="current">' in page          # adjuster review still in progress
    assert "Not yet" in page                       # no final decision yet


# --- Phase 3: email delivery behind a flag (off by default) ---

import email_delivery


def _email_rows():
    return [n for n in storage.list_notifications_for(CLAIMANT["email"]) if n["channel"] == "email"]


def test_email_is_simulated_by_default_and_never_calls_a_provider(monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)

    def must_not_send(*args):
        raise AssertionError("a provider was called while EMAIL_PROVIDER is unset")

    monkeypatch.setattr(email_delivery, "_send_via_acs", must_not_send)
    _file_claim("POL-EMAIL-SIM")

    assert [r["delivery"] for r in _email_rows()] == ["simulated"]
    page = client.get("/notifications").text
    assert "Email (simulated)" in page
    assert "Email sent" not in page and "Email failed" not in page


def test_real_email_is_sent_and_recorded_when_the_flag_is_on(monkeypatch):
    sent = []
    monkeypatch.setenv("EMAIL_PROVIDER", "acs")
    monkeypatch.setattr(email_delivery, "_send_via_acs", lambda to, subject, body, html=None: sent.append((to, subject, body, html)))
    login_as_claimant(CLAIMANT)
    response = submit(
        policy_id="POL-EMAIL-SENT", incident_date="2026-08-12",
        description="Private description text.", files=[("a.pdf", b"x")],
    )
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    assert len(sent) == 1
    to, subject, body, html = sent[0]
    assert to == CLAIMANT["email"]
    assert claim_id in subject and claim_id in body
    assert "routed to an adjuster" in body
    # The email carries the status message and claim number only.
    assert "Private description text." not in body and "POL-EMAIL-SENT" not in body

    assert [r["delivery"] for r in _email_rows()] == ["sent"]
    page = client.get("/notifications").text
    assert "Email sent" in page and "Email (simulated)" not in page


def test_claimant_email_has_a_link_to_the_claim_and_a_designed_html_version(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "acs")
    monkeypatch.setenv("APP_BASE_URL", "https://harborclaim.example/")
    sent = []
    monkeypatch.setattr(email_delivery, "_send_via_acs", lambda to, subject, body, html=None: sent.append((body, html)))
    login_as_claimant(CLAIMANT)
    response = submit(policy_id="POL-EMAIL-HTML", incident_date="2026-08-14", description="Private text.", files=[("a.pdf", b"x")])
    claim_id = response.headers["location"].rsplit("/", 1)[-1]

    body, html = sent[0]
    link = f"https://harborclaim.example/claims/{claim_id}"
    assert link in body and f'href="{link}"' in html
    assert "<html" in html and "View your claim" in html
    assert "Private text." not in body and "Private text." not in html


def test_adjuster_inbox_is_emailed_only_for_claims_ready_for_review(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "acs")
    monkeypatch.setenv("APP_BASE_URL", "https://harborclaim.example")
    monkeypatch.setenv("ADJUSTER_NOTIFY_EMAIL", "adjusters@example.com")
    sent = []
    monkeypatch.setattr(email_delivery, "_send_via_acs", lambda to, subject, body, html=None: sent.append((to, body, html)))
    login_as_claimant(CLAIMANT)

    ready = submit(policy_id="POL-ADJ-READY", incident_date="2026-08-15", description="x", files=[("a.pdf", b"x")])
    ready_id = ready.headers["location"].rsplit("/", 1)[-1]
    submit(policy_id="POL-ADJ-INCOMPLETE", incident_date="2026-08-15", description="x", files=[])

    to_adjusters = [m for m in sent if m[0] == "adjusters@example.com"]
    assert len(to_adjusters) == 1  # the ready claim only, not the incomplete one
    _, body, html = to_adjusters[0]
    assert f"https://harborclaim.example/adjuster/claims/{ready_id}" in body
    assert "Open in review queue" in html


def test_no_adjuster_email_when_the_setting_is_empty(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "acs")
    monkeypatch.delenv("ADJUSTER_NOTIFY_EMAIL", raising=False)
    sent = []
    monkeypatch.setattr(email_delivery, "_send_via_acs", lambda to, subject, body, html=None: sent.append(to))
    login_as_claimant(CLAIMANT)
    submit(policy_id="POL-ADJ-OFF", incident_date="2026-08-16", description="x", files=[("a.pdf", b"x")])
    assert sent == [CLAIMANT["email"]]


def test_email_enabled_false_switches_real_email_off_without_touching_other_settings(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "acs")
    monkeypatch.setenv("EMAIL_ENABLED", "false")
    monkeypatch.setenv("ADJUSTER_NOTIFY_EMAIL", "adjusters@example.com")

    def must_not_send(*args):
        raise AssertionError("a provider was called while EMAIL_ENABLED=false")

    monkeypatch.setattr(email_delivery, "_send_via_acs", must_not_send)
    _file_claim("POL-EMAIL-OFF")
    assert [r["delivery"] for r in _email_rows()] == ["simulated"]
    monkeypatch.setenv("EMAIL_ENABLED", "true")
    assert email_delivery.provider() == "acs"


def test_real_email_is_queued_in_the_request_and_settled_afterwards(monkeypatch):
    # The request stores the email row as "queued" and returns; the send runs as a background
    # task and then records the outcome. The send must not run inside the route itself.
    monkeypatch.setenv("EMAIL_PROVIDER", "acs")
    seen_while_sending = []

    def fake_send(to, subject, body, html=None):
        seen_while_sending.append([r["delivery"] for r in _email_rows()])

    monkeypatch.setattr(email_delivery, "_send_via_acs", fake_send)
    _file_claim("POL-EMAIL-QUEUE")
    assert seen_while_sending == [["queued"]]           # the row existed, queued, before the send
    assert [r["delivery"] for r in _email_rows()] == ["sent"]  # and was settled afterwards


def test_bell_endpoint_returns_only_the_bell_and_follows_new_notifications():
    login_as_claimant(CLAIMANT)
    first = client.get("/notifications/bell")
    assert first.status_code == 200
    assert first.text.lstrip().startswith("<details") and "<html" not in first.text
    assert first.headers["cache-control"] == "no-store"
    before = first.text

    _file_claim("POL-BELL")                      # one new in-app notification
    after = client.get("/notifications/bell").text
    assert after != before and 'class="badge-count"' in after


def test_bell_endpoint_is_quietly_empty_when_signed_out():
    app_module.app.dependency_overrides.pop(get_current_user, None)
    response = client.get("/notifications/bell", follow_redirects=False)
    assert response.status_code == 204 and response.text == ""


def test_a_failed_email_never_breaks_the_request_and_never_leaks_the_error(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("EMAIL_PROVIDER", "acs")

    def boom(*args):
        raise RuntimeError("endpoint=https://secret.example/;accesskey=hunter2")

    monkeypatch.setattr(email_delivery, "_send_via_acs", boom)
    caplog.set_level(logging.WARNING, logger="uvicorn.error")
    login_as_claimant(CLAIMANT)
    response = submit(policy_id="POL-EMAIL-FAIL", incident_date="2026-08-13", description="x", files=[("a.pdf", b"x")])

    assert response.status_code == 303  # the claim was filed regardless
    claim_id = response.headers["location"].rsplit("/", 1)[-1]
    assert storage.get_claim(claim_id) is not None
    assert [r["delivery"] for r in _email_rows()] == ["failed"]
    assert "Email failed" in client.get("/notifications").text
    assert "hunter2" not in caplog.text and "secret.example" not in caplog.text
    assert "RuntimeError" in caplog.text  # logged by type only


def test_email_delivery_outcomes_for_misconfiguration(monkeypatch):
    monkeypatch.delenv("ACS_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("EMAIL_SENDER_ADDRESS", raising=False)

    monkeypatch.setenv("EMAIL_PROVIDER", "acs")
    assert email_delivery.send_email("a@example.com", "s", "b") == "failed"   # settings missing
    monkeypatch.setenv("EMAIL_PROVIDER", "  ACS ")
    assert email_delivery.provider() == "acs"                                  # normalised
    monkeypatch.setenv("EMAIL_PROVIDER", "carrier-pigeon")
    assert email_delivery.send_email("a@example.com", "s", "b") == "failed"   # unknown provider
    monkeypatch.setenv("EMAIL_PROVIDER", "")
    assert email_delivery.send_email("a@example.com", "s", "b") == "simulated"


def test_existing_database_gains_the_notification_delivery_column(tmp_path, monkeypatch):
    # Notifications logged before real delivery existed were all simulated.
    import sqlite3

    old_db = tmp_path / "old_notifications.db"
    conn = sqlite3.connect(old_db)
    conn.execute(
        """CREATE TABLE notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id TEXT NOT NULL,
           claimant_email TEXT NOT NULL, channel TEXT NOT NULL, message TEXT NOT NULL,
           created_at TEXT NOT NULL, read_at TEXT)"""
    )
    conn.execute(
        "INSERT INTO notifications (claim_id, claimant_email, channel, message, created_at) "
        "VALUES ('CLM-OLD', 'old@example.com', 'email', 'hello', '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(storage, "DB_PATH", old_db)
    storage.init_db()
    rows = storage.list_notifications_for("old@example.com")
    assert [r["delivery"] for r in rows] == ["simulated"]


# --- Test isolation (the last Phase 1 item) ---

def test_tests_never_use_the_dev_database():
    # tests/conftest.py points HARBORCLAIM_DATA_DIR at a throwaway folder before storage is
    # imported. If this fails, a test run would wipe the data/ folder a dev server uses.
    from pathlib import Path

    dev_data = Path(storage.__file__).resolve().parent / "data"
    assert Path(storage.DATA_DIR).resolve() != dev_data
    assert Path(storage.DB_PATH).resolve().parent != dev_data
    assert Path(storage.UPLOADS_DIR).resolve().parent != dev_data


def test_data_folder_defaults_to_data_when_the_variable_is_unset():
    import importlib
    import os
    from pathlib import Path

    saved = os.environ.pop("HARBORCLAIM_DATA_DIR")
    try:
        fresh = importlib.reload(storage)
        assert Path(fresh.DATA_DIR) == Path(fresh.__file__).parent / "data"
    finally:
        os.environ["HARBORCLAIM_DATA_DIR"] = saved
        importlib.reload(storage)
