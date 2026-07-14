from fastapi import APIRouter, HTTPException, Depends

from config import db
from utils import require_admin, get_current_user, now_iso
from routers.tenants import get_current_tenant
from models import CardCompanyIn, CardPersonalIn

router = APIRouter()

DEFAULT_COMPANY = {
    "name": "Pool & Landscaping of Vistancia",
    "region": "Peoria & Vistancia, Arizona",
    "tagline": "Your trusted local pool & landscaping pros in Vistancia.",
    "contact_name": "Brian",
    "phone": "602-887-4400",
    "email": "brian@plofv.com",
    "website": "https://www.poolandlandscapingofvistancia.com/",
    "google_review": "https://share.google/TMIyxRkwapL0PlnWV",
}


async def _company(tenant_id: str | None = None) -> dict:
    q = {"id": "company"}
    if tenant_id:
        q["tenant_id"] = tenant_id
    doc = await db.card_settings.find_one(q, {"_id": 0}) or {}
    if not doc and tenant_id:
        # legacy fallback: use global singleton if per-tenant hasn't been created yet
        doc = await db.card_settings.find_one({"id": "company"}, {"_id": 0}) or {}
    return {**DEFAULT_COMPANY, **{k: v for k, v in doc.items() if k not in ("id", "tenant_id") and v not in (None, "")}}


@router.get("/card")
async def get_card(user: dict = Depends(get_current_user),
                   tenant: dict = Depends(get_current_tenant)):
    company = await _company(tenant["id"])
    personal = None
    can_personal = bool(user.get("technician_id"))
    if can_personal:
        tid = user["technician_id"]
        saved = await db.card_settings.find_one(
            {"id": f"tech:{tid}", "tenant_id": tenant["id"]}, {"_id": 0}
        ) or {}
        tech = await db.technicians.find_one(
            {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0}
        ) or {}
        personal = {
            "name": saved.get("name") or user.get("name", ""),
            "title": saved.get("title") or tech.get("specialty") or "Service Technician",
            "phone": saved.get("phone") or tech.get("phone") or company["phone"],
            "email": saved.get("email") or user.get("email", ""),
        }
    return {
        "company": company,
        "personal": personal,
        "can_edit_company": user.get("role") in ("admin", "super_admin"),
        "can_edit_personal": can_personal,
    }


@router.put("/card/company")
async def save_company(body: CardCompanyIn,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    doc = {"id": "company", "tenant_id": tenant["id"], "updated_at": now_iso(),
           **body.model_dump(exclude_none=True)}
    await db.card_settings.update_one(
        {"id": "company", "tenant_id": tenant["id"]},
        {"$set": doc}, upsert=True,
    )
    return await _company(tenant["id"])


@router.put("/card/personal")
async def save_personal(body: CardPersonalIn,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    if not user.get("technician_id"):
        raise HTTPException(403, "Only technicians have a personal card")
    tid = user["technician_id"]
    doc = {"id": f"tech:{tid}", "tenant_id": tenant["id"], "updated_at": now_iso(),
           **body.model_dump(exclude_none=True)}
    await db.card_settings.update_one(
        {"id": f"tech:{tid}", "tenant_id": tenant["id"]},
        {"$set": doc}, upsert=True,
    )
    return {"ok": True}
