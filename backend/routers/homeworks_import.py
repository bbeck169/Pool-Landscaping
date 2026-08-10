"""Phase 55-a · Aug-2026 — Homeworks (Copilot CRM) importer scaffold.

Endpoints (all under ``/api/imports/homeworks/*``, admin + super_admin
gated):
  * POST   /batches                        — create pending batch
  * GET    /batches                        — list tenant batches
  * GET    /batches/{id}                   — detail + latest 100 staging rows
  * POST   /batches/{id}/rollback          — purge all import_batch_id rows

Also:
  * POST   /credentials                    — upsert Fernet-encrypted email+password
  * GET    /credentials                    — presence check (no plaintext)

Scaffold only — no scraping logic. Batches stay in ``pending`` state
until Phase 55-b lands the customer scraper. Rollback is safe to
call on empty or half-filled batches — it's a per-collection
``delete_many({import_batch_id: id})`` sweep + a state flip.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from config import db, logger
from routers.tenants import get_current_tenant
from services.suppliers.crypto import decrypt, encrypt
from utils import get_current_user, require_admin


router = APIRouter()

VALID_ENTITY_TYPES = frozenset({
    "customers", "properties", "jobs", "recurring_schedules",
    "invoices", "payments", "quotes", "attachments",
})
_COLLECTIONS_WITH_BATCH_ID = (
    "customers", "properties", "customer_locations", "jobs",
    "recurring_schedules", "invoices", "payments", "quotes",
    "customer_notes", "job_notes", "homeworks_staging",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _NewBatchIn(BaseModel):
    entity_types_planned: List[str] = list(VALID_ENTITY_TYPES)


class _CredsIn(BaseModel):
    email: EmailStr
    password: str


# ─── Batches ────────────────────────────────────────────────────────────
@router.post("/imports/homeworks/batches")
async def create_batch(
    body: _NewBatchIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    bad = [t for t in body.entity_types_planned if t not in VALID_ENTITY_TYPES]
    if bad:
        raise HTTPException(400, {"error": "invalid_entity_types",
                                    "unknown": bad})
    doc = {
        "id": uuid.uuid4().hex,
        "tenant_id": tenant["id"],
        "source": "copilot_crm",
        "state": "pending",
        "entity_types_planned": list(body.entity_types_planned),
        "entity_counts": {t: 0 for t in body.entity_types_planned},
        "started_at": None,
        "completed_at": None,
        "created_at": _now_iso(),
        "created_by_user_id": user.get("id"),
    }
    await db.import_batches.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/imports/homeworks/batches")
async def list_batches(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    cursor = db.import_batches.find(
        {"tenant_id": tenant["id"]},
        {"_id": 0},
    ).sort("created_at", -1)
    async for d in cursor:
        rows.append(d)
    return {"batches": rows}


@router.get("/imports/homeworks/batches/{batch_id}")
async def get_batch(
    batch_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    row = await db.import_batches.find_one(
        {"tenant_id": tenant["id"], "id": batch_id},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, {"error": "batch_not_found"})
    # Latest 100 staging rows for the batch — powers the detail drawer.
    staging: List[Dict[str, Any]] = []
    cursor = db.homeworks_staging.find(
        {"tenant_id": tenant["id"], "batch_id": batch_id},
        {"_id": 0, "raw_payload": 0},   # drop payload for list view
    ).sort("imported_at", -1)
    async for s in cursor:
        staging.append(s)
        if len(staging) >= 100:
            break
    return {**row, "staging_latest": staging}


@router.post("/imports/homeworks/batches/{batch_id}/rollback")
async def rollback_batch(
    batch_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    row = await db.import_batches.find_one(
        {"tenant_id": tenant["id"], "id": batch_id},
        {"_id": 0, "id": 1, "state": 1},
    )
    if not row:
        raise HTTPException(404, {"error": "batch_not_found"})
    # Idempotent — rollback of an already-rolled batch is a no-op.
    if row.get("state") == "rolled_back":
        return {"ok": True, "batch_id": batch_id,
                 "already_rolled_back": True, "purged_counts": {}}

    purged: Dict[str, int] = {}
    for coll_name in _COLLECTIONS_WITH_BATCH_ID:
        try:
            r = await db[coll_name].delete_many(
                {"tenant_id": tenant["id"],
                 "import_batch_id": batch_id},
            )
            purged[coll_name] = int(getattr(r, "deleted_count", 0) or 0)
        except Exception as e:                                    # noqa: BLE001
            logger.warning(f"[homeworks rollback] {coll_name}: {e}")
            purged[coll_name] = 0

    await db.import_batches.update_one(
        {"id": batch_id, "tenant_id": tenant["id"]},
        {"$set": {"state": "rolled_back",
                    "rolled_back_at": _now_iso(),
                    "rolled_back_by_user_id": user.get("id"),
                    "purged_counts": purged}},
    )
    return {"ok": True, "batch_id": batch_id, "purged_counts": purged}


# ─── Credentials (Fernet-encrypted) ─────────────────────────────────────
@router.post("/imports/homeworks/credentials")
async def upsert_credentials(
    body: _CredsIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    now = _now_iso()
    doc = {
        "tenant_id": tenant["id"],
        "source": "copilot_crm",
        "encrypted_email": encrypt(str(body.email)),
        "encrypted_password": encrypt(body.password),
        "updated_at": now,
        "updated_by_user_id": user.get("id"),
    }
    existing = await db.homeworks_credentials.find_one(
        {"tenant_id": tenant["id"]}, {"_id": 0, "id": 1, "created_at": 1},
    )
    if existing:
        doc["id"] = existing["id"]
        doc["created_at"] = existing.get("created_at") or now
        await db.homeworks_credentials.update_one(
            {"tenant_id": tenant["id"]}, {"$set": doc})
    else:
        doc["id"] = uuid.uuid4().hex
        doc["created_at"] = now
        await db.homeworks_credentials.insert_one(doc)
    return {"ok": True, "updated_at": now}


@router.get("/imports/homeworks/credentials")
async def get_credentials(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    row = await db.homeworks_credentials.find_one(
        {"tenant_id": tenant["id"]},
        {"_id": 0, "encrypted_email": 1, "updated_at": 1},
    )
    if not row:
        return {"has_credentials": False,
                 "email": None, "updated_at": None}
    # Return the decrypted email so admin can see WHICH account is
    # cached; password is never surfaced.
    email = decrypt(row.get("encrypted_email")) or ""
    return {"has_credentials": True, "email": email,
              "updated_at": row.get("updated_at")}
