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


def _mock_enabled() -> bool:
    return (os.environ.get("TEST_LLM_MOCK") or "").strip() in ("1", "true", "yes")


def _mock_copy(*, trigger_event: str, channel: str, tone: str,
                 company_name: str) -> Dict[str, Any]:
    """Deterministic mock — safe for tests and offline dev.

    Shape matches the real-LLM contract: {subject?, body_text, body_sms?}.
    Subject is only populated for email; ``body_sms`` only for sms.
    """
    trig = (trigger_event or "").replace(".", " ").title()
    if channel == "sms":
        text = (f"Hi {{customer.first_name}} — {company_name} here. "
                 f"Quick note re: {trig.lower()}. Reply STOP to opt out.")
        return {
            "subject": None,
            "body_text": text,
            "body_sms": text,
            "notes": "Mocked response — TEST_LLM_MOCK=1.",
        }
    subject = f"[{company_name}] {trig}"
    body = (
        f"Hi {{customer.first_name}},\n\n"
        f"This is an automated update about your {trig.lower()}.\n"
        f"— The {company_name} team\n"
    )
    return {
        "subject": subject,
        "body_text": body,
        "body_sms": None,
        "notes": "Mocked response — TEST_LLM_MOCK=1.",
    }


def _build_system_prompt(*, trigger_event: str, channel: str, tone: str,
                           company_name: str, extra_context: str) -> str:
    channel_line = (
        "Return an SMS body (max 240 chars). No subject. Include a "
        "STOP-to-opt-out clause."
        if channel == "sms" else
        "Return an email subject and a plain-text body. Keep subject "
        "≤ 60 chars. Body should be ≤ 180 words."
    )
    return (
        f"You are the AI Autopilot copy generator for {company_name} — "
        "a field-service business (pool / landscaping).\n"
        f"Generate customer-facing copy for the automation rule below.\n"
        f"Trigger event: {trigger_event}\n"
        f"Channel: {channel}\n"
        f"Tone: {tone}\n"
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
                          extra_context: str = "") -> Dict[str, Any]:
    """High-level entrypoint. Never raises — on LLM failure returns
    ``{"error": "..."}`` with an empty body so the router can log and
    still 200. Router decides whether to persist on error."""
    tone = (tone or "friendly").lower()
    if tone not in ALLOWED_TONES:
        tone = "friendly"

    if _mock_enabled():
        raw = _mock_copy(trigger_event=trigger_event, channel=channel,
                           tone=tone, company_name=company_name)
    else:
        key = EMERGENT_LLM_KEY or os.environ.get("EMERGENT_LLM_KEY", "")
        if not key:
            return {"error": "EMERGENT_LLM_KEY missing — set env or TEST_LLM_MOCK=1"}
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
        except Exception as e:
            return {"error": f"emergentintegrations import failed: {e}"}
        try:
            system_prompt = _build_system_prompt(
                trigger_event=trigger_event, channel=channel,
                tone=tone, company_name=company_name,
                extra_context=extra_context,
            )
            chat = (LlmChat(api_key=key, session_id=new_id(),
                             system_message=system_prompt)
                    .with_model(DEFAULT_MODEL_PROVIDER, DEFAULT_MODEL_NAME))
            msg = UserMessage(text=f"Draft the {channel} copy now.")
            resp = await chat.send_message(msg)
            text = str(resp).strip()
            start = text.find("{")
            end = text.rfind("}")
            raw = json.loads(text[start:end + 1]) if start >= 0 else {}
        except Exception as e:
            logger.warning(f"[autopilot_copy] LLM call failed: {e}")
            return {"error": f"llm_call_failed: {e}"}

    return _normalize(raw, channel=channel)
