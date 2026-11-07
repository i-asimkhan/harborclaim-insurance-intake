"""
Fixes from the adjuster-view review of CLM-6AD24F55: status badge, duplicate and
overwritten decisions, decision reasons, notifications, info-request drafts, citations,
labels, intake validation and the deterministic claim-type check.

    python -m pytest tests/test_review_fixes.py -v
"""

import re

import storage
from tests.test_app import client, CLAIMANT, login_as_adjuster, login_as_claimant, setup_function, submit  # noqa: F401


def _file_claim(policy_id="POL-FIX", description="Rear-ended at a red light on Main St."):
    login_as_claimant(CLAIMANT)
    response = submit(policy_id=policy_id, incident_date="2026-08-10", description=description,
                      files=[("a.pdf", b"x")])
    assert response.status_code == 303, response.text
    return response.headers["location"].rsplit("/", 1)[-1]


def _adjuster(username="fix.adjuster"):
    login_as_adjuster(username, storage.create_adjuster(username))


def _decide(claim_id, decision, reason=""):
    return client.post(f"/adjuster/claims/{claim_id}/decision",
                       data={"decision": decision, "reason": reason}, follow_redirects=False)


def _badge(html):
    return re.search(r'id="claim_status">(.*?)</span>', html, re.S).group(1)


# --- 1. The status badge follows the latest decision ---

def test_badge_shows_intake_status_until_a_decision_then_the_latest_decision():
    claim_id = _file_claim()
    _adjuster()
    assert "READY_FOR_REVIEW" in _badge(client.get(f"/adjuster/claims/{claim_id}").text)

    _decide(claim_id, "NEEDS_MORE_REVIEW")
    badge = _badge(client.get(f"/adjuster/claims/{claim_id}").text)
    assert "NEEDS_MORE_REVIEW" in badge and "READY_FOR_REVIEW" not in badge

    _decide(claim_id, "APPROVED")
    assert "APPROVED" in _badge(client.get(f"/adjuster/claims/{claim_id}").text)
    # The intake status underneath is untouched: the queue and the bell still filter on it.
    assert storage.get_claim(claim_id)["status"] == "READY_FOR_REVIEW"


# --- 2. A repeated decision adds no row and no second notice ---

def test_repeating_the_latest_decision_records_it_once():
    claim_id = _file_claim()
    _adjuster()
    notices_before = len(storage.list_notifications_for(CLAIMANT["email"]))
    _decide(claim_id, "NEEDS_MORE_REVIEW")
    _decide(claim_id, "NEEDS_MORE_REVIEW")   # the 8-second double submit on CLM-6AD24F55
    assert [d["decision"] for d in storage.get_claim(claim_id)["decisions"]] == ["NEEDS_MORE_REVIEW"]
    notices_after = len(storage.list_notifications_for(CLAIMANT["email"]))
    assert notices_after - notices_before <= 2   # at most one notice (in-app + email), never two


def test_more_review_button_is_hidden_once_the_claim_is_marked_for_more_review():
    claim_id = _file_claim()
    _adjuster()
    _decide(claim_id, "NEEDS_MORE_REVIEW")
    page = client.get(f"/adjuster/claims/{claim_id}").text
    assert 'value="NEEDS_MORE_REVIEW"' not in page
    assert 'value="APPROVED"' in page


# --- 3. A final decision can't be overwritten ---

def test_a_final_decision_cannot_be_overwritten():
    claim_id = _file_claim()
    _adjuster()
    _decide(claim_id, "DECLINED", reason="Policy lapsed before the incident date.")
    for later in ("APPROVED", "NEEDS_MORE_REVIEW", "DECLINED"):
        response = _decide(claim_id, later, reason="Trying to change it afterwards.")
        assert response.status_code == 403
        assert "final decision is already recorded" in response.text
    assert [d["decision"] for d in storage.get_claim(claim_id)["decisions"]] == ["DECLINED"]
    page = client.get(f"/adjuster/claims/{claim_id}").text
    assert 'id="decision_final"' in page and 'id="decision_form"' not in page


def test_no_decision_on_an_incomplete_claim_even_by_direct_post():
    login_as_claimant(CLAIMANT)
    response = submit(policy_id="POL-INCOMPLETE", incident_date="", description="Rear-ended at a light.",
                      files=[("a.pdf", b"x")])
    claim_id = response.headers["location"].rsplit("/", 1)[-1]
    _adjuster()
    assert _decide(claim_id, "APPROVED").status_code == 403
    assert storage.get_claim(claim_id)["decisions"] == []


# --- 4. A decision carries a reason; a decline must have one ---

def test_decline_without_a_reason_is_refused():
    claim_id = _file_claim()
    _adjuster()
    for reason in ("", "   ", "too short"):
        response = _decide(claim_id, "DECLINED", reason=reason)
        assert response.status_code == 400 and "needs a written reason" in response.text
    assert storage.get_claim(claim_id)["decisions"] == []


def test_decline_reason_is_stored_shown_and_sent_to_the_claimant():
    claim_id = _file_claim()
    _adjuster()
    reason = "The policy lapsed on 2026-07-31, before the incident date."
    assert _decide(claim_id, "DECLINED", reason=reason).status_code == 303
    assert storage.get_claim(claim_id)["decisions"][0]["reason"] == reason

    adjuster_page = client.get(f"/adjuster/claims/{claim_id}").text
    assert reason in adjuster_page and " UTC" in adjuster_page
    assert any(reason in n["message"] for n in storage.list_notifications_for(CLAIMANT["email"]))
    login_as_claimant(CLAIMANT)
    assert f"Reason: {reason}" in client.get(f"/claims/{claim_id}").text


def test_more_review_reason_stays_internal():
    claim_id = _file_claim()
    _adjuster()
    note = "Check the incident date against the repair invoice."
    _decide(claim_id, "NEEDS_MORE_REVIEW", reason=note)
    assert note in client.get(f"/adjuster/claims/{claim_id}").text
    assert not any(note in n["message"] for n in storage.list_notifications_for(CLAIMANT["email"]))
    login_as_claimant(CLAIMANT)
    assert note not in client.get(f"/claims/{claim_id}").text


def test_reason_is_capped():
    claim_id = _file_claim()
    _adjuster()
    assert _decide(claim_id, "APPROVED", reason="x" * 1001).status_code == 400


def test_existing_decisions_survive_the_reason_migration():
    """A database from before reasons existed: init_db must add the column, not drop the table."""
    claim_id = _file_claim()
    with storage._connect() as conn:
        conn.execute("DROP TABLE adjuster_decisions")
        conn.execute("""CREATE TABLE adjuster_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id TEXT NOT NULL REFERENCES claims(claim_id),
            decision TEXT NOT NULL, adjuster_username TEXT NOT NULL, decided_at TEXT NOT NULL)""")
        conn.execute("INSERT INTO adjuster_decisions (claim_id, decision, adjuster_username, decided_at) "
                     "VALUES (?, 'NEEDS_MORE_REVIEW', 'old.adjuster', '2026-10-18T18:19:30+00:00')", (claim_id,))
    storage.init_db()
    storage.init_db()   # and again: a second startup must not drop it either
    decisions = storage.get_claim(claim_id)["decisions"]
    assert [(d["decision"], d["adjuster_username"], d["reason"]) for d in decisions] == \
        [("NEEDS_MORE_REVIEW", "old.adjuster", None)]
