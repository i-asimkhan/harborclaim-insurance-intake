"""
Read-only tools for HarborClaim's Phase 5 agents (docs/design/AGENTS.md, sections 4 and 5).

Every tool reads through storage.py's read functions only: no SQL, no file paths, and no
function that writes anything (a test enforces both). Scope -- one claim, or one claimant's own
claims -- is set by Python from the route or session and passed in; the model never supplies it.
Model-supplied arguments are validated here before a tool runs.

Tools return plain JSON-able values. "Nothing found" is a normal result, not an error.
"""

import re
from dataclasses import dataclass, field

import storage
from main import READY_FOR_REVIEW
from validation import CLAIM_TYPES

PER_DOCUMENT_CHARS = 12_000
TOTAL_CHARS = 40_000
CLAIM_ID_FORMAT = re.compile(r"^CLM-[0-9A-F]{8}$")
LINE_AMOUNT = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")
LINE_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


class ToolRefused(Exception):
    """Invalid arguments: the harness answers the call with a refusal and doesn't count it."""


@dataclass
class Scope:
    """What a run may touch. Built by Python, never by the model."""
    claim_id: str | None = None
    claimant_email: str | None = None
    record: dict | None = None                                 # storage.get_claim(claim_id)
    sources: dict[str, list[str]] = field(default_factory=dict)  # citable source -> pages of text
    not_read: list[str] = field(default_factory=list)            # unreadable or truncated, for the page


# --- Prefetch: the fixed, non-agentic part ----------------------------------------------------

def claim_form_text(claim: dict) -> str:
    type_label = CLAIM_TYPES.get(claim["claim_type"], (claim["claim_type"],))[0]
    return (f"Policy ID: {claim['policy_id'] or '(not provided)'}\n"
            f"Incident date: {claim['incident_date'] or '(not provided)'}\n"
            f"Claim type: {type_label}")


def claim_scope(claim_id: str) -> Scope | None:
    """The scope for the intake and adjuster agents: one claim, its fields and its documents' text."""
    record = storage.get_claim(claim_id)
    if record is None:
        return None
    claim = record["claim"]
    scope = Scope(claim_id=claim_id, record=record)
    scope.sources["claim form"] = [claim_form_text(claim)]
    scope.sources["description"] = [claim["description"] or "(no description given)"]
    budget = TOTAL_CHARS
    for doc in record["documents"]:
        pages = storage.read_document_pages(claim_id, doc["filename"]) or []
        if not any(p.strip() for p in pages):
            scope.not_read.append(f"{doc['filename']} -- not readable as text; open the original")
            continue
        kept, used = [], 0
        for page in pages:
            room = min(PER_DOCUMENT_CHARS - used, budget)
            if room <= 0:
                break
            kept.append(page[:room])
            used += len(kept[-1])
            budget -= len(kept[-1])
        if sum(len(p) for p in kept) < sum(len(p) for p in pages):
            scope.not_read.append(f"{doc['filename']} -- only partly read (too long); open the original")
        scope.sources[doc["filename"]] = kept
    return scope


def claimant_scope(claimant_email: str) -> Scope:
    return Scope(claimant_email=claimant_email)


def context_text(scope: Scope) -> str:
    """The prefetched claim, as the model sees it."""
    parts = []
    for name, pages in scope.sources.items():
        for number, text in enumerate(pages, start=1):
            parts.append(f"=== SOURCE: {name} | PAGE {number} ===\n{text}")
    if scope.not_read:
        parts.append("=== NOT READ ===\n" + "\n".join(scope.not_read))
    facts = scope.record["facts"] if scope.record else []
    if facts:
        parts.append("=== AUTOMATED EXTRACTION (regex, not AI) ===\n"
                     + "\n".join(f"{f['field']}: {f['value']} ({f['source']})" for f in facts))
    claim_type = scope.record["claim"]["claim_type"] if scope.record else None
    if claim_type in CLAIM_TYPES:
        parts.append(f"=== DOCUMENT HINT FOR THIS CLAIM TYPE ===\n{CLAIM_TYPES[claim_type][1]}")
    return "\n\n".join(parts)


