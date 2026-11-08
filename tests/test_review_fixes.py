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
    assert "Ready for review" in _badge(client.get(f"/adjuster/claims/{claim_id}").text)

    _decide(claim_id, "NEEDS_MORE_REVIEW")
    badge = _badge(client.get(f"/adjuster/claims/{claim_id}").text)
    assert "Needs more review" in badge and "Ready for review" not in badge

    _decide(claim_id, "APPROVED")
    assert "Approved" in _badge(client.get(f"/adjuster/claims/{claim_id}").text)
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


# --- 5. Claim data sent to a model: redaction and the data policy ---

import httpx

import agent_tools
import ai_client
import privacy


def test_redact_removes_contact_and_card_details_but_keeps_claim_facts():
    text = ("Call Jordan at (813) 555-0142 or 813.555.0199, email jordan.ellis@example.com. "
            "SSN 123-45-6789. Card 4111 1111 1111 1111. Policy HC-AUTO-1042, claim 1234567812345678, "
            "incident 2026-09-17, estimate $1,450.00.")
    out = privacy.redact(text)
    for gone in ("555-0142", "555.0199", "jordan.ellis@example.com", "123-45-6789", "4111 1111 1111 1111"):
        assert gone not in out
    for kept in ("HC-AUTO-1042", "2026-09-17", "$1,450.00", "1234567812345678", "Jordan"):
        assert kept in out   # a non-card long number, dates, amounts and names stay


def test_agent_sources_are_redacted_for_the_model_and_the_gate_alike():
    claim_id = _file_claim(description="Other driver's number is 813-555-0142; rear-ended on Main St.")
    scope = agent_tools.claim_scope(claim_id)
    assert "813-555-0142" not in scope.sources["description"][0]
    assert "[phone removed]" in scope.sources["description"][0]


def _fake_ok(payload, headers, timeout):
    _fake_ok.payloads.append(payload)
    return httpx.Response(200, json={"model": payload["model"], "choices": [
        {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}], "usage": {}})


