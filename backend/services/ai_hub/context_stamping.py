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
