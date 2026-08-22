"""Feb-2026 · P22 — PII redaction helper for LLM-bound text.

Backs the Privacy Policy claim (P21, §4):

    "We do NOT send customer names, addresses, or phone numbers to
    LLM providers."

The audit in P22 found 9 call sites that DID interpolate raw customer
PII into LLM prompts. Those sites have been refactored to either:

  * strip the field from the prompt entirely, or
  * substitute a symbolic reference (``[CUSTOMER]``, ``[REVIEWER]``,
    ``[LOCATION]``) and re-inject the real value into the LLM's
    *output* — never its input.

For free-text callers where PII may sneak in incidentally (technician
service notes, admin-authored copilot prompts), ``redact_pii()`` is
applied as defense-in-depth. It scrubs emails and phone numbers with
high-confidence regexes and leaves everything else untouched. Names
are intentionally NOT auto-detected — false-positive rate on names is
too high to be worth the AI-output-quality tradeoff (e.g. redacting
"Marina" would break the AI Concierge's own persona name).

The companion static-grep test
(``tests/test_no_raw_customer_field_in_llm_prompts.py``) fails loudly
if a future dev reintroduces a raw ``customer.name`` / ``.phone`` /
``.email`` interpolation in a file that also touches ``LlmChat``.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional


# Public replacement tokens — stable strings so downstream tests can
# assert against them if needed.
EMAIL_TOKEN = "[EMAIL_REDACTED]"
PHONE_TOKEN = "[PHONE_REDACTED]"
ADDRESS_TOKEN = "[ADDRESS_REDACTED]"


# ── Email ────────────────────────────────────────────────────────────
# Standard RFC-adjacent email pattern. Deliberately conservative — we
# do NOT try to match every exotic RFC-5322 form because the false-
# positive risk on service notes (e.g. "@customer said …") is real.
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
)


# ── Phone ────────────────────────────────────────────────────────────
# Multiple patterns; ordered longest→shortest so E.164 matches BEFORE
# the plain 10-digit form and we don't leave a stray leading "+1".
#
# Covers, in order:
#   1. E.164 international         →  +1 623 555 0100  /  +447700900123
#   2. US grouped w/ separators    →  (623) 555-0100  ·  623-555-0100
#   3. US contiguous 10-digit      →  6235550100
#   4. US w/ leading "1"            →  1-623-555-0100
#
# We do NOT match bare 7-digit local numbers to avoid clobbering
# things like SKU codes or job numbers.
_PHONE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # E.164 (+ country code, 8-15 digits w/ optional spaces/dashes).
    re.compile(r"\+\d{1,3}[\s\-.]?\d{1,4}[\s\-.]?\d{1,4}[\s\-.]?\d{1,9}"),
    # US "1-NPA-NXX-XXXX" and "1 NPA NXX XXXX".
    re.compile(r"\b1[\s\-.]?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b"),
    # US NPA-NXX-XXXX with punctuation OR spaces OR parens.
    re.compile(r"\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b"),
    # Contiguous 10-digit run (last-resort — after the others).
    re.compile(r"\b\d{10}\b"),
)


def redact_pii(
    text: Optional[str],
    address_fields: Optional[Iterable[str]] = None,
) -> str:
    """Return ``text`` with emails, phones, and any explicitly-passed
    address strings scrubbed.

    Parameters
    ----------
    text
        Input string.  ``None`` and empty strings pass through as
        ``""`` — safe to use in f-string interpolation.
    address_fields
        Iterable of *exact* address strings the caller wants redacted
        (e.g. ``[customer.service_address, customer.mailing_address]``).
        Only fields the caller *knows* are addresses are scrubbed.
        We do NOT auto-detect address strings from prose because the
        false-positive rate on service notes is too high.

    Returns
    -------
    str
        Scrubbed text.  Non-string inputs are coerced via ``str()``.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return ""

    # Address pass first — user-supplied strings might contain digits
    # that would otherwise match the phone patterns.
    if address_fields:
        for addr in address_fields:
            if not addr or not isinstance(addr, str):
                continue
            addr_clean = addr.strip()
            if len(addr_clean) < 4:
                continue
            # Case-insensitive literal replace — addresses are stored
            # with varying case in Mongo.
            text = re.sub(re.escape(addr_clean), ADDRESS_TOKEN, text,
                             flags=re.IGNORECASE)

    text = _EMAIL_RE.sub(EMAIL_TOKEN, text)
    for pat in _PHONE_PATTERNS:
        text = pat.sub(PHONE_TOKEN, text)
    return text


__all__ = [
    "redact_pii",
    "EMAIL_TOKEN", "PHONE_TOKEN", "ADDRESS_TOKEN",
]
