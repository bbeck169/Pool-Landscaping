"""Soshie · Regex-only content-safety gate · Feb-2026 · P1.

Cheap first-line moderation. Runs on every drafted post BEFORE it
lands in the approval queue. Flags:

* Any phrase from ``brand_brain.dont_say`` (case-insensitive match).
* Any phrase from :data:`BANNED_PHRASES` (profanity / legal-risk /
  competitor slur baseline — small curated list).
* PII patterns (email, phone, SSN, credit-card) — accidentally
  leaking a customer's contact info into a social post is
  a real risk.

The LLM verdict layer is deferred to Phase 9 per the ship plan.

Returned shape::
    {"flags": [{"type": str, "match": str, "source": str}, ...],
     "clean": bool}

Callers should treat any non-empty ``flags`` array as
"soft-block" — the action stays ``pending`` with the flags
attached, and requires a second admin acknowledgement before
publishing. Regex hits are stored on the action row so admins
can see them before approving.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# Very small curated list — expand as real hits accrue.  Kept
# short so we don't pretend to be a full moderation engine; the
# LLM verdict layer (P9) is where real coverage lives.
BANNED_PHRASES: List[str] = [
    # Legal-risk / regulatory
    "guaranteed", "guarantee results", "risk-free",
    "no risk", "cure", "instant results",
    # Common competitor put-downs (we don't want brand fights)
    "scam", "ripoff", "rip-off", "fraudulent",
    # Off-brand / off-limits for a family services biz
    "clickbait", "dm me", "swipe up now",
]


# PII patterns — deliberately loose so a marginal match still
# surfaces as a flag for admin review.  Precision matters less
# than recall for a soft-block gate.
_PII_PATTERNS: List[tuple] = [
    ("email",  re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    ("phone",  re.compile(r"\b(?:\+?1[-.\s]?)?"
                             r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("ssn",    re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit_card",
     re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
]


def _match_phrases(text: str, phrases: List[str], *,
                     source: str) -> List[Dict[str, str]]:
    """Case-insensitive substring match — cheap and deterministic.
    A whole-word regex would miss common transformations
    (leetspeak, plural, punctuation) so we lean loose."""
    if not text or not phrases:
        return []
    lowered = text.lower()
    out: List[Dict[str, str]] = []
    for p in phrases:
        key = (p or "").strip().lower()
        if not key:
            continue
        if key in lowered:
            out.append({
                "type": "phrase",
                "match": p,
                "source": source,
            })
    return out


def _match_pii(text: str) -> List[Dict[str, str]]:
    if not text:
        return []
    out: List[Dict[str, str]] = []
    for kind, pat in _PII_PATTERNS:
        for m in pat.finditer(text):
            out.append({
                "type": "pii",
                "match": m.group(0)[:60],
                "source": kind,
            })
    return out


def moderate(text: str, *,
                dont_say: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run all regex layers.  Returns ``{"flags": [...], "clean": bool}``.

    ``dont_say`` should be passed from ``brand_brain.dont_say`` when
    available; None is treated as an empty list."""
    flags: List[Dict[str, str]] = []
    flags += _match_phrases(text, dont_say or [], source="brand_brain.dont_say")
    flags += _match_phrases(text, BANNED_PHRASES, source="banned_phrases")
    flags += _match_pii(text)
    return {"flags": flags, "clean": not flags}
