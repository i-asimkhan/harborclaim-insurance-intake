"""
MOCK summary generator -- HarborClaim.

Assembles an adjuster-facing summary from the claim's own fields plus
whatever extraction.py found, using a fixed text template -- no model call,
nothing generated that isn't a direct restatement of data already on the
claim. See MOCKS.md for what a real version (an LLM call, with citations
back to source documents) would add and why this project stops short of it.

The Design Deliverable's pressure test asks what happens when an AI summary
conflicts with the source documents. The honest answer for *this* summary is
that it can't -- it only ever restates fields that are already stored and
visible on the same page, so there's nothing in it a reviewer can't check in
five seconds against the claim detail and document list right above it.
"""


def _or_not_provided(value, label: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"[{label} not provided]"


def generate_summary(claim: dict, facts: list[dict]) -> str:
    amounts = sorted({f["value"] for f in facts if f["field"] == "mentioned_amount"})
    dates = sorted({f["value"] for f in facts if f["field"] == "mentioned_date"})
    incident_types = sorted({f["value"] for f in facts if f["field"] == "incident_type"})
    unread_docs = [f for f in facts if f["field"] == "document_not_processed"]

    # A missing field is named as missing, never left as a silent blank --
    # an omission in the summary must be visible, not just absent.
    policy_id = _or_not_provided(claim.get("policy_id"), "policy ID")
    incident_date = _or_not_provided(claim.get("incident_date"), "incident date")
    description = claim.get("description")
    lines = [
        f"Policy {policy_id} -- incident reported {incident_date}.",
        f"Claimant's description: \"{description.strip()}\""
        if isinstance(description, str) and description.strip()
        else "Claimant's description: not provided.",
    ]

    # Stated separately from the extracted incident types below, so a mismatch
    # (claimant picked Health, the documents describe a collision) is visible side by side.
    if claim.get("claim_type"):
        lines.append(f"Claim type selected by the claimant: {claim['claim_type']}.")
    if incident_types:
        lines.append(f"Incident type(s) mentioned in text: {', '.join(incident_types)}.")
    if amounts:
        lines.append(f"Dollar amounts mentioned in text: {', '.join(amounts)}.")
    if dates:
        lines.append(f"Dates mentioned in text: {', '.join(dates)}.")
    if claim["documents"]:
        lines.append(f"Documents on file: {', '.join(claim['documents'])}.")
    else:
        lines.append("Documents on file: none provided.")
    if unread_docs:
        lines.append(
            f"Not text-processed by this mock extractor: "
            f"{', '.join(d['source'] for d in unread_docs)} -- open the original file to review."
        )

    lines.append(
        "This summary restates fields already stored on this claim -- every line above is "
        "checkable against the claim detail and document list on this same page."
    )
    return "\n".join(lines)
