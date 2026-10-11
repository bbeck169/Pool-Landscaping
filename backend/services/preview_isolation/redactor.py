"""Preview isolation · free-text redactor.

Pattern-matches and replaces PII tokens WITHIN free-text fields
(``notes``, ``service_notes``, ``description``, ``internal_notes``,
``custom_fields`` values) so admin business text ("Gate code is
4321", "Customer prefers morning service") survives while real
emails / phones / SSNs / CCs / URL-embedded PII query params are
redacted.

Returned string is byte-stable: same input → same output.
"""
from __future__ import annotations

import re
from typing import Any

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
# Phones: liberal — matches ``(602) 555-1234``, ``602.555.1234``,
# ``+1-602-555-1234``, raw 10/11-digit runs. The 4321-style false-
# positive guard: require AT LEAST one hyphen / dot / paren / plus /
# whitespace separator OR a run of 10+ digits. Short raw digit runs
# (gate codes, zip codes, order numbers) pass through.
_PHONE = re.compile(
    r"(?:\+?\d{1,3}[\s.\-]?)?"
    r"(?:\(\d{3}\)|\d{3})[\s.\-]"
    r"\d{3}[\s.\-]\d{4}"
    r"|\b\d{10,11}\b"
)
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# CC — Luhn is overkill for free-text; a 13-19 digit run broken by
# optional spaces/hyphens is enough to catch pasted card numbers.
_CC = re.compile(r"\b(?:\d[\s\-]?){13,19}\b")
# URLs with PII in query params — strip the offending param, keep
# the rest of the URL so documentation links survive.
_URL_PII_PARAM = re.compile(
    r"([?&])(email|phone|ssn|dob|password|token)=[^&\s]+",
    re.IGNORECASE,
)


def redact_free_text(value: Any) -> Any:
    """If ``value`` is a string, apply all redaction passes and
    return the sanitized string. Non-strings pass through unchanged
    (lists / dicts / numbers / None are handled by the caller)."""
    if not isinstance(value, str):
        return value
    out = value
    out = _EMAIL.sub("[redacted-email]", out)
    out = _SSN.sub("[redacted-ssn]", out)
    out = _CC.sub("[redacted-cc]", out)
    out = _PHONE.sub("[redacted-phone]", out)
    # URL PII params: strip the ``email=xxx`` chunk, keep the leading
    # separator so other params stay valid. Re-collapse ``?&`` /
    # ``&&`` leftovers to a single char.
    out = _URL_PII_PARAM.sub(r"\1", out)
    out = re.sub(r"[?&]&", "&", out)
    out = re.sub(r"\?&", "?", out)
    out = re.sub(r"[?&]$", "", out)
    return out


__all__ = ["redact_free_text"]
