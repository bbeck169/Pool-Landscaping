"""Phase 28.1 · Warranty / Service-Plan Portal.

Plans, contracts, claims + customer portal + expiration reminder cron.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


# ─── Seed defaults ───────────────────────────────────────────────────
_DEFAULT_PLANS = [
    {"name": "Basic Pool Warranty", "kind": "warranty",
      "duration_months": 12,
      "coverage_summary": "Covers manufacturer defects on pump/filter",
      "price": 0, "renewal_kind": "none"},
    {"name": "Extended Pool Warranty", "kind": "extended_warranty",
      "duration_months": 24,
      "coverage_summary": "Extended coverage on all pool equipment",
      "price": 299, "renewal_kind": "manual"},
    {"name": "Monthly Service Membership", "kind": "service_plan",
      "duration_months": 12,
      "coverage_summary": "Weekly pool service + 10% off repairs",
      "price": 89, "renewal_kind": "auto"},
    {"name": "Landscape Maintenance Contract", "kind": "maintenance_contract",
      "duration_months": 12,
      "coverage_summary": "Monthly mow + quarterly cleanup",
      "price": 199, "renewal_kind": "manual"},
]


async def _ensure_seeded(tenant_id: str):
    n = await db.warranty_plans.count_documents({"tenant_id": tenant_id})
    if n > 0: return
    for p in _DEFAULT_PLANS:
        await db.warranty_plans.insert_one({
            **p, "id": new_id(), "tenant_id": tenant_id,
            "terms_html": "", "created_at": now_iso(),
            "updated_at": now_iso(),
        })


def _add_months(start: str, months: int) -> str:
    d = datetime.strptime(start[:10], "%Y-%m-%d").date()
    return (d + relativedelta(months=months)).isoformat()


# ─── Models ──────────────────────────────────────────────────────────
class PlanIn(BaseModel):
    name: str
    kind: str = Field(..., pattern="^(warranty|service_plan|maintenance_contract|extended_warranty)$")
    duration_months: int = Field(..., gt=0)
    coverage_summary: str = ""
    price: float = 0
    terms_html: str = ""
    renewal_kind: str = Field("manual", pattern="^(auto|manual|none)$")


class PlanPatch(BaseModel):
    name: Optional[str] = None
    coverage_summary: Optional[str] = None
    price: Optional[float] = None
    duration_months: Optional[int] = None
    terms_html: Optional[str] = None
    renewal_kind: Optional[str] = None


class ContractIn(BaseModel):
    plan_id: str
    customer_id: str
    asset_reference: Optional[str] = None
    start_date: str
    notes: Optional[str] = ""
    price_override: Optional[float] = None
    custom_end_date: Optional[str] = None


class ContractPatch(BaseModel):
    notes: Optional[str] = None
    custom_end_date: Optional[str] = None
    asset_reference: Optional[str] = None


class CancelIn(BaseModel): reason: str
class RenewIn(BaseModel): new_end_date: Optional[str] = None


class ClaimIn(BaseModel):
    description: str
    issue_type: str = "general"


class ClaimPatch(BaseModel):
    status: Optional[str] = Field(None,
        pattern="^(submitted|reviewing|approved|resolved|rejected)$")
    admin_notes: Optional[str] = None
    resolution_notes: Optional[str] = None


# ═══════════ PLANS ═══════════════════════════════════════════════════

@router.get("/warranties/plans")
async def list_plans(user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    await _ensure_seeded(tenant["id"])
    rows = await db.warranty_plans.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}).sort("name", 1).to_list(200)
    return {"items": rows, "total": len(rows)}


@router.post("/warranties/plans")
async def create_plan(body: PlanIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    doc = {**body.model_dump(), "id": new_id(),
             "tenant_id": tenant["id"],
             "created_at": now_iso(), "updated_at": now_iso()}
    await db.warranty_plans.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.patch("/warranties/plans/{pid}")
async def update_plan(pid: str, body: PlanPatch,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.model_dump(exclude_unset=True).items()
            if v is not None}
    if upd:
        upd["updated_at"] = now_iso()
        r = await db.warranty_plans.update_one(
            {"id": pid, "tenant_id": tenant["id"]}, {"$set": upd})
        if r.matched_count == 0:
            raise HTTPException(404, "Plan not found")
    return await db.warranty_plans.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/warranties/plans/{pid}")
async def delete_plan(pid: str,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    active = await db.warranty_contracts.count_documents(
        {"tenant_id": tenant["id"], "plan_id": pid,
          "status": {"$in": ["active", "claim_pending"]}})
    if active:
        raise HTTPException(409,
            f"{active} active contract(s) reference this plan")
    r = await db.warranty_plans.delete_one(
        {"id": pid, "tenant_id": tenant["id"]})
    if r.deleted_count == 0:
        raise HTTPException(404, "Plan not found")
    return {"deleted": True}


# ═══════════ CONTRACTS ═══════════════════════════════════════════════

@router.get("/warranties/contracts")
async def list_contracts(customer_id: Optional[str] = None,
                             status: Optional[str] = None,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if customer_id: q["customer_id"] = customer_id
    if status: q["status"] = status
    rows = await db.warranty_contracts.find(
        q, {"_id": 0}).sort("end_date", 1).to_list(1000)
    return {"items": rows, "total": len(rows)}


@router.post("/warranties/contracts")
async def create_contract(body: ContractIn,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    plan = await db.warranty_plans.find_one(
        {"id": body.plan_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not plan: raise HTTPException(404, "Plan not found")
    cust = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not cust: raise HTTPException(404, "Customer not found")
    end_date = body.custom_end_date or _add_months(
        body.start_date, plan["duration_months"])
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "plan_id": body.plan_id,
        "plan_name_snapshot": plan.get("name"),
        "plan_kind_snapshot": plan.get("kind"),
        "customer_id": body.customer_id,
        "customer_name_snapshot": cust.get("name"),
        "asset_reference": body.asset_reference,
        "start_date": body.start_date,
        "end_date": end_date,
        "custom_end_date": body.custom_end_date,
        "price_paid": (body.price_override
                          if body.price_override is not None
                          else plan.get("price", 0)),
        "status": "active",
        "notes": body.notes or "",
        "created_by": user["id"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.warranty_contracts.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.patch("/warranties/contracts/{cid}")
async def update_contract(cid: str, body: ContractPatch,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.model_dump(exclude_unset=True).items()
            if v is not None}
    if "custom_end_date" in upd:
        upd["end_date"] = upd["custom_end_date"]
    if upd:
        upd["updated_at"] = now_iso()
        r = await db.warranty_contracts.update_one(
            {"id": cid, "tenant_id": tenant["id"]}, {"$set": upd})
        if r.matched_count == 0:
            raise HTTPException(404, "Contract not found")
    return await db.warranty_contracts.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.post("/warranties/contracts/{cid}/cancel")
async def cancel_contract(cid: str, body: CancelIn,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    r = await db.warranty_contracts.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"status": "cancelled",
                    "cancelled_at": now_iso(),
                    "cancel_reason": body.reason,
                    "updated_at": now_iso()}})
    if r.matched_count == 0:
        raise HTTPException(404, "Contract not found")
    return await db.warranty_contracts.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.post("/warranties/contracts/{cid}/renew")
async def renew_contract(cid: str, body: RenewIn = RenewIn(),
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    original = await db.warranty_contracts.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not original:
        raise HTTPException(404, "Contract not found")
    plan = await db.warranty_plans.find_one(
        {"id": original["plan_id"], "tenant_id": tenant["id"]},
        {"_id": 0}) or {}
    new_start = original["end_date"]
    new_end = (body.new_end_date
                 or _add_months(new_start, plan.get("duration_months") or 12))
    new_doc = {**original, "id": new_id(),
                 "start_date": new_start, "end_date": new_end,
                 "status": "active", "created_at": now_iso(),
                 "updated_at": now_iso()}
    new_doc.pop("cancelled_at", None); new_doc.pop("cancel_reason", None)
    new_doc.pop("renewed_at", None); new_doc.pop("renewal_contract_id", None)
    await db.warranty_contracts.insert_one(dict(new_doc))
    await db.warranty_contracts.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"status": "renewed",
                    "renewed_at": now_iso(),
                    "renewal_contract_id": new_doc["id"],
                    "updated_at": now_iso()}})
    new_doc.pop("_id", None)
    return new_doc


@router.post("/warranties/contracts/{cid}/file-claim")
async def file_claim_admin(cid: str, body: ClaimIn,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    return await _file_claim(cid, body, user, tenant, filed_by_role="admin")


async def _file_claim(cid: str, body: ClaimIn, user: dict,
                          tenant: dict, filed_by_role: str) -> Dict[str, Any]:
    contract = await db.warranty_contracts.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not contract:
        raise HTTPException(404, "Contract not found")
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "contract_id": cid,
        "customer_id": contract["customer_id"],
        "filed_by": user["id"],
        "filed_by_role": filed_by_role,
        "description": body.description,
        "issue_type": body.issue_type,
        "status": "submitted",
        "admin_notes": "",
        "resolution_notes": "",
        "resolved_at": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.warranty_claims.insert_one(dict(doc))
    await db.warranty_contracts.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"status": "claim_pending",
                    "updated_at": now_iso()}})
    doc.pop("_id", None)
    return doc


# ═══════════ CLAIMS ══════════════════════════════════════════════════

@router.get("/warranties/claims")
async def list_claims(status: Optional[str] = None,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if status: q["status"] = status
    rows = await db.warranty_claims.find(
        q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return {"items": rows, "total": len(rows)}


@router.patch("/warranties/claims/{cid}")
async def update_claim(cid: str, body: ClaimPatch,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.model_dump(exclude_unset=True).items()
            if v is not None}
    if upd.get("status") == "resolved":
        upd["resolved_at"] = now_iso()
    if upd:
        upd["updated_at"] = now_iso()
        r = await db.warranty_claims.update_one(
            {"id": cid, "tenant_id": tenant["id"]}, {"$set": upd})
        if r.matched_count == 0:
            raise HTTPException(404, "Claim not found")
    doc = await db.warranty_claims.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    # If claim resolved/rejected, restore contract to active.
    if upd.get("status") in ("resolved", "rejected"):
        await db.warranty_contracts.update_one(
            {"id": doc["contract_id"], "tenant_id": tenant["id"],
              "status": "claim_pending"},
            {"$set": {"status": "active", "updated_at": now_iso()}})
    return doc


# ═══════════ CUSTOMER PORTAL ═════════════════════════════════════════

@router.get("/portal/warranties")
async def portal_list_contracts(user: dict = Depends(get_current_user),
                                     tenant: dict = Depends(get_current_tenant)):
    if user.get("role") != "customer":
        raise HTTPException(403, "Customer portal only")
    cid = user.get("customer_id") or user.get("id")
    rows = await db.warranty_contracts.find(
        {"tenant_id": tenant["id"], "customer_id": cid},
        {"_id": 0}).sort("end_date", 1).to_list(500)
    return {"items": rows, "total": len(rows)}


@router.post("/portal/warranties/{cid}/file-claim")
async def portal_file_claim(cid: str, body: ClaimIn,
                                 user: dict = Depends(get_current_user),
                                 tenant: dict = Depends(get_current_tenant)):
    if user.get("role") != "customer":
        raise HTTPException(403, "Customer portal only")
    customer_id = user.get("customer_id") or user.get("id")
    contract = await db.warranty_contracts.find_one(
        {"id": cid, "tenant_id": tenant["id"],
          "customer_id": customer_id}, {"_id": 0})
    if not contract:
        raise HTTPException(404, "Contract not found or not yours")
    return await _file_claim(cid, body, user, tenant, filed_by_role="customer")


@router.get("/portal/warranties/{cid}/claims")
async def portal_list_claims(cid: str,
                                  user: dict = Depends(get_current_user),
                                  tenant: dict = Depends(get_current_tenant)):
    if user.get("role") != "customer":
        raise HTTPException(403, "Customer portal only")
    customer_id = user.get("customer_id") or user.get("id")
    rows = await db.warranty_claims.find(
        {"tenant_id": tenant["id"], "contract_id": cid,
          "customer_id": customer_id},
        {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": rows, "total": len(rows)}


# ═══════════ Expiration reminder cron ════════════════════════════════

REMINDER_STAGES = [60, 30, 14, 7, 1]


async def scheduled_warranty_expiration_scan_all():
    """Daily 08:00 UTC. Sends stage-based reminders to customer + admin."""
    today = datetime.now(timezone.utc).date()
    tenants = await db.tenants.find(
        {}, {"_id": 0, "id": 1}).to_list(500)
    for t in tenants:
        try:
            for stage in REMINDER_STAGES:
                target_day = (today + timedelta(days=stage)).isoformat()
                cursor = db.warranty_contracts.find({
                    "tenant_id": t["id"], "status": "active",
                    "end_date": target_day,
                }, {"_id": 0})
                async for contract in cursor:
                    already = await db.warranty_reminders_sent.find_one({
                        "tenant_id": t["id"],
                        "contract_id": contract["id"],
                        "stage": stage,
                    })
                    if already:
                        continue
                    # Best-effort email via existing Resend pipeline.
                    channel = "email"
                    status = "sent"
                    try:
                        from emailer import send_email
                        cust = await db.customers.find_one(
                            {"id": contract["customer_id"],
                              "tenant_id": t["id"]}, {"_id": 0}) or {}
                        if cust.get("email"):
                            await send_email(
                                to=cust["email"],
                                subject=f"Your warranty expires in {stage} days",
                                html=(f"<p>Hi {cust.get('name','')},</p>"
                                        f"<p>Your {contract.get('plan_name_snapshot','warranty')} "
                                        f"contract expires on {contract['end_date']}. "
                                        f"Contact us to renew.</p>"))
                        else:
                            status = "skipped_no_email"
                    except Exception as ex:
                        logger.warning(f"warranty email failed: {ex}")
                        status = "failed"
                    await db.warranty_reminders_sent.insert_one({
                        "id": new_id(), "tenant_id": t["id"],
                        "contract_id": contract["id"],
                        "customer_id": contract["customer_id"],
                        "stage": stage, "channel": channel,
                        "status": status, "sent_at": now_iso(),
                    })
        except Exception as ex:
            logger.warning(f"warranty cron failed for {t['id']}: {ex}")


@router.post("/warranties/_test/run-scan-now")
async def dev_run_scan(user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    """Dev-only trigger — same logic as the cron for tests + manual admin
    triggers."""
    await scheduled_warranty_expiration_scan_all()
    n = await db.warranty_reminders_sent.count_documents(
        {"tenant_id": tenant["id"]})
    return {"reminders_sent_total": n}