def _ai_on(monkeypatch, models, policy):
    monkeypatch.setenv("AI_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("AI_MODELS", models)
    monkeypatch.setenv("AI_DATA_POLICY", policy)
    _fake_ok.payloads = []
    monkeypatch.setattr(ai_client, "_post", _fake_ok)


def test_production_refuses_free_models_without_calling_out(monkeypatch):
    _ai_on(monkeypatch, "nvidia/nemotron-3.5-super-vl:free,openrouter/free", "production")
    result = ai_client.chat([{"role": "user", "content": "hi"}])
    assert not result.ok and result.error_type == "bad_config"
    assert _fake_ok.payloads == []


def test_production_skips_free_models_and_asks_for_no_data_collection(monkeypatch):
    _ai_on(monkeypatch, "nvidia/nemotron-3.5-super-vl:free,vendor/paid-model", "production")
    result = ai_client.chat([{"role": "user", "content": "hi"}])
    assert result.ok and [p["model"] for p in _fake_ok.payloads] == ["vendor/paid-model"]
    assert _fake_ok.payloads[0]["provider"] == {"data_collection": "deny"}


def test_test_policy_keeps_free_models_and_says_so_on_the_ai_page(monkeypatch):
    _ai_on(monkeypatch, "nvidia/nemotron-3.5-super-vl:free", "")
    assert ai_client.chat([{"role": "user", "content": "hi"}]).ok
    assert "provider" not in _fake_ok.payloads[0]
    _adjuster()
    page = client.get("/adjuster/ai").text
    assert "Data policy: <strong>test</strong>" in page and "fictional claims only" in page


# --- 6. Only a final decision notifies the claimant ---

def test_needs_more_review_sends_the_claimant_nothing_but_a_final_decision_does():
    claim_id = _file_claim()
    _adjuster()

    def decision_notices():
        return [n for n in storage.list_notifications_for(CLAIMANT["email"]) if "decision" in n["message"]]

    _decide(claim_id, "NEEDS_MORE_REVIEW", reason="Compare the dates.")
    assert decision_notices() == []
    _decide(claim_id, "APPROVED")
    assert {n["channel"] for n in decision_notices()} == {"in_app", "email"}
    assert all("Approved" in n["message"] for n in decision_notices())


# --- 7. Approving over open review findings needs an acknowledgement ---

REVIEW_WITH_FINDINGS = {
    "summary": [],
    "worth_checking": [
        {"kind": "type_mismatch", "finding": "Claim type Auto, but the notes describe a slip-and-fall.", "citations": []},
        {"kind": "date_difference", "finding": "Form says 2026-10-18; the notes say 2026-09-17.", "citations": []},
    ],
    "missing_or_unclear": ["Medical documentation has not been received."],
}


def _record_review(claim_id, output=REVIEW_WITH_FINDINGS):
    run_id = storage.start_agent_run(claim_id, "intake", "system", "intake-test", model="test-model")
    storage.finish_agent_run(run_id, "passed", output=output, gate={"reasons": []}, trace=[])


def test_approval_over_open_findings_needs_the_box_ticked_and_is_recorded():
    claim_id = _file_claim()
    _record_review(claim_id)
    _adjuster()
    page = client.get(f"/adjuster/claims/{claim_id}").text
    assert 'data-open-findings="3"' in page and 'name="acknowledge"' in page

    refused = _decide(claim_id, "APPROVED")
    assert refused.status_code == 400 and "3 review findings are still open" in refused.text
    assert storage.get_claim(claim_id)["decisions"] == []

    client.post(f"/adjuster/claims/{claim_id}/decision", data={"decision": "APPROVED", "acknowledge": "yes"})
    decision = storage.get_claim(claim_id)["decisions"][0]
    assert decision["decision"] == "APPROVED" and decision["open_findings"] == 3
    assert "3 open findings at the time, acknowledged" in client.get(f"/adjuster/claims/{claim_id}").text


def test_decline_and_more_review_need_no_acknowledgement():
    claim_id = _file_claim()
    _record_review(claim_id)
    _adjuster()
    assert _decide(claim_id, "NEEDS_MORE_REVIEW").status_code == 303
    assert _decide(claim_id, "DECLINED", reason="The injury is not covered by an auto policy.").status_code == 303


def test_no_findings_means_no_box_and_a_plain_approval():
    claim_id = _file_claim()
    _record_review(claim_id, {"summary": [], "worth_checking": [], "missing_or_unclear": []})
    _adjuster()
    assert 'name="acknowledge"' not in client.get(f"/adjuster/claims/{claim_id}").text
    assert _decide(claim_id, "APPROVED").status_code == 303


# --- 14. Consistency checks by code, independent of the AI ---

import consistency

INJURY_NOTES = b"Slip-and-fall on the insured premises on 2026-09-17. Minor wrist injury, treated 2026-09-18."


def _file_typed_claim(claim_type, incident_date, notes, policy_id="POL-CHECK"):
    login_as_claimant(CLAIMANT)
    response = submit(policy_id=policy_id, incident_date=incident_date, claim_type=claim_type,
                      description="Filed for the review test, with notes attached.",
                      files=[("injury_notes.txt", notes)])
    assert response.status_code == 303, response.text
    return response.headers["location"].rsplit("/", 1)[-1]


def test_auto_claim_with_injury_notes_and_another_date_is_flagged_by_code():
    claim_id = _file_typed_claim("auto", "2026-10-18", INJURY_NOTES)
    kinds = {c["kind"]: c for c in consistency.check(storage.get_claim(claim_id))}
    assert set(kinds) == {"type_mismatch", "date_difference"}
    assert "Filed as Auto" in kinds["type_mismatch"]["finding"] and "bodily injury" in kinds["type_mismatch"]["finding"]
    assert "2026-10-18" in kinds["date_difference"]["finding"] and "2026-09-17" in kinds["date_difference"]["finding"]

    _adjuster()
    page = client.get(f"/adjuster/claims/{claim_id}").text
    assert 'id="code_checks"' in page and "HarborClaim's own rules" in page
    # They count as open findings, so approval needs the acknowledgement even with AI off.
    assert 'data-open-findings="2"' in page
    assert _decide(claim_id, "APPROVED").status_code == 400


def test_matching_type_and_date_raise_nothing():
    claim_id = _file_typed_claim("health", "2026-09-17", INJURY_NOTES)
    assert consistency.check(storage.get_claim(claim_id)) == []


def test_an_auto_claim_mentioning_a_collision_and_an_injury_is_not_a_mismatch():
    notes = b"Rear-end collision on 2026-10-18; the driver reported a neck injury."
    claim_id = _file_typed_claim("auto", "2026-10-18", notes)
    assert consistency.check(storage.get_claim(claim_id)) == []


# --- 8. The request drafts ask about what was actually found ---

import agents


def test_template_request_asks_to_confirm_type_and_date_and_for_medical_documents():
    claim_id = _file_typed_claim("auto", "2026-10-18", INJURY_NOTES, policy_id="POL-REQ")
    draft = agents.template_request(storage.get_claim(claim_id))
    assert "Please confirm the claim type" in draft and "bodily injury" in draft
    assert "Please confirm the incident date" in draft and "2026-09-17" in draft
    assert "treatment notes or a medical bill" in draft
    assert "police report" not in draft   # the Auto checklist no longer stands in for the findings


def test_template_request_falls_back_to_the_type_checklist_when_nothing_is_found():
    claim_id = _file_typed_claim("auto", "2026-10-18", b"Rear-end collision on 2026-10-18 on Main St.",
                                 policy_id="POL-REQ-OK")
    draft = agents.template_request(storage.get_claim(claim_id))
    assert "police report" in draft and "confirm" not in draft


def test_request_agent_tool_offers_the_consistency_checks():
    claim_id = _file_typed_claim("auto", "2026-10-18", INJURY_NOTES, policy_id="POL-REQ-TOOL")
    result = agent_tools.get_completeness(agent_tools.claim_scope(claim_id))
    assert {c["kind"] for c in result["consistency_checks"]} == {"type_mismatch", "date_difference"}
    assert "medical bill" in result["documents_that_usually_help"]


# --- 9. Broad questions get an answer; "not found" isn't labelled as checked ---

def test_adjuster_prompt_answers_broad_questions_from_the_sources():
    prompt = agents.ADJUSTER_PROMPT
    assert "what is this about" in prompt and "get_intake_review has the review's summary" in prompt
    assert "only when the sources hold nothing" in prompt
    assert agents.PROMPT_VERSION["adjuster"] == "adjuster-v3"


def test_not_found_answer_is_not_labelled_as_checked_against_the_documents():
    claim_id = _file_claim()
    run_id = storage.start_agent_run(claim_id, "adjuster", "fix.adjuster", "adjuster-v3",
                                     question="What colour was the other car?", model="test-model")
    storage.finish_agent_run(run_id, "passed", output={"answer": [], "not_found": True, "refused": False},
                             gate={"reasons": []}, trace=[])
    _adjuster()
    page = client.get(f"/adjuster/claims/{claim_id}").text
    qa = page[page.index("What colour was the other car?"):]
    qa = qa[:qa.index("</details>")]
    assert "Nothing found in this claim&#39;s records" in qa or "Nothing found in this claim's records" in qa
    assert "Checked against the documents" not in qa


# --- 10. Citations: each source and page once, and they link to the source ---

def test_repeated_citations_collapse_and_link_to_the_source():
    claim_id = _file_typed_claim("auto", "2026-10-18", INJURY_NOTES, policy_id="POL-CITE")
    form = lambda q: {"source": "claim form", "page": 1, "quote": q}
    notes = lambda q: {"source": "injury_notes.txt", "page": 1, "quote": q}
    _record_review(claim_id, {
        "summary": [{"text": "The form lists the policy, date and type.",
                     "citations": [form("Policy ID: POL-CITE"), form("Incident date: 2026-10-18"), form("Claim type: Auto")]},
                    {"text": "The notes describe a fall.",
                     "citations": [notes("Slip-and-fall on the insured premises"), notes("Minor wrist injury, treated")]}],
        "worth_checking": [], "missing_or_unclear": []})
    _adjuster()
    page = client.get(f"/adjuster/claims/{claim_id}").text
    review = page[page.index('id="ai_review"'):]
    first = review[:review.index("</li>")]
    assert first.count("claim form, p. 1") == 1
    assert 'href="#basics"' in first and "Policy ID: POL-CITE / Incident date: 2026-10-18" in first
    assert f'href="/adjuster/claims/{claim_id}/documents/injury_notes.txt#page=1"' in review
    assert review.count("injury_notes.txt, p. 1") == 1
    assert 'id="basics"' in page


# --- 11. "Not summarised" says what it is and where each value was found ---

import agent_gate


def test_not_summarised_items_quote_the_line_they_were_found_on():
    facts = [{"field": "mentioned_date", "value": "2026-09-18", "source": "notes.pdf"},
             {"field": "mentioned_amount", "value": "$1,450.00", "source": "notes.pdf"}]
    sources = {"notes.pdf": ["Slip-and-fall on 2026-09-17.\nFollow-up visit booked for 2026-09-18 at the clinic.\n"
                             "Estimated cost $1,450.00."]}
    output = {"summary": [{"text": "Treatment cost $1,450.00.", "citations": []}], "worth_checking": []}
    items = agent_gate.not_summarised(facts, output, sources)
    assert items == ['2026-09-18 (notes.pdf): "Follow-up visit booked for 2026-09-18 at the clinic."']
    # Without sources the old, bare form is kept.
    assert agent_gate.not_summarised(facts, output) == ["2026-09-18 (notes.pdf)"]


def test_not_summarised_heading_is_plain_english():
    claim_id = _file_claim()
    _record_review(claim_id, {"summary": [], "worth_checking": [], "missing_or_unclear": [],
                              "computed": {"not_summarised": ["2026-09-18 (notes.pdf)"]}})
    _adjuster()
    page = client.get(f"/adjuster/claims/{claim_id}").text
    assert "Dates and amounts the summary doesn't mention" in page and "Not summarised" not in page


# --- 12. Pages show readable statuses, not codes ---

def test_pages_show_status_labels_not_codes():
    claim_id = _file_claim()
    _adjuster()
    _decide(claim_id, "NEEDS_MORE_REVIEW")
    adjuster = client.get(f"/adjuster/claims/{claim_id}").text
    queue = client.get("/adjuster").text
    login_as_claimant(CLAIMANT)
    claimant = client.get(f"/claims/{claim_id}").text
    mine = client.get("/claims").text
    for html in (adjuster, queue, claimant, mine):
        visible = re.sub(r'(value|data-[a-z-]+)="[^"]*"', "", html)   # codes may stay in form values
        visible = re.sub(r"<script.*?</script>", "", visible, flags=re.S)
        for code in ("READY_FOR_REVIEW", "NEEDS_INFORMATION", "NEEDS_MORE_REVIEW"):
            assert code not in visible, code
    assert "<strong>Needs more review</strong>" in adjuster


# --- 13. Intake refuses a description with no real words ---

import validation


def test_keyboard_mash_description_is_refused_at_intake():
    login_as_claimant(CLAIMANT)
    claims_before = len(storage.list_claims())
    response = submit(policy_id="POL-123", incident_date="2026-10-18", description="ggregrrg3wt3g3",
                      files=[("a.pdf", b"x")])
    assert response.status_code in (400, 200) and "Describe what happened in words" in response.text
    assert len(storage.list_claims()) == claims_before


def test_readable_descriptions_pass_and_a_blank_one_is_left_to_the_completeness_check():
    for good in ("Pipe burst in the kitchen.", "I was rear-ended.",
                 "Hit on 2026-09-10 at 5pm, damage $1,850.00 to the bumper."):
        assert validation.description_is_readable(good), good
    for junk in ("ggregrrg3wt3g3", "asdf qwer zxcv", "x", "!!!! ???? ...."):
        assert not validation.description_is_readable(junk), junk
    assert validation.validate_claim_fields("POL-1", "", "") == []   # blank: check_claim reports it missing
