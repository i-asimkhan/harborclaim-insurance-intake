"""
Claim completeness checker -- HarborClaim Insurance Claim Intake System.

Decides whether a submitted claim has enough information to hand to a human
adjuster. It never approves, declines, or pays a claim; that decision stays
out of scope on purpose (per the assignment's pressure test: source documents
and human review remain authoritative, not this checker).
"""

import json

REQUIRED_TEXT_FIELDS = ["policy_id", "incident_date", "description"]

READY_FOR_REVIEW = "READY_FOR_REVIEW"
NEEDS_INFORMATION = "NEEDS_INFORMATION"


def check_claim(claim: dict) -> dict:
    """Check a claim for completeness.

    Returns {"status": READY_FOR_REVIEW | NEEDS_INFORMATION, "missing": [...]}.
    A field is missing if it's absent, not a string, or blank after stripping
    whitespace. "documents" must be a non-empty list.
    """
    missing = []

    for field in REQUIRED_TEXT_FIELDS:
        value = claim.get(field)
        if not isinstance(value, str) or not value.strip():
            missing.append(field)

    documents = claim.get("documents")
    if not isinstance(documents, list) or len(documents) == 0:
        missing.append("documents")

    status = NEEDS_INFORMATION if missing else READY_FOR_REVIEW
    return {"status": status, "missing": missing}


def format_result(claim_id: str, result: dict) -> str:
    if result["status"] == READY_FOR_REVIEW:
        return f"[{claim_id}] {READY_FOR_REVIEW}"
    return f"[{claim_id}] {NEEDS_INFORMATION} -- missing: {', '.join(result['missing'])}"


def run_demo() -> None:
    complete_claim = {
        "claim_id": "CLM-1001",
        "policy_id": "POL-48213",
        "incident_date": "2026-09-10",
        "description": "Rear-end collision in parking lot, minor bumper damage.",
        "documents": ["police_report.pdf", "photos.zip"],
    }

    incomplete_claim = {
        "claim_id": "CLM-1002",
        "policy_id": "POL-77410",
        "incident_date": "",
        "description": "Kitchen fire, water damage to adjoining room.",
        "documents": ["photos.zip"],
    }

    for claim in (complete_claim, incomplete_claim):
        result = check_claim(claim)
        print(format_result(claim["claim_id"], result))
        print(json.dumps(result, indent=2))
        print()


if __name__ == "__main__":
    run_demo()
