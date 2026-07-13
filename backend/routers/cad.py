from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List, Any
from pydantic import BaseModel, Field

from config import db
from utils import now_iso, new_id, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


class DesignIn(BaseModel):
    name: str = "Untitled design"
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None
    canvas_w_ft: float = 60.0
    canvas_h_ft: float = 40.0
    boundary: List[Any] = Field(default_factory=list)
    elements: List[Any] = Field(default_factory=list)
    area_sqft: float = 0.0
    perimeter_ft: float = 0.0
    thumbnail: Optional[str] = None


def _doc_public(d: dict) -> dict:
    d.pop("_id", None)
    return d


@router.post("/designs")
async def create_design(body: DesignIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    now = now_iso()
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "name": body.name or "Untitled design",
        "customer_id": body.customer_id,
        "lead_id": body.lead_id,
        "canvas_w_ft": body.canvas_w_ft,
        "canvas_h_ft": body.canvas_h_ft,
        "boundary": body.boundary,
        "elements": body.elements,
        "area_sqft": body.area_sqft,
        "perimeter_ft": body.perimeter_ft,
        "thumbnail": body.thumbnail,
        "created_at": now,
        "updated_at": now,
    }
    await db.designs.insert_one(doc)
    return _doc_public(doc)


@router.get("/designs")
async def list_designs(customer_id: Optional[str] = Query(None),
                       lead_id: Optional[str] = Query(None),
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    q: dict = {"tenant_id": tenant["id"]}
    if customer_id:
        q["customer_id"] = customer_id
    if lead_id:
        q["lead_id"] = lead_id
    docs = await db.designs.find(
        q,
        {"_id": 0, "elements": 0, "boundary": 0},
    ).sort("updated_at", -1).to_list(300)
    return docs


@router.get("/designs/{did}")
async def get_design(did: str,
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    d = await db.designs.find_one({"id": did, "tenant_id": tenant["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Design not found")
    return d


@router.put("/designs/{did}")
async def update_design(did: str, body: DesignIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    d = await db.designs.find_one({"id": did, "tenant_id": tenant["id"]})
    if not d:
        raise HTTPException(404, "Design not found")
    update = {
        "name": body.name or "Untitled design",
        "customer_id": body.customer_id,
        "lead_id": body.lead_id,
        "canvas_w_ft": body.canvas_w_ft,
        "canvas_h_ft": body.canvas_h_ft,
        "boundary": body.boundary,
        "elements": body.elements,
        "area_sqft": body.area_sqft,
        "perimeter_ft": body.perimeter_ft,
        "thumbnail": body.thumbnail,
        "updated_at": now_iso(),
    }
    await db.designs.update_one({"id": did, "tenant_id": tenant["id"]}, {"$set": update})
    return await get_design(did, user, tenant)


@router.delete("/designs/{did}")
async def delete_design(did: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    await db.designs.delete_one({"id": did, "tenant_id": tenant["id"]})
    return {"ok": True}
