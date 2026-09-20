"""Phase A1 · Feb-2026 · Proactive Intelligence — alert store router.

Five endpoints under ``/api/intelligence/``:

  * ``GET   /alerts``                       — cursor-paginated list.
  * ``POST  /alerts/{alert_id}/read``       — mark one read.
  * ``POST  /alerts/{alert_id}/dismiss``    — mark one dismissed.
  * ``POST  /alerts/mark-all-read``         — bulk read (optional
                                              category filter).
  * ``POST  /scans/missed-service/run-now`` — manual scan trigger
                                              (admin+super_admin).

Every route is admin+super_admin only and tenant-scoped.  Non-admin
callers get ``403 insufficient_role_for_alerts``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter()

_FULL_ALERTS_ROLES = {"admin", "super_admin"}
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


def _require_admin(user: Dict[str, Any]) -> str:
    role = (user.get("role") or "").lower()
    if role not in _FULL_ALERTS_ROLES:
        raise HTTPException(
            status_code=403, detail="insufficient_role_for_alerts",
        )
    return role


def _oid_or_400(alert_id: str) -> ObjectId:
    try:
        return ObjectId(alert_id)
    except (InvalidId, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid_alert_id")


def _shape_alert(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Return the wire shape — ObjectId → str, timestamps → ISO."""
    def _iso(v):
        if isinstance(v, datetime):
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            return v.astimezone(timezone.utc).isoformat()
        return v
    return {
        "id":              str(doc.get("_id")),
        "tenant_id":       doc.get("tenant_id"),
        "alert_key":       doc.get("alert_key"),
        "severity":        doc.get("severity"),
        "category":        doc.get("category"),
        "title":           doc.get("title") or "",
        "body":            doc.get("body") or "",
        "customer_id":     doc.get("customer_id"),
        "job_id":          doc.get("job_id"),
        "actor_context":   doc.get("actor_context") or {},
        "created_at":      _iso(doc.get("created_at")),
        "read_at":         _iso(doc.get("read_at")),
        "dismissed_at":    _iso(doc.get("dismissed_at")),
        "acknowledged_by": doc.get("acknowledged_by"),
    }


