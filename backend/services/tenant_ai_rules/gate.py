"""MTH-A · Feb-2026 — Gate helpers.

Two pure-ish helpers that any AI-comms callsite can invoke to
decide whether an AI-driven send should actually fire:

* :func:`resolve_ai_send_gate` — combined master-switch + per-
  employee enable/disable + working-hours check.  Returns
  ``(allowed: bool, reason: str)`` so callers can log the reason.
* :func:`match_escalation` — matches a message against the
  tenant's escalation ruleset (keyword OR regex, opt-in via
  ``is_regex=True``).  Returns the first matching rule or None.

Consumers:
  * ``services.ai_hub.context_stamping.stamp_agent_context`` (MTH-A
    wiring).
  * Future MTH-C AI-employee send paths.
  * MTH-D "test this rule" endpoint.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from config import logger
from services.tenant_ai_rules.resolver import resolve_rules_for_tenant
from services.tenant_ai_rules.schema import DAY_KEYS


def _now_in_tz(tz_name: str,
                 now: Optional[datetime] = None) -> datetime:
    """Return ``now`` in the tenant's timezone.  ``now`` may be
    supplied (aware or naive) for deterministic tests; when naive it
    is treated as UTC."""
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(tz_name)
    except Exception:                                            # noqa: BLE001
        tz = ZoneInfo("UTC")
    if now is None:
        now = datetime.now(tz=tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("UTC"))
    return now.astimezone(tz)


def _within_working_hours(
    working_hours: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Tuple[bool, str]:
    """Return ``(within, reason)``.

    Contract:
      * ``enabled=False`` → always within (rule disabled).
      * No windows for today → not within.
      * ``start <= now_local_time <= end`` for at least one of the
        day's windows → within.
    """
    if not isinstance(working_hours, dict):
        return True, "working_hours_missing_defaults_open"
    if not working_hours.get("enabled", True):
        return True, "working_hours_disabled"
    tz_name = working_hours.get("timezone") or "UTC"
    local = _now_in_tz(tz_name, now)
    day = DAY_KEYS[local.weekday()]
    now_hhmm = local.strftime("%H:%M")
    windows = working_hours.get("windows") or []
    for w in windows:
        if w.get("day") != day:
            continue
        start = w.get("start", "")
        end = w.get("end", "")
        if start and end and start <= now_hhmm <= end:
            return True, f"in_window_{day}_{start}_{end}"
    return False, f"outside_windows_{day}_at_{now_hhmm}_{tz_name}"


async def resolve_ai_send_gate(
    tenant_id: str,
    employee_key: Optional[str],
    *, now: Optional[datetime] = None,
    use_cache: bool = True,
) -> Tuple[bool, str]:
    """Combined gate.

    Order (fail-first):

      1. Master switch — if ``master_ai_send_live_comms=False`` →
         (False, "master_switch_off").
      2. Per-employee flag — if
         ``employee_enable_disable[employee_key]=False`` →
         (False, "employee_disabled").  Unknown employee → same
         result (fail-safe).
      3. Working hours — outside window → (False, "outside_working_hours").
      4. Otherwise → (True, "ok").

    ``employee_key=None`` skips step 2 — useful for platform-level
    tests that only care about the master switch + hours.
    """
    resolved = await resolve_rules_for_tenant(
        tenant_id, use_cache=use_cache,
    )
    if not resolved.get("master_ai_send_live_comms"):
        return False, "master_switch_off"

    rules = resolved.get("rules") or {}
    if employee_key:
        emp_map = rules.get("employee_enable_disable") or {}
        # Missing employee row = disabled (fail-safe).
        if not emp_map.get(employee_key, False):
            return False, "employee_disabled"

    within, reason = _within_working_hours(
        rules.get("working_hours") or {}, now,
    )
    if not within:
        return False, "outside_working_hours"

    return True, "ok"


def match_escalation(
    text: str, escalation_rules: Any,
) -> Optional[Dict[str, Any]]:
    """Return the first escalation rule that fires for ``text``.

    ``escalation_rules`` is the array shape validated by
    :mod:`services.tenant_ai_rules.schema`.  Each rule with
    ``is_regex=True`` is compiled + matched via :meth:`re.search`
    (case-insensitive).  Non-regex rules do a case-insensitive
    substring match.  Compile / eval failures skip the rule with a
    WARN.
    """
    if not isinstance(text, str) or not text:
        return None
    if not isinstance(escalation_rules, list):
        return None
    haystack_lower = text.lower()
    for rule in escalation_rules:
        if not isinstance(rule, dict):
            continue
        keyword = rule.get("keyword")
        if not isinstance(keyword, str) or not keyword:
            continue
        try:
            if rule.get("is_regex"):
                if re.search(keyword, text, re.IGNORECASE):
                    return dict(rule)
            else:
                if keyword.lower() in haystack_lower:
                    return dict(rule)
        except re.error as exc:
            logger.warning(
                "[mth-a] escalation regex compile failed for %r: %s",
                keyword, exc,
            )
            continue
    return None
