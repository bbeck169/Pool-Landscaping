"""MTH-C · Feb-2026 — gated-send helper with defer semantics.

Wraps :func:`stamp_agent_context_with_gate` and augments it with
the deferred-queue path.  Callers who ALREADY have the send
payload in hand should adopt this helper instead of the raw
``_with_gate`` — the raw wrapper does not know how to enqueue.

Contract — returns a decision dict:

.. code-block:: python

    {
        "action": "send" | "defer" | "block",
        "context": CommsContext,     # what the caller should stamp
        "reason": str,               # gate reason
        "deferred_id": Optional[str],
    }

Master switch off / employee disabled → ``action="block"``,
``context=AGENT`` (redirect to admin per SAFE-SEND).

Outside working hours + payload provided → ``action="defer"``,
``context=AGENT`` (the caller MUST NOT send; the queue will fire
at the next window).

Outside working hours + NO payload → ``action="block"`` (fallback:
we can't enqueue an empty payload).

Everything clean → ``action="send"``, ``context=`` whatever the
sync stamper resolved.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from config import logger
from services.ai_hub.context_stamping import stamp_agent_context
from services.comms_env_guard import CommsContext


async def stamp_agent_context_with_gate_or_defer(
    *, tenant_id: Optional[str],
    employee: Optional[Dict[str, Any]],
    requested_context: Optional[CommsContext] = None,
    payload_kind: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """One-call helper — resolves the gate, enqueues if needed."""
    # Fast-path — sync stamper already handles unknown / unauthorized
    # employees.  If it returned AGENT we can short-circuit.
    base = stamp_agent_context(
        employee=employee, requested_context=requested_context,
    )
    if base == CommsContext.AGENT:
        return {
            "action": "block",
            "context": CommsContext.AGENT,
            "reason": "employee_unauthorized_or_missing",
            "deferred_id": None,
        }
    if not tenant_id:
        return {
            "action": "send",
            "context": base,
            "reason": "no_tenant_scope",
            "deferred_id": None,
        }

    from services.tenant_ai_rules.gate import resolve_ai_send_gate
    try:
        allowed, reason = await resolve_ai_send_gate(
            tenant_id, (employee or {}).get("key"), now=now,
        )
    except Exception as exc:                                       # noqa: BLE001
        logger.warning(
            "[mth-c] gated_send resolver failed tenant=%s employee=%s "
            "error=%s → falling back to base",
            tenant_id, (employee or {}).get("key"), exc,
        )
        return {
            "action": "send",
            "context": base,
            "reason": "gate_lookup_failed",
            "deferred_id": None,
        }
    if allowed:
        return {
            "action": "send",
            "context": base,
            "reason": "ok",
            "deferred_id": None,
        }

    # Gate rejected.  Split hairs on the reason.
    if reason == "master_switch_off":
        logger.warning(
            "[mth-c] ai_hub.master_switch_blocked tenant=%s employee=%s "
            "attempted_context=%s → agent",
            tenant_id, (employee or {}).get("key"),
            (requested_context.value if requested_context else None),
        )
        return {
            "action": "block",
            "context": CommsContext.AGENT,
            "reason": "master_switch_off",
            "deferred_id": None,
        }
    if reason == "employee_disabled":
        return {
            "action": "block",
            "context": CommsContext.AGENT,
            "reason": "employee_disabled",
            "deferred_id": None,
        }
    if reason == "outside_working_hours":
        if not payload_kind or not payload:
            # Caller didn't provide a payload — we can't defer.
            return {
                "action": "block",
                "context": CommsContext.AGENT,
                "reason": "outside_working_hours_no_payload",
                "deferred_id": None,
            }
        # Look up the tenant's working_hours to compute next window.
        from services.tenant_ai_rules.resolver import (
            resolve_rules_for_tenant,
        )
        from services.ai_comms.deferred_queue import enqueue_deferred
        try:
            resolved = await resolve_rules_for_tenant(tenant_id)
        except Exception as exc:                                   # noqa: BLE001
            logger.warning(
                "[mth-c] gated_send defer resolve failed tenant=%s error=%s",
                tenant_id, exc,
            )
            return {
                "action": "block",
                "context": CommsContext.AGENT,
                "reason": "outside_working_hours_defer_lookup_failed",
                "deferred_id": None,
            }
        working_hours = (resolved.get("rules") or {}).get("working_hours") or {}
        result = await enqueue_deferred(
            tenant_id=tenant_id,
            employee_key=(employee or {}).get("key"),
            payload_kind=payload_kind,
            payload=payload,
            working_hours=working_hours,
        )
        if result.get("deferred"):
            return {
                "action": "defer",
                "context": CommsContext.AGENT,
                "reason": "outside_working_hours",
                "deferred_id": (result.get("doc") or {}).get("id"),
            }
        # Couldn't compute next window → fall through as block.
        return {
            "action": "block",
            "context": CommsContext.AGENT,
            "reason": (result.get("reason")
                        or "outside_working_hours_no_window"),
            "deferred_id": None,
        }
    # Unknown reason string — treat as block for safety.
    return {
        "action": "block",
        "context": CommsContext.AGENT,
        "reason": reason or "gate_denied",
        "deferred_id": None,
    }


__all__ = ["stamp_agent_context_with_gate_or_defer"]
