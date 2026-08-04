"""Phase 49 · Feb-2026 — Lana intent classification.

Rule-first, LLM-fallback intent extraction. Rule-first because it's fast,
deterministic, and free — an admin who types "add todo: call Alan" should
get the todo without spending an Emergent LLM token or waiting for the
model round-trip.

Intents:
    schedule_job    — "schedule a pool clean for Alan Chesebrough Wednesday at 10am"
    add_todo        — "remind me to call Alan"  (no explicit time)
                     — "add todo: order muriatic acid"
    set_reminder    — "remind me at 3pm to call Alan"
                     — "text me tomorrow at 9 to review the schedule"
    chat            — anything else (falls back to the existing chat path).

The parser is deliberately conservative: any ambiguity → chat. That way
we NEVER accidentally book a real job because the model hallucinated a
customer name. The mobile UI then re-confirms schedule_job intents
before writing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any


@dataclass
class LanaIntent:
    kind: str  # "schedule_job" | "add_todo" | "set_reminder" | "chat"
    args: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return {"kind": self.kind, "args": self.args, "confidence": self.confidence}


_SCHEDULE_RE = re.compile(
    r"^\s*(?:lana[,\s]+)?(?:please\s+)?"
    r"(?:schedule|book|add(?:\s+a)?)\s+"
    r"(?:a\s+)?(?P<service>pool clean|pool cleaning|repair|maintenance|equipment check|"
    r"tile clean|acid wash|drain|filter clean|inspection|service call|visit)\s+"
    r"for\s+(?P<who>.+?)\s+"
    r"(?:on\s+|at\s+|this\s+|next\s+|tomorrow|today|"
    r"(?=(?:mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)))"
    r"(?P<when>.+?)\s*[.!?]?\s*$",
    re.IGNORECASE,
)

_REMINDER_RE = re.compile(
    r"^\s*(?:lana[,\s]+)?"
    r"(?:remind|text|ping|message)\s+(?:me\s+)?"
    r"(?:at|on|in|by|tomorrow|today|next|this)\s+"
    r"(?P<when>.+?)\s+"
    r"(?:to|about|that)\s+"
    r"(?P<what>.+?)\s*[.!?]?\s*$",
    re.IGNORECASE,
)

_TODO_RE = re.compile(
    r"^\s*(?:lana[,\s]+)?"
    r"(?:(?:add|create|new)\s+(?:a\s+)?todo(?:\s+item)?[:\s]+"
    r"|todo[:\s]+"
    r"|remember\s+to\s+"
    r"|remind\s+me\s+to\s+)"
    r"(?P<what>.+?)\s*[.!?]?\s*$",
    re.IGNORECASE,
)


def parse_when(when_str: str, *, now: Optional[datetime] = None) -> Optional[str]:
    """Return an ISO-8601 UTC string or None. Best-effort natural-date
    parsing via ``dateparser``. Timezone: we lean on the process default
    (UTC) — Phase 49 does not yet do per-tenant TZ resolution."""
    try:
        import dateparser
    except ImportError:  # pragma: no cover — requirements.txt guarantees dateparser
        return None
    now = now or datetime.now(timezone.utc)
    parsed = dateparser.parse(
        when_str,
        settings={
            "RELATIVE_BASE": now,
            "PREFER_DATES_FROM": "future",
            "TIMEZONE": "UTC",
            "RETURN_AS_TIMEZONE_AWARE": True,
        },
    )
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def classify(message: str, *, now: Optional[datetime] = None) -> LanaIntent:
    """Classify a single user turn. Rule-first."""
    text = (message or "").strip()
    if not text:
        return LanaIntent("chat", confidence=0.0)

    # 1) set_reminder — must have BOTH a time and an action, matched
    #    verbatim by the pattern.
    m = _REMINDER_RE.match(text)
    if m:
        when_iso = parse_when(m.group("when"), now=now)
        if when_iso:
            return LanaIntent(
                "set_reminder",
                args={"remind_at": when_iso, "text": m.group("what").strip()},
                confidence=0.9,
            )

    # 2) schedule_job — needs service, customer, when — all parseable.
    m = _SCHEDULE_RE.match(text)
    if m:
        when_iso = parse_when(m.group("when"), now=now)
        if when_iso:
            return LanaIntent(
                "schedule_job",
                args={
                    "service_type": _norm_service(m.group("service")),
                    "customer_name": m.group("who").strip(),
                    "scheduled_date": when_iso,
                },
                confidence=0.85,
            )

    # 3) add_todo — action with no parseable time.
    m = _TODO_RE.match(text)
    if m:
        return LanaIntent(
            "add_todo",
            args={"text": m.group("what").strip()},
            confidence=0.8,
        )

    return LanaIntent("chat", confidence=1.0)


def _norm_service(raw: str) -> str:
    s = (raw or "").strip().lower()
    if "clean" in s:
        return "Pool Cleaning"
    if "repair" in s:
        return "Repair"
    if "acid" in s:
        return "Acid Wash"
    if "drain" in s:
        return "Drain"
    if "filter" in s:
        return "Filter Clean"
    if "inspection" in s or "check" in s:
        return "Inspection"
    return raw.title() if raw else "Service Call"


# ── Destructive-intent guard ──────────────────────────────────────────
# Lana is read+create only. If the message mentions delete/cancel/refund
# we bail with a chat response asking the user to do it from the admin
# console. Keeps the surface area of "an LLM can mutate your data"
# deliberately small.
_DESTRUCTIVE_TOKENS = ("delete", "cancel", "refund", "remove", "wipe", "purge")


def looks_destructive(message: str) -> bool:
    low = (message or "").lower()
    return any(tok in low for tok in _DESTRUCTIVE_TOKENS)
