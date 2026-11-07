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
