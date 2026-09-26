"""Measurements — persisted L·W·D + points from the mobile map / manual entry.

Historical shape (July-2024): admin-only POST + GET + DELETE, satellite
measure flow only, no tech access.

Feb-2026 extension (M1 · manual measurements from Customer Detail →
Measurements tab):
  * ``type`` + ``unit`` fields added (optional, additive-nullable so the
    existing satellite POST continues to work without any client change).
  * ``POST /measurements`` opens to ``require_tech_or_above`` — techs
    can now record measurements against a customer_id from the field.
    ``GET`` + ``DELETE`` stay on ``require_admin`` per the current brief.
  * Server auto-attaches ``technician_id``, ``technician_name``,
    ``created_at``, ``tenant_id`` — clients cannot spoof these; the
    ``MeasurementIn`` Pydantic model does not accept them so any
    client-supplied value in the JSON body is silently ignored.
  * ``customer_id`` / ``lead_id`` (when provided) are validated against
    the caller's tenant so a compromised tech cannot POST measurements
    onto another tenant's customer records.
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List, Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

from config import db
from utils import now_iso, new_id, require_admin
from routers.tenants import get_current_tenant
from routers.pool_calculators import require_tech_or_above

router = APIRouter()


# Legal (type, unit) combinations for the M1 manual flow.  If ``type``
# is provided, ``unit`` must be present AND fall inside its set below.
# If neither is provided, the row is a legacy satellite-flow record
# and no combo validation runs.
_TYPE_UNIT_ALLOWED = {
    "linear":    {"ft", "yd"},
    "area":      {"sqft"},
    "perimeter": {"ft", "yd"},
}


class MeasurementIn(BaseModel):
    name: str = "Measurement"
    mode: str = "area"
    points: List[Any] = Field(default_factory=list)
    distance_ft: float = 0.0
    perimeter_ft: float = 0.0
    area_sqft: float = 0.0
    acres: float = 0.0
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None
    # M1 · Feb-2026 · manual measurement classification.  Both fields
    # are additive-nullable — legacy satellite POSTs omit them and
    # the row persists without a type/unit tag.
    type: Optional[Literal["linear", "area", "perimeter"]] = None
    unit: Optional[Literal["ft", "sqft", "yd"]] = None

    @model_validator(mode="after")
    def _enforce_type_unit_combo(self) -> "MeasurementIn":
        # Only enforce the combo when ``type`` is explicitly set.  A
        # bare ``unit`` with no ``type`` is allowed (still matches the
        # satellite backward-compat contract) but ``type`` without a
        # ``unit`` is rejected because the mobile UX requires the tech
        # to pick both.
        if self.type is not None:
            if self.unit is None:
                raise ValueError(
                    f"type={self.type!r} requires unit to be one of "
                    f"{sorted(_TYPE_UNIT_ALLOWED[self.type])}"
                )
            allowed = _TYPE_UNIT_ALLOWED[self.type]
            if self.unit not in allowed:
                raise ValueError(
                    f"unit={self.unit!r} not valid for type={self.type!r}; "
                    f"expected one of {sorted(allowed)}"
                )
        return self


async def _assert_owns_customer(cid: Optional[str], tenant_id: str) -> None:
    if not cid:
        return
    hit = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant_id}, {"_id": 0, "id": 1},
    )
    if not hit:
        raise HTTPException(
            status_code=403,
            detail="customer_id not found in caller tenant",
        )


async def _assert_owns_lead(lid: Optional[str], tenant_id: str) -> None:
    if not lid:
        return
    hit = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant_id}, {"_id": 0, "id": 1},
    )
    if not hit:
        raise HTTPException(
            status_code=403,
            detail="lead_id not found in caller tenant",
        )


@router.post("/measurements")
async def create_measurement(body: MeasurementIn,
                             user: dict = Depends(require_tech_or_above),
                             tenant: dict = Depends(get_current_tenant)):
    # Cross-tenant hardening — the M1 tech surface passes a
    # customer_id from the field; validate that customer lives in
    # the tech's tenant before we persist.
    await _assert_owns_customer(body.customer_id, tenant["id"])
    await _assert_owns_lead(body.lead_id, tenant["id"])

    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        # Legacy fields — kept for backward compat with any existing
        # consumer that reads them.
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        # M1 · Feb-2026 · tech attribution mirror fields.  Callers
        # cannot spoof these because ``MeasurementIn`` does not
        # declare them; Pydantic drops any technician_* keys the
        # client tries to smuggle in.
        "technician_id": user["id"],
        "technician_name": user.get("name", ""),
        "name": body.name or "Measurement",
        "mode": body.mode,
        "points": body.points,
        "distance_ft": body.distance_ft,
        "perimeter_ft": body.perimeter_ft,
        "area_sqft": body.area_sqft,
        "acres": body.acres,
        "customer_id": body.customer_id,
        "lead_id": body.lead_id,
        "type": body.type,
        "unit": body.unit,
        "created_at": now_iso(),
    }
    await db.measurements.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/measurements")
async def list_measurements(customer_id: Optional[str] = Query(None),
                            lead_id: Optional[str] = Query(None),
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    q: dict = {"tenant_id": tenant["id"]}
    if customer_id:
        q["customer_id"] = customer_id
    if lead_id:
        q["lead_id"] = lead_id
    return await db.measurements.find(q, {"_id": 0}).sort("created_at", -1).to_list(300)


@router.delete("/measurements/{mid}")
async def delete_measurement(mid: str,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    await db.measurements.delete_one({"id": mid, "tenant_id": tenant["id"]})
    return {"ok": True}
