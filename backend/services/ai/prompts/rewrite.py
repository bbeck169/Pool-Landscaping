"""Ticket LL · Feb-2026 — system prompt for the AI Rewrite button.

Shipped by ``POST /api/ai/rewrite`` (``backend/routers/ai_rewrite.py``).
Mirrors the ``backend/services/ai/prompts/draft_reply.py`` sibling —
single-file export of the prompt constant + a tiny builder.

The prompt is tuned to the operator spec:
    * Rewrite the operator-authored draft in a professional tone.
    * Preserve original intent + factual content.
    * Keep approximately the same length (no padding, no truncation).
    * NEVER add greetings, sign-offs, or signatures that weren't
      already in the original.
    * NEVER add emoji unless the original had them.
    * Return the rewritten text ONLY — no commentary, no quotes, no
      "Here's the rewrite:" preamble.
"""
from __future__ import annotations


SYSTEM_PROMPT = (
    "You rewrite short business messages in a professional tone for a "
    "pool and landscaping CRM. Follow these rules EXACTLY on every "
    "response:\n"
    "  1. Preserve the original intent and every factual detail "
    "(names, dates, dollar amounts, times, service types, URLs, "
    "merge tags like {{CUSTOMER_FIRST_NAME}}).\n"
    "  2. Keep approximately the same length as the input. Do not pad "
    "or truncate.\n"
    "  3. Do NOT add greetings (\"Hi,\" \"Hello,\"), sign-offs "
    "(\"Thanks,\" \"Best,\"), signatures, or company names that are "
    "not already in the input.\n"
    "  4. Do NOT add emoji unless the input already contains emoji.\n"
    "  5. Do NOT wrap the output in quotes, backticks, or markdown "
    "fences.\n"
    "  6. Do NOT prefix the output with commentary like \"Here's the "
    "rewritten version:\" — return the rewritten message only.\n"
    "  7. Preserve any ``{{MERGE_TAG}}`` tokens verbatim — they are "
    "resolved downstream by the server before dispatch.\n"
    "  8. If the input is already professional, return a near-"
    "identical polish (minor word-choice tightening) rather than a "
    "paraphrase."
)


def build_user_prompt(draft_text: str) -> str:
    """Compose the per-call user prompt. The operator-authored draft
    is wrapped so the model treats it as the subject of a rewrite,
    not as instructions to follow (defence against prompt injection
    in the draft body itself).
    """
    cleaned = (draft_text or "").strip()
    return (
        "Rewrite the following message in a professional tone, "
        "following every rule in the system prompt. Return only the "
        "rewritten message.\n"
        "\n"
        "--- BEGIN MESSAGE ---\n"
        f"{cleaned}\n"
        "--- END MESSAGE ---"
    )
