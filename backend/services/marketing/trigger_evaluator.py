"""Feb 2026 · Marketing · Phase 1 — Trigger evaluator + enrollment
time resolver.

The Phase-1 Custom Trigger Builder introduces a richer trigger
schema stored on ``marketing_sequences.trigger``::

    {
      "logic": "AND" | "OR",
      "conditions": [
        {
          "event": "job_completed",
          "delay": {"mode": "after", "value": 3, "unit": "day"},
          "filters": {
            "customer_segment": ["pool"],
            "work_class": ["service"],
            "tags": ["vip"],
            "technician_id": ["<uuid>", ...],
            "crew_id": ["<uuid>", ...],
            "job_value_gte": 500,
            "zip": ["85387", ...],
            "last_visit_gte_days": 30,
            "custom_fields": [{"key": "pool_type", "op": "eq", "value": "salt"}]
          }
        }
      ]
    }

This module exposes two pure primitives:
  * :func:`evaluate_conditions` — returns True iff the trigger
    matches the incoming event payload + hydrated context.
  * :func:`resolve_enrollment_time` — computes the ``next_send_at``
    based on the matched condition's ``delay`` mode.

Both are DB-agnostic (they take a hydrated context dict) so the
enrollment engine can call them from any surface — the domain-
event hook, the daily cron, the ``/preview-matches`` endpoint,
and future automation surfaces (e.g. workflow branches).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


# ─── Delay mode resolver ─────────────────────────────────────────────
_UNIT_TO_SECONDS = {
    "minute": 60,
    "hour":   3600,
    "day":    86400,
    "week":   604800,
}


def _validate_delay(delay: Dict[str, Any]) -> Dict[str, Any]:
    """Return a normalised delay dict or raise ValueError."""
    if not isinstance(delay, dict):
        raise ValueError("delay must be a dict")
    mode = str(delay.get("mode") or "").lower()
    if mode == "immediate":
        return {"mode": "immediate"}
    if mode == "after":
        val = int(delay.get("value") or 0)
        unit = str(delay.get("unit") or "day").lower()
        if unit not in _UNIT_TO_SECONDS:
            raise ValueError(f"invalid delay unit: {unit}")
        if val < 0:
            raise ValueError(f"'after' delay value must be >= 0")
        return {"mode": "after", "value": val, "unit": unit}
    if mode == "before":
        val = int(delay.get("value") or 0)
        if val < 0:
            raise ValueError("'before' delay value must be >= 0")
        # ``before`` only supports days per the Phase-1 spec — the
        # send-window "on_weekday" mode handles finer-grained
        # scheduling.
        return {"mode": "before", "value": val, "unit": "day"}
    if mode == "on_weekday":
        wd = int(delay.get("weekday", 0))
        if wd < 0 or wd > 6:
            raise ValueError("weekday must be 0-6")
        tod = str(delay.get("time_local") or "09:00")
        # Accept "HH:MM" only.
        if ":" not in tod:
            raise ValueError("time_local must be HH:MM")
        return {"mode": "on_weekday", "weekday": wd, "time_local": tod}
    raise ValueError(f"unknown delay mode: {mode!r}")


def resolve_enrollment_time(
    condition: Dict[str, Any],
    event_payload: Dict[str, Any],
    tenant_now: Optional[datetime] = None,
) -> datetime:
    """Given a matched condition + the event payload, return the
    UTC datetime at which the enrolment's first send should fire.

    Arguments
    ---------
    condition
        The matched ``trigger.conditions[i]`` dict.  The ``delay``
        sub-dict drives the return value.
    event_payload
        The normalised event dict.  When the delay mode is
        ``before``, we expect ``event_payload["scheduled_at"]`` to
        be an ISO datetime string — that's the anchor we subtract
        the offset from.  If missing, we fall back to
        ``tenant_now`` so the enrolment still lands (belt +
        braces).
    tenant_now
        Injectable "now" for tests.  Defaults to ``datetime.now(UTC)``.
    """
    now = tenant_now or datetime.now(timezone.utc)
    delay_raw = condition.get("delay") or {"mode": "immediate"}
    delay = _validate_delay(delay_raw)
    mode = delay["mode"]

    if mode == "immediate":
        return now
    if mode == "after":
        secs = int(delay["value"]) * _UNIT_TO_SECONDS[delay["unit"]]
        return now + timedelta(seconds=secs)
    if mode == "before":
        # Anchor on ``event_payload.scheduled_at`` (the event's
        # native scheduled time) — subtract offset days.
        sched = event_payload.get("scheduled_at")
        anchor = _parse_iso(sched) if sched else now
        return anchor - timedelta(days=int(delay["value"]))
    if mode == "on_weekday":
        target_wd = int(delay["weekday"])
        h, m = delay["time_local"].split(":")
        candidate = now.replace(
            hour=int(h), minute=int(m), second=0, microsecond=0,
        )
        # Days-forward to the next matching weekday. If today is
        # the target day but the time is already past, we bump to
        # next week to preserve "next matching window" semantics.
        cur_wd = now.weekday()
        days_ahead = (target_wd - cur_wd) % 7
        if days_ahead == 0 and candidate <= now:
            days_ahead = 7
        return candidate + timedelta(days=days_ahead)
    return now


def _parse_iso(s: Any) -> datetime:
    """Tolerant ISO-8601 parser — accepts ``Z``-suffix + naive
    strings by treating them as UTC."""
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    if not isinstance(s, str):
        return datetime.now(timezone.utc)
    txt = s.strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(txt)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        # Fallback for date-only strings ``YYYY-MM-DD``.
        try:
            return datetime.fromisoformat(txt + "T00:00:00+00:00")
        except Exception:
            return datetime.now(timezone.utc)


# ─── Filter matcher ──────────────────────────────────────────────────
def _matches_list_filter(needle_list: List[str], haystack: Any) -> bool:
    """Membership test tolerant to string/list ``haystack`` shapes."""
    if not needle_list:
        return True
    if haystack is None:
        return False
    if isinstance(haystack, (list, tuple, set)):
        return bool(set(needle_list) & set(haystack))
    return str(haystack) in [str(x) for x in needle_list]


def _matches_custom_field(spec: Dict[str, Any], ctx_fields: Dict[str, Any]) -> bool:
    key = spec.get("key")
    op = str(spec.get("op") or "eq").lower()
    want = spec.get("value")
    if not key:
        return False
    got = ctx_fields.get(key) if isinstance(ctx_fields, dict) else None
    if op == "eq":
        return str(got) == str(want)
    if op == "neq":
        return str(got) != str(want)
    if op == "contains":
        return want is not None and str(want).lower() in str(got or "").lower()
    if op == "gte":
        try:
            return float(got) >= float(want)
        except Exception:
            return False
    if op == "lte":
        try:
            return float(got) <= float(want)
        except Exception:
            return False
    if op == "in":
        needles = want if isinstance(want, (list, tuple)) else [want]
        return str(got) in [str(x) for x in needles]
    return False


def _match_filters(filters: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """Return True iff every filter dim in ``filters`` matches ``ctx``.

    ``ctx`` is the hydrated context shape produced by
    :func:`hydrate_event_ctx` — it exposes flattened keys like
    ``customer_segment``, ``work_class``, ``tags``, ``technician_id``,
    ``crew_id``, ``job_value``, ``zip``, ``last_visit_days_ago``,
    ``custom_fields``.

    Missing filters are treated as "don't care" (pass).  Missing ctx
    fields for a specified filter fail closed (return False) to
    avoid enrolling contacts the customer explicitly excluded.
    """
    if not filters:
        return True

    def _list(k):
        v = filters.get(k)
        if v is None:
            return None
        return list(v) if isinstance(v, (list, tuple)) else [v]

    # 1. customer_segment
    seg = _list("customer_segment")
    if seg and not _matches_list_filter(seg, ctx.get("customer_segment")):
        return False
    # 2. work_class
    wc = _list("work_class")
    if wc and not _matches_list_filter(wc, ctx.get("work_class")):
        return False
    # 3. tags — set intersection.
    tags = _list("tags")
    if tags and not _matches_list_filter(tags, ctx.get("tags")):
        return False
    # 4. technician_id — set intersection.
    tids = _list("technician_id")
    if tids and not _matches_list_filter(tids, ctx.get("technician_id")):
        return False
    # 5. crew_id
    cids = _list("crew_id")
    if cids and not _matches_list_filter(cids, ctx.get("crew_id")):
        return False
    # 6. job_value_gte
    jv_min = filters.get("job_value_gte")
    if jv_min is not None:
        try:
            if float(ctx.get("job_value") or 0) < float(jv_min):
                return False
        except Exception:
            return False
    # 7. zip
    zips = _list("zip")
    if zips and not _matches_list_filter(zips, ctx.get("zip")):
        return False
    # 8. last_visit_gte_days — the customer must have gone AT LEAST
    #    N days without a visit. ``ctx.last_visit_days_ago`` is the
    #    number of days since the last completed job (float).
    lv_min = filters.get("last_visit_gte_days")
    if lv_min is not None:
        try:
            days_since = float(ctx.get("last_visit_days_ago") or 0)
            if days_since < float(lv_min):
                return False
        except Exception:
            return False
    # 9. custom_fields — every spec must match.
    cf_specs = filters.get("custom_fields") or []
    if cf_specs:
        cf_ctx = ctx.get("custom_fields") or {}
        for spec in cf_specs:
            if not _matches_custom_field(spec, cf_ctx):
                return False
    return True


# ─── Top-level trigger evaluator ─────────────────────────────────────
def _condition_matches(
    condition: Dict[str, Any],
    event_payload: Dict[str, Any],
    ctx: Dict[str, Any],
) -> bool:
    """One-condition match — event key equality AND filters pass."""
    from services.marketing.event_registry import canonicalize_event_key
    cond_event = canonicalize_event_key(str(condition.get("event") or ""))
    payload_event = canonicalize_event_key(str(event_payload.get("event") or ""))
    if not cond_event or cond_event != payload_event:
        return False
    return _match_filters(condition.get("filters") or {}, ctx)


def evaluate_conditions(
    trigger: Dict[str, Any],
    event_payload: Dict[str, Any],
    ctx: Dict[str, Any],
) -> bool:
    """Return True iff the trigger's logic combining every condition
    holds.

    ``logic`` defaults to ``"AND"``.  Empty ``conditions[]`` → False
    (no rule to match against; caller should treat as "sequence
    doesn't want to run for this event").
    """
    if not isinstance(trigger, dict):
        return False
    conditions = trigger.get("conditions") or []
    if not conditions:
        return False
    logic = str(trigger.get("logic") or "AND").upper()
    results = [
        _condition_matches(c, event_payload, ctx) for c in conditions
    ]
    if logic == "OR":
        return any(results)
    return all(results)


def find_matching_condition(
    trigger: Dict[str, Any],
    event_payload: Dict[str, Any],
    ctx: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Return the FIRST condition whose ``event`` + ``filters`` match
    the incoming event.  Used by the enrolment engine to pick which
    condition's ``delay`` drives ``next_send_at`` when a trigger
    has multiple conditions across different events (OR logic).

    Returns ``None`` when no condition matches.
    """
    for c in (trigger.get("conditions") or []):
        if _condition_matches(c, event_payload, ctx):
            return c
    return None
