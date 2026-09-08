"""QuoteIQ Phase Q3-B · AI Autopilot copy generator.

Given an automation rule (trigger event + channel) generate suggested
email/SMS copy. Attaches to the rule as ``ai_generated_copy`` so a UI
can preview/apply it without silently overwriting the linked template.

Test mode: set ``TEST_LLM_MOCK=1`` and the LLM call is bypassed with a
deterministic dictionary keyed by trigger/channel. Same code path is
exercised in tests. Real path uses the Emergent LLM key + Claude
Sonnet — same provider the estimator uses so tenants see consistent
output shape/tone.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from config import EMERGENT_LLM_KEY, logger
from utils import new_id


DEFAULT_MODEL_PROVIDER = "anthropic"
DEFAULT_MODEL_NAME = "claude-sonnet-4-5"

ALLOWED_TONES = {"friendly", "professional", "urgent", "casual"}
ALLOWED_USE_CASES = {"seasonal", "invoice_followup", "generic"}


def _mock_enabled() -> bool:
    return (os.environ.get("TEST_LLM_MOCK") or "").strip() in ("1", "true", "yes")


def _mock_copy(*, trigger_event: str, channel: str, tone: str,
                 use_case: str, brand_voice_snippet: str,
                 company_name: str) -> Dict[str, Any]:
    """Deterministic mock — safe for tests and offline dev.

    Shape matches the real-LLM contract: {subject?, body_text, body_sms?}.
    Subject is only populated for email; ``body_sms`` only for sms.
    Voice/use_case are threaded into the strings so the caller can
    verify they reached the generator end-to-end.
    """
    trig = (trigger_event or "").replace(".", " ").title()
    voice_hint = f" [voice:{brand_voice_snippet[:20]}]" if brand_voice_snippet else ""
    use_hint = f" [{use_case}]" if use_case and use_case != "generic" else ""
    if channel == "sms":
        text = (f"Hi {{customer.first_name}} — {company_name} here.{use_hint}"
                 f" Quick {tone} note re: {trig.lower()}.{voice_hint}"
                 f" Reply STOP to opt out.")
        return {
            "subject": None,
            "body_text": text,
            "body_sms": text,
            "notes": "Mocked response — TEST_LLM_MOCK=1.",
        }
    subject = f"[{company_name}] {trig}{use_hint}"
    body = (
        f"Hi {{customer.first_name}},\n\n"
        f"This is a {tone} update about your {trig.lower()}.{use_hint}\n"
        f"{voice_hint}\n"
        f"— The {company_name} team\n"
    )
    return {
        "subject": subject,
        "body_text": body,
        "body_sms": None,
        "notes": "Mocked response — TEST_LLM_MOCK=1.",
    }


def _build_system_prompt(*, trigger_event: str, channel: str, tone: str,
                           use_case: str, brand_voice_snippet: str,
                           company_name: str, extra_context: str) -> str:
    channel_line = (
        "Return an SMS body (max 240 chars). No subject. Include a "
        "STOP-to-opt-out clause."
        if channel == "sms" else
        "Return an email subject and a plain-text body. Keep subject "
        "≤ 60 chars. Body should be ≤ 180 words."
    )
    use_case_line = {
        "seasonal": "Frame the message around a seasonal service opportunity "
                    "(pool open/close, spring/fall care).",
        "invoice_followup": "Frame the message as a professional invoice "
                            "follow-up (unpaid balance, gentle reminder, "
                            "clear next step).",
        "generic": "General-purpose customer-facing update.",
    }.get(use_case, "General-purpose customer-facing update.")
    voice_line = (
        f"Brand voice reference (mirror this style closely): {brand_voice_snippet}"
        if brand_voice_snippet else
        "No explicit brand voice supplied — use a natural, human tone."
    )
    return (
        f"You are the AI Autopilot copy generator for {company_name} — "
        "a field-service business (pool / landscaping).\n"
        f"Generate customer-facing copy for the automation rule below.\n"
        f"Trigger event: {trigger_event}\n"
        f"Channel: {channel}\n"
        f"Tone: {tone}\n"
        f"Use-case: {use_case} — {use_case_line}\n"
        f"{voice_line}\n"
        f"Extra context: {extra_context or '(none)'}\n\n"
        f"{channel_line}\n\n"
        "Output STRICT JSON. Do not include text outside the JSON block. "
        'Shape: {"subject": "<or null for sms>", "body_text": "<plain text>", '
        '"body_sms": "<or null for email>"}\n'
        "Use `{customer.first_name}` and `{company.name}` as literal token "
        "placeholders — they will be interpolated at send time."
    )


def _normalize(raw: Dict[str, Any], *, channel: str) -> Dict[str, Any]:
    subject = raw.get("subject")
    body_text = str(raw.get("body_text") or "").strip()
    body_sms = raw.get("body_sms")
    if channel == "sms":
        subject = None
        if not body_sms:
            body_sms = body_text
    else:
        body_sms = None
        subject = str(subject or "").strip() or "Update from your service team"
    return {
        "subject": subject,
        "body_text": body_text,
        "body_sms": body_sms,
    }


async def generate_copy(*, trigger_event: str, channel: str,
                          tone: str, company_name: str,
                          use_case: str = "generic",
                          brand_voice_snippet: str = "",
                          extra_context: str = "",
                          tenant_id: Optional[str] = None,
                          ) -> Dict[str, Any]:
    """High-level entrypoint. Never raises — on LLM failure returns
    ``{"error": "..."}`` with an empty body so the router can log and
    still 200. Router decides whether to persist on error.

    Phase I1.7.e · chunk 2.c · Feb-2026 — Threads ``tenant_id``
    into ``call_llm_with_fallback`` for tenant-BYO provider
    routing + per-tenant AI cap enforcement. Cap-exceeded is
    surfaced verbatim as
    ``{"error": "ai_spend_cap_exceeded", "cap_exceeded": True, ...}``
    so the transactional caller (comms router) can raise HTTP 429
    via :func:`services.ai.cap_http.raise_if_ai_cap_exceeded`.
    """
    tone = (tone or "friendly").lower()
    if tone not in ALLOWED_TONES:
        tone = "friendly"
    use_case = (use_case or "generic").lower()
    if use_case not in ALLOWED_USE_CASES:
        use_case = "generic"

    if _mock_enabled():
        raw = _mock_copy(trigger_event=trigger_event, channel=channel,
                           tone=tone, use_case=use_case,
                           brand_voice_snippet=brand_voice_snippet,
                           company_name=company_name)
        out = _normalize(raw, channel=channel)
        out["ai_meta"] = {"provider": "mock"}
        return out

    system_prompt = _build_system_prompt(
        trigger_event=trigger_event, channel=channel,
        tone=tone, use_case=use_case,
        brand_voice_snippet=brand_voice_snippet,
        company_name=company_name,
        extra_context=extra_context,
    )
    from services.llm_provider import call_llm_with_fallback
    r = await call_llm_with_fallback(
        system_prompt=system_prompt,
        user_text=f"Draft the {channel} copy now.",
        provider=DEFAULT_MODEL_PROVIDER,
        model=DEFAULT_MODEL_NAME,
        tenant_id=tenant_id,
    )
    if r.get("cap_exceeded"):
        # Phase I1.7.e · chunk 2.c · Feb-2026 — propagate cap-exceeded
        # verbatim so the transactional router raises HTTP 429.
        return {"error": "ai_spend_cap_exceeded",
                 "cap_exceeded": True,
                 "ai_meta": {"provider": r.get("provider") or "tenant_byo"}}
    if r.get("error"):
        return {"error": r["error"], "ai_meta": {"provider": r.get("provider")}}
    out = _normalize(r["raw"], channel=channel)
    out["ai_meta"] = {"provider": r.get("provider")}
    return out
