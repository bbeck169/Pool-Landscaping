from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List, Any
from pydantic import BaseModel, Field

from config import db
from utils import now_iso, new_id, require_admin

router = APIRouter()


class MeasurementIn(BaseModel):
    name: str = "Measurement"
    mode: str = "area"                 # "distance" | "area"
    points: List[Any] = Field(default_factory=list)   # [{latitude, longitude}]
    distance_ft: float = 0.0
    perimeter_ft: float = 0.0
    area_sqft: float = 0.0
    acres: float = 0.0
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None


@router.post("/measurements")
async def create_measurement(body: MeasurementIn, user: dict = Depends(require_admin)):
    doc = {
        "id": new_id(),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "name": body.name or "Measurement",
        "mode": body.mode,
        "points": body.points,
        "distance_ft": body.distance_ft,
        "perimeter_ft": body.perimeter_ft,
        "area_sqft": body.area_sqft,
        "acres": body.acres,
        "customer_id": body.customer_id,
        "lead_id": body.lead_id,
        "created_at": now_iso(),
    }
    await db.measurements.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/measurements")
async def list_measurements(customer_id: Optional[str] = Query(None), lead_id: Optional[str] = Query(None),
                            user: dict = Depends(require_admin)):
    q: dict = {}
    if customer_id:
        q["customer_id"] = customer_id
    if lead_id:
        q["lead_id"] = lead_id
    return await db.measurements.find(q, {"_id": 0}).sort("created_at", -1).to_list(300)


@router.delete("/measurements/{mid}")
async def delete_measurement(mid: str, user: dict = Depends(require_admin)):
    await db.measurements.delete_one({"id": mid})
    return {"ok": True}
