"""Feb-2026 · MARCO · Sub-phase D — voice-to-task intent parser.

Single-purpose service that turns an admin utterance into a
structured ``ParsedTodo`` (title / due_at / priority / notes) or
``None`` when the utterance is NOT a task-creation intent.

Pipeline
────────
1. Zero-cost heuristic filter — utterances that don't look like a
   task-creation intent short-circuit to None (saves an LLM call
   on every admin turn).
2. Emergent LLM (Claude Sonnet 4.5 via ``call_llm_with_fallback``
   with ``parse_json=True``) — structured extraction.  When the
   JSON is malformed we retry ONCE with a stricter reminder in the
   system prompt.
3. Date resolution via ``dateparser`` — the LLM returns either an
   ISO string OR a natural-language phrase like "tomorrow 3pm";
   we normalize both to a timezone-aware ISO string in the
   caller's timezone (default ``America/New_York`` when the user
   profile lacks a tz).

Priority extraction is done LLM-side but also has a keyword-based
sanity check — "urgent" / "asap" / "critical" override a "med"
default even if the LLM missed the cue.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

try:
    import dateparser                                            # noqa: F401
    _HAS_DATEPARSER = True
except Exception:                                                # noqa: BLE001
    _HAS_DATEPARSER = False

logger = logging.getLogger("services.marco_task_parser")

# ── Constants ─────────────────────────────────────────────────────
DEFAULT_TZ = "America/New_York"

_TODO_INTENT_KEYWORDS = re.compile(
    r"(?:"
    r"\b(?:remind\s+me|remember|schedule|follow[ -]?up|add\s+a?\s*task"
    r"|note\s+to\s+self|todo|to[- ]do|book\s+a|set\s+a\s+reminder"
    r"|remember\s+to)\b"
    # A leading priority marker ("Urgent:", "ASAP -", "Critical,")
    # is a canonical admin dictation pattern that ALSO qualifies as
    # a task-creation intent — the priority word alone isn't enough
    # to justify an LLM call, but paired with a colon / dash /
    # comma it's an unambiguous "queue this up" cue.
    r"|(?:^|\s)(?:urgent|asap|critical|emergency)\s*[:,\-]"
    r")",
    re.IGNORECASE,
)

_URGENT_KEYWORDS = re.compile(
    r"\b(urgent|asap|critical|emergency|right\s+away|immediately)\b",
    re.IGNORECASE,
)
_HIGH_KEYWORDS = re.compile(
    r"\b(high[ -]?priority|priority\s+one|top\s+priority|by\s+end\s+of\s+day)\b",
    re.IGNORECASE,
)
_LOW_KEYWORDS = re.compile(
    r"\b(low[ -]?priority|whenever|no[ -]?rush|when\s+you\s+can)\b",
    re.IGNORECASE,
)

_TITLE_FILLER_PREFIX = re.compile(
    r"^(hey\s+marco[,:]?|marco[,:]?|please[,:]?|remind\s+me\s+to\s+|"
    r"remember\s+to\s+|note\s+to\s+self[,:]?\s*|add\s+a?\s*task[,:]?\s*"
    r"(that\s+says?\s+)?|todo[,:]?\s*|to[- ]do[,:]?\s*|"
    r"follow[ -]?up[,:]?\s*(on\s+)?)+",
    re.IGNORECASE,
)


ParsedTodo = Dict[str, Any]   # {title, due_at, priority, notes}


# ══════════════════════════════════════════════════════════════════
# Public entry point.
# ══════════════════════════════════════════════════════════════════
async def parse_todo_intent(
    utterance: str,
    user_tz: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[ParsedTodo]:
    """Extract a structured todo from ``utterance`` OR return None.

    Args:
        utterance: Raw text from the admin (chat or voice
            transcript).
        user_tz: IANA timezone name.  Defaults to
            ``America/New_York`` when unset.  Relative dates
            ("tomorrow", "EOW", "in 2 hours") resolve against this
            tz.
        now: Reference "now" for relative-date arithmetic.  Only
            used to make tests deterministic — production callers
            pass ``datetime.now(timezone.utc)`` or ``None``.

    Returns:
        Dict with ``title`` (str), ``due_at`` (ISO datetime),
        ``priority`` (low/med/high/urgent), ``notes`` (str), OR
        ``None`` when the utterance isn't a task intent.
    """
    if not utterance or not utterance.strip():
        return None
    tz = user_tz or DEFAULT_TZ
    ref_now = now or datetime.now(timezone.utc)

    # ── Step 1 · heuristic filter ────────────────────────────────
    if not _looks_like_todo_intent(utterance):
        return None

    # ── Step 2 · LLM extraction (with 1 retry on malformed JSON) ─
    llm_parsed = await _llm_extract(utterance, tz, ref_now)
    if not llm_parsed:
        # LLM unreachable / capped / malformed twice.  Try the
        # regex fallback so we at least return SOMETHING for
        # deterministic tests + degraded-mode operation.
        llm_parsed = _regex_fallback(utterance)
        if not llm_parsed:
            return None

    # ── Step 3 · normalise due_at ────────────────────────────────
    due_at_iso = _resolve_due_at(
        llm_parsed.get("due_at"), tz, ref_now,
    )
    if not due_at_iso:
        # If we can't pin a date, refuse — a todo without a due
        # time is not actionable by Sub-phase E's cron.
        return None

    # ── Step 4 · priority coercion + keyword sanity check ───────
    priority = _coerce_priority(
        llm_parsed.get("priority"), utterance,
    )

    # ── Step 5 · clean up the title (strip filler) ──────────────
    title = _clean_title(llm_parsed.get("title") or utterance)
    if not title:
        return None

    return {
        "title": title[:280],
        "due_at": due_at_iso,
        "priority": priority,
        "notes": (llm_parsed.get("notes") or None),
    }


# ══════════════════════════════════════════════════════════════════
# Helpers.
# ══════════════════════════════════════════════════════════════════
def _looks_like_todo_intent(text: str) -> bool:
    """Zero-cost pre-filter.  Any keyword hit + reasonable length
    → considered a candidate.  Under-matches are cheaper than
    over-matches (we'd rather MISS a task than fire an LLM call
    on every "what's the weather" utterance)."""
    if len(text.strip()) < 5:
        return False
    return bool(_TODO_INTENT_KEYWORDS.search(text))


async def _llm_extract(
    utterance: str, tz: str, now: datetime,
) -> Optional[Dict[str, Any]]:
    """Route the utterance through the central AI chokepoint
    (``call_llm_with_fallback`` with ``parse_json=True``).  Returns
    the parsed JSON dict OR None when everything failed.  Retries
    once on malformed JSON with a stricter reminder."""
    try:
        from services.llm_provider import call_llm_with_fallback
    except Exception as _exc:                                    # noqa: BLE001
        logger.warning("[marco-parser] llm_provider import failed: %s", _exc)
        return None

    system_prompt = _build_extractor_system_prompt(tz, now)
    user_text = utterance.strip()

    for attempt in range(2):
        try:
            result = await call_llm_with_fallback(
                system_prompt=system_prompt,
                user_text=user_text,
                provider="anthropic",
                model="claude-sonnet-4-5",
                parse_json=True,
            )
        except Exception as _exc:                                # noqa: BLE001
            logger.warning(
                "[marco-parser] LLM call failed (attempt %s): %s",
                attempt + 1, _exc,
            )
            continue

        if not result or result.get("error"):
            continue

        parsed = result.get("parsed")
        if isinstance(parsed, dict) and parsed:
            # Contract check — must carry a title AND some date
            # hint (either due_at ISO or a natural-language phrase
            # that _resolve_due_at can handle).
            if parsed.get("title") and parsed.get("due_at"):
                return parsed
        # First attempt malformed — reinforce the JSON contract
        # for the retry.
        system_prompt = system_prompt + (
            "\n\n>>> Your previous reply did NOT satisfy the JSON"
            " contract.  Return ONLY a valid JSON object with"
            " title (str), due_at (ISO datetime string), priority"
            " (one of: low, med, high, urgent), notes (str or"
            " empty).  No prose, no markdown fence."
        )
    return None


def _build_extractor_system_prompt(tz: str, now: datetime) -> str:
    now_iso = now.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z",
    )
    return (
        "You are a strict task extractor.  The user is an admin"
        " at a service business dictating a TODO to their"
        " assistant.  Your job is to return a JSON object with the"
        " fields:\n\n"
        "  * title (str): a concise action phrase (5-12 words),"
        " no filler like 'please' or 'remind me'.\n"
        "  * due_at (str): the resolved due date/time as an ISO"
        " 8601 string in the user's timezone."
        f"  User tz = {tz}.  Current time = {now_iso}."
        "  Resolve relative phrases ('tomorrow at 3pm', 'end of"
        " week', 'in 2 hours', 'next Tuesday morning') against"
        " that now.\n"
        "  * priority (str): one of 'low', 'med', 'high',"
        " 'urgent'.  Words like 'urgent' or 'asap' or 'critical'"
        " → 'urgent'.  'High priority' or 'by end of day' →"
        " 'high'.  'Whenever' or 'no rush' → 'low'.  Default"
        " 'med'.\n"
        "  * notes (str): any supplementary detail from the"
        " utterance NOT already captured in title.  Empty string"
        " if none.\n\n"
        "Output ONLY the JSON object.  No prose, no markdown"
        " code fence, no chain-of-thought.  If the utterance"
        " is NOT a task-creation intent, return the JSON literal"
        " ``{}`` (an empty object)."
    )


def _regex_fallback(utterance: str) -> Optional[Dict[str, Any]]:
    """Last-ditch regex parser for when the LLM is unreachable.

    Extracts a rough title + a due-date phrase for
    ``dateparser`` to resolve later.  Priority defaults to 'med'
    unless keyword-flagged.
    """
    # Extract a rough "date phrase" — trailing "tomorrow at 3pm",
    # "in 2 hours", "by end of week", etc.  Extremely permissive.
    _date_hint = re.search(
        r"\b(tomorrow|today|tonight|next\s+\w+|this\s+\w+|in\s+\d+\s+"
        r"(?:minutes?|hours?|days?|weeks?)|end\s+of\s+(?:day|week|month)"
        r"|eow|eod|eom|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
        utterance, re.IGNORECASE,
    )
    if not _date_hint:
        return None
    return {
        "title": utterance,
        "due_at": _date_hint.group(0),
        "priority": "med",
        "notes": "",
    }


def _resolve_due_at(
    due_at_raw: Any, tz: str, now: datetime,
) -> Optional[str]:
    """Normalise a due_at candidate to a tz-aware ISO string.

    Accepts:
      * ISO 8601 strings (with or without tz suffix) — parsed via
        ``datetime.fromisoformat`` first.
      * Natural-language phrases ('tomorrow 3pm', 'in 2 hours',
        'end of week') — resolved via ``dateparser`` with
        ``RELATIVE_BASE=now`` + ``TIMEZONE=tz``.

    Returns the ISO string or None on failure.
    """
    if not due_at_raw:
        return None
    raw = str(due_at_raw).strip()
    if not raw:
        return None

    # Try ISO first (fast path when the LLM cooperates).
    try:
        # datetime.fromisoformat handles ``2026-02-13T15:00:00-05:00``
        # and ``2026-02-13T20:00:00Z`` in Python 3.11.
        cleaned = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            # Assume the caller's tz.
            dt = _localize(dt, tz)
        return dt.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z",
        )
    except (ValueError, TypeError):
        pass

    # Try our idiom pre-resolver for phrases dateparser can't
    # handle natively ("end of month", "eow", "next Tuesday 9am",
    # "this Friday", etc.).  Returns a resolved tz-aware datetime
    # or None.
    idiom_dt = _resolve_idiom_phrase(raw, tz, now)
    if idiom_dt is not None:
        return idiom_dt.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z",
        )

    # Fallback — dateparser.
    if not _HAS_DATEPARSER:
        return None
    import dateparser as _dp
    settings = {
        "RELATIVE_BASE": now.astimezone(timezone.utc).replace(tzinfo=None),
        "TIMEZONE": tz,
        "TO_TIMEZONE": "UTC",
        "PREFER_DATES_FROM": "future",
        "RETURN_AS_TIMEZONE_AWARE": True,
    }
    dt = _dp.parse(raw, settings=settings)
    if not dt:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z",
    )


# ── Idiom resolver ────────────────────────────────────────────────
# ``dateparser`` handles most natural phrases but stumbles on:
#   * "end of month" / "eom"       → last calendar day, 17:00 local
#   * "end of week"  / "eow"       → this-week's Friday, 17:00 local
#   * "end of day"   / "eod"       → today, 17:00 local
#   * "this <weekday>"             → nearest future <weekday>
#   * "next <weekday> [time]"      → the <weekday> AFTER this one
#   * "<weekday> morning/afternoon/evening/night/noon"
#                                   → weekday + canonical time
#
# We normalise these to a datetime directly (skipping dateparser
# entirely) because dateparser's own natural-language coverage of
# these phrases is inconsistent across releases and we need the
# parser to be deterministic for admin dictation.
# ══════════════════════════════════════════════════════════════════
_WEEKDAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_TIME_OF_DAY = {
    "morning": (9, 0),
    "afternoon": (14, 0),
    "evening": (18, 0),
    "night": (21, 0),
    "noon": (12, 0),
    "midnight": (0, 0),
}
_END_OF_MAP = {
    "day": "eod", "eod": "eod",
    "week": "eow", "eow": "eow",
    "month": "eom", "eom": "eom",
}
_TIME_IN_PHRASE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
    re.IGNORECASE,
)


def _resolve_idiom_phrase(
    raw: str, tz: str, now: datetime,
) -> Optional[datetime]:
    """Handle idioms dateparser can't reliably parse.  Returns a
    tz-aware datetime or None to let the caller fall through to
    dateparser."""
    text = raw.strip().lower()

    # Localise "now" to the caller's tz for weekday / month math.
    try:
        from zoneinfo import ZoneInfo
        local_now = now.astimezone(ZoneInfo(tz))
    except Exception:                                            # noqa: BLE001
        local_now = now.astimezone(timezone.utc)

    # ── "end of X" / eod / eow / eom ─────────────────────────────
    m = re.match(
        r"^(?:by\s+)?(?:end\s+of\s+(day|week|month)|(eod|eow|eom))\b",
        text,
    )
    if m:
        key = _END_OF_MAP[(m.group(1) or m.group(2))]
        if key == "eod":
            return local_now.replace(
                hour=17, minute=0, second=0, microsecond=0,
            )
        if key == "eow":
            # Friday of the current week (Mon=0..Fri=4).
            days_ahead = (4 - local_now.weekday()) % 7
            # If it's already Friday afternoon, roll to next Friday
            # so the todo is still in the future.
            if days_ahead == 0 and local_now.hour >= 17:
                days_ahead = 7
            target = local_now + timedelta(days=days_ahead)
            return target.replace(
                hour=17, minute=0, second=0, microsecond=0,
            )
        if key == "eom":
            # Last day of the current month, 17:00 local.
            year, month = local_now.year, local_now.month
            if month == 12:
                next_first = local_now.replace(
                    year=year + 1, month=1, day=1,
                    hour=0, minute=0, second=0, microsecond=0,
                )
            else:
                next_first = local_now.replace(
                    month=month + 1, day=1,
                    hour=0, minute=0, second=0, microsecond=0,
                )
            last_day = next_first - timedelta(days=1)
            return last_day.replace(
                hour=17, minute=0, second=0, microsecond=0,
            )

    # ── "this <weekday> [time]" / "next <weekday> [time]" ────────
    m = re.match(
        r"^(this|next)\s+(monday|tuesday|wednesday|thursday|friday"
        r"|saturday|sunday)\b(.*)$",
        text,
    )
    if m:
        qualifier = m.group(1)
        weekday = _WEEKDAY_NAMES[m.group(2)]
        rest = (m.group(3) or "").strip()
        days_ahead = (weekday - local_now.weekday()) % 7
        # "this <weekday>" — nearest future occurrence (today ok
        # only if the time hasn't passed; we defer that check to
        # the past-date guard).  "next <weekday>" — the weekday
        # AFTER the nearest one, so add 7 when qualifier=='next'
        # and the nearest one is this week.
        if qualifier == "next" and days_ahead == 0:
            days_ahead = 7
        elif qualifier == "this" and days_ahead == 0:
            # Same day — leave as today so time-of-day parsing can
            # still surface a future moment.  Callers reject stale
            # times via the past-date guard.
            pass
        target = local_now + timedelta(days=days_ahead)
        hour, minute = _extract_time_of_day(rest)
        return target.replace(
            hour=hour, minute=minute, second=0, microsecond=0,
        )

    # ── "<weekday> morning/afternoon/evening/night/noon" ─────────
    m = re.match(
        r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r"\s+(morning|afternoon|evening|night|noon|midnight)$",
        text,
    )
    if m:
        weekday = _WEEKDAY_NAMES[m.group(1)]
        hour, minute = _TIME_OF_DAY[m.group(2)]
        days_ahead = (weekday - local_now.weekday()) % 7
        if days_ahead == 0 and (
            local_now.hour, local_now.minute
        ) >= (hour, minute):
            days_ahead = 7
        target = local_now + timedelta(days=days_ahead)
        return target.replace(
            hour=hour, minute=minute, second=0, microsecond=0,
        )

    return None


def _extract_time_of_day(fragment: str) -> tuple[int, int]:
    """Extract HH,MM from a fragment like 'at 9am' or '3:30pm' or
    'morning'.  Defaults to 09:00 when nothing explicit is
    present."""
    fragment = fragment.strip().lstrip("at").strip()
    if not fragment:
        return 9, 0
    for word, (h, m) in _TIME_OF_DAY.items():
        if word in fragment:
            return h, m
    m = _TIME_IN_PHRASE.search(fragment)
    if m:
        h = int(m.group(1))
        minute = int(m.group(2) or 0)
        meridian = m.group(3).lower()
        if meridian == "pm" and h != 12:
            h += 12
        elif meridian == "am" and h == 12:
            h = 0
        return h, minute
    return 9, 0


def _localize(dt: datetime, tz: str) -> datetime:
    """Attach ``tz`` (IANA name) to a naive datetime.  Falls back
    to UTC if ``zoneinfo`` can't resolve the tz."""
    try:
        from zoneinfo import ZoneInfo
        return dt.replace(tzinfo=ZoneInfo(tz))
    except Exception:                                            # noqa: BLE001
        return dt.replace(tzinfo=timezone.utc)


