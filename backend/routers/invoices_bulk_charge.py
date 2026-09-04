"""Phase 14b · Feb-2026 — Invoice filters + bulk charge-card-on-file.

Composes strictly on top of Phase 14a's ``services.payments.stripe_charge``.
No new Stripe primitives; this module orchestrates dry-run eligibility
scans + sequential real charges, and persists an audit trail into the
fresh ``db.bulk_charge_runs`` collection.

Endpoints (all under ``/api``):
* ``GET /invoices/line-item-categories`` — distinct catalog per tenant.
* ``POST /invoices/bulk-charge-card-on-file`` — dry-run OR real charge.
* ``GET  /invoices/bulk-charge-runs``       — recent runs list.
* ``GET  /invoices/bulk-charge-runs/{id}`` — run detail.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from config import db
from routers.tenants import get_current_tenant
from services.payments import stripe_charge as stripe_svc
from utils import get_current_user

logger = logging.getLogger("invoices_bulk_charge")
router = APIRouter(tags=["invoices-bulk"])

_ADMIN_ROLES = ("admin", "manager", "super_admin")
_MAX_BULK_INVOICES = 100
_IDEMPOTENCY_WINDOW_HOURS = 24
_INTER_CHARGE_DELAY_SEC = 0.075  # 75 ms sits inside the 50-100 ms spec band.

# ── 60-second in-memory category cache per (tenant_id) ────────────────
_CATEGORY_CACHE: Dict[str, Dict[str, Any]] = {}
_CATEGORY_TTL_SEC = 60


def _require_admin(user: dict) -> None:
    if (user.get("role") or "") not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin/manager only")


# ═════════════════════════════════════════════════════════════════════
# Distinct categories helper
# ═════════════════════════════════════════════════════════════════════
@router.get("/invoices/line-item-categories")
async def get_line_item_categories(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    now = time.monotonic()
    cached = _CATEGORY_CACHE.get(tenant["id"])
    if cached and (now - cached["at"]) < _CATEGORY_TTL_SEC:
        return {"categories": cached["value"], "cached": True}

    pipeline = [
        {"$match": {"tenant_id": tenant["id"], "doc_type": "invoice"}},
        {"$unwind": "$line_items"},
        {"$match": {"line_items.category": {"$nin": [None, ""]}}},
        {"$group": {"_id": {"$toLower": "$line_items.category"},
                     "display": {"$first": "$line_items.category"}}},
        {"$sort": {"display": 1}},
        {"$limit": 200},
    ]
    values = [row["display"] async for row in db.quotes.aggregate(pipeline)]
    _CATEGORY_CACHE[tenant["id"]] = {"value": values, "at": now}
    return {"categories": values, "cached": False}


# ═════════════════════════════════════════════════════════════════════
# Bulk charge — request/response models
# ═════════════════════════════════════════════════════════════════════
class BulkChargeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_ids: List[str] = Field(min_length=1, max_length=_MAX_BULK_INVOICES)
    dry_run: bool = True
    idempotency_key: str = Field(min_length=1, max_length=200)


# ── Eligibility helpers ──────────────────────────────────────────────
def _card_expired(pm: dict, now: datetime) -> bool:
    exp_y = pm.get("exp_year")
    exp_m = pm.get("exp_month")
    if not exp_y or not exp_m:
        # No expiry data — treat as valid (Stripe would still validate).
        return False
    try:
        exp_y = int(exp_y)
        exp_m = int(exp_m)
    except (TypeError, ValueError):
        return False
    if exp_y < now.year:
        return True
    if exp_y == now.year and exp_m < now.month:
        return True
    return False


async def _pick_default_pm(tenant_id: str, customer_id: str) -> Optional[dict]:
    """Return the customer's default (or only) non-deleted PM, or None."""
    q = {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
    }
    default_pm = await db.payment_methods.find_one(
        {**q, "is_default": True}, {"_id": 0}
    )
    if default_pm:
        return default_pm
    return await db.payment_methods.find_one(q, {"_id": 0})


