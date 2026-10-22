"""TD-ai-phase1 · Oct-2026 — prompt templates for ``POST /api/ai/draft-reply``.

Two public builders:

  * :func:`build_system_prompt` — stance block appended to the AI Brain
    system prompt (loaded by the router via
    ``ai_brain.build_system_prompt(tenant_id)``). Keeps brand voice +
    role expectation + privacy guarantees in one place.
  * :func:`build_user_prompt` — compose-specific user prompt per
    channel (``"sms"`` | ``"email"``) with the operator-provided
    intent hint + redacted prior message + allowlisted recipient
    context (first name placeholder, service type, upcoming visit).

The returned prompts NEVER contain the recipient's real first name —
they use the token ``[FIRSTNAME]`` which the router substitutes AFTER
the LLM call. This preserves the project-wide "customer names are NOT
sent to LLM providers" privacy claim first established in Phase P22
(``reviews_ai_reply.py:71-76``).
"""
from __future__ import annotations

from typing import Optional

# ``[FIRSTNAME]`` placeholder token: picked specifically because the
# Claude + GPT tokenizers both treat ``[FIRSTNAME]`` as a 3-token
# sequence that is almost never produced spontaneously, so echoing
# it back verbatim is extremely reliable.
FIRSTNAME_TOKEN = "[FIRSTNAME]"


def _channel_rules(channel: str) -> str:
    if channel == "sms":
        return (
            "- SMS: keep the full message under 320 characters.\n"
            "- Plaintext only — no markdown, no links unless the "
            "operator provided one explicitly.\n"
        )
    return (
        "- Email: write a 60–120 word body plus a 4–8 word subject line.\n"
        "- Begin the response with ``Subject: ...`` on its own line, "
        "then a blank line, then the body.\n"
    )


def build_system_prompt(brand_voice_system: str, channel: str) -> str:
    """Compose the full system prompt from the AI-Brain brand voice +
    the compose stance. ``brand_voice_system`` is the output of
    ``routers.ai_brain.build_system_prompt(tenant_id)`` — may be empty
    when the tenant has not configured AI Brain yet."""
    stance = (
        "You are drafting a short, operator-reviewed reply to a "
        f"customer or lead. {_channel_rules(channel)}"
        "- Natural, human tone. No form-letter phrasing.\n"
        f"- Address the recipient as {FIRSTNAME_TOKEN} — the app will "
        "substitute the real first name AFTER you reply. Do NOT guess "
        "at a name.\n"
        "- Do NOT invent facts, prices, invoice amounts, or scheduling "
        "promises that were not provided in the context.\n"
        "- Sign with the company name at the end (email) or omit the "
        "sign-off entirely (SMS).\n"
    )
    if brand_voice_system:
        return f"{brand_voice_system.rstrip()}\n\n{stance}"
    return stance


def build_user_prompt(*, channel: str,
                        service_type: Optional[str],
                        upcoming_visit_date: Optional[str],
                        redacted_prior_message: Optional[str],
                        intent_hint: Optional[str]) -> str:
    """Assemble the user turn. Order is fixed and documented in
    ``memory/td_ai_phase0_scoping.md §4.3``:
    brand → recipient → prior → intent.

    All inputs that could carry PII must be pre-redacted by the
    caller (``services.ai.compose_context``). This builder does NOT
    redact — it only composes.
    """
    lines = [
        f"Draft a {channel} reply.",
        "",
        f"Recipient first name: {FIRSTNAME_TOKEN}",
        f"Service type: {service_type or 'general service'}",
        (f"Upcoming visit: {upcoming_visit_date}"
         if upcoming_visit_date else "Upcoming visit: none scheduled"),
    ]
    if redacted_prior_message:
        lines += [
            "",
            "Prior message from the customer (redacted):",
            f"  \"{redacted_prior_message}\"",
        ]
    if intent_hint:
        lines += [
            "",
            f"Operator intent: \"{intent_hint}\"",
        ]
    lines += [
        "",
        "Rules:",
        _channel_rules(channel).rstrip(),
        f"- Address the recipient as {FIRSTNAME_TOKEN}.",
        "- Natural tone. No corporate buzzwords.",
        "- Do NOT quote prices or invoice amounts.",
    ]
    return "\n".join(lines)
