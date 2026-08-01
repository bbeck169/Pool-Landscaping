"""Phase 11 · Feb-2026 — Invoice reconciliation log (super-admin diagnostic).

Read-only view of ``db.invoice_reconciliation_log`` written by the
``scripts/migrate_invoices_to_quotes.py`` migrator. Exposes any drift
between the retired ``db.invoices`` and ``db.quotes`` (source of truth).

**Manager is NOT authorized** — this is a super-admin-only tool.
Historical Lumino ``paid_at`` drift caused by the pre-refactor writes
(bugs B4/B5) is NOT reflected here; that will be reconciled in a
separate follow-up phase.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from config import db
from utils import get_current_user


router = APIRouter()

_SUPER_ADMIN_ONLY = {"super_admin", "admin"}


def _require_super_admin(u: Dict[str, Any]) -> None:
    if (u.get("role") or "").lower() not in _SUPER_ADMIN_ONLY:
        raise HTTPException(403, {"error": "forbidden",
                                    "required_role": "super_admin"})


@router.get("/admin/invoice-reconciliation-log",
             operation_id="admin.invoiceReconciliationLog",
             tags=["admin"])
async def api_reconciliation_log(limit: int = 100,
                                    action: str | None = None,
                                    caller: Dict[str, Any] = Depends(get_current_user)):
    _require_super_admin(caller)
    limit = max(1, min(int(limit), 500))
    # Phase 15 · Feb-2026 — optional ``action`` filter surfaces the new
    # ``backfill_lumino_paid_at`` rows alongside the existing Phase 11
    # migration entries. When unset, all rows are returned (backwards
    # compatible with pre-Phase-15 callers).
    q: Dict[str, Any] = {}
    if action:
        q["action"] = action
    items: List[Dict[str, Any]] = []
    async for r in db.invoice_reconciliation_log.find(q, {"_id": 0}).sort(
            "logged_at", -1).limit(limit):
        items.append(r)
    return {
        "items": items, "count": len(items),
        "filter": {"action": action} if action else {},
        "notes": [
            "Phase 11 refactor unified db.invoices → db.quotes (doc_type=invoice).",
            "This log lists drift found during the migration script — "
            "duplicate rows present in BOTH collections at migration time.",
            "Phase 15 adds action=backfill_lumino_paid_at rows for historical "
            "Lumino paid_at drift (bugs B4/B5) surfaced via db.payment_events.",
        ],
    }
