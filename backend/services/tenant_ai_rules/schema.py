"""MTH-A · Feb-2026 — Rule-engine schema, action inventory, defaults,
validation.

Everything in this module is pure data + pure functions.  No DB
access.  Callers: ``store`` (persistence), ``resolver`` (merge),
``routers/tenant_ai_rules`` (payload validation).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from services.ai_hub.employee_registry import EMPLOYEES


# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

MAX_DOC_SIZE_BYTES: int = 50 * 1024                 # 50 KiB per brief
MIN_REASON_LEN: int = 8                             # HD-A convention

RULE_CATEGORIES: Tuple[str, ...] = (
    "tone_voice",
    "auto_action_allowlist",
    "employee_enable_disable",
    "working_hours",
    "escalation_rules",
)

TONE_STYLES: Tuple[str, ...] = ("formal", "friendly", "technical")
ALLOWLIST_MODES: Tuple[str, ...] = ("auto", "admin_approval")
ESCALATION_ROLES: Tuple[str, ...] = ("admin", "super")
ESCALATION_CHANNELS: Tuple[str, ...] = ("email", "sms", "both")
DAY_KEYS: Tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri",
                              "sat", "sun")

# ═══════════════════════════════════════════════════════════════════
# Action inventory
#
# Grep-inventoried from:
#   backend/services/marco/actions.py::ACTION_REGISTRY
#   backend/services/ai_employee_tools.py::TOOL_REGISTRY
#   backend/routers/ai_employees.py (CASEY/EMMIE/BUDDY/VIZZY/DEXTER/
#                                       SOSHIE/SCOUTY/COMMET action sets)
#
# Default policy per brief: ``admin_approval`` for every action —
# safety-first. Admins flip individual actions to ``auto`` via
# ``PUT /api/tenant-ai-rules/auto_action_allowlist``.
# ═══════════════════════════════════════════════════════════════════

# MARCO — voice / chat action-parser registry (write ops).
_MARCO_ACTIONS: Tuple[str, ...] = (
    "marco.clock_in",
    "marco.clock_out",
    "marco.add_line_item",
    "marco.save_note",
)

# MARCO — orchestrator tool registry (mostly reads + create_admin_todo
# + delegate_task).  Included so admins can require approval on the
# admin-write tools if they prefer.
_MARCO_TOOLS: Tuple[str, ...] = (
    "marco.lookup_customer",
    "marco.lookup_invoices",
    "marco.lookup_invoice_detail",
    "marco.lookup_next_visit",
    "marco.lookup_service_history",
    "marco.lookup_balance",
    "marco.lookup_schedule",
    "marco.search_customers",
    "marco.delegate_task",
    "marco.create_admin_todo",
)

# AI Employees — specialist actions from ai_employees.py.
_EMPLOYEE_ACTIONS: Tuple[str, ...] = (
    # Casey — visibility copilot.
    "casey.draft_directory_submission",
    "casey.suggest_directory_updates",
    "casey.draft_outreach_reply",
    # Emmie — email marketing.
    "emmie.draft_campaign",
    "emmie.suggest_ab_subjects",
    "emmie.analyze_campaign",
    "emmie.suggest_seasonal_ideas",
    "emmie.rewrite_copy",
    # Buddy / Vizzy / Dexter — analytics trio.
    "buddy.weekly_growth_brief",
    "buddy.pipeline_analysis",
    "buddy.pricing_recommendation",
    "buddy.marketing_weekly_recap",
    "vizzy.daily_brief",
    "vizzy.prep_call",
    "vizzy.prioritize_today",
    "vizzy.top_performing_sequences",
    "dexter.ad_hoc_query",
    "dexter.top_customers_report",
    "dexter.chemical_profitability_report",
    "dexter.review_pipeline_health",
    # Soshie / Scouty / Commet.
    "soshie.draft_post",
    "soshie.publish_blog",
    "soshie.schedule_post",
    "soshie.suggest_content_calendar",
    "soshie.analyze_engagement",
    "soshie.hashtag_research",
    "scouty.draft_job_posting",
    "scouty.screen_resume",
    "scouty.suggest_interview_questions",
    "scouty.generate_offer_letter",
    "scouty.pipeline_summary",
    "commet.draft_funnel_copy",
    "commet.analyze_conversion",
    "commet.suggest_ab_variants",
    "commet.recommend_cta_changes",
    "commet.funnel_stage_report",
    # SO-A · Feb-2026 — DISPATCH (Diana) actions.  ``schedule_recommendation``
    # is the read-only recommendation-synthesis action (always auto in
    # practice — it's a suggestion, not a mutation); ``reassign`` is the
    # apply-optimization mutator that admins gate via allowlist.
    "dispatch.schedule_recommendation",
    "dispatch.reassign",
)

ACTION_INVENTORY: Tuple[str, ...] = tuple(sorted(
    set(_MARCO_ACTIONS) | set(_MARCO_TOOLS) | set(_EMPLOYEE_ACTIONS)
))

# Employees — snapshot the 18-employee registry.
EMPLOYEE_KEYS: Tuple[str, ...] = tuple(e.key for e in EMPLOYEES)


# ═══════════════════════════════════════════════════════════════════
# Default rule document (platform defaults)
# ═══════════════════════════════════════════════════════════════════

def default_rules_doc() -> Dict[str, Any]:
    """Return a *fresh* copy of the platform-default rules payload.

    Callers get their own dict — safe to mutate.  Shape mirrors the
    ``rules`` sub-tree of ``tenant_ai_rules`` (no top-level ``id`` /
    ``tenant_id`` / audit fields).
    """
    return {
        "tone_voice": {
            "style": "friendly",
            "custom_directive": "",
        },
        "auto_action_allowlist": {
            action: "admin_approval" for action in ACTION_INVENTORY
        },
        "employee_enable_disable": {
            key: True for key in EMPLOYEE_KEYS
        },
        "working_hours": {
            "enabled": True,
            "timezone": "America/Los_Angeles",
            "windows": [
                {"day": "mon", "start": "08:00", "end": "17:00"},
                {"day": "tue", "start": "08:00", "end": "17:00"},
                {"day": "wed", "start": "08:00", "end": "17:00"},
                {"day": "thu", "start": "08:00", "end": "17:00"},
                {"day": "fri", "start": "08:00", "end": "17:00"},
            ],
        },
        "escalation_rules": [
            {"keyword": "refund", "is_regex": False,
             "target_role": "admin", "sla_minutes": 5,
             "notify_channel": "email"},
        ],
    }


# ═══════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════

_TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


class RuleValidationError(ValueError):
    """Raised by :func:`validate_category_payload`.  Routers translate
    to HTTP 400 with the message body as ``detail``."""


def _err(msg: str) -> "RuleValidationError":                    # helper
    return RuleValidationError(msg)


def _validate_tone_voice(value: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise _err("tone_voice must be an object")
    style = value.get("style")
    if style not in TONE_STYLES:
        raise _err(f"tone_voice.style must be one of {TONE_STYLES}")
    directive = value.get("custom_directive", "")
    if directive is None:
        directive = ""
    if not isinstance(directive, str):
        raise _err("tone_voice.custom_directive must be a string")
    if len(directive) > 2000:
        raise _err("tone_voice.custom_directive exceeds 2000 chars")
    return {"style": style, "custom_directive": directive}


def _validate_auto_action_allowlist(
    value: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise _err("auto_action_allowlist must be an object")
    out: Dict[str, str] = {}
    for k, v in value.items():
        if not isinstance(k, str):
            raise _err(
                "auto_action_allowlist keys must be strings",
            )
        if k not in ACTION_INVENTORY:
            raise _err(
                f"auto_action_allowlist: unknown action {k!r} "
                "(not in server-side inventory)",
            )
        if v not in ALLOWLIST_MODES:
            raise _err(
                f"auto_action_allowlist[{k!r}] must be one of "
                f"{ALLOWLIST_MODES}",
            )
        out[k] = v
    return out


def _validate_employee_enable_disable(
    value: Dict[str, Any],
) -> Dict[str, bool]:
    if not isinstance(value, dict):
        raise _err("employee_enable_disable must be an object")
    out: Dict[str, bool] = {}
    for k, v in value.items():
        if k not in EMPLOYEE_KEYS:
            raise _err(
                f"employee_enable_disable: unknown employee "
                f"{k!r} (not in 18-employee registry)",
            )
        if not isinstance(v, bool):
            raise _err(
                f"employee_enable_disable[{k!r}] must be a boolean",
            )
        out[k] = v
    return out


def _validate_working_hours(value: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise _err("working_hours must be an object")
    enabled = value.get("enabled", True)
    if not isinstance(enabled, bool):
        raise _err("working_hours.enabled must be a boolean")
    tz = value.get("timezone")
    if not isinstance(tz, str) or not tz:
        raise _err("working_hours.timezone must be a non-empty string")
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(tz)
        except ZoneInfoNotFoundError:
            raise _err(
                f"working_hours.timezone {tz!r} is not a recognised "
                "IANA zone",
            )
    except ImportError:                                           # noqa: BLE001
        # zoneinfo unavailable — accept as opaque string.
        pass
    windows = value.get("windows") or []
    if not isinstance(windows, list):
        raise _err("working_hours.windows must be a list")
    if len(windows) > 21:                       # 3 windows/day × 7
        raise _err("working_hours.windows exceeds 21 entries")
    out_windows: List[Dict[str, str]] = []
    for w in windows:
        if not isinstance(w, dict):
            raise _err("working_hours.windows[*] must be objects")
        day = w.get("day")
        if day not in DAY_KEYS:
            raise _err(
                f"working_hours.windows[*].day must be one of "
                f"{DAY_KEYS}",
            )
        start = w.get("start", "")
        end = w.get("end", "")
        if not (_TIME_RE.match(start) and _TIME_RE.match(end)):
            raise _err(
                "working_hours.windows[*] start/end must be "
                "HH:MM (24-hour)",
            )
        if start >= end:
            raise _err(
                "working_hours.windows[*] start must be < end",
            )
        out_windows.append({"day": day, "start": start, "end": end})
    return {"enabled": enabled, "timezone": tz,
            "windows": out_windows}


def _validate_escalation_rules(
    value: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise _err("escalation_rules must be an array")
    if len(value) > 50:
        raise _err("escalation_rules exceeds 50 entries")
    out: List[Dict[str, Any]] = []
    for r in value:
        if not isinstance(r, dict):
            raise _err("escalation_rules[*] must be objects")
        keyword = r.get("keyword")
        if not isinstance(keyword, str) or not keyword.strip():
            raise _err(
                "escalation_rules[*].keyword must be a non-empty "
                "string",
            )
        is_regex = bool(r.get("is_regex", False))
        if is_regex:
            try:
                re.compile(keyword)
            except re.error as exc:
                raise _err(
                    f"escalation_rules[*].keyword is not a valid "
                    f"regex ({exc})",
                )
        target_role = r.get("target_role", "admin")
        if target_role not in ESCALATION_ROLES:
            raise _err(
                f"escalation_rules[*].target_role must be one of "
                f"{ESCALATION_ROLES}",
            )
        sla = r.get("sla_minutes", 5)
        if not isinstance(sla, int) or sla < 1 or sla > 24 * 60:
            raise _err(
                "escalation_rules[*].sla_minutes must be an int "
                "in 1..1440",
            )
        channel = r.get("notify_channel", "email")
        if channel not in ESCALATION_CHANNELS:
            raise _err(
                f"escalation_rules[*].notify_channel must be one "
                f"of {ESCALATION_CHANNELS}",
            )
        out.append({
            "keyword": keyword,
            "is_regex": is_regex,
            "target_role": target_role,
            "sla_minutes": sla,
            "notify_channel": channel,
        })
    return out


_CATEGORY_VALIDATORS = {
    "tone_voice": _validate_tone_voice,
    "auto_action_allowlist": _validate_auto_action_allowlist,
    "employee_enable_disable": _validate_employee_enable_disable,
    "working_hours": _validate_working_hours,
    "escalation_rules": _validate_escalation_rules,
}


def validate_category_payload(category: str, value: Any) -> Any:
    """Validate + normalize the payload for a single rule category.

    Raises :class:`RuleValidationError` on any shape / range failure.
    Returns a normalised copy safe to persist.
    """
    if category not in RULE_CATEGORIES:
        raise _err(f"unknown rule category {category!r}")
    return _CATEGORY_VALIDATORS[category](value)


def doc_size_bytes(doc: Dict[str, Any]) -> int:
    """Serialised UTF-8 size of a rules doc — used by the 50 KiB gate."""
    return len(json.dumps(doc, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8"))
