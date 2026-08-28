"""Backlog #iii · Feb-2026 — Supplier-name autocomplete surface.

``GET /api/pricebook/supplier-names``

Powers the "Suppliers" tab autocomplete on the Edit-Item modal. Union
of two sources, tenant-scoped:

  1. Phase 54 ``suppliers`` catalog (Pool360, SiteOne, Ewing, Heritage,
     ePoolSupply + any custom rows) → ``display_name``.
  2. Every distinct ``supplier_name`` already present on any pricebook
     item's ``suppliers[]`` row within the tenant.

Case-preserving dedup — the first-seen casing wins. Sorted
alphabetically case-insensitive. Response shape:

  ``{"names": ["ePoolSupply", "Ewing", "Local Distributor", ...]}``

Free-text create still allowed on the client — this endpoint is
autocomplete-only, not a hard constraint.

Role gate: ``require_admin``.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends

from config import db
from routers.tenants import get_current_tenant
from utils import require_admin


router = APIRouter()


@router.get("/pricebook/supplier-names")
async def list_supplier_names(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> dict:
    tid = tenant["id"]
    seen: dict = {}  # lower-case → first-seen casing

    def _add(name: str) -> None:
        s = str(name or "").strip()
        if not s:
            return
        key = s.lower()
        if key not in seen:
            seen[key] = s

    # 1. Phase 54 supplier catalog.
    async for s in db.suppliers.find(
        {"tenant_id": tid, "$or": [
            {"deleted_at": None}, {"deleted_at": {"$exists": False}},
        ]},
        {"_id": 0, "display_name": 1},
    ):
        _add(s.get("display_name"))

    # 2. Phase 56-a pricebook_suppliers catalog (also feeds the
    #    Phase 56-b modal, keep the autocomplete consistent).
    async for s in db.pricebook_suppliers.find(
        {"tenant_id": tid, "$or": [
            {"deleted_at": None}, {"deleted_at": {"$exists": False}},
        ]},
        {"_id": 0, "display_name": 1},
    ):
        _add(s.get("display_name"))

    # 3. Distinct supplier_name across every item's suppliers[] list.
    #    Use the collection-level ``$distinct`` on the nested path.
    try:
        distinct_names = await db.items.distinct(
            "suppliers.supplier_name",
            {"tenant_id": tid, "$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ]},
        )
        for n in distinct_names or []:
            _add(n)
    except Exception:                                              # noqa: BLE001
        # Fallback: scan a bounded window.
        async for it in db.items.find(
            {"tenant_id": tid, "suppliers": {"$exists": True, "$ne": []}},
            {"_id": 0, "suppliers": 1},
        ).limit(2000):
            for r in (it.get("suppliers") or []):
                if isinstance(r, dict):
                    _add(r.get("supplier_name"))

    names: List[str] = sorted(seen.values(), key=lambda s: s.lower())
    return {"names": names, "total": len(names)}
