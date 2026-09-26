"""MA1 · MARCO parser — LLM-driven natural-language command parser.

Contract
────────
Input:
    transcript (str) — the tech's raw voice-to-text output.
    tenant_id (str) — used for BYO provider routing + cap enforcement.

Output (happy path):
    {"action": <str>, "args": <dict>, "raw_llm": <str>}
    where ``action`` ∈ {"clock_in", "clock_out", "add_line_item",
                         "save_note", "unknown"}.

Output (error):
    {"error": "llm_upstream_error" | "llm_parse_error",
     "detail": <str>, "raw_llm": <str>}

The parser NEVER raises — every failure mode is expressed as an
``error`` field so the endpoint layer can render a friendly toast.

Provider routing
────────────────
Uses :func:`services.llm_provider.call_llm_with_fallback` with the
default (Claude Sonnet 4.5 → OpenAI fallback) chain. Passes
``tenant_id`` so BYO providers and per-tenant AI spend caps are
honoured. No hard model pin — MARCO is voice UX, resilience wins.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from services.llm_provider import call_llm_with_fallback


# Actions the parser is allowed to emit. Anything else is coerced to
# ``llm_parse_error`` so a hallucinated action never reaches the
# registry.
KNOWN_ACTIONS = {"clock_in", "clock_out", "add_line_item", "save_note"}


SYSTEM_PROMPT = """You are MARCO, a voice command parser for a pool / landscaping technician mobile app.

Parse the technician's spoken command into a single JSON action.

Available actions (JSON key "action"):
- "clock_in": tech starts their workday. args = {}.
- "clock_out": tech ends their workday. args = {}.
- "add_line_item": tech adds a pricebook item to the current invoice.
    args = {"item_query": <string, natural-language item name>,
            "quantity": <number, defaults to 1 if unstated>}
- "save_note": tech dictates a note to attach to the service report.
    args = {"text": <string, the full note text>}

If the transcript doesn't clearly match any known action, return:
{"action": "unknown", "args": {}}

Return ONLY valid JSON in this exact shape:
{"action": "<one of the above>", "args": {...}}

Do NOT include explanations, markdown fences, or code blocks — pure
JSON only.
"""


async def parse_transcript(*, transcript: str, tenant_id: str) -> Dict[str, Any]:
    """Parse a tech's voice transcript into a MARCO action + args.

    See module docstring for contract.
    """
    result = await call_llm_with_fallback(
        system_prompt=SYSTEM_PROMPT,
        user_text=transcript,
        tenant_id=tenant_id,
        parse_json=True,
    )
    # ── upstream error / BYO cap / provider failure ──────────────
    if result.get("error"):
        return {
            "error": "llm_upstream_error",
            "detail": str(result.get("error")),
            "raw_llm": "",
        }
    # ── extract + normalise ``raw`` ──────────────────────────────
    raw = result.get("raw")
    raw_str: str
    if isinstance(raw, str):
        raw_str = raw
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {
                "error": "llm_parse_error",
                "detail": "LLM returned non-JSON output",
                "raw_llm": raw_str[:500],
            }
    else:
        try:
            raw_str = json.dumps(raw)
        except (TypeError, ValueError):
            raw_str = ""
    if not isinstance(raw, dict):
        return {
            "error": "llm_parse_error",
            "detail": "LLM output is not a JSON object",
            "raw_llm": raw_str[:500],
        }
    action = raw.get("action")
    args = raw.get("args") or {}
    if action != "unknown" and action not in KNOWN_ACTIONS:
        return {
            "error": "llm_parse_error",
            "detail": f"Unknown action from LLM: {action!r}",
            "raw_llm": raw_str[:500],
        }
    if not isinstance(args, dict):
        args = {}
    return {"action": action, "args": args, "raw_llm": raw_str[:500]}
