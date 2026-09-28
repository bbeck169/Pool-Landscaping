"""MTH-C · Feb-2026 — Tone / voice preamble builder.

Prepends a short directive to each AI employee's static
``system_prompt`` at USE time (never mutates the registry).  Kept
tiny + pure — the resolver already handles the tenant lookup +
cache; this module is a string factory + one thin async wrapper.

Contract:

* ``build_tone_directive(rules)`` — synchronous, deterministic.
  Returns the preamble string.  Empty string when ``rules`` is
  missing / not a dict.
* ``build_employee_system_prompt(employee, tenant_id)`` — async,
  resolves ``resolve_rules_for_tenant`` and returns
  ``directive + "\n\n" + employee.system_prompt``.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

_STYLE_PREAMBLES = {
    "formal": (
        "Respond with professional, courteous language. "
        "Avoid contractions."
    ),
    "friendly": (
        "Respond conversationally, warm and approachable. "
        "Use contractions naturally."
    ),
    "technical": (
        "Respond precisely and technically. Use industry "
        "terminology and cite specifics."
    ),
}

# Cap kept in lock-step with the FE MTH-B textarea limit so admins
# see the same truncation both sides.  Backend schema already caps
# at 2000; we truncate to 500 defensively regardless.
CUSTOM_DIRECTIVE_MAX = 500

_HEADER = "— Tone & voice guidance —"


def build_tone_directive(rules: Optional[Dict[str, Any]]) -> str:
    """Return the preamble string for ``rules['tone_voice']``.

    Falls back to the ``friendly`` preamble when the style is
    missing / invalid.  Appends the truncated ``custom_directive``
    on its own line when non-empty.
    """
    tv = {}
    if isinstance(rules, dict):
        tv = rules.get("tone_voice") or {}
        if not isinstance(tv, dict):
            tv = {}
    style_raw = str(tv.get("style") or "").strip().lower()
    preamble = _STYLE_PREAMBLES.get(style_raw) or _STYLE_PREAMBLES["friendly"]
    lines = [_HEADER, preamble]
    directive = tv.get("custom_directive")
    if isinstance(directive, str) and directive.strip():
        clipped = directive.strip()[:CUSTOM_DIRECTIVE_MAX]
        lines.append(f"Tenant directive: {clipped}")
    return "\n".join(lines)


async def build_employee_system_prompt(
    employee: Optional[Dict[str, Any]],
    tenant_id: Optional[str],
    *,
    use_cache: bool = True,
) -> str:
    """Prepend the tenant-scoped tone directive to the employee's
    persisted ``system_prompt``.

    ``employee`` is the ``ai_employees`` row dict.  ``tenant_id``
    is the tenant scope for rules resolution.  When ``tenant_id``
    is falsy we short-circuit to the raw employee prompt so
    tests / seed paths that don't have a tenant work unchanged.
    """
    base = ""
    if employee:
        base = str(employee.get("system_prompt") or "")
    if not tenant_id:
        return base
    try:
        # Local import — resolver pulls Motor which we don't want
        # at module top-level for unit tests that stub Motor.
        from services.tenant_ai_rules.resolver import (
            resolve_rules_for_tenant,
        )
        resolved = await resolve_rules_for_tenant(
            tenant_id, use_cache=use_cache,
        )
    except Exception:                                              # noqa: BLE001
        # Resolver failed — return the raw employee prompt.  The
        # send-side gate already fails safe, so a missing tone
        # preamble is acceptable in the degraded path.
        return base
    directive = build_tone_directive(resolved.get("rules") or {})
    if not base:
        return directive
    return f"{directive}\n\n{base}"


__all__ = [
    "build_tone_directive",
    "build_employee_system_prompt",
    "CUSTOM_DIRECTIVE_MAX",
]