# --- Intake tools -----------------------------------------------------------------------------

def _lines(scope: Scope):
    for name, pages in scope.sources.items():
        for number, text in enumerate(pages, start=1):
            for line in text.splitlines():
                if line.strip():
                    yield name, number, line.strip()


def _sentences(scope: Scope):
    """Whole sentences per page: PDF line breaks fall mid-sentence, so search passages and their
    citations are built from sentences, not lines."""
    for name, pages in scope.sources.items():
        for number, text in enumerate(pages, start=1):
            flat = re.sub(r"\s+", " ", text).strip()
            for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9$])", flat):
                if sentence.strip():
                    yield name, number, sentence.strip()


def list_amounts(scope: Scope) -> list[dict]:
    """Every dollar amount, with its source, page and the line it sits on. Lists, never judges."""
    return [{"amount": m, "source": name, "page": page, "line": line}
            for name, page, line in _lines(scope) for m in LINE_AMOUNT.findall(line)]


def list_dates(scope: Scope) -> dict:
    """Every date, with its source, page and line, plus the claimed incident date."""
    found = [{"date": m, "source": name, "page": page, "line": line}
             for name, page, line in _lines(scope) for m in LINE_DATE.findall(line)]
    return {"claimed_incident_date": scope.record["claim"]["incident_date"] or None, "dates": found}


def find_claims_for_policy(scope: Scope) -> dict:
    """Other claims on the same policy: count and filed dates only."""
    policy_id = scope.record["claim"]["policy_id"]
    if not policy_id:
        return {"policy_id": None, "other_claims": 0, "filed": []}
    others = [c for c in storage.claims_for_policy(policy_id) if c["claim_id"] != scope.claim_id]
    return {"policy_id": policy_id, "other_claims": len(others), "filed": [c["created_at"][:10] for c in others]}


# --- Adjuster tools ---------------------------------------------------------------------------

def _source_arg(scope: Scope, source) -> str:
    if not isinstance(source, str) or source not in scope.sources:
        raise ToolRefused(f"source must be one of: {', '.join(scope.sources)}")
    return source


def read_document(scope: Scope, source, page=None) -> dict:
    name = _source_arg(scope, source)
    pages = scope.sources[name]
    if page is None:
        return {"source": name, "pages": [{"page": i, "text": t} for i, t in enumerate(pages, start=1)]}
    if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= len(pages):
        raise ToolRefused(f"{name} has pages 1 to {len(pages)}")
    return {"source": name, "pages": [{"page": page, "text": pages[page - 1]}]}


def search_documents(scope: Scope, query) -> list[dict]:
    """Sentences sharing the most words with the query; keyword scoring, no embeddings."""
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ToolRefused("query must be 1 to 200 characters")
    words = {w for w in re.findall(r"[a-z0-9$]+", query.lower()) if len(w) > 2}
    scored = []
    for name, page, sentence in _sentences(scope):
        score = len(words & set(re.findall(r"[a-z0-9$]+", sentence.lower())))
        if score:
            scored.append((score, {"source": name, "page": page, "passage": sentence}))
    scored.sort(key=lambda s: -s[0])
    return [hit for _, hit in scored[:8]]


def get_intake_review(scope: Scope) -> dict:
    run = storage.latest_finished_agent_run(scope.claim_id, "intake")
    if run is None or run["output"] is None:
        return {"available": False}
    return {"available": True, "gate_status": run["status"], "review": run["output"]}


# --- Claimant tools ---------------------------------------------------------------------------

def _own_claim(scope: Scope, claim_id) -> dict | None:
    if not isinstance(claim_id, str) or not CLAIM_ID_FORMAT.match(claim_id):
        raise ToolRefused("claim_id looks like CLM- followed by 8 characters, e.g. CLM-1A2B3C4D")
    record = storage.get_claim(claim_id)
    if record is None or record["claim"]["claimant_email"] != scope.claimant_email:
        return None  # the same answer for "not yours" and "doesn't exist"
    return record


