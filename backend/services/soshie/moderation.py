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
from typing import Any, Dict, List, Optional, Tuple


# Very small curated list — expand as real hits accrue.  Kept
# short so we don't pretend to be a full moderation engine; the
# LLM verdict layer (P9) is where real coverage lives.
#
# Phase H7 · Feb-2026 — Every banned phrase is tagged as
# ``high``-confidence, which drives the two-stage regex+LLM combo
# pipeline in :mod:`services.soshie.llm_moderation.moderate_post`
# to short-circuit to ``block`` without spending an LLM call.
BANNED_PHRASES: List[str] = [
    # Legal-risk / regulatory
    "guaranteed", "guarantee results", "risk-free",
    "no risk", "cure", "instant results",
    # Common competitor put-downs (we don't want brand fights)
    "scam", "ripoff", "rip-off", "fraudulent",
    # Off-brand / off-limits for a family services biz
    "clickbait", "dm me", "swipe up now",
]


# Phase H7 · Feb-2026 — Per-pattern confidence tiers. ``high``-
# confidence hits are policy blockers the LLM shouldn't need to
# adjudicate (profanity, legal-risk claims, competitor bashing).
# ``low``-confidence hits are heuristic signals — a phone-number-
# looking substring in "call us at (555) 123-4567" is legitimate
# business content, so we pass those to the LLM as a flag and
# let it make the call.  Every regex pattern in this module MUST
# be classified via one of these confidence tags; the
# ``_confidence_for`` helper is the single source of truth.
_HIGH_CONFIDENCE_SOURCES = frozenset({
    "brand_brain.dont_say",
    "banned_phrases",
})
_LOW_CONFIDENCE_SOURCES = frozenset({
    "email", "phone", "ssn", "credit_card",
})


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


def _confidence_for(flag: Dict[str, str]) -> str:
    """Return ``"high"`` or ``"low"`` for a regex flag. Unknown
    sources default to ``"low"`` — safer default because a
    misclassified block risks over-blocking, while a
    misclassified flag just costs an extra LLM call."""
    src = flag.get("source") or ""
    if src in _HIGH_CONFIDENCE_SOURCES:
        return "high"
    if src in _LOW_CONFIDENCE_SOURCES:
        return "low"
    return "low"


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


# ─── Phase H7 · Two-stage combo pre-decision ──────────────────────────
def prefilter(text: str, *,
                 dont_say: Optional[List[str]] = None,
                 ) -> Tuple[str, List[Dict[str, str]], List[Dict[str, str]]]:
    """Phase H7 · Feb-2026 — Regex pre-decision for the combined
    regex+LLM pipeline.

    Returns ``(pre_decision, high_flags, low_flags)`` where:

        * ``pre_decision`` is one of:
            - ``"block"``   → at least one high-confidence hit;
                                caller should short-circuit and
                                MUST NOT invoke the LLM.
            - ``"flag"``    → no high-confidence hits but at
                                least one low-confidence hit;
                                caller should still run the LLM
                                and take the more conservative of
                                the two decisions.
            - ``"approve"`` → no regex hits at all; LLM is the
                                only remaining source of truth.
        * ``high_flags``: full flag payloads with confidence=``high``.
        * ``low_flags``:  full flag payloads with confidence=``low``.

    The public :func:`moderate` shape is preserved for legacy
    callers — this function is a strictly additive facade.
    """
    result = moderate(text, dont_say=dont_say)
    high: List[Dict[str, str]] = []
    low: List[Dict[str, str]] = []
    for f in result["flags"]:
        (high if _confidence_for(f) == "high" else low).append(f)
    if high:
        return "block", high, low
    if low:
        return "flag", high, low
    return "approve", high, low
