"""AI Hub · Feb-2026 — SAFE-SEND-A integration hook.

Every AI-driven comms callsite (drafts sent from MARCO / Soshie
/ marketing autopilot on behalf of an employee) MUST route
through :func:`stamp_agent_context` before handing the payload
to ``services.comms_email_adapter.send_email`` or
``services.comms_sms_adapter.send_sms``.

Contract:

* Authorized employee (``authorized_for_public_use=True``): the
  caller's ``requested_context`` is preserved verbatim.  If the
  caller passed ``None``, we default to ``CommsContext.SYSTEM``
  (real customer send).
* Unauthorized employee (default state, ``False``): we FORCE
  ``CommsContext.AGENT`` regardless of what the caller passed.
  This is the fail-safe — until an admin explicitly authorizes
  the employee, every send redirects to the tenant admin per
  the SAFE-SEND redirect rule (business_card.email/phone).

The downgrade path emits a WARN-level log
``ai_hub.context_downgraded`` so ops can spot AI callers that
are trying to bypass the gate.

MTH-A · Feb-2026 — Multi-Tenant Hub rules layered on top.
:func:`stamp_agent_context_with_gate` is the async variant that
also consults the per-tenant AI rule engine
(``services.tenant_ai_rules.gate.resolve_ai_send_gate``).  It
returns ``AGENT`` (safety redirect) when ANY of these fire —
master switch off / employee disabled for the tenant / outside
tenant working hours — even if the employee is
``authorized_for_public_use=True``.  New callsites adopt the
async wrapper; legacy sync callers can migrate on their own
schedule since the sync function's contract is unchanged.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from config import logger
from services.comms_env_guard import CommsContext


def stamp_agent_context(
    *,
    employee: Optional[Dict[str, Any]],
    requested_context: Optional[CommsContext] = None,
) -> CommsContext:
    """Resolve the effective ``CommsContext`` for an AI-driven send.

    ``employee`` — the ``ai_employees`` row for the AI worker
    initiating the send.  ``None`` is treated as unauthorized
    (fail-safe) — an unrecognised employee never gets to send
    real customer comms.

    ``requested_context`` — what the caller wants.  Ignored when
    the employee is unauthorized.  Preserved verbatim when the
    employee is authorized.  ``None`` defaults to ``SYSTEM`` for
    authorized employees.
    """
    # Fail-safe: unknown/missing employee → AGENT (redirect).
    if not employee:
        logger.warning(
            "ai_hub.context_downgraded reason=missing_employee "
            "attempted=%s → agent",
            requested_context.value if requested_context else None,
        )
        return CommsContext.AGENT

    authorized = bool(employee.get("authorized_for_public_use"))
    if authorized:
        # Trusted — honour whatever the caller stamped.  ``None``
        # → default production context (SYSTEM).
        return requested_context or CommsContext.SYSTEM

    # Unauthorized — force AGENT.  Log the attempted context so
    # ops can spot AI paths that keep asking for SYSTEM after a
    # deliberate downgrade.
    attempted = requested_context.value if requested_context else None
    if attempted and requested_context != CommsContext.AGENT:
        logger.warning(
            "ai_hub.context_downgraded employee_id=%s employee_key=%s "
            "attempted=%s → agent (authorized_for_public_use=False)",
            employee.get("id"), employee.get("key"), attempted,
        )
    return CommsContext.AGENT


async def stamp_agent_context_with_gate(
    *,
    tenant_id: str,
    employee: Optional[Dict[str, Any]],
    requested_context: Optional[CommsContext] = None,
) -> CommsContext:
    """MTH-A wrapper — adds the per-tenant AI rule engine gate on
    top of the AIHUB-A employee-authorization check.

    The gate can force ``CommsContext.AGENT`` even when the
    employee is authorized, if the tenant admin flipped:

      * the master switch off (``master_ai_send_live_comms=False``);
      * that specific employee off; or
      * a working-hours window that excludes "now" in the tenant's
        timezone.

    Falls back to sync :func:`stamp_agent_context` when the gate
    lookup itself raises — the send should NOT crash because the
    rules collection is temporarily unavailable, so we bias toward
    the safer AGENT outcome via the sync path (which already
    handles the ``authorized_for_public_use`` gate).
    """
    # Fast-path base — if the sync path would already redirect
    # (missing / unauthorized employee), skip the gate DB reads.
    base = stamp_agent_context(
        employee=employee, requested_context=requested_context,
    )
    if base == CommsContext.AGENT:
        return base
    if not tenant_id:
        # No tenant scope → can't consult rules; fall back to base
        # (which is safe — the employee IS authorized to have
        # reached this branch).
        return base
    try:
        from services.tenant_ai_rules.gate import resolve_ai_send_gate
        allowed, reason = await resolve_ai_send_gate(
            tenant_id, (employee or {}).get("key"),
        )
    except Exception as exc:                                     # noqa: BLE001
        logger.warning(
            "ai_hub.gate_lookup_failed tenant=%s employee=%s error=%s "
            "→ falling back to sync context",
            tenant_id, (employee or {}).get("key"), exc,
        )
        return base
    if not allowed:
        logger.warning(
            "ai_hub.context_downgraded reason=%s tenant=%s "
            "employee=%s attempted=%s → agent",
            reason, tenant_id, (employee or {}).get("key"),
            base.value,
        )
        return CommsContext.AGENT
    return base