def _coerce_priority(
    llm_priority: Any, utterance: str,
) -> str:
    """Coerce the LLM's priority string + keyword sanity check.

    Precedence: keyword-based UPGRADE only.  If the utterance
    contains 'urgent' but the LLM returned 'med', we bump to
    'urgent'.  Never DOWNGRADE — a cautious LLM label is
    respected.
    """
    valid = {"low", "med", "high", "urgent"}
    p = str(llm_priority or "med").lower().strip()
    if p not in valid:
        p = "med"
    if _URGENT_KEYWORDS.search(utterance):
        return "urgent"
    if _HIGH_KEYWORDS.search(utterance) and p in ("low", "med"):
        return "high"
    if _LOW_KEYWORDS.search(utterance) and p == "med":
        return "low"
    return p


def _clean_title(raw_title: str) -> str:
    t = (raw_title or "").strip()
    # Strip common utterance-filler prefixes iteratively.
    for _ in range(4):
        stripped = _TITLE_FILLER_PREFIX.sub("", t).strip()
        if stripped == t:
            break
        t = stripped
    # Trim trailing punctuation.
    t = re.sub(r"[.!?,;\s]+$", "", t)
    return t


# ══════════════════════════════════════════════════════════════════
# Guard used by the ``create_admin_todo`` tool — reject due_at
# values that landed in the past (>5min lookback tolerance).
# ══════════════════════════════════════════════════════════════════
_PAST_TOLERANCE = timedelta(minutes=5)


def due_at_is_in_past(due_at_iso: str,
                        now: Optional[datetime] = None) -> bool:
    """Return True iff ``due_at_iso`` is more than 5 minutes ago.
    ``dateparser`` resolutions can drift into the past by seconds
    when 'tomorrow' is uttered right after midnight — the 5 min
    tolerance absorbs that jitter."""
    try:
        cleaned = due_at_iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ref = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return dt < (ref - _PAST_TOLERANCE)


# Exposed for tests / callers that want to bypass the LLM.
__all__ = [
    "parse_todo_intent", "due_at_is_in_past",
    "DEFAULT_TZ", "ParsedTodo",
]
