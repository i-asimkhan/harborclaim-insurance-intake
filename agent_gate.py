"""
The deterministic gate for HarborClaim's Phase 5 agents (docs/design/AGENTS.md, section 6).

Every agent output passes through here before anyone sees it. Pure Python: no model call, no
storage access. Rules:

    G1  output parses, matches the schema's shape exactly (no extra keys), stays within the caps
    G2  every citation names a source on this claim and a page that exists
    G3  every quote is verbatim in that source and page (after normalising case, whitespace,
        quote marks, dashes, bullets), on word boundaries; "..." splits a quote into pieces that
        must appear in order, and the text a quote skips -- or the word just before it -- must not
        be a negation ("not", "no", "never"); a quote (or piece) is at least 4 words, or 2 when it
        contains an amount or a date
    G4  every number in a sentence's own text is supported by that sentence's quotes: "$" amounts
        are compared as cents, YYYY-MM-DD dates as dates, and any other digits must appear in the
        quotes as written; a finding may also use numbers from this run's recorded tool results.
        Dates in other forms, amounts in words, currencies other than "$", "%", "k" and ordinals
        ("the 10th") are unverifiable and flagged; lines with no citations may contain no numbers
    G5  no decision, coverage, payment or accusation wording in the model's own text (quotes
        exempt). Matched on word stems, with a short list of everyday exemptions ("declined
        treatment", "covered with a tarp", "water settled near")
    G6  claimant answers mention only the claimant's own claim IDs (any spelling of CLM-XXXXXXXX)
    G7  claimant answers contain no email address but the claimant's own, written in any form
    G8  no quote or model text carries an instruction-like pattern (possible prompt injection)
    G9  an intake "type_mismatch" finding names a claim type other than the claim form's
    C   claimant answers: no money amounts at all, and decision or payment wording only when this
        run's tool results show that decision (e.g. "Decision recorded: Approved"). A drafted
        request to the claimant (the request agent) is held to C, G5 accusations, G6, G7 and G8 too:
        the claimant will read it, after the adjuster has edited and sent it

check() returns {"status": "passed" | "flagged", "reasons": [{"rule", "where", "detail"}]}.
G1 failures are returned as status "invalid": the harness then ends the run unavailable.

Known limit: the gate checks that numbers come from the cited quotes, not that the sentence
attributes them to the right document ("the police report says $4,240.00" citing both documents
passes). The adjuster sees each citation's source next to the sentence.
"""

import re
import unicodedata

# --- Normalising ------------------------------------------------------------------------------

_CHAR_MAP = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    " ": " ", "·": " ", "•": " ", "‧": " ", "‑": "-",
})


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(_CHAR_MAP)


def normalise(text: str) -> str:
    text = nfkc(text).lower()
    text = re.sub(r"\s*(--|–|—)\s*", " - ", text)
    return re.sub(r"\s+", " ", text).strip()


# --- Numbers ----------------------------------------------------------------------------------

