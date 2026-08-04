"""Phase 49 · Feb-2026 — Schedule intent → job creation.

Fuzzy-matches a spoken/typed customer name to a real ``db.customers``
row, then routes the ``JobIn`` payload through the SAME endpoint the
web admin uses (``routers.jobs.create_job``). No duplicate create
logic. Requires an explicit confirmation step in the caller before
writing (see :func:`preview` vs :func:`commit`).
"""
from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional


async def _find_customer(db, tenant_id: str, name: str) -> Optional[Dict[str, Any]]:
    """Best-effort fuzzy match. Returns the closest customer above a
    0.6 SequenceMatcher score, or None."""
    rows = await db.customers.find(
        {"tenant_id": tenant_id, "is_active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "address": 1, "phone": 1, "email": 1},
    ).to_list(1000)
    if not rows:
        return None

    target = (name or "").strip().lower()
    if not target:
        return None
    scored: List[tuple[float, Dict[str, Any]]] = []
    for r in rows:
        cn = (r.get("name") or "").lower()
        if not cn:
            continue
        score = difflib.SequenceMatcher(None, target, cn).ratio()
        # Boost exact-substring hits so "Alan" matches "Alan Chesebrough"
        # even though the ratio would otherwise be lowish.
        if target in cn or cn in target:
            score = max(score, 0.85)
        scored.append((score, r))
    scored.sort(key=lambda t: t[0], reverse=True)
    if not scored or scored[0][0] < 0.6:
        return None
    return scored[0][1]


async def preview(
    db, *, tenant_id: str, customer_name: str, service_type: str, scheduled_date: str,
) -> Dict[str, Any]:
    """Resolve the customer + return a preview payload the caller can
    quote back to the user for confirmation. Nothing is written."""
    cust = await _find_customer(db, tenant_id, customer_name)
    if not cust:
        return {
            "ok": False,
            "reason": "customer_not_found",
            "asked_for": customer_name,
        }
    return {
        "ok": True,
        "preview": {
            "title": f"{service_type} — {cust['name']}",
            "customer_id": cust["id"],
            "customer_name": cust["name"],
            "address": cust.get("address") or "",
            "service_type": service_type,
            "scheduled_date": scheduled_date,
        },
    }


async def commit(
    db, *, tenant_id: str, actor_user_id: Optional[str],
    customer_id: str, service_type: str, scheduled_date: str, title: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the job via ``routers.jobs.create_job`` so we inherit
    every downstream side-effect (dispatch board, calendar, tech
    assignment, multi-property gate, etc.). Returns the created job doc.
    """
    from models import JobIn
    from routers.jobs import create_job

    cust = await db.customers.find_one({"id": customer_id, "tenant_id": tenant_id},
                                        {"_id": 0})
    if not cust:
        return {"ok": False, "reason": "customer_not_found"}

    payload = JobIn(
        title=title or f"{service_type} — {cust.get('name') or 'Customer'}",
        customer_id=customer_id,
        service_type=service_type,
        scheduled_date=scheduled_date,
        address=cust.get("address") or "",
    )
    user_stub = {"id": actor_user_id, "role": "admin", "tenant_id": tenant_id}
    tenant_stub = {"id": tenant_id}
    try:
        job = await create_job(payload, user=user_stub, tenant=tenant_stub)
    except Exception as exc:
        return {"ok": False, "reason": "create_job_failed", "detail": str(exc)}
    return {"ok": True, "job": job}
