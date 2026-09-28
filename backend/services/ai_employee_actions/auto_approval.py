"""MTH-C · Feb-2026 — Auto-approval gate for ai_employee_actions.

Wires the tenant AI rules ``auto_action_allowlist`` map into the
``ai_employee_actions`` create path.  When an action is created:

  1. Consult :func:`should_auto_execute` — True iff
     - master switch on,
     - employee enabled for this tenant,
     - allowlist marks the action key ``auto``.
  2. When True: writer flips the row to ``approved`` with
     ``decided_by="system:auto_allowlist"`` + ``auto_approved=True``
     and calls the same executor branch admins would.  An audit
     row lands in ``ai_action_audit``.
  3. When False: row stays ``pending`` — current behavior.

Master switch is the ULTIMATE authority — this helper NEVER
auto-approves when it's off, even if the allowlist says ``auto``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import logger

_UTC = timezone.utc


async def should_auto_execute(
    tenant_id: Optional[str],
    action_key: Optional[str],
    employee_key: Optional[str],
    *, use_cache: bool = True,
) -> Dict[str, Any]:
    """Return a decision dict:

    .. code-block:: python

        {
            "auto": bool,
            "reason": str,          # "ok" or a fail-reason
            "rule_source": "tenant" | "platform" | None,
        }

    The ``rule_source`` reports whether the allowlist entry came
    from a tenant override or the platform default (used for
    audit).  Falls back to a False decision on any lookup error.
    """
    if not tenant_id or not action_key or not employee_key:
        return {"auto": False, "reason": "missing_scope", "rule_source": None}
    try:
        from services.tenant_ai_rules.resolver import (
            resolve_rules_for_tenant,
        )
        resolved = await resolve_rules_for_tenant(
            tenant_id, use_cache=use_cache,
        )
    except Exception as exc:                                       # noqa: BLE001
        logger.warning(
            "[mth-c] auto_approval resolve failed tenant=%s error=%s",
            tenant_id, exc,
        )
        return {"auto": False, "reason": "resolver_error", "rule_source": None}

    # Master switch — highest authority.
    if not resolved.get("master_ai_send_live_comms"):
        return {"auto": False, "reason": "master_switch_off",
                "rule_source": None}

    rules = resolved.get("rules") or {}

    # Per-employee enable gate.
    emp_map = rules.get("employee_enable_disable") or {}
    if not emp_map.get(employee_key, False):
        return {"auto": False, "reason": "employee_disabled",
                "rule_source": None}

    # Allowlist lookup.
    allowlist = rules.get("auto_action_allowlist") or {}
    mode = allowlist.get(action_key)
    if mode != "auto":
        return {"auto": False, "reason": f"allowlist_{mode or 'unset'}",
                "rule_source": None}

    override_map = resolved.get("override_map") or {}
    om_key = f"auto_action_allowlist.{action_key}"
    src = override_map.get(om_key) or "platform"
    return {"auto": True, "reason": "ok", "rule_source": src}


async def write_audit(
    *, tenant_id: str, action_id: str, action_key: str,
    employee_key: str, rule_source: Optional[str], reason: str,
) -> None:
    """Insert one ``ai_action_audit`` row per auto-approval decision.

    ``reason`` is either ``"auto_action_allowlist"`` (positive
    decision — action was auto-executed) or the failure reason
    (kept for future forensics).  Row is minimal — audit only
    exists for auto-approval decisions in this phase.
    """
    try:
        from config import db
        await db.ai_action_audit.insert_one({
            "id": f"auto-{action_id}",
            "tenant_id": tenant_id,
            "action_id": action_id,
            "action_key": action_key,
            "employee_key": employee_key,
            "kind": "auto_approval",
            "rule_source": rule_source,
            "reason": reason,
            "created_at": datetime.now(_UTC).isoformat(),
        })
    except Exception:                                              # noqa: BLE001
        # Audit failure MUST NOT block execution.
        logger.exception(
            "[mth-c] auto_approval audit write failed action=%s", action_id,
        )


__all__ = ["should_auto_execute", "write_audit"]
