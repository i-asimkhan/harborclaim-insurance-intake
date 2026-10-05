"""
MOCK fact extractor -- HarborClaim.

This is not AI. It reads real text (the claim description, plus the text
layer of any uploaded .pdf/.txt documents, via pypdf for PDFs), then finds
facts in that text with plain regular expressions: dollar amounts, dates,
and a fixed list of incident-type keywords. No model is called, nothing is
inferred beyond what the regex literally matches, and every fact records
which document it came from so a reviewer can check the source directly --
see MOCKS.md for why this is built this way and what a real version would
need instead.

Mirrors the same "mock" boundary the Design Deliverable calls for (AI may
assist with extraction, but it's explicitly optional for the take-home) and
the same shape a classmate's submission used for the same slot in their own
pipeline (regex over uploaded document text, not a model call).
"""

import re
from pathlib import Path

from pypdf import PdfReader

AMOUNT_PATTERN = re.compile(r"\$\s?[\d,]+(?:\.\d{2})?")
DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

INCIDENT_KEYWORDS = {
    "collision": "Collision",
    "rear-end": "Collision",
    "fire": "Fire",
    "water damage": "Water damage",
    "flood": "Water damage",
    "theft": "Theft",
    "stolen": "Theft",
    "vandalism": "Vandalism",
    "windstorm": "Wind/storm",
    "hail": "Wind/storm",
    "injury": "Bodily injury",
}


def _read_document_text(stored_path: Path, content_type: str | None) -> str:
    """Best-effort text read. Returns "" for anything this mock can't read
    (images, zips, unknown binary) -- it does not guess or hallucinate text
    for formats it has no real way to parse.
    """
    suffix = stored_path.suffix.lower()
    try:
        if suffix == ".txt":
            return stored_path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".pdf":
            reader = PdfReader(str(stored_path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""
    return ""


def extract_facts(description: str, documents: list[dict]) -> list[dict]:
    """Returns a list of {"field", "value", "source"} dicts.

    `documents` is the list of document dicts from storage.get_claim()
    (filename, content_type, ...) plus a "stored_path" the caller adds --
    see app.py's call site.
    """
    facts = []

    def scan(text: str, source: str) -> None:
        for match in AMOUNT_PATTERN.finditer(text):
            facts.append({"field": "mentioned_amount", "value": match.group(), "source": source})
        for match in DATE_PATTERN.finditer(text):
            facts.append({"field": "mentioned_date", "value": match.group(), "source": source})
        lowered = text.lower()
        seen_types = set()
        for keyword, label in INCIDENT_KEYWORDS.items():
            if keyword in lowered and label not in seen_types:
                facts.append({"field": "incident_type", "value": label, "source": source})
                seen_types.add(label)

    scan(description, "description")

    for doc in documents:
        stored_path = doc.get("stored_path")
        if not stored_path:
            continue
        path = Path(stored_path)
        text = _read_document_text(path, doc.get("content_type"))
        if text:
            scan(text, doc["filename"])
        else:
            facts.append({
                "field": "document_not_processed",
                "value": f"{doc['filename']} ({doc.get('content_type') or 'unknown type'}) -- "
                         f"this mock only reads .txt and .pdf text",
                "source": doc["filename"],
            })

    return facts