AMOUNT = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?(?![\d.,]*\d)")
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")
_MONTHS = (r"(january|february|march|april|may|june|july|august|september|october|november|december|"
           r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?")
_ORDINAL_WORD = (r"(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|"
                 r"thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|twentieth|"
                 r"thirtieth|(twenty|thirty)[\s-](first|second|third|fourth|fifth|sixth|seventh|eighth|ninth))")
_NUMBER_WORD = (r"(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|"
                r"forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)")
UNVERIFIABLE = re.compile(
    rf"\b{_MONTHS}\s+(the\s+)?{_ORDINAL_WORD}\b|\b{_ORDINAL_WORD}\s+(day\s+)?of\s+{_MONTHS}(?![a-z])"
    rf"|\b{_MONTHS}\s+\d{{1,2}}|\b\d{{1,2}}(st|nd|rd|th)?\s+(of\s+)?{_MONTHS}(?![a-z])"
    rf"|\b\d{{1,2}}(st|nd|rd|th)\b|\b\d{{1,4}}[/.]\d{{1,2}}[/.]\d{{1,4}}\b|\b\d{{4}}-(\d-\d{{1,2}}|\d{{2}}-\d)\b"
    rf"|\b{_NUMBER_WORD}[\s-]+(hundred|thousand|million|dollars?|bucks|usd)\b"
    rf"|\d\s*(%|percent\b|k\b|bucks\b|dollars?\b|usd\b|eur\b|gbp\b)|\b(usd|eur|gbp)\s*\d|[£€¥]\s*\d",
    re.I,
)


def amounts_in(text: str) -> set[int]:
    """Dollar amounts, as cents."""
    cents = set()
    for whole, fraction in AMOUNT.findall(nfkc(text)):
        cents.add(int(whole.replace(",", "")) * 100 + int((fraction or "0").ljust(2, "0")))
    return cents


def dates_in(text: str) -> set[str]:
    return {f"{y}-{m}-{d}" for y, m, d in ISO_DATE.findall(nfkc(text))}


def numbers_in(text: str) -> tuple[set[int], set[str]]:
    return amounts_in(text), dates_in(text)


def other_digits_in(text: str) -> set[str]:
    """Digit runs that are not part of a "$" amount or a YYYY-MM-DD date, commas removed."""
    text = AMOUNT.sub(" ", ISO_DATE.sub(" ", nfkc(text)))
    return {d.replace(",", "").rstrip(".") for d in DIGITS.findall(text)}


def has_any_number(text: str) -> bool:
    return bool(DIGITS.search(nfkc(text))) or bool(UNVERIFIABLE.search(nfkc(text)))


# --- G3: quotes -------------------------------------------------------------------------------

NEGATION = re.compile(r"\b(not|no|never|none|nor|without)\b|n't\b")


def _word_find(haystack: str, needle: str, start: int) -> int:
    """Index of needle in haystack at or after start, on word boundaries; -1 if none."""
    for m in re.finditer(re.escape(needle), haystack[start:]):
        i = start + m.start()
        before = haystack[i - 1] if i > 0 else " "
        j = i + len(needle)
        after = haystack[j] if j < len(haystack) else " "
        if not before.isalnum() and not after.isalnum():
            return i
    return -1


FIELD_QUOTE = re.compile(r"[A-Za-z][A-Za-z ]{0,24}:\s+\S+(\s+\S+)+\.?")


def quote_ok(quote: str, page_text: str) -> bool:
    pieces = [normalise(p).strip(" .,;:\"'") for p in re.split(r"\.\.\.|…", nfkc(quote))]
    pieces = [p for p in pieces if p]
    if not pieces:
        return False
    for piece in pieces:
        # Any digits count, so a short field like "Policy ID: HC-AUTO-1042" (first live run) can be quoted.
        has_number = bool(amounts_in(piece) or dates_in(piece) or re.search(r"\d", piece))
        if len(piece.split()) < (2 if has_number else 4):
            return False
    haystack = normalise(page_text)
    # Try every place the first piece occurs; accept if one reading works end to end.
    start = 0
    while True:
        i = _word_find(haystack, pieces[0], start)
        if i < 0:
            return False
        preceding = haystack[max(0, i - 12):i].split()
        ok = not (preceding and NEGATION.fullmatch(preceding[-1]))
        end = i + len(pieces[0])
        for piece in pieces[1:]:
            if not ok:
                break
            j = _word_find(haystack, piece, end)
            if j < 0 or NEGATION.search(haystack[end:j]):
                ok = False
                break
            end = j + len(piece)
        if ok:
            return True
        start = i + 1


# --- G5, G8 and the claimant rule: wording ----------------------------------------------------

DECISION_STEMS = re.compile(
    r"\bapprov\w*|\bden(y|ies|ied|ial|ials)\b|\breject\w*|\bdeclin\w*|\bsettle(s|d|ment|ments)?\b"
    r"|\breimburs\w*|\bpayment\w*|\bpayable\b|\bpay\s?outs?\b|\bcompensat\w*"
    r"|\bcover(s|ed|age|ages)?\b|\bqualif(y|ies|ied)\s+for\b|\bwarrant(s|ed)?\b|\brecommend\w*"
    r"|\beligib\w*|\bineligib\w*|\bentitle\w*|\baccept(s|ed|ing|ance|able)?\b|\bhono(u)?r(s|ed|ing)?\b"
    r"|\bvalid\s+claim\b",
    re.I,
)
ACCUSATION_STEMS = re.compile(
    r"\bfraud\w*|\bsuspicio\w*|\bstaged\b|\bexaggerat\w*|\binflat\w*|\bpadd(ed|ing)\b|\bfake\w*|\bfalsif\w*"
    r"|\bmisrepresent\w*|\bbogus\b|\bfishy\b|\b(not\s+)?credib\w*|\blegitima\w*|\bdishonest\w*|\bfabricat\w*"
    r"|\bscam\w*|\blying\b|\bliars?\b|\bred\s+flags?\b",
    re.I,
)
# Everyday uses of the stems above that say nothing about a decision.
EXEMPT = re.compile(
    r"\bdeclined\s+(medical\s+|any\s+|further\s+)?(treatment|care|transport|an?\s+ambulance|to\s+\w+)"
    r"|\bcovered\s+(with|in)\b|\bsettled\s+(near|on|in|at|into|under|around|over)\b"
    # Car and building parts (first demo claim: "rear bumper cover").
    r"|\b(bumper|engine|seat|wheel|mirror|drain|vent|roof|floor|pool)\s+covers?\b",
    re.I,
)
INJECTION = re.compile(
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}?\b(instruction|instructions|rules?|above|previous|"
    r"prior|guidance|told|prompt)\b"
    r"|\b(approve|pay|accept|settle)\b.{0,20}?\bclaim\b|\bmark\b.{0,30}?\bas\s+approved\b"
    r"|\b(automated|ai)\s+(reviewers?|review|assistants?|systems?)\s+(should|must|need|are|is)\b"
    r"|\bstatus\s+(to|as)\s+(approved|paid|verified|accepted)\b|\b(record|mark)\b.{0,25}?\bas\s+verified\b"
    r"|\bapproved\s+for\s+payment\b"
    r"|(^|\n)\s*(system|assistant|developer)\s*:|\bsystem prompt\b|\bnew instructions\b|\byou are now\b",
    re.I | re.S,
)
CLAIM_ID_ANY = re.compile(r"\bCLM\W{0,3}([0-9A-F]{8})\b", re.I)
EMAIL_ANY = re.compile(
    r"[\w.+-]+\s*(@|\[at\]|\(at\)|\s+at\s+)\s*[\w-]+\s*(\.|\[dot\]|\(dot\)|\s+dot\s+)\s*[a-z]{2,}", re.I)
PLAIN_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def _without_exemptions(text: str) -> str:
    return EXEMPT.sub(" ", nfkc(text))


def policy_violations(text: str) -> list[str]:
    cleaned = _without_exemptions(text)
    return [m.group(0) for m in DECISION_STEMS.finditer(cleaned)] + \
           [m.group(0) for m in ACCUSATION_STEMS.finditer(cleaned)]


# --- Shapes (G1) ------------------------------------------------------------------------------

LIST_CAPS = {"summary": 8, "worth_checking": 6, "missing_or_unclear": 5, "answer": 6, "items": 5}
FINDING_KINDS = {"amount_difference", "date_difference", "type_mismatch", "missing_document",
                 "prior_claims_on_policy", "other"}
TOP_KEYS = {"intake": {"summary", "worth_checking", "missing_or_unclear"},
            "adjuster": {"answer", "not_found", "refused"}, "claimant": {"answer", "refused"},
            "request": {"message", "items"}}


def _is_citations(value) -> bool:
    return isinstance(value, list) and all(
        isinstance(c, dict) and set(c) == {"source", "page", "quote"} and isinstance(c["source"], str)
        and isinstance(c["quote"], str) and isinstance(c["page"], int) and not isinstance(c["page"], bool)
        for c in value)


def _is_sentence(s, text_key="text", extra=frozenset()) -> bool:
    return (isinstance(s, dict) and set(s) == {text_key, "citations", *extra} and isinstance(s[text_key], str)
            and _is_citations(s["citations"]))


def shape_errors(agent: str, output) -> list[str]:
    if agent not in TOP_KEYS:
        return [f"unknown agent {agent!r}"]
    if not isinstance(output, dict):
        return ["output is not a JSON object"]
    if set(output) != TOP_KEYS[agent]:
        return [f"keys must be exactly {sorted(TOP_KEYS[agent])}"]
    errors = []
    if agent == "intake":
        if not all(isinstance(output[k], list) for k in TOP_KEYS["intake"]):
            return ["summary, worth_checking and missing_or_unclear must be lists"]
        if not output["summary"]:
            # Seen in the first live run: an empty review would otherwise "pass" and be labelled
            # "checked against the documents" with nothing under it.
            errors.append("summary is empty")
        errors += [f"summary[{i}] malformed" for i, s in enumerate(output["summary"]) if not _is_sentence(s)]
        errors += [f"worth_checking[{i}] malformed" for i, f in enumerate(output["worth_checking"])
                   if not (_is_sentence(f, "finding", {"kind"}) and f["kind"] in FINDING_KINDS)]
        if not all(isinstance(m, str) for m in output["missing_or_unclear"]):
            errors.append("missing_or_unclear must be strings")
    elif agent == "adjuster":
        if not isinstance(output["answer"], list) or not isinstance(output["not_found"], bool) \
                or not isinstance(output["refused"], bool):
            return ["answer must be a list; not_found and refused booleans"]
        errors += [f"answer[{i}] malformed" for i, s in enumerate(output["answer"]) if not _is_sentence(s)]
    elif agent == "request":
        if not isinstance(output["message"], str) or not isinstance(output["items"], list) \
                or not all(isinstance(i, str) for i in output["items"]):
            return ["message must be a string; items a list of strings"]
        if not output["message"].strip():
            errors.append("message is empty")
        if len(output["message"]) > 1200 or any(len(i) > 200 for i in output["items"]):
            errors.append("message or an item is too long")
    else:
        if not isinstance(output["answer"], str) or not isinstance(output["refused"], bool):
            return ["answer must be a string; refused a boolean"]
        if len(output["answer"]) > 1200:
            errors.append("answer is too long")
    for key, cap in LIST_CAPS.items():
        if isinstance(output.get(key), list) and len(output[key]) > cap:
            errors.append(f"{key} has {len(output[key])} items (max {cap})")
    return errors


# --- The checks -------------------------------------------------------------------------------

def _reason(rule, where, detail):
    return {"rule": rule, "where": where, "detail": detail}


def _check_wording(where: str, text: str, reasons: list[dict]) -> None:
    for phrase in policy_violations(text):
        reasons.append(_reason("G5", where, f"decision, coverage, payment or accusation wording: {phrase!r}"))
    if INJECTION.search(nfkc(text)):
        reasons.append(_reason("G8", where, "the model's own text looks like an injected instruction"))


def _check_cited(where: str, text: str, citations: list[dict], sources: dict[str, list[str]],
                 tool_numbers: tuple[set, set, set] | None, reasons: list[dict]) -> None:
    quoted_amounts: set[int] = set()
    quoted_dates: set[str] = set()
    quoted_digits: set[str] = set()
    if not citations:
        reasons.append(_reason("G2", where, "no citation"))
    for c in citations:
        pages = sources.get(c["source"])
        if pages is None:
            reasons.append(_reason("G2", where, f"unknown source {c['source']!r}"))
            continue
        if not 1 <= c["page"] <= len(pages):
            reasons.append(_reason("G2", where, f"{c['source']} has no page {c['page']}"))
            continue
        page = pages[c["page"] - 1]
        # The claim form is code-written, one short field per line ("Claim type: Auto"), so a whole
        # line of it is a precise quote even under the word minimum. Documents get no such exception.
        whole_form_line = c["source"] == "claim form" and normalise(c["quote"]).strip(" .") in {
            normalise(line) for line in page.splitlines() if line.strip()}
        # A short labelled field from a document ("Driver: Jordan Ellis", first demo claim) is
        # evidence too: "Label: value", 3 words or more, found verbatim on word boundaries.
        field_quote = bool(FIELD_QUOTE.fullmatch(nfkc(c["quote"]).strip())) and \
            _word_find(normalise(page), normalise(c["quote"]).strip(" ."), 0) >= 0
        if not (whole_form_line or field_quote or quote_ok(c["quote"], page)):
            # Say which: a verbatim but short quote ("Driver: Jordan Ellis", first demo claim) is
            # not the same failure as an invented one.
            found = normalise(c["quote"]).strip(" .,;:\"'") in normalise(page)
            detail = "quote is too short to count as evidence" if found else "quote not found verbatim"
            reasons.append(_reason("G3", where, f"{detail} in {c['source']}: {c['quote'][:80]!r}"))
        if INJECTION.search(nfkc(c["quote"])):
            reasons.append(_reason("G8", where, "quote looks like an injected instruction"))
        quoted_amounts |= amounts_in(c["quote"])
        quoted_dates |= dates_in(c["quote"])
        quoted_digits |= other_digits_in(c["quote"]) | {str(a // 100) for a in amounts_in(c["quote"])}

    extra_amounts, extra_dates, extra_digits = tool_numbers or (set(), set(), set())
    for cents in amounts_in(text) - quoted_amounts - extra_amounts:
        reasons.append(_reason("G4", where, f"${cents / 100:,.2f} is not in the cited quotes"))
    for date in dates_in(text) - quoted_dates - extra_dates:
        reasons.append(_reason("G4", where, f"{date} is not in the cited quotes"))
    # Single-digit counts ("3 line items") are allowed; anything bigger must be in the quotes.
    for digits in other_digits_in(text) - quoted_digits - extra_digits - set("123456789"):
        reasons.append(_reason("G4", where, f"the number {digits} is not in the cited quotes"))
    # A pattern copied word for word from this sentence's own quotes is verified, not invented:
    # "4th Avenue" in a street address (golden set, 2026-11-02) is not a date written as "the 4th".
    quoted_text = " ".join(normalise(c["quote"]) for c in citations)
    if any(normalise(m.group()).rstrip(".") not in quoted_text for m in UNVERIFIABLE.finditer(nfkc(text))):
        reasons.append(_reason("G4", where, "a date or amount is not written as YYYY-MM-DD or $X,XXX.XX"))
    _check_wording(where, text, reasons)


CLAIMANT_DECISION_WORDS = {
    "approved": re.compile(r"\bapprov\w*|\baccept\w*", re.I),
    "declined": re.compile(r"\bdeclin\w*|\bden(y|ies|ied|ial)\b|\breject\w*", re.I),
}
CLAIMANT_MONEY = re.compile(r"\breimburs\w*|\bpa(y|id|ying|yment|yments|yout|youts)\b|\bsettl\w*|\bcompensat\w*"
                            # "check" only as a payment ("your check", "mail a check"); the verb
                            # ("I can check your claims") was blocking every greeting in the first live try.
                            r"|\b(a|your)\s+checks?\b|\bchecks?\s+(will|is|was|has|in\s+the\s+mail)\b"
                            r"|\b(mail|send|sent|issu|cut)\w*\s+(you\s+)?(a\s+)?checks?\b"
                            r"|\bcheques?\b|\bcover(s|ed|age)?\b|\bincluded\s+in\s+your\s+policy\b"
                            r"|\bentitle\w*|\beligib\w*", re.I)


def _check_claimant(text: str, tool_text: str, claimant_email: str | None, own: set[str],
                    reasons: list[dict], where: str = "answer") -> None:
    clean = _without_exemptions(text)
    if amounts_in(clean) or re.search(r"[$£€¥]|\b(usd|dollars?|bucks)\b", clean, re.I):
        reasons.append(_reason("C", where, "a money amount (no claimant tool provides one)"))
    for m in CLAIMANT_MONEY.finditer(clean):
        reasons.append(_reason("C", where, f"payment or coverage wording: {m.group(0)!r}"))
    for decision, pattern in CLAIMANT_DECISION_WORDS.items():
        if pattern.search(clean) and f"decision recorded: {decision}" not in tool_text.lower():
            reasons.append(_reason("C", where, f"says the claim is {decision} without that decision on record"))
    for m in ACCUSATION_STEMS.finditer(clean):
        reasons.append(_reason("G5", where, f"accusation wording: {m.group(0)!r}"))
    if INJECTION.search(clean):
        reasons.append(_reason("G8", where, "looks like an injected instruction"))
    for m in CLAIM_ID_ANY.finditer(clean):
        claim_id = f"CLM-{m.group(1).upper()}"
        if claim_id not in own:
            reasons.append(_reason("G6", where, f"mentions a claim that isn't the claimant's: {claim_id}"))
    for m in EMAIL_ANY.finditer(clean):
        found = re.sub(r"\s+", "", m.group(0)).lower()
        if not claimant_email or found != claimant_email.lower():
            reasons.append(_reason("G7", where, "mentions an email address"))


def check(agent: str, output, *, sources: dict[str, list[str]] | None = None,
          tool_numbers: tuple[set, set, set] | None = None, tool_text: str = "",
          claimant_email: str | None = None, own_claim_ids: set[str] | None = None) -> dict:
    """Run every rule that applies to this agent. `sources` maps each citable source name to its
    pages of text; `tool_numbers` are the ($ cents, dates, other digits) in this run's evidence
    tool results; `tool_text` is the claimant tools' results as text."""
    errors = shape_errors(agent, output)
    if errors:
        return {"status": "invalid", "reasons": [_reason("G1", "output", e) for e in errors]}

    reasons: list[dict] = []
    sources = sources or {}
    if agent == "intake":
        for i, s in enumerate(output["summary"]):
            _check_cited(f"summary[{i}]", s["text"], s["citations"], sources, None, reasons)
        for i, f in enumerate(output["worth_checking"]):
            _check_cited(f"worth_checking[{i}]", f["finding"], f["citations"], sources, tool_numbers, reasons)
            if f["kind"] == "type_mismatch" and not _names_other_type(f["finding"], sources):
                reasons.append(_reason("G9", f"worth_checking[{i}]",
                                       "a type mismatch must name a claim type other than the claim form's"))
        for i, m in enumerate(output["missing_or_unclear"]):
            where = f"missing_or_unclear[{i}]"
            if has_any_number(m):
                reasons.append(_reason("G4", where, "an uncited line may not contain amounts, dates or numbers"))
            _check_wording(where, m, reasons)
    elif agent == "adjuster":
        for i, s in enumerate(output["answer"]):
            _check_cited(f"answer[{i}]", s["text"], s["citations"], sources, tool_numbers, reasons)
    elif agent == "request":
        _check_claimant(output["message"], tool_text, claimant_email, own_claim_ids or set(), reasons, "message")
        for i, item in enumerate(output["items"]):
            _check_claimant(item, tool_text, claimant_email, own_claim_ids or set(), reasons, f"items[{i}]")
    else:
        _check_claimant(output["answer"], tool_text, claimant_email, own_claim_ids or set(), reasons)
    return {"status": "flagged" if reasons else "passed", "reasons": reasons}


# Words that point to each claim type, for G9. "Claim type: X" is a line of the code-written claim form.
TYPE_WORDS = {"auto": r"auto|vehicles?|cars?|collision|traffic|windshield",
              "property": r"property|home|house|roof|kitchen|basement|fence|burglary",
              "health": r"health|injury|injured|medical|clinic|hospital|treatment|urgent care"}


def _names_other_type(finding: str, sources: dict[str, list[str]]) -> bool:
    form = " ".join(sources.get("claim form", [])).lower()
    on_form = next((t for t in TYPE_WORDS if re.search(rf"claim type:\s*{t}", form)), None)
    if on_form is None:
        return True                       # no claim type on the form: nothing to check against
    return any(re.search(rf"\b({words})\b", finding, re.I)
               for t, words in TYPE_WORDS.items() if t != on_form)


def injection_warnings(sources: dict[str, list[str]]) -> list[str]:
    """Sources containing instruction-like text, listed by code at prefetch, so a model that obeys
    such text without quoting it is still visible to the adjuster."""
    return [f"{name} (page {i}) contains text that reads like an instruction to the AI"
            for name, pages in sources.items() for i, text in enumerate(pages, start=1)
            if INJECTION.search(nfkc(text))]


CONTEXT_CHARS = 90


def _context(value: str, pages: list[str] | None) -> str | None:
    """The line a value was found on, shortened around it, so a bare date isn't left unexplained."""
    for page in pages or []:
        for line in page.splitlines():
            i = line.find(value)
            if i >= 0:
                line = " ".join(line.split())
                i = line.find(value)
                start = max(0, i - CONTEXT_CHARS // 2)
                snippet = line[start:start + CONTEXT_CHARS].strip()
                return ("…" if start > 0 else "") + snippet + ("…" if start + CONTEXT_CHARS < len(line) else "")
    return None


def not_summarised(facts: list[dict], output: dict, sources: dict[str, list[str]] | None = None) -> list[str]:
    """Regex-extracted amounts and dates that appear in no summary sentence or finding: shown under
    the summary so an omission is visible (computed by code, not reported by the model). With the
    run's sources, each item also quotes the line it was found on."""
    texts = [s["text"] for s in output.get("summary", [])] + [f["finding"] for f in output.get("worth_checking", [])]
    covered_amounts = set().union(*(amounts_in(t) for t in texts)) if texts else set()
    covered_dates = set().union(*(dates_in(t) for t in texts)) if texts else set()
    missing = []
    for fact in facts:
        uncovered = (fact["field"] == "mentioned_amount" and not amounts_in(fact["value"]) <= covered_amounts) or \
                    (fact["field"] == "mentioned_date" and fact["value"] not in covered_dates)
        if uncovered:
            context = _context(fact["value"], (sources or {}).get(fact["source"]))
            missing.append(f"{fact['value']} ({fact['source']})" + (f': "{context}"' if context else ""))
    return list(dict.fromkeys(missing))