@router.get("/intelligence/alerts")
async def list_alerts(
    unread_only: bool = Query(False),
    category:    Optional[str] = Query(None),
    limit:       int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    before:      Optional[str] = Query(
        None,
        description="ISO cursor — return alerts strictly earlier",
    ),
    include_dismissed: bool = Query(
        False,
        description="Include dismissed alerts (default: hide them)",
    ),
    user:   Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """List alerts for the caller's tenant. Cursor-paginated via
    ``before=<ISO>``. Returns ``items`` + top-level
    ``unread_count`` (the unread total for the tenant regardless of
    filter — the bell badge reads this)."""
    _require_admin(user)
    tenant_id = tenant["id"]
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if unread_only:
        q["read_at"] = None
    if category:
        q["category"] = category
    if not include_dismissed:
        q["dismissed_at"] = None
    if before:
        try:
            cursor_iso = before
            # Motor accepts strings for ISO datetimes when comparing
            # against string-stored dates; we store as ``datetime``,
            # so parse the cursor.
            parsed = datetime.fromisoformat(
                before.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            q["created_at"] = {"$lt": parsed}
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400,
                                    detail="invalid_before_cursor")

    items: List[Dict[str, Any]] = []
    async for doc in db.intelligence_alerts.find(q).sort(
        "created_at", -1,
    ).limit(limit):
        items.append(_shape_alert(doc))

    unread_count = await db.intelligence_alerts.count_documents({
        "tenant_id":    tenant_id,
        "read_at":      None,
        "dismissed_at": None,
    })
    next_before = items[-1]["created_at"] if items else None
    return {
        "items":        items,
        "limit":        limit,
        "unread_count": unread_count,
        "next_before":  next_before,
    }


@router.post("/intelligence/alerts/{alert_id}/read")
async def mark_alert_read(
    alert_id: str,
    user:   Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    oid = _oid_or_400(alert_id)
    now = datetime.now(timezone.utc)
    # Idempotent — only stamp read_at when it's currently null.
    await db.intelligence_alerts.update_one(
        {"_id": oid, "tenant_id": tenant["id"], "read_at": None},
        {"$set": {"read_at":         now,
                    "acknowledged_by": user.get("id")}},
    )
    doc = await db.intelligence_alerts.find_one(
        {"_id": oid, "tenant_id": tenant["id"]},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="alert_not_found")
    return _shape_alert(doc)


@router.post("/intelligence/alerts/{alert_id}/dismiss")
async def dismiss_alert(
    alert_id: str,
    user:   Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    oid = _oid_or_400(alert_id)
    now = datetime.now(timezone.utc)
    # Dismissing also implicitly marks read (so the badge count
    # ticks down). Idempotent when already dismissed.
    await db.intelligence_alerts.update_one(
        {"_id": oid, "tenant_id": tenant["id"],
         "dismissed_at": None},
        {"$set": {"dismissed_at":    now,
                    "read_at":         now,
                    "acknowledged_by": user.get("id")}},
    )
    doc = await db.intelligence_alerts.find_one(
        {"_id": oid, "tenant_id": tenant["id"]},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="alert_not_found")
    return _shape_alert(doc)


class _MarkAllReadBody(BaseModel):
    category: Optional[str] = None


@router.post("/intelligence/alerts/mark-all-read")
async def mark_all_read(
    body:   _MarkAllReadBody = Body(default_factory=_MarkAllReadBody),
    user:   Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    q: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "read_at":   None,
    }
    if body.category:
        q["category"] = body.category
    now = datetime.now(timezone.utc)
    res = await db.intelligence_alerts.update_many(
        q,
        {"$set": {"read_at":         now,
                    "acknowledged_by": user.get("id")}},
    )
    return {
        "matched":  res.matched_count,
        "modified": res.modified_count,
        "category": body.category,
    }


@router.post("/intelligence/scans/missed-service/run-now")
async def run_missed_service_scan_now(
    user:   Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Manual trigger for the missed-service scan against the
    caller's own tenant.  Admin+super_admin only."""
    _require_admin(user)
    from services.intelligence.missed_service_scan import (
        run_missed_service_scan,
    )
    result = await run_missed_service_scan(tenant_id=tenant["id"])
    return result


@router.post("/intelligence/scans/chemistry-upsell/run-now")
async def run_chemistry_upsell_scan_now(
    user:   Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Phase A2 · Feb-2026 — manual trigger for the chemistry-upsell
    scan against the caller's own tenant.  Admin+super_admin only.

    Response shape mirrors the missed-service scan:
    ``{"tenant_id", "scanned_customers", "alerts_emitted",
    "alerts_deduped", "by_tenant"}``.
    """
    _require_admin(user)
    from services.intelligence.chemistry_upsell_scan import (
        run_chemistry_upsell_scan,
    )
    result = await run_chemistry_upsell_scan(tenant_id=tenant["id"])
    return result


@router.post("/intelligence/scans/churn-risk/run-now")
async def run_churn_risk_scan_now(
    user:   Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Phase A3 · Feb-2026 — manual trigger for the churn-risk scan
    against the caller's own tenant.  Admin+super_admin only.

    Response adds ``by_signal`` on top of the standard shape:
    ``{"tenant_id", "scanned_customers", "alerts_emitted",
    "alerts_deduped", "by_signal": {"missed_payments", "recurring_cancelled"},
    "by_tenant"}``.
    """
    _require_admin(user)
    from services.intelligence.churn_risk_scan import (
        run_churn_risk_scan,
    )
    result = await run_churn_risk_scan(tenant_id=tenant["id"])
    return result


@router.post("/intelligence/scans/renewal/run-now")
async def run_renewal_scan_now(
    user:   Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Phase A4 · Feb-2026 — manual trigger for the 30-day renewal
    scan against the caller's own tenant.  Admin+super_admin only.

    Response shape:
    ``{"tenant_id", "scanned_agreements", "alerts_emitted",
    "alerts_deduped", "emails_sent", "auto_renew_receipts_sent",
    "by_tenant"}``.
    """
    _require_admin(user)
    from services.intelligence.renewal_scan import run_renewal_scan
    result = await run_renewal_scan(tenant_id=tenant["id"])
    return result


@router.post("/agreements/{agreement_id}/resend-renewal-email")
async def resend_agreement_renewal_email(
    agreement_id: str,
    user:   Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Phase A4 · Feb-2026 — admin "Resend renewal email" row
    action on the intelligence alerts page. Admin+super_admin
    only; tech gets 403 ``insufficient_role_for_alerts``.

    ``agreement_id`` refers to a ``warranty_contracts.id``.

    Phase A5 · Feb-2026 nit fix — returns HTTP 404
    ``agreement_not_found`` when the contract doesn't exist,
    HTTP 400 ``contract_inactive`` when the contract is present
    but not in ``active`` status. Successful sends stay 200.
    """
    _require_admin(user)
    from services.intelligence.renewal_scan import (
        resend_renewal_email_for_contract,
    )
    result = await resend_renewal_email_for_contract(
        tenant["id"], agreement_id,
    )
    reason = (result or {}).get("reason")
    if reason == "contract_not_found":
        raise HTTPException(
            status_code=404, detail="agreement_not_found",
        )
    if reason == "contract_inactive":
        raise HTTPException(
            status_code=400, detail="agreement_inactive",
        )
    return result