def _progress(record: dict) -> str:
    latest = record["decisions"][-1]["decision"] if record["decisions"] else None
    if latest in ("APPROVED", "DECLINED"):
        return f"Decision recorded: {latest.title()}"
    if record["status"] == READY_FOR_REVIEW:
        return "With an adjuster for review"
    return "Waiting for missing information from you"


def list_my_claims(scope: Scope) -> list[dict]:
    return [{"claim_id": r["claim"]["claim_id"],
             "claim_type": CLAIM_TYPES.get(r["claim"]["claim_type"], (r["claim"]["claim_type"],))[0],
             "filed": r["history"][0]["at"][:10], "progress": _progress(r)}
            for r in storage.list_claims_for(scope.claimant_email)]


def get_claim_status(scope: Scope, claim_id) -> dict:
    record = _own_claim(scope, claim_id)
    if record is None:
        return {"found": False}
    return {"found": True, "claim_id": claim_id, "progress": _progress(record)}


def get_missing_items(scope: Scope, claim_id) -> dict:
    record = _own_claim(scope, claim_id)
    if record is None:
        return {"found": False}
    words = {"policy_id": "policy ID", "incident_date": "incident date", "description": "description of what happened",
             "documents": "at least one supporting document"}
    return {"found": True, "missing": [words.get(m, m) for m in record["missing"]]}


def get_document_hints(scope: Scope, claim_type) -> dict:
    if not isinstance(claim_type, str) or claim_type.lower() not in CLAIM_TYPES:
        raise ToolRefused(f"claim_type must be one of: {', '.join(CLAIM_TYPES)}")
    label, hint = CLAIM_TYPES[claim_type.lower()]
    return {"claim_type": label, "hint": hint}


# --- Specs: what the model sees, per charter --------------------------------------------------

def _spec(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or [],
                       "additionalProperties": False}}}


TOOLS = {
    "intake": {
        "list_amounts": (list_amounts, _spec(
            "list_amounts", "Every dollar amount in this claim's sources, each with its source, page and line.")),
        "list_dates": (list_dates, _spec(
            "list_dates", "Every date in this claim's sources, each with its source, page and line, "
                          "plus the claimed incident date.")),
        "find_claims_for_policy": (find_claims_for_policy, _spec(
            "find_claims_for_policy", "How many other claims exist on this claim's policy, and when they were filed.")),
    },
    "adjuster": {
        "search_documents": (search_documents, _spec(
            "search_documents", "Find passages in this claim's sources that match a few keywords.",
            {"query": {"type": "string", "description": "a few keywords"}}, ["query"])),
        "read_document": (read_document, _spec(
            "read_document", "Read one of this claim's sources, all pages or one page.",
            {"source": {"type": "string"}, "page": {"type": "integer"}}, ["source"])),
        "get_intake_review": (get_intake_review, _spec(
            "get_intake_review", "The latest automated intake review of this claim and whether it passed checks.")),
    },
    "claimant": {
        "list_my_claims": (list_my_claims, _spec("list_my_claims", "The signed-in claimant's own claims.")),
        "get_claim_status": (get_claim_status, _spec(
            "get_claim_status", "Where one of the claimant's own claims stands.",
            {"claim_id": {"type": "string"}}, ["claim_id"])),
        "get_missing_items": (get_missing_items, _spec(
            "get_missing_items", "What is still missing from one of the claimant's own claims.",
            {"claim_id": {"type": "string"}}, ["claim_id"])),
        "get_document_hints": (get_document_hints, _spec(
            "get_document_hints", "Which documents usually help for a claim type.",
            {"claim_type": {"type": "string", "enum": list(CLAIM_TYPES)}}, ["claim_type"])),
    },
}
