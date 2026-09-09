"""Feb-2026 · Editable Sent Docs · Phase 1 — document versions API.

Read-only admin endpoint:
  * ``GET /api/documents/{doc_type}/{doc_id}/versions`` — paginated
    list of ``document_versions`` rows for one doc, metadata only
    (no ``snapshot`` body). Sorted by ``version DESC``.

Phase 2 will add the snapshot-detail endpoint and Phase 3 the
restore endpoint. Keeping this file surface small so those phases
plug in with a single import each.

Auth: ``require_admin`` gates every route. The multi-tenant scope
comes off ``user['tenant_id']``.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from services.documents import normalize_doc_type
from utils import require_admin


router = APIRouter()


@router.get("/documents/{doc_type}/{doc_id}/versions")
async def list_document_versions(
    doc_type: str,
    doc_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[int] = Query(
        default=None,
        description="Return versions with ``version < cursor``. "
                    "Absent → return the top page.",
    ),
    user: dict = Depends(require_admin),
):
    """Return version metadata (never the full ``snapshot`` body).

    Result shape:
      * ``items`` — list of rows, newest first
      * ``next_cursor`` — pass back to fetch the next page, or None
      * ``total`` — total version count for this doc (for a small
        header widget on the UI drawer)
    """
    canonical = normalize_doc_type(doc_type)
    if not canonical:
        raise HTTPException(400, f"unknown doc_type {doc_type!r}")

    tenant_id = user.get("tenant_id")
    q: dict = {"doc_type": canonical, "doc_id": doc_id}
    if tenant_id:
        q["tenant_id"] = tenant_id
    if cursor is not None:
        q["version"] = {"$lt": int(cursor)}

    total = await db.document_versions.count_documents(
        {"doc_type": canonical, "doc_id": doc_id,
         **({"tenant_id": tenant_id} if tenant_id else {})},
    )

    projection = {
        "_id": 0, "id": 1, "doc_type": 1, "doc_id": 1, "version": 1,
        "is_baseline": 1, "saved_by_user_id": 1,
        "saved_by_user_email": 1, "saved_by_role": 1, "saved_at": 1,
        "status_at_edit": 1, "reason": 1, "changed_fields": 1,
        "lock_bypass_ack": 1, "signature_invalidated": 1,
        "restore_of_version": 1,
    }
    items = []
    async for row in db.document_versions.find(q, projection).sort(
        "version", -1,
    ).limit(limit):
        _sa = row.get("saved_at")
        if _sa and not isinstance(_sa, str):
            try:
                row["saved_at"] = _sa.isoformat()
            except Exception:  # noqa: BLE001
                row["saved_at"] = str(_sa)
        items.append(row)

    next_cursor = None
    if len(items) == limit and items:
        next_cursor = items[-1]["version"]

    return {
        "items": items,
        "total": total,
        "next_cursor": next_cursor,
        "doc_type": canonical,
        "doc_id": doc_id,
    }