async def _eligibility_and_pm(
    invoice: dict, tenant_id: str, now: datetime,
) -> tuple[str, Optional[dict], Optional[dict]]:
    """Return (status_or_reason, payment_method_or_None, meta).

    ``status_or_reason`` values:
      * "eligible"        — clear to charge.
      * "already_paid" | "zero_balance" | "no_card_on_file" | "card_expired"
    """
    total = float(invoice.get("total") or 0)
    paid = float(invoice.get("amount_paid") or 0)
    outstanding_cents = int(round(max(0.0, total - paid) * 100))
    # ``zero_balance`` first: a total of 0 (or negative) means there's
    # nothing to charge — the invoice was never billable. That's a
    # distinct diagnostic from ``already_paid`` (money actually collected).
    if total <= 0:
        return "zero_balance", None, {"outstanding_cents": 0}
    if (invoice.get("payment_status") or "").lower() == "paid" or paid >= total:
        return "already_paid", None, {"outstanding_cents": 0}
    if (total - paid) <= 0:
        return "zero_balance", None, {"outstanding_cents": 0}
    pm = await _pick_default_pm(tenant_id, invoice.get("customer_id"))
    if not pm:
        return "no_card_on_file", None, {"outstanding_cents": outstanding_cents}
    if _card_expired(pm, now):
        return "card_expired", pm, {"outstanding_cents": outstanding_cents}
    return "eligible", pm, {"outstanding_cents": outstanding_cents}


