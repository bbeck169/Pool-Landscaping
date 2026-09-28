"""MTH-D · Feb-2026 — Preview service.

Materialises a "what would this rule change do?" answer for a
pending edit without persisting anything.  Dispatches on
``preview_kind``:

* ``response``               → run a synthetic MARCO reply using the
                               overlay-adjusted tone directive.
* ``escalation_match``       → per-message escalation-rule scan
                               using the overlaid rules array.
* ``working_hours_status``   → inside/outside + next window in the
                               tenant tz for a probe datetime.
* ``auto_action_walkthrough``→ resolved reason-chain for one
                               (employee_key, action_key) pair.

Zero-side-effect contract:

* Overlay bypasses the resolver cache (read + write) so a preview
  never poisons the shared 30-s payload.
* ``response`` kind does NOT touch ``ai_employee_messages``,
  ``ai_employee_actions``, credit debits, KB retrieval, or any
  SAFE-SEND adapter — the LLM caller is invoked in isolation.
* Every LLM call caps at ``max_tokens=400`` regardless of caller
  intent (previews are display-only).
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import logger
from services.tenant_ai_rules.resolver import resolve_rules_for_tenant
from services.tenant_ai_rules.prompt_injection import (
    build_tone_directive, CUSTOM_DIRECTIVE_MAX,
)
from services.tenant_ai_rules.schema import (
    RULE_CATEGORIES, validate_category_payload, RuleValidationError,
)

# Preview-only ceilings.
MAX_TEST_MESSAGES = 5
LLM_MAX_TOKENS = 400
PROMPT_PREVIEW_CHARS = 800
_UTC = timezone.utc


class PreviewError(Exception):
    def __init__(self, code: str, message: str,
                 http_status: int = 400,
                 detail: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.detail = detail or {}
        super().__init__(message)


def _to_dict_snapshot(resolved: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "rules": resolved.get("rules") or {},
        "override_map": resolved.get("override_map") or {},
        "master_ai_send_live_comms": bool(
            resolved.get("master_ai_send_live_comms"),
        ),
        "overlay_applied": bool(resolved.get("overlay_applied")),
    }


async def _resolve_with_pending(
    tenant_id: str, category: str, pending_value: Any,
    *, skip_validation: bool = False,
) -> Dict[str, Any]:
    # Validate the pending value with the category schema so a
    # malformed preview surface fails with the same error shape as
    # a real save.  The ``escalation_match`` preview path skips
    # this — a malformed regex there is a WARNING, not a hard
    # failure (that's the whole point of surfacing the preview).
    if not skip_validation:
        try:
            validate_category_payload(category, pending_value)
        except RuleValidationError as exc:
            raise PreviewError(
                code="invalid_pending_value",
                message=str(exc),
                http_status=422,
            ) from None
    overlay = {category: pending_value}
    return await resolve_rules_for_tenant(tenant_id, overlay=overlay)


def _build_tone_warnings(resolved_rules: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    tv = (resolved_rules or {}).get("tone_voice") or {}
    directive = tv.get("custom_directive") or ""
    if isinstance(directive, str) and len(directive) > CUSTOM_DIRECTIVE_MAX:
        warnings.append(
            f"custom_directive truncated at {CUSTOM_DIRECTIVE_MAX} chars",
        )
    return warnings


# ─── Response preview (tone_voice) ───────────────────────────────


async def _preview_response(
    *, tenant_id: str, resolved: Dict[str, Any],
    preview_input: Dict[str, Any],
) -> Dict[str, Any]:
    user_message = str(
        (preview_input or {}).get("user_message")
        or "When can you come clean my pool?",
    )[:500]
    directive = build_tone_directive(resolved.get("rules") or {})
    # Compact standalone MARCO persona so the preview doesn't have
    # to bring in the full chat pipeline (KB, brand brain, etc.)
    # — MTH-D contract says preview is response-shape only.
    persona = (
        "You are MARCO, the executive AI assistant for a pool "
        "service company. Reply to the customer's message in ONE "
        "short paragraph. Keep it under 90 words. Do NOT include "
        "any tool calls or JSON — this is a preview only."
    )
    system_prompt = f"{directive}\n\n{persona}"
    started = time.monotonic()
    llm_result: Dict[str, Any]
    try:
        from services.llm_provider import call_llm_with_fallback
        llm_result = await call_llm_with_fallback(
            system_prompt=system_prompt,
            user_text=user_message,
            parse_json=False,
            max_tokens=LLM_MAX_TOKENS,
            tenant_id=tenant_id,
        )
    except Exception as exc:                                       # noqa: BLE001
        logger.warning("[mth-d] llm preview raised: %s", exc)
        llm_result = {"error": str(exc), "provider": "unknown"}
    llm_ms = int((time.monotonic() - started) * 1000)

    if llm_result.get("error"):
        return {
            "prompt_preview": system_prompt[:PROMPT_PREVIEW_CHARS],
            "user_message": user_message,
            "error": "llm_unavailable",
            "message": (
                "Preview couldn't reach the language model — "
                f"{llm_result.get('error')}. Try again in a "
                "moment, or check the platform LLM key."
            ),
            "provider": llm_result.get("provider"),
            "llm_ms": llm_ms,
        }

    raw = llm_result.get("raw")
    # call_llm_with_fallback returns ``raw`` — the parsed JSON when
    # parse_json=True, else the plain text (usually a str).  We
    # asked with parse_json=False so ``raw`` should be a str.
    if isinstance(raw, dict):
        sample = raw.get("text") or str(raw)
    else:
        sample = str(raw or "")
    return {
        "prompt_preview": system_prompt[:PROMPT_PREVIEW_CHARS],
        "user_message": user_message,
        "sample_response": sample.strip(),
        "provider": llm_result.get("provider"),
        "model": llm_result.get("model"),
        "llm_ms": llm_ms,
        "prompt_tokens": llm_result.get("prompt_tokens"),
        "completion_tokens": llm_result.get("completion_tokens"),
    }


# ─── Escalation match preview ────────────────────────────────────


def _describe_escalation_hit(
    text: str, hit: Optional[Dict[str, Any]],
) -> str:
    if not hit:
        return "no match"
    kw = hit.get("keyword") or ""
    if hit.get("is_regex"):
        m = None
        try:
            m = re.search(kw, text or "", flags=re.IGNORECASE)
        except re.error:
            pass
        pos = m.start() if m else -1
        return f"matched regex /{kw}/ at index {pos}"
    lower = (text or "").lower()
    pos = lower.find(kw.lower()) if kw else -1
    return f"matched keyword '{kw}' (case-insensitive substring) at index {pos}"


async def _preview_escalation_match(
    *, resolved: Dict[str, Any], preview_input: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    from services.tenant_ai_rules.gate import match_escalation
    rules = ((resolved.get("rules") or {}).get("escalation_rules")) or []
    warnings: List[str] = []
    for idx, r in enumerate(rules):
        if not isinstance(r, dict):
            continue
        if r.get("is_regex"):
            try:
                re.compile(r.get("keyword") or "")
            except re.error as exc:
                warnings.append(
                    f"rule[{idx}] regex is malformed: {exc}",
                )
    messages_raw = (preview_input or {}).get("test_messages") or []
    if not isinstance(messages_raw, list):
        raise PreviewError(
            "invalid_preview_input",
            "test_messages must be a list of strings",
            http_status=422,
        )
    if len(messages_raw) > MAX_TEST_MESSAGES:
        warnings.append(
            f"received {len(messages_raw)} test_messages — capped at "
            f"{MAX_TEST_MESSAGES}",
        )
    messages = [str(m or "")[:2000] for m in messages_raw[:MAX_TEST_MESSAGES]]
    out: List[Dict[str, Any]] = []
    for msg in messages:
        hit = match_escalation(msg, rules)
        out.append({
            "message": msg,
            "matched_rule": hit,
            "reasoning": _describe_escalation_hit(msg, hit),
        })
    return {"results": out}, warnings


# ─── Working hours status preview ────────────────────────────────


async def _preview_working_hours_status(
    *, resolved: Dict[str, Any], preview_input: Dict[str, Any],
) -> Dict[str, Any]:
    wh = ((resolved.get("rules") or {}).get("working_hours")) or {}
    probe_raw = (preview_input or {}).get("probe_datetime")
    if probe_raw:
        try:
            probe = datetime.fromisoformat(str(probe_raw).replace("Z", "+00:00"))
        except Exception:                                          # noqa: BLE001
            raise PreviewError(
                "invalid_preview_input",
                f"probe_datetime is not ISO-8601: {probe_raw!r}",
                http_status=422,
            ) from None
        if probe.tzinfo is None:
            probe = probe.replace(tzinfo=_UTC)
        probe = probe.astimezone(_UTC)
    else:
        probe = datetime.now(_UTC)

    tz_name = wh.get("timezone") or "UTC"
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(tz_name)
    except Exception:                                              # noqa: BLE001
        tz = ZoneInfo("UTC")
    local = probe.astimezone(tz)
    inside_window: Optional[Dict[str, Any]] = None
    enabled = bool(wh.get("enabled", True))
    for w in (wh.get("windows") or []):
        if not isinstance(w, dict):
            continue
        from services.tenant_ai_rules.schema import DAY_KEYS
        try:
            weekday_key = DAY_KEYS[local.weekday()]
        except Exception:                                          # noqa: BLE001
            weekday_key = ""
        if w.get("day") != weekday_key:
            continue
        try:
            sh, sm = str(w.get("start", "00:00")).split(":")
            eh, em = str(w.get("end", "00:00")).split(":")
            start = local.replace(hour=int(sh), minute=int(sm),
                                     second=0, microsecond=0)
            end = local.replace(hour=int(eh), minute=int(em),
                                   second=0, microsecond=0)
        except Exception:                                          # noqa: BLE001
            continue
        if start <= local < end:
            inside_window = {
                "day": w.get("day"),
                "start": w.get("start"),
                "end": w.get("end"),
            }
            break

    # Next window start (walks the deferred_queue helper).
    from services.ai_comms.deferred_queue import compute_next_send_at
    next_start = compute_next_send_at(wh, deferred_at=probe)

    def _fmt_next(dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        return dt.astimezone(tz).isoformat()

    if not enabled:
        summary = (
            "Working-hours restriction is OFF — AI actions run at "
            "any hour."
        )
    elif inside_window:
        summary = (
            f"Inside window ({inside_window['start']}–"
            f"{inside_window['end']} {inside_window['day']}, "
            f"{tz_name})."
        )
    elif next_start is not None:
        summary = (
            f"Outside every window. Next window opens "
            f"{next_start.astimezone(tz).strftime('%A %H:%M')} "
            f"({tz_name})."
        )
    else:
        summary = (
            "Outside every window. No future window configured — "
            "AI actions will remain blocked."
        )
    return {
        "inside_window": bool(inside_window),
        "current_window": inside_window,
        "next_window_start": _fmt_next(next_start),
        "timezone_used": tz_name,
        "probe_datetime": probe.isoformat(),
        "enabled": enabled,
        "summary": summary,
    }


# ─── Auto-action walkthrough ─────────────────────────────────────


def _resolve_walkthrough(
    resolved: Dict[str, Any], employee_key: str, action_key: str,
) -> Dict[str, Any]:
    chain: List[Dict[str, Any]] = []
    master = bool(resolved.get("master_ai_send_live_comms"))
    chain.append({
        "check": "master_switch",
        "ok": master,
        "reason": "on" if master else "off — blocks all auto-execution",
    })
    if not master:
        return {
            "would_auto_execute": False,
            "reason_chain": chain,
            "final_verdict": "queues for admin approval (master switch off)",
        }

    rules = resolved.get("rules") or {}
    emp_map = rules.get("employee_enable_disable") or {}
    emp_on = bool(emp_map.get(employee_key, False))
    chain.append({
        "check": "employee_enabled",
        "ok": emp_on,
        "reason": (
            "enabled for this tenant" if emp_on else
            "disabled for this tenant"
        ),
    })
    if not emp_on:
        return {
            "would_auto_execute": False,
            "reason_chain": chain,
            "final_verdict": "queues for admin approval (employee disabled)",
        }

    allow = rules.get("auto_action_allowlist") or {}
    mode = allow.get(action_key)
    ok = mode == "auto"
    chain.append({
        "check": "action_allowlist",
        "ok": ok,
        "reason": (
            "auto — bypasses admin approval" if ok else
            f"{mode or 'unset'} — requires admin approval"
        ),
    })
    return {
        "would_auto_execute": ok,
        "reason_chain": chain,
        "final_verdict": (
            "auto-executes immediately" if ok
            else "queues for admin approval"
        ),
    }


# ─── Top-level dispatcher ────────────────────────────────────────


async def preview_rules(
    *, tenant_id: str, category: str, pending_value: Any,
    preview_kind: str, preview_input: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if category not in RULE_CATEGORIES:
        raise PreviewError(
            code="invalid_category",
            message=f"unknown category {category!r}",
            http_status=422,
        )
    preview_input = preview_input or {}
    valid_kinds = {
        "response", "escalation_match",
        "working_hours_status", "auto_action_walkthrough",
    }
    if preview_kind not in valid_kinds:
        raise PreviewError(
            code="invalid_preview_kind",
            message=(
                f"unknown preview_kind {preview_kind!r} — expected "
                f"one of {sorted(valid_kinds)}"
            ),
            http_status=422,
        )
    resolved = await _resolve_with_pending(
        tenant_id, category, pending_value,
        skip_validation=(
            category == "escalation_rules"
            and preview_kind == "escalation_match"
        ),
    )
    warnings: List[str] = _build_tone_warnings(resolved.get("rules") or {})

    if preview_kind == "response":
        output = await _preview_response(
            tenant_id=tenant_id, resolved=resolved,
            preview_input=preview_input,
        )
    elif preview_kind == "escalation_match":
        output, kind_warnings = await _preview_escalation_match(
            resolved=resolved, preview_input=preview_input,
        )
        warnings.extend(kind_warnings)
    elif preview_kind == "working_hours_status":
        output = await _preview_working_hours_status(
            resolved=resolved, preview_input=preview_input,
        )
    else:
        employee_key = str((preview_input or {}).get("employee_key") or "")
        action_key = str((preview_input or {}).get("action_key") or "")
        if not employee_key or not action_key:
            raise PreviewError(
                code="invalid_preview_input",
                message="employee_key and action_key are required",
                http_status=422,
            )
        output = _resolve_walkthrough(resolved, employee_key, action_key)

    return {
        "preview_kind": preview_kind,
        "category": category,
        "resolved_rules_snapshot": _to_dict_snapshot(resolved),
        "override_diff": resolved.get("override_map") or {},
        "output": output,
        "warnings": warnings,
    }


__all__ = [
    "PreviewError",
    "preview_rules",
    "MAX_TEST_MESSAGES",
    "LLM_MAX_TOKENS",
]
