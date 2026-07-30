"""LZ5 · Feb-2026 — Lumino Payment Link Backfill.

Retro-active dispatcher for unpaid invoices that pre-date the LZ2
Zapier bridge (or where the initial dispatch was lost). Iterates
Reads ``db.quotes`` (``doc_type=="invoice"``, the sole source of truth
post-Phase 11) for candidates that:

  * are ``doc_type=invoice``
  * have ``status`` in an unpaid state (``sent``, ``overdue``,
    ``partial``, ``unpaid``, or ``None`` — legacy rows sometimes
    predate the status field)
  * do NOT already carry ``lumino_payment_url`` (or the legacy
    ``lumino_payment_link``) — the field name we write today is
    ``lumino_payment_url`` per LZ1/LZ3 convention, but we check
    both to be safe
  * are NOT paid (``paid_at`` missing / falsey), voided, or cancelled

For each candidate, reuses the exact same code path as
``POST /api/invoices/{id}/request-payment-link`` — namely
``services.lumino_zapier_dispatcher.dispatch_invoice_link_request``.
On success we write an audit row (``kind="lumino_backfill"``) with
the correlation id.

Route
-----
``POST /api/admin/lumino/backfill-payment-links``  (super_admin only)

Body
----
::

    {
      "dry_run": true,                        # default true — no dispatch
      "limit": 100,                           # default 100, hard-capped 500
      "tenant_id": "opt",                     # optional single-tenant scope
      "invoice_ids": ["a", "b", ...],         # optional explicit list
      "min_created_at": "2025-01-01T00:00:00Z" # optional ISO lower bound
    }

Response
--------
::

    {
      "dry_run": bool,
      "total_candidates": int,
      "dispatched": int,
      "skipped": int,
      "errors": int,
      "results": [
        {"invoice_id": "...", "invoice_number": "...",
          "status": "dispatched"|"skipped"|"error",
          "correlation_id": "...", "reason": "..."}
      ]
    }
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from services.lumino_zapier_dispatcher import dispatch_invoice_link_request
from utils import get_current_user

router = APIRouter()

# Hard cap enforced regardless of client-supplied ``limit``.
_HARD_CAP = 500
# Small polite delay between dispatches so we don't hammer Zapier.
_DISPATCH_SLEEP_SECS = 0.25

_UNPAID_STATUSES = ["sent", "overdue", "partial", "unpaid", None]


class BackfillBody(BaseModel):
    dry_run: bool = True
    limit: int = Field(100, ge=1, le=_HARD_CAP)
    tenant_id: Optional[str] = None
    invoice_ids: Optional[List[str]] = None
    min_created_at: Optional[str] = None


def _require_super_admin(user: dict) -> None:
    role = (user or {}).get("role")
    if role != "super_admin":
        raise HTTPException(403, {"error": "super_admin_only"})


def _has_lumino_link(inv: Dict[str, Any]) -> bool:
    return bool(
        (inv.get("lumino_payment_url") or "").strip()
        or (inv.get("lumino_payment_link") or "").strip()
    )


def _is_paid(inv: Dict[str, Any]) -> bool:
    if inv.get("paid_at"):
        return True
    if (inv.get("status") or "").lower() in ("paid", "closed"):
        return True
    if (inv.get("payment_status") or "").lower() == "paid":
        return True
    return False


def _is_dead(inv: Dict[str, Any]) -> bool:
    return (inv.get("status") or "").lower() in (
        "void", "voided", "cancelled", "canceled", "refunded",
    )


async def _load_candidates(body: BackfillBody) -> List[Dict[str, Any]]:
    """Return up to ``body.limit`` unpaid invoices with no Lumino link.

    Phase 11 (Feb-2026) — single-collection reader. Reads only from
    ``db.quotes`` (``doc_type=invoice``, the source of truth). The
    former ``db.invoices`` fallback was retired.
    """
    limit = min(body.limit, _HARD_CAP)

    base_query: Dict[str, Any] = {}
    if body.tenant_id:
        base_query["tenant_id"] = body.tenant_id
    if body.min_created_at:
        base_query["created_at"] = {"$gte": body.min_created_at}
    if body.invoice_ids:
        base_query["id"] = {"$in": body.invoice_ids}

    # ─── db.quotes (doc_type=invoice) — source of truth ───
    quotes_query = dict(base_query)
    quotes_query["doc_type"] = "invoice"
    quotes_query["status"] = {"$in": _UNPAID_STATUSES}
    quotes_query["paid_at"] = {"$in": [None, ""]}
    # NOTE: Mongo ``$in [None,""]`` also matches "field missing" in
    # most driver versions but not all — add an explicit ``$exists``
    # branch via $or to be safe.
    quotes_query = {"$and": [
        {k: v for k, v in quotes_query.items() if k != "paid_at"},
        {"$or": [
            {"paid_at": {"$exists": False}},
            {"paid_at": None},
            {"paid_at": ""},
        ]},
        {"$or": [
            {"lumino_payment_url": {"$exists": False}},
            {"lumino_payment_url": None},
            {"lumino_payment_url": ""},
        ]},
        {"$or": [
            {"lumino_payment_link": {"$exists": False}},
            {"lumino_payment_link": None},
            {"lumino_payment_link": ""},
        ]},
    ]}
    rows = await db.quotes.find(quotes_query, {"_id": 0}).sort(
        "created_at", -1).to_list(limit * 2)

    # Final in-Python filter — belt-and-braces for the guards the
    # dispatcher would otherwise apply anyway.
    out: List[Dict[str, Any]] = []
    for inv in rows:
        if _has_lumino_link(inv):
            continue
        if _is_paid(inv):
            continue
        if _is_dead(inv):
            continue
        out.append(inv)
        if len(out) >= limit:
            break
    return out


async def _load_customer(inv: Dict[str, Any]) -> Dict[str, Any]:
    """Minimal customer payload for the dispatcher (mirror of the
    single-invoice endpoint)."""
    cid = inv.get("customer_id")
    if not cid:
        return {}
    cust = await db.customers.find_one({"id": cid}, {"_id": 0})
    if cust:
        return cust
    return {"id": cid,
            "name": inv.get("customer_name"),
            "email": inv.get("customer_email")}


async def _write_audit(*, invoice: Dict[str, Any], user: Dict[str, Any],
                        correlation_id: str, tenant_id: Optional[str]) -> None:
    """Persist a ``kind=lumino_backfill`` row to ``db.audits`` so the
    backfill can be reconciled after the fact."""
    doc = {
        "id": uuid.uuid4().hex,
        "kind": "lumino_backfill",
        "invoice_id": invoice.get("id"),
        "invoice_number": invoice.get("invoice_number"),
        "correlation_id": correlation_id,
        "tenant_id": tenant_id or invoice.get("tenant_id"),
        "dispatched_by_user_id": (user or {}).get("id"),
        "dispatched_by_email": (user or {}).get("email"),
        "received_at": datetime.now(timezone.utc),
        "source": "lz5_backfill",
    }
    try:
        await db.audits.insert_one(dict(doc))
    except Exception as exc:                                          # noqa: BLE001
        logger.warning("[LZ5] audit insert failed invoice=%s err=%s",
                        invoice.get("id"), type(exc).__name__)


@router.post("/admin/lumino/backfill-payment-links")
async def backfill_payment_links(
    body: BackfillBody,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_super_admin(user)

    candidates = await _load_candidates(body)

    # ─── Dry-run branch ───────────────────────────────────────────
    if body.dry_run:
        preview = [
            {
                "invoice_id": inv.get("id"),
                "invoice_number": inv.get("invoice_number"),
                "customer_id": inv.get("customer_id"),
                "customer_name": inv.get("customer_name"),
                "total": inv.get("total"),
                "status": inv.get("status"),
                "created_at": inv.get("created_at"),
            }
            for inv in candidates
        ]
        return {
            "dry_run": True,
            "total_candidates": len(candidates),
            "dispatched": 0,
            "skipped": 0,
            "errors": 0,
            "results": preview,
        }

    # ─── Live dispatch branch ─────────────────────────────────────
    dispatched = skipped = errors = 0
    results: List[Dict[str, Any]] = []

    for idx, inv in enumerate(candidates):
        entry = {
            "invoice_id": inv.get("id"),
            "invoice_number": inv.get("invoice_number"),
            "status": "error",
            "correlation_id": None,
            "reason": None,
        }
        try:
            customer = await _load_customer(inv)
            outcome = await dispatch_invoice_link_request(
                inv, customer, base_return_url="",
            )
            entry["correlation_id"] = outcome.get("correlation_id")
            if outcome.get("dispatched"):
                entry["status"] = "dispatched"
                entry["reason"] = None
                dispatched += 1
                await _write_audit(
                    invoice=inv, user=user,
                    correlation_id=outcome.get("correlation_id") or "",
                    tenant_id=body.tenant_id,
                )
            else:
                entry["status"] = "skipped"
                entry["reason"] = outcome.get("reason") or "unknown"
                skipped += 1
        except Exception as exc:                                      # noqa: BLE001
            entry["status"] = "error"
            entry["reason"] = f"{type(exc).__name__}: {exc}"
            errors += 1
            logger.warning("[LZ5] dispatch crashed for invoice=%s: %s",
                            inv.get("id"), exc)
        results.append(entry)

        # Polite pacing so we don't slam Zapier in tight loops.
        if idx < len(candidates) - 1:
            await asyncio.sleep(_DISPATCH_SLEEP_SECS)

    logger.info(
        "[LZ5] backfill complete candidates=%d dispatched=%d skipped=%d "
        "errors=%d by=%s",
        len(candidates), dispatched, skipped, errors,
        (user or {}).get("email"),
    )
    return {
        "dry_run": False,
        "total_candidates": len(candidates),
        "dispatched": dispatched,
        "skipped": skipped,
        "errors": errors,
        "results": results,
    }