# ── Bulk charge endpoint ──────────────────────────────────────────────
@router.post("/invoices/bulk-charge-card-on-file")
async def bulk_charge_card_on_file(
    body: BulkChargeBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    return await execute_bulk_charge(body=body, user=user, tenant=tenant)


async def execute_bulk_charge(
    *, body: BulkChargeBody, user: dict, tenant: dict
) -> Dict[str, Any]:
    """Core loop — extracted so pytest can drive it in-process (bypassing
    HTTP + Depends) to keep the stripe stub inside the same interpreter."""

    # ── Idempotency replay guard ─────────────────────────────────────
    existing = await db.bulk_charge_runs.find_one(
        {"tenant_id": tenant["id"], "idempotency_key": body.idempotency_key},
        {"_id": 0},
    )
    if existing:
        # Enforce the 24 h window — outside that window we still return the
        # persisted response (idempotency keys are permanent; the DB unique
        # index would reject a re-insert either way).
        return {
            "run_id": existing["run_id"],
            "dry_run": existing["dry_run"],
            "results": existing["results"],
            "summary": existing["summary"],
            "replayed": True,
        }

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    now = started_at
    results: List[Dict[str, Any]] = []

    # Preload all invoices in one query so cross-tenant IDs get ``not_found``
    # without leaking a hint through per-row lookups.
    docs = await db.quotes.find(
        {
            "id": {"$in": body.invoice_ids},
            "tenant_id": tenant["id"],
            "doc_type": "invoice",
        },
        {"_id": 0},
    ).to_list(_MAX_BULK_INVOICES)
    by_id = {d["id"]: d for d in docs}

    total_amount_cents = 0
    for invoice_id in body.invoice_ids:
        invoice = by_id.get(invoice_id)
        if not invoice:
            results.append({
                "invoice_id": invoice_id,
                "status": "skipped",
                "skip_reason": "not_found",
            })
            continue
        reason, pm, meta = await _eligibility_and_pm(invoice, tenant["id"], now)
        outstanding_cents = int(meta.get("outstanding_cents") or 0)
        if reason != "eligible":
            results.append({
                "invoice_id": invoice_id,
                "status": "skipped",
                "skip_reason": reason,
            })
            continue

        if body.dry_run:
            results.append({
                "invoice_id": invoice_id,
                "status": "would_charge",
                "amount_cents": outstanding_cents,
                "payment_method_id": pm.get("provider_payment_method_id"),
            })
            total_amount_cents += outstanding_cents
            continue

        # Real charge path — rate-limit between calls.
        if any(r["status"] == "charged" for r in results):
            await asyncio.sleep(_INTER_CHARGE_DELAY_SEC)
        try:
            res = await stripe_svc.charge_card_on_file(
                tenant_id=tenant["id"],
                customer_id=invoice["customer_id"],
                payment_method_id=pm["provider_payment_method_id"],
                amount_cents=outstanding_cents,
                currency=(invoice.get("currency") or "usd"),
                invoice_id=invoice_id,
                description=f"Invoice {invoice.get('invoice_number') or invoice_id}",
                metadata={"bulk_run_id": run_id,
                            "bulk_idempotency_key": body.idempotency_key},
                actor_user_id=user.get("id"),
                idempotency_key=f"{body.idempotency_key}:{invoice_id}",
                # K14 · Feb-2026 — propagate the K13 impersonation
                # context so the ``stripe_charges`` row (payments
                # ledger) records who really pressed the button.
                via_impersonation=bool(user.get("is_impersonated")),
                acting_admin_id=user.get("impersonator_id"),
            )
        except Exception as exc:  # noqa: BLE001 — bubble as failed row.
            results.append({
                "invoice_id": invoice_id,
                "status": "failed",
                "error_code": type(exc).__name__,
                "error_message": str(exc)[:400],
                "amount_charged_cents": 0,
            })
            continue

        if res.get("ok") and res.get("payment_intent_id"):
            results.append({
                "invoice_id": invoice_id,
                "status": "charged",
                "charge_id": res.get("payment_intent_id"),
                "amount_charged_cents": outstanding_cents,
                "provider_status": res.get("status"),
            })
            total_amount_cents += outstanding_cents
            # K14 · Feb-2026 — emit a communication-timeline audit
            # event so the customer's timeline surfaces "Invoice
            # auto-charged" alongside emails/SMS. Non-blocking:
            # the ledger already carries the payments row; a failure
            # here must not cause a charged invoice to appear failed.
            try:
                await db.audit_events.insert_one({
                    "id": str(uuid.uuid4()),
                    "event_type": "invoice_auto_charged",
                    "tenant_id": tenant["id"],
                    "actor_id": user.get("id"),
                    "actor_email": user.get("email"),
                    "via_impersonation": bool(user.get("is_impersonated")),
                    "acting_admin_id": user.get("impersonator_id"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "payload": {
                        "invoice_id": invoice_id,
                        "customer_id": invoice.get("customer_id"),
                        "amount_cents": outstanding_cents,
                        "currency": (invoice.get("currency") or "usd"),
                        "payment_intent_id": res.get("payment_intent_id"),
                        "payment_method_id": pm.get("provider_payment_method_id"),
                        "bulk_run_id": run_id,
                        "invoice_number": invoice.get("invoice_number"),
                    },
                })
            except Exception as _ae:  # noqa: BLE001
                logger.warning(
                    "[bulk-charge] audit_events insert failed inv=%s: %s",
                    invoice_id, _ae,
                )
            # Mirror payment_status on the invoice (best-effort — the
            # webhook handler in Phase 14a upserts the charge row; this
            # patch keeps the invoice list fresh without waiting).
            try:
                await db.quotes.update_one(
                    {"id": invoice_id, "tenant_id": tenant["id"]},
                    {
                        "$set": {
                            "payment_status": "paid",
                            "amount_paid": float(invoice.get("total") or 0),
                            "last_bulk_charge_run_id": run_id,
                            "last_charge_at": datetime.now(timezone.utc).isoformat(),
                        }
                    },
                )
            except Exception as exc:  # pragma: no cover — never blocks
                logger.warning("[bulk-charge] mirror payment_status failed: %s", exc)
        else:
            # Phase 14a returned a non-ok result without raising (e.g.
            # PaymentIntent requires_action). Record as failed — no charge id.
            results.append({
                "invoice_id": invoice_id,
                "status": "failed",
                "error_code": "not_ok_no_charge_id",
                "error_message": (
                    f"provider status={res.get('status') or 'unknown'} "
                    f"pi={res.get('payment_intent_id')}"
                )[:400],
                "provider_status": res.get("status"),
                "amount_charged_cents": 0,
            })

    summary = {
        "total": len(results),
        "charged": sum(1 for r in results if r["status"] == "charged"),
        "would_charge": sum(1 for r in results if r["status"] == "would_charge"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "total_amount_charged_cents": (
            sum(int(r.get("amount_charged_cents") or 0) for r in results
                 if r["status"] == "charged")
        ),
    }

    completed_at = datetime.now(timezone.utc)
    run_doc = {
        "id": run_id,
        "run_id": run_id,
        "tenant_id": tenant["id"],
        "idempotency_key": body.idempotency_key,
        "initiated_by": user.get("id"),
        "dry_run": body.dry_run,
        "invoice_count": len(body.invoice_ids),
        "total_amount_cents": total_amount_cents,
        "results": results,
        "summary": summary,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    try:
        await db.bulk_charge_runs.insert_one(run_doc)
    except Exception as exc:
        # Unique-index race: another concurrent call raced to insert with the
        # same (tenant, idempotency_key). Fall through to the replay branch.
        logger.warning("[bulk-charge] insert race: %s", exc)
        again = await db.bulk_charge_runs.find_one(
            {"tenant_id": tenant["id"], "idempotency_key": body.idempotency_key},
            {"_id": 0},
        )
        if again:
            return {
                "run_id": again["run_id"],
                "dry_run": again["dry_run"],
                "results": again["results"],
                "summary": again["summary"],
                "replayed": True,
            }
        raise

    return {
        "run_id": run_id,
        "dry_run": body.dry_run,
        "results": results,
        "summary": summary,
    }


# ═════════════════════════════════════════════════════════════════════
# Phase K38 · Feb-2026 — Bulk charge ACH on file.
# Mirrors the card flow above but:
#  * Filters PMs by ``type == "us_bank_account"`` and requires
#    ``verification_status == "verified"``.
#  * Delegates to :func:`stripe_svc.charge_ach_on_file` which requests
#    a ``payment_method_types=["us_bank_account"]`` PaymentIntent —
#    Stripe returns ``status="processing"`` on the initial confirm.
#  * Flips the invoice to ``pending_ach`` (NOT ``paid``) — the
#    webhook (``payment_intent.succeeded``) moves it to ``paid`` when
#    settlement clears in 3–5 business days.
# ═════════════════════════════════════════════════════════════════════
async def _pick_default_ach_pm(tenant_id: str, customer_id: str) -> Optional[dict]:
    """Return the customer's default (or only) verified ``us_bank_account``
    payment method mirror row, or ``None``.
    """
    base_q = {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "type": "us_bank_account",
        "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
    }
    default_pm = await db.payment_methods.find_one(
        {**base_q, "is_default": True}, {"_id": 0}
    )
    if default_pm:
        return default_pm
    return await db.payment_methods.find_one(base_q, {"_id": 0})


async def _ach_eligibility_and_pm(
    invoice: dict, tenant_id: str,
) -> tuple[str, Optional[dict], Optional[dict]]:
    """Return (status_or_reason, payment_method_or_None, meta).

    ``status_or_reason`` values:
      * "eligible"          — clear to charge.
      * "already_paid" | "zero_balance" | "pending_ach"
      * "no_bank_on_file"   — no us_bank_account PM.
      * "bank_unverified"   — PM exists but verification_status != verified.
    """
    total = float(invoice.get("total") or 0)
    paid = float(invoice.get("amount_paid") or 0)
    outstanding_cents = int(round(max(0.0, total - paid) * 100))
    if total <= 0:
        return "zero_balance", None, {"outstanding_cents": 0}
    pstatus = (invoice.get("payment_status") or "").lower()
    if pstatus == "paid" or paid >= total:
        return "already_paid", None, {"outstanding_cents": 0}
    if pstatus == "pending_ach":
        return "pending_ach", None, {"outstanding_cents": outstanding_cents}
    if (total - paid) <= 0:
        return "zero_balance", None, {"outstanding_cents": 0}
    pm = await _pick_default_ach_pm(tenant_id, invoice.get("customer_id"))
    if not pm:
        return "no_bank_on_file", None, {"outstanding_cents": outstanding_cents}
    if (pm.get("verification_status") or "") != "verified":
        return "bank_unverified", pm, {"outstanding_cents": outstanding_cents}
    return "eligible", pm, {"outstanding_cents": outstanding_cents}


@router.post("/invoices/bulk-charge-ach-on-file")
async def bulk_charge_ach_on_file(
    body: BulkChargeBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    return await execute_bulk_charge_ach(body=body, user=user, tenant=tenant)


async def execute_bulk_charge_ach(
    *, body: BulkChargeBody, user: dict, tenant: dict
) -> Dict[str, Any]:
    """Core loop for ACH bulk charge — extracted so pytest can drive it
    in-process (bypassing HTTP + Depends) to keep the stripe stub inside
    the same interpreter."""

    # Idempotency replay — same 24h window as the card flow.
    existing = await db.bulk_charge_runs.find_one(
        {"tenant_id": tenant["id"], "idempotency_key": body.idempotency_key},
        {"_id": 0},
    )
    if existing:
        return {
            "run_id": existing["run_id"],
            "dry_run": existing["dry_run"],
            "results": existing["results"],
            "summary": existing["summary"],
            "replayed": True,
            "payment_method_type": existing.get("payment_method_type") or "ach",
        }

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    results: List[Dict[str, Any]] = []

    docs = await db.quotes.find(
        {
            "id": {"$in": body.invoice_ids},
            "tenant_id": tenant["id"],
            "doc_type": "invoice",
        },
        {"_id": 0},
    ).to_list(_MAX_BULK_INVOICES)
    by_id = {d["id"]: d for d in docs}

    total_amount_cents = 0
    for invoice_id in body.invoice_ids:
        invoice = by_id.get(invoice_id)
        if not invoice:
            results.append({
                "invoice_id": invoice_id,
                "status": "skipped",
                "skip_reason": "not_found",
            })
            continue
        reason, pm, meta = await _ach_eligibility_and_pm(invoice, tenant["id"])
        outstanding_cents = int(meta.get("outstanding_cents") or 0)
        if reason != "eligible":
            results.append({
                "invoice_id": invoice_id,
                "status": "skipped",
                "skip_reason": reason,
            })
            continue

        if body.dry_run:
            results.append({
                "invoice_id": invoice_id,
                "status": "would_charge",
                "amount_cents": outstanding_cents,
                "payment_method_id": pm.get("provider_payment_method_id"),
                "bank_last4": pm.get("last4") or "",
                "bank_name": pm.get("bank_name") or "",
            })
            total_amount_cents += outstanding_cents
            continue

        # Real ACH intent create — rate-limit between calls.
        if any(r["status"] == "initiated" for r in results):
            await asyncio.sleep(_INTER_CHARGE_DELAY_SEC)
        try:
            res = await stripe_svc.charge_ach_on_file(
                tenant_id=tenant["id"],
                customer_id=invoice["customer_id"],
                payment_method_id=pm["provider_payment_method_id"],
                amount_cents=outstanding_cents,
                currency=(invoice.get("currency") or "usd"),
                invoice_id=invoice_id,
                description=f"Invoice {invoice.get('invoice_number') or invoice_id}",
                metadata={"bulk_run_id": run_id,
                            "bulk_idempotency_key": body.idempotency_key},
                actor_user_id=user.get("id"),
                idempotency_key=f"{body.idempotency_key}:ach:{invoice_id}",
                via_impersonation=bool(user.get("is_impersonated")),
                acting_admin_id=user.get("impersonator_id"),
            )
        except Exception as exc:  # noqa: BLE001
            results.append({
                "invoice_id": invoice_id,
                "status": "failed",
                "error_code": type(exc).__name__,
                "error_message": str(exc)[:400],
                "amount_charged_cents": 0,
            })
            continue

        if res.get("ok") and res.get("payment_intent_id"):
            results.append({
                "invoice_id": invoice_id,
                "status": "initiated",
                "charge_id": res.get("payment_intent_id"),
                "amount_charged_cents": outstanding_cents,
                "provider_status": res.get("status"),
                "bank_last4": pm.get("last4") or "",
                "bank_name": pm.get("bank_name") or "",
            })
            total_amount_cents += outstanding_cents
            # Emit audit event for the ACH initiation. Non-blocking.
            try:
                await db.audit_events.insert_one({
                    "id": str(uuid.uuid4()),
                    "event_type": "invoice_ach_initiated",
                    "tenant_id": tenant["id"],
                    "actor_id": user.get("id"),
                    "actor_email": user.get("email"),
                    "via_impersonation": bool(user.get("is_impersonated")),
                    "acting_admin_id": user.get("impersonator_id"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "payload": {
                        "invoice_id": invoice_id,
                        "customer_id": invoice.get("customer_id"),
                        "amount_cents": outstanding_cents,
                        "currency": (invoice.get("currency") or "usd"),
                        "payment_intent_id": res.get("payment_intent_id"),
                        "payment_method_id": pm.get("provider_payment_method_id"),
                        "bulk_run_id": run_id,
                        "invoice_number": invoice.get("invoice_number"),
                        "bank_last4": pm.get("last4") or "",
                    },
                })
            except Exception as _ae:  # noqa: BLE001
                logger.warning(
                    "[bulk-charge-ach] audit_events insert failed inv=%s: %s",
                    invoice_id, _ae,
                )
            # Flip invoice to ``pending_ach`` — NOT ``paid``. The
            # ``payment_intent.succeeded`` webhook (3–5 business days
            # later) will flip pending_ach → paid; a
            # ``payment_intent.payment_failed`` will revert to unpaid.
            try:
                await db.quotes.update_one(
                    {"id": invoice_id, "tenant_id": tenant["id"]},
                    {
                        "$set": {
                            "payment_status": "pending_ach",
                            "last_bulk_charge_run_id": run_id,
                            "last_ach_intent_id": res.get("payment_intent_id"),
                            "last_charge_at": datetime.now(timezone.utc).isoformat(),
                        }
                    },
                )
            except Exception as exc:  # pragma: no cover — never blocks
                logger.warning("[bulk-charge-ach] pending_ach mirror failed: %s", exc)
        else:
            results.append({
                "invoice_id": invoice_id,
                "status": "failed",
                "error_code": "not_ok_no_charge_id",
                "error_message": (
                    f"provider status={res.get('status') or 'unknown'} "
                    f"pi={res.get('payment_intent_id')}"
                )[:400],
                "provider_status": res.get("status"),
                "amount_charged_cents": 0,
            })

    summary = {
        "total": len(results),
        "initiated": sum(1 for r in results if r["status"] == "initiated"),
        "would_charge": sum(1 for r in results if r["status"] == "would_charge"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "total_amount_initiated_cents": (
            sum(int(r.get("amount_charged_cents") or 0) for r in results
                 if r["status"] == "initiated")
        ),
    }

    completed_at = datetime.now(timezone.utc)
    run_doc = {
        "id": run_id,
        "run_id": run_id,
        "tenant_id": tenant["id"],
        "idempotency_key": body.idempotency_key,
        "initiated_by": user.get("id"),
        "dry_run": body.dry_run,
        "invoice_count": len(body.invoice_ids),
        "total_amount_cents": total_amount_cents,
        "payment_method_type": "ach",
        "results": results,
        "summary": summary,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    try:
        await db.bulk_charge_runs.insert_one(run_doc)
    except Exception as exc:
        # Unique-index race — replay branch.
        logger.warning("[bulk-charge-ach] insert race: %s", exc)
        again = await db.bulk_charge_runs.find_one(
            {"tenant_id": tenant["id"], "idempotency_key": body.idempotency_key},
            {"_id": 0},
        )
        if again:
            return {
                "run_id": again["run_id"],
                "dry_run": again["dry_run"],
                "results": again["results"],
                "summary": again["summary"],
                "replayed": True,
                "payment_method_type": again.get("payment_method_type") or "ach",
            }
        raise

    return {
        "run_id": run_id,
        "dry_run": body.dry_run,
        "results": results,
        "summary": summary,
        "payment_method_type": "ach",
    }


# ═════════════════════════════════════════════════════════════════════
# Runs list + detail
# ═════════════════════════════════════════════════════════════════════
@router.get("/invoices/bulk-charge-runs")
async def list_bulk_charge_runs(
    limit: int = Query(20, ge=1, le=200),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    rows = await db.bulk_charge_runs.find(
        {"tenant_id": tenant["id"]},
        {"_id": 0, "results": 0},
    ).sort("started_at", -1).to_list(limit)
    return {"runs": rows}


@router.get("/invoices/bulk-charge-runs/{run_id}")
async def get_bulk_charge_run(
    run_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    doc = await db.bulk_charge_runs.find_one(
        {"tenant_id": tenant["id"], "run_id": run_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "run not found")
    return doc


# ═════════════════════════════════════════════════════════════════════
# Index hook — imported by scripts/create_session_indexes.py boot pass.
# ═════════════════════════════════════════════════════════════════════
async def ensure_indexes(db_client=None) -> None:
    target = db_client if db_client is not None else db
    from pymongo.errors import OperationFailure
    try:
        await target.bulk_charge_runs.create_index(
            [("tenant_id", 1), ("idempotency_key", 1)],
            name="tenant_idempotency_unique",
            unique=True,
        )
    except OperationFailure as e:
        if "already exists" not in str(e).lower():
            raise
    try:
        await target.bulk_charge_runs.create_index(
            [("tenant_id", 1), ("started_at", -1)],
            name="tenant_started_at_desc",
        )
    except OperationFailure as e:
        if "already exists" not in str(e).lower():
            raise
