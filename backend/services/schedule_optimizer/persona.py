"""SO-A · Feb-2026 — DISPATCH persona plain-English synthesis.

Standalone MARCO-style pattern from MTH-D preview: compact system
prompt + direct :func:`services.llm_provider.call_llm_with_fallback`
so we never enter the chat pipeline and never touch any side-effect
surface.  Tone shaping via MTH-C
:func:`services.tenant_ai_rules.prompt_injection.build_tone_directive`
so per-tenant tone_voice + custom_directive both flow through.

Fallback: if the LLM is unavailable (no key, provider error), each
suggestion gets a deterministic template string so the FE never
sees an empty ``plain_english`` field.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from config import logger
from services.tenant_ai_rules.prompt_injection import build_tone_directive


LLM_MAX_TOKENS = 300


def template_line(*, tech_name: str, insertion_index: int,
                   detour_minutes: float, detour_miles: float) -> str:
    """Deterministic fallback — used when the LLM is disabled by
    rules, unavailable, or when the master switch is off."""
    return (
        f"{tech_name} — insertion at position {insertion_index + 1} "
        f"adds {detour_minutes:.1f} min, {detour_miles:.1f} mi."
    )


def _one_line_prompt(items: List[Dict[str, Any]]) -> str:
    """Build the DIANA prompt body from per-tech items."""
    lines = []
    for it in items:
        lines.append(
            f"Tech: {it['tech_name']} · Insertion at position "
            f"{it['insertion_index'] + 1} of {it['route_len'] + 1} · "
            f"Detour: +{it['detour_minutes']:.1f} min, "
            f"+{it['detour_miles']:.1f} mi"
        )
    return "\n".join(lines)


async def synthesize_plain_english(
    *, tenant_id: str, resolved_rules: Dict[str, Any],
    items: List[Dict[str, Any]], enabled: bool,
) -> Dict[str, Any]:
    """Return ``{ "lines": [str, ...], "source": str }`` — one line
    per item in the SAME order.  ``source`` is one of
    ``"llm"`` / ``"template_fallback_disabled"`` /
    ``"template_fallback_master_off"`` / ``"template_fallback_error"``.
    """
    fallback_lines = [
        template_line(
            tech_name=it["tech_name"],
            insertion_index=it["insertion_index"],
            detour_minutes=it["detour_minutes"],
            detour_miles=it["detour_miles"],
        )
        for it in items
    ]

    if not enabled:
        return {"lines": fallback_lines, "source": "template_fallback_disabled",
                "llm_ms": 0}

    tone_directive = build_tone_directive(resolved_rules or {})
    persona = (
        "You are DIANA (DISPATCH), the AI scheduling assistant for a pool "
        "service company. For EACH technician below, produce ONE short "
        "sentence (max 25 words) explaining why they are a good fit for "
        "this insertion and citing the detour cost. Output exactly N "
        "lines — one per technician, in the same order. Do NOT number, "
        "do NOT prefix with a bullet, no JSON."
    )
    system_prompt = f"{tone_directive}\n\n{persona}"
    user_text = _one_line_prompt(items)

    started = time.monotonic()
    try:
        from services.llm_provider import call_llm_with_fallback
        result = await call_llm_with_fallback(
            system_prompt=system_prompt,
            user_text=user_text,
            parse_json=False,
            max_tokens=LLM_MAX_TOKENS,
            tenant_id=tenant_id,
        )
    except Exception as exc:                                       # noqa: BLE001
        logger.warning("[so-a.persona] llm raised: %s", exc)
        return {"lines": fallback_lines,
                "source": "template_fallback_error",
                "llm_ms": int((time.monotonic() - started) * 1000)}

    if result.get("error"):
        logger.warning("[so-a.persona] llm error: %s", result.get("error"))
        return {"lines": fallback_lines,
                "source": "template_fallback_error",
                "llm_ms": int((time.monotonic() - started) * 1000)}

    raw = result.get("raw")
    if isinstance(raw, dict):
        text = str(raw.get("text") or raw)
    else:
        text = str(raw or "")

    parsed = [ln.strip(" -•*\t") for ln in text.splitlines() if ln.strip()]
    if len(parsed) < len(items):
        # Fill missing tail with the fallback template.
        parsed = parsed + fallback_lines[len(parsed):]
    else:
        parsed = parsed[:len(items)]
    return {
        "lines": parsed,
        "source": "llm",
        "provider": result.get("provider"),
        "model": result.get("model"),
        "llm_ms": int((time.monotonic() - started) * 1000),
    }


__all__ = [
    "template_line", "synthesize_plain_english", "LLM_MAX_TOKENS",
]
