"""Feb-2026 · Editable Sent Docs · Phase 1 → 2 — document versions API.

Read-only admin endpoints:

  * ``GET /api/documents/{doc_type}/{doc_id}/versions`` — Phase 1,
    metadata-only. Retained for backwards compatibility.

  * ``GET /api/invoices/{id}/versions`` — Phase 2 alias with the
    full snapshot body inline (needed by the version-history
    drawer's "View snapshot" quick-preview).
  * ``GET /api/quotes/{qid}/versions`` — Phase 2 estimate/quote
    alias.

The Phase-2 payload shape:
    {
      "items": [
        {
          "version_id": str,
          "version": int,
          "is_baseline": bool,
          "created_at": ISO-str,
          "created_by": {"user_id": str, "email": str, "name": str},
          "change_summary": str | None,
          "diff_field_count": int,
          "status_at_edit": str,
          "signature_invalidated": bool,
          "lock_bypass_ack": bool,
          "document_snapshot": dict,
        },
      ],
      "total": int,
      "doc_id": str,
      "doc_type": str,
    }

Auth: ``require_admin`` on every route.  The tenant scope filter
comes from the caller's JWT ``tenant_id`` — a super_admin from
tenant A can NOT enumerate versions of a doc in tenant B.

Rate limit: 20 requests / minute / user (Phase 2). Implemented via
a small in-memory + Mongo TTL counter — fail-open on Mongo hiccups.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from config import db
from services.documents import normalize_doc_type
from utils import require_admin


log = logging.getLogger("routers.document_versions")
router = APIRouter()


# ═════════════════════════════════════════════════════════════════
# Rate limit — 20 / minute / user for the Phase-2 read paths
# ═════════════════════════════════════════════════════════════════
_RATE_MAX_PER_MINUTE = 20
_RATE_TTL_SECONDS = 300
_RATE_INDEX_READY = False


async def _ensure_rate_index() -> None:
    global _RATE_INDEX_READY
    if _RATE_INDEX_READY:
        return
    try:
        await db.doc_versions_rate.create_index(
            "bucket_dt", expireAfterSeconds=_RATE_TTL_SECONDS,
        )
        await db.doc_versions_rate.create_index(
            [("user_id", 1), ("bucket_iso", 1)],
        )
        _RATE_INDEX_READY = True
    except Exception as exc:  # noqa: BLE001
        log.warning(f"[doc_versions_rate] index setup partial: {exc}")


async def _rate_check(user_id: str) -> None:
    """Charge one hit and raise 429 when the caller has already
    made ``_RATE_MAX_PER_MINUTE`` calls in the current minute."""
    if not user_id:
        return
    await _ensure_rate_index()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    try:
        cur = await db.doc_versions_rate.count_documents({
            "user_id": user_id, "bucket_iso": now.isoformat(),
        })
        if cur >= _RATE_MAX_PER_MINUTE:
            raise HTTPException(
                status_code=429,
                detail={
                    "error_code": "rate_limited",
                    "message": (
                        "document-version reads are rate-limited to "
                        f"{_RATE_MAX_PER_MINUTE}/min per user"
                    ),
                    "retry_after": (now + timedelta(minutes=1)).isoformat(),
                },
            )
        await db.doc_versions_rate.insert_one({
            "user_id": user_id, "bucket_iso": now.isoformat(),
            "bucket_dt": now,
        })
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        # Fail-open — rate-limit backing-store hiccups MUST NOT
        # block a legitimate admin from viewing history.
        log.warning(f"[doc_versions_rate] check failed: {exc}")


# ═════════════════════════════════════════════════════════════════
# Serialisation helper — write-time metadata → Phase-2 wire shape
# ═════════════════════════════════════════════════════════════════
def _to_wire_row(row: Dict[str, Any], display_name: str) -> Dict[str, Any]:
    """Re-shape a ``document_versions`` row into the Phase-2 wire
    contract. ``display_name`` comes from the user-directory hit
    performed once per response (see :func:`_hydrate_user_names`)."""
    _sa = row.get("saved_at")
    if _sa and not isinstance(_sa, str):
        try:
            _sa = _sa.isoformat()
        except Exception:  # noqa: BLE001
            _sa = str(_sa)
    return {
        "version_id": row.get("id"),
        "version": row.get("version"),
        "is_baseline": bool(row.get("is_baseline")),
        "created_at": _sa,
        "created_by": {
            "user_id": row.get("saved_by_user_id") or "",
            "email": row.get("saved_by_user_email") or "",
            "name": display_name or "",
        },
        "change_summary": row.get("change_summary"),
        "diff_field_count": int(row.get("diff_field_count") or 0),
        "status_at_edit": row.get("status_at_edit"),
        "signature_invalidated": bool(row.get("signature_invalidated")),
        "lock_bypass_ack": bool(row.get("lock_bypass_ack")),
        "document_snapshot": row.get("snapshot") or {},
    }


async def _hydrate_user_names(rows: List[Dict[str, Any]]) -> Dict[str, str]:
    """Batch-load user display names in one Mongo round-trip.
    Handles the ``"system"`` marker (baseline snapshots) up-front."""
    ids = {r.get("saved_by_user_id") for r in rows
             if r.get("saved_by_user_id") and r.get("saved_by_user_id") != "system"}
    if not ids:
        return {}
    out: Dict[str, str] = {}
    try:
        async for u in db.users.find(
            {"id": {"$in": list(ids)}},
            {"_id": 0, "id": 1, "full_name": 1, "name": 1,
             "first_name": 1, "last_name": 1, "email": 1},
        ):
            uid = u.get("id") or ""
            name = (u.get("full_name")
                    or u.get("name")
                    or " ".join(
                        v for v in (u.get("first_name"), u.get("last_name")) if v
                    ).strip()
                    or u.get("email")
                    or "")
            out[uid] = name
    except Exception as exc:  # noqa: BLE001
        log.warning(f"[doc_versions] user-name hydration failed: {exc}")
    return out


# ═════════════════════════════════════════════════════════════════
# Shared list handler powering both aliases + the legacy endpoint
# ═════════════════════════════════════════════════════════════════
async def _list_versions(
    *, canonical_doc_type: str, doc_id: str, tenant_id: Optional[str],
    limit: int, cursor: Optional[int], include_snapshot: bool,
    user_id: str,
) -> Dict[str, Any]:
    await _rate_check(user_id)

    # Fetch total.
    base_q: Dict[str, Any] = {
        "doc_type": canonical_doc_type, "doc_id": doc_id,
    }
    if tenant_id:
        base_q["tenant_id"] = tenant_id
    total = await db.document_versions.count_documents(base_q)

    # Page query.
    q = dict(base_q)
    _cur = cursor
    if _cur is not None and not isinstance(_cur, (int, float)):
        # Callers hitting the router function directly (pytest) pass
        # the raw FastAPI ``Query`` default sentinel.  Ignore it.
        _cur = None
    if _cur is not None:
        q["version"] = {"$lt": int(_cur)}
    projection: Dict[str, Any] = {
        "_id": 0, "id": 1, "doc_type": 1, "doc_id": 1, "version": 1,
        "is_baseline": 1, "saved_by_user_id": 1,
        "saved_by_user_email": 1, "saved_by_role": 1, "saved_at": 1,
        "status_at_edit": 1, "reason": 1, "changed_fields": 1,
        "change_summary": 1, "diff_field_count": 1,
        "lock_bypass_ack": 1, "signature_invalidated": 1,
        "restore_of_version": 1,
    }
    if include_snapshot:
        projection["snapshot"] = 1

    _lim = limit if isinstance(limit, (int, float)) else 50
    raw: List[Dict[str, Any]] = []
    async for row in db.document_versions.find(q, projection).sort(
        "version", -1,
    ).limit(int(_lim)):
        raw.append(row)

    return {"raw": raw, "total": total}


# ═════════════════════════════════════════════════════════════════
# Phase 1 · legacy metadata-only endpoint (unchanged contract)
# ═════════════════════════════════════════════════════════════════
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
    """Phase 1 shape — metadata only, no ``snapshot`` body."""
    canonical = normalize_doc_type(doc_type)
    if not canonical:
        raise HTTPException(400, f"unknown doc_type {doc_type!r}")

    tenant_id = user.get("tenant_id")
    result = await _list_versions(
        canonical_doc_type=canonical, doc_id=doc_id,
        tenant_id=tenant_id, limit=limit, cursor=cursor,
        include_snapshot=False,
        user_id=(user.get("id") or ""),
    )
    items = []
    for row in result["raw"]:
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
        "total": result["total"],
        "next_cursor": next_cursor,
        "doc_type": canonical,
        "doc_id": doc_id,
    }


# ═════════════════════════════════════════════════════════════════
# Phase 2 · Invoice / Quote alias endpoints (with snapshot body)
# ═════════════════════════════════════════════════════════════════
async def _resolve_quote_or_invoice(
    *, doc_id: str, expected_doc_type: str, tenant_id: Optional[str],
) -> Dict[str, Any]:
    """Fetch a doc from ``db.quotes`` under the caller's tenant.
    Enforces the doc-type discriminator so the ``/invoices/…`` URL
    can't be used to enumerate an estimate's history and vice
    versa. Raises 404 on miss."""
    q: Dict[str, Any] = {"id": doc_id}
    if tenant_id:
        q["tenant_id"] = tenant_id
    doc = await db.quotes.find_one(q, {"_id": 0})
    if not doc:
        raise HTTPException(404, "document_not_found")
    dt = str(doc.get("doc_type") or "quote").lower()
    if expected_doc_type == "invoice" and dt != "invoice":
        raise HTTPException(404, "not_an_invoice")
    if expected_doc_type == "quote" and dt == "invoice":
        raise HTTPException(404, "not_a_quote")
    return doc


async def _phase2_list_response(
    *, canonical_doc_type: str, doc_id: str, tenant_id: Optional[str],
    limit: int, cursor: Optional[int], user_id: str,
) -> Dict[str, Any]:
    result = await _list_versions(
        canonical_doc_type=canonical_doc_type, doc_id=doc_id,
        tenant_id=tenant_id, limit=limit, cursor=cursor,
        include_snapshot=True, user_id=user_id,
    )
    name_by_id = await _hydrate_user_names(result["raw"])
    items = [
        _to_wire_row(
            r, name_by_id.get(r.get("saved_by_user_id") or "", ""),
        )
        for r in result["raw"]
    ]
    next_cursor = None
    if len(items) == limit and items:
        next_cursor = items[-1]["version"]
    return {
        "items": items,
        "total": result["total"],
        "next_cursor": next_cursor,
        "doc_type": canonical_doc_type,
        "doc_id": doc_id,
    }


@router.get(
    "/invoices/{id}/versions",
    summary="List version history for an invoice",
    description=(
        "Feb-2026 · Editable Sent Docs Phase 2. Admin-only, "
        "tenant-scoped, rate-limited to 20 requests / minute / "
        "user. Returns full ``document_snapshot`` bodies inline so "
        "the drawer's quick-preview modal never needs a follow-up "
        "round-trip. Ordered newest first."
    ),
    responses={
        200: {"description": "Version list"},
        404: {"description": (
            "Invoice not found in the caller's tenant, or the doc "
            "id resolves to a quote/estimate — use ``/api/quotes/"
            "{qid}/versions`` for those."
        )},
        429: {"description": "Rate limit exceeded (20 / minute / user)"},
    },
)
async def list_invoice_versions(
    id: str,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[int] = Query(default=None),
    user: dict = Depends(require_admin),
) -> Dict[str, Any]:
    tenant_id = user.get("tenant_id")
    # Ensures the doc exists AND is an invoice under this tenant.
    await _resolve_quote_or_invoice(
        doc_id=id, expected_doc_type="invoice", tenant_id=tenant_id,
    )
    return await _phase2_list_response(
        canonical_doc_type="invoice", doc_id=id,
        tenant_id=tenant_id, limit=limit, cursor=cursor,
        user_id=(user.get("id") or ""),
    )


@router.get(
    "/quotes/{qid}/versions",
    summary="List version history for a quote / estimate",
    description=(
        "Feb-2026 · Editable Sent Docs Phase 2. Same contract as "
        "``/invoices/{id}/versions`` — admin-only, tenant-scoped, "
        "rate-limited to 20/min/user, includes the full "
        "``document_snapshot`` inline."
    ),
    responses={
        200: {"description": "Version list"},
        404: {"description": (
            "Quote/estimate not found in tenant, or the id "
            "resolves to an invoice — use ``/api/invoices/{id}/"
            "versions`` for those."
        )},
        429: {"description": "Rate limit exceeded (20 / minute / user)"},
    },
)
async def list_quote_versions(
    qid: str,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[int] = Query(default=None),
    user: dict = Depends(require_admin),
) -> Dict[str, Any]:
    tenant_id = user.get("tenant_id")
    await _resolve_quote_or_invoice(
        doc_id=qid, expected_doc_type="quote", tenant_id=tenant_id,
    )
    return await _phase2_list_response(
        canonical_doc_type="quote", doc_id=qid,
        tenant_id=tenant_id, limit=limit, cursor=cursor,
        user_id=(user.get("id") or ""),
    )
