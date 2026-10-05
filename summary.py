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


def generate_summary(claim: dict, facts: list[dict]) -> str:
    amounts = sorted({f["value"] for f in facts if f["field"] == "mentioned_amount"})
    dates = sorted({f["value"] for f in facts if f["field"] == "mentioned_date"})
    incident_types = sorted({f["value"] for f in facts if f["field"] == "incident_type"})
    unread_docs = [f for f in facts if f["field"] == "document_not_processed"]

    lines = [
        f"Policy {claim['policy_id']} -- incident reported {claim['incident_date']}.",
        f"Claimant's description: \"{claim['description']}\"",
    ]

    if incident_types:
        lines.append(f"Incident type(s) mentioned in text: {', '.join(incident_types)}.")
    if amounts:
        lines.append(f"Dollar amounts mentioned in text: {', '.join(amounts)}.")
    if dates:
        lines.append(f"Dates mentioned in text: {', '.join(dates)}.")
    if claim["documents"]:
        lines.append(f"Documents on file: {', '.join(claim['documents'])}.")
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
