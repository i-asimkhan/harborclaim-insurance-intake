"""
What claim data may reach a model, and which models may see it.

Two controls, both applied before anything leaves the app:

1. redact(): contact and financial identifiers are removed from every claim source (document
   text and the description) when the agents' scope is built, in agent_tools.claim_scope. The
   model and the gate read the same redacted sources, so quote checks still line up. This is
   pattern-based: it removes emails, phone numbers, SSNs and card numbers. It does NOT remove
   names, addresses or medical details, which is why the second control exists.

2. The data policy (AI_DATA_POLICY):
     test        (default) any configured model may be used. Free-tier models may log prompts or
                 use them for training, so this is for fictional or test claims only.
     production  real claim data. Free-tier models (":free", and the "openrouter/free" router)
                 are refused, and OpenRouter is asked to route only to providers that don't
                 collect prompt data (provider.data_collection = "deny"). A provider agreement
                 covering retention (and health data, for injury claims) is still needed; this
                 setting can't create one.
"""

import os
import re

TEST = "test"
PRODUCTION = "production"

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# US-style numbers: (813) 555-0142, 813-555-0142, 813.555.0142, +1 813 555 0142. Dates
# (2026-09-17) and amounts ($1,450.00) don't have the 3-3-4 shape, so they're left alone.
_PHONE = re.compile(r"(?<![\w-])(?:\+?1[ .-]?)?(?:\(\d{3}\)\s?|\d{3}[ .-])\d{3}[ .-]\d{4}(?![\w-])")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _card(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group())
    # Only a number that passes the card checksum: a long policy or claim number is kept.
    return "[card number removed]" if 13 <= len(digits) <= 19 and _luhn_ok(digits) else match.group()


def redact(text: str) -> str:
    if not text:
        return text
    text = _EMAIL.sub("[email removed]", text)
    text = _SSN.sub("[SSN removed]", text)
    text = _CARD.sub(_card, text)
    return _PHONE.sub("[phone removed]", text)


def data_policy() -> str:
    value = os.environ.get("AI_DATA_POLICY", "").strip().lower()
    return PRODUCTION if value == PRODUCTION else TEST


def is_free_tier(model: str) -> bool:
    return model.endswith(":free") or model == "openrouter/free"


def model_allowed(model: str) -> bool:
    return not (data_policy() == PRODUCTION and is_free_tier(model))
