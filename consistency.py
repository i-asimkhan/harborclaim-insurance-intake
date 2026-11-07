"""
Consistency checks by code -- not AI.

Compares the claim form with the facts the keyword scan (extraction.py) found in the
documents, so a mismatch is flagged even when the AI is off or its review failed its checks.
Each finding says what disagrees and what to ask the claimant; it flags, it never decides.

    type_mismatch     the documents describe incidents, and none of them fits the claim type
                      (an auto claim whose notes mention both a collision and an injury is fine)
    date_difference   the documents mention dates, but never the claim form's incident date
"""

from validation import CLAIM_TYPES

# Which claim types each incident label from extraction.INCIDENT_KEYWORDS can belong to.
FITS = {
    "Collision": {"auto", "liability"},
    "Fire": {"property"},
    "Water damage": {"property"},
    "Theft": {"theft", "auto", "property"},
    "Vandalism": {"property", "auto"},
    "Wind/storm": {"property", "auto"},
    "Bodily injury": {"health", "liability"},
}


def _type_label(claim_type: str) -> str:
    return CLAIM_TYPES.get(claim_type, (claim_type,))[0]


def check(record: dict) -> list[dict]:
    """[{"kind", "finding", "ask"}] for one claim record (storage.get_claim)."""
    claim = record["claim"]
    facts = record["facts"]
    findings = []

    claim_type = claim["claim_type"]
    if claim_type in CLAIM_TYPES and claim_type != "other":
        incidents: dict[str, list[str]] = {}
        for f in facts:
            if f["field"] == "incident_type" and f["source"] != "description":
                incidents.setdefault(f["value"], []).append(f["source"])
        if incidents and not any(claim_type in FITS.get(label, set()) for label in incidents):
            described = ", ".join(f"{label.lower()} ({', '.join(dict.fromkeys(src))})" for label, src in incidents.items())
            findings.append({
                "kind": "type_mismatch",
                "finding": f"Filed as {_type_label(claim_type)}, but the documents describe: {described}.",
                "ask": f"Please confirm the claim type. It was filed as {_type_label(claim_type)}, but your "
                       f"documents describe {' and '.join(label.lower() for label in incidents)}.",
            })

    incident_date = claim["incident_date"]
    doc_dates = sorted({f["value"] for f in facts if f["field"] == "mentioned_date" and f["source"] != "description"})
    if incident_date and doc_dates and incident_date not in doc_dates:
        findings.append({
            "kind": "date_difference",
            "finding": f"The claim form gives incident date {incident_date}; the documents mention "
                       f"{', '.join(doc_dates)} but not that date.",
            "ask": f"Please confirm the incident date. The claim form says {incident_date}, but your documents "
                   f"mention {', '.join(doc_dates)}.",
        })
    return findings
