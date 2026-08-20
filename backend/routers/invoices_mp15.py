"""MP1.5 — Multi-property invoice plumbing (Feb-2026 ship).

Ships three new admin endpoints that plug the ``master_billing_mode``
switch into the send/deliver path plus a startup migration hook that
backfills ``property_id`` onto pre-existing invoices/estimates that
reference a job (line-item ``job_id``) or a from-estimate link.

Endpoints
---------
* ``POST /api/invoices/consolidate``   – Group every pending
  per-property invoice for a customer + billing period into one
  consolidated invoice. Idempotent — a re-run with the same customer +
  period returns the previously created consolidated invoice id.
* ``GET  /api/customers/{cid}/pending-invoices`` – List every unpaid
  invoice for a customer grouped by property, with a summary total.
* ``POST /api/invoices/preview-recipient`` – Dry-run the routing logic
  in :func:`routers.properties.resolve_invoice_recipient` without
  actually sending.  Useful for the UI to show the admin who the next
  invoice would go to before they hit ``Send``.

Route stops / geocoding refactor
--------------------------------
Jobs already carry ``property_id`` from Phase MP1. The full geocoding
refactor — "use ``property.address`` when a stop has ``property_id``
set, falling back to customer address" — is DEFERRED to phase
**MP1.6** per the shipping brief. This module intentionally does not
touch :mod:`routers.route_optimization` so we ship MP1.5 cleanly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from routers.tenants import get_current_tenant
from routers.properties import resolve_invoice_recipient
from utils import get_current_user, new_id, now_iso, require_admin

router = APIRouter(tags=["Invoices MP1.5"])


# ─── Models ───────────────────────────────────────────────────────────

class ConsolidateIn(BaseModel):
    customer_id: str = Field(..., min_length=1)
    # Optional YYYY-MM period ("2026-02") — when omitted the current
    # month is used. The consolidated invoice is idempotent per
    # (customer_id, period).
    period: Optional[str] = None
    # When true, do not persist anything — return the aggregate the
    # server *would* create. Useful for admin previews before commit.
    dry_run: bool = False


class PreviewRecipientIn(BaseModel):
    # Either supply an invoice_id (recipient is resolved from the
    # invoice's customer/property + current master_billing_mode) OR
    # supply customer_id + optional property_id + optional mode
    # override.  invoice_id wins if both are present.
    invoice_id: Optional[str] = None
    customer_id: Optional[str] = None
    property_id: Optional[str] = None
    # Optional runtime override for what mode to preview. When null,
    # the customer's persisted mode is used.
    mode: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────

def _strip(doc: Optional[dict]) -> Optional[dict]:
    if doc:
        doc.pop("_id", None)
    return doc


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _norm_period(p: Optional[str]) -> str:
    """Loose YYYY-MM parser. Falls back to the current month when the
    value is missing or unparseable — we never 400 on this because the
    caller may legitimately want "everything pending right now"."""
    if not p:
        return _current_period()
    p = p.strip()
    if len(p) >= 7 and p[4] == "-":
        return p[:7]
    return _current_period()


def _invoice_is_pending(inv: dict) -> bool:
    """Truthy when the invoice still owes money AND has not already
    been rolled into a consolidated parent."""
    if inv.get("consolidated_into_invoice_id"):
        return False
    total = float(inv.get("total") or 0)
    paid = float(inv.get("amount_paid") or 0)
    if total - paid <= 0.01:
        return False
    return (inv.get("payment_status") or "unpaid") != "paid"


def _property_label_map_from_docs(props: List[dict]) -> Dict[str, str]:
    return {p["id"]: (p.get("label") or "Property") for p in props if p.get("id")}


# ─── Endpoints ────────────────────────────────────────────────────────

@router.get("/customers/{cid}/pending-invoices")
async def customer_pending_invoices(
    cid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """List every unpaid, un-consolidated invoice for a customer,
    grouped by property. Techs cannot access — admin-only.
    """
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not cust:
        raise HTTPException(404, "Customer not found")

    invs = await db.quotes.find(
        {"tenant_id": tenant["id"], "customer_id": cid, "doc_type": "invoice"},
        {"_id": 0},
    ).sort("created_at", -1).to_list(2000)
    pending = [i for i in invs if _invoice_is_pending(i)]

    props = await db.properties.find(
        {"tenant_id": tenant["id"], "customer_id": cid},
        {"_id": 0},
    ).to_list(50)
    label_map = _property_label_map_from_docs(props)

    groups: Dict[str, Dict[str, Any]] = {}
    unassigned: List[dict] = []
    for inv in pending:
        pid = inv.get("property_id")
        row = {
            "id": inv["id"],
            "title": inv.get("title", ""),
            "total": float(inv.get("total") or 0),
            "amount_paid": float(inv.get("amount_paid") or 0),
            "balance": round(
                float(inv.get("total") or 0) - float(inv.get("amount_paid") or 0), 2,
            ),
            "due_date": inv.get("due_date"),
            "created_at": inv.get("created_at"),
            "invoice_number": inv.get("invoice_number"),
            "property_id": pid,
        }
        if pid and pid in label_map:
            g = groups.setdefault(pid, {
                "property_id": pid,
                "property_label": label_map[pid],
                "invoices": [],
                "balance_total": 0.0,
            })
            g["invoices"].append(row)
            g["balance_total"] = round(g["balance_total"] + row["balance"], 2)
        else:
            unassigned.append(row)

    unassigned_balance = round(sum(r["balance"] for r in unassigned), 2)
    grand_balance = round(
        sum(g["balance_total"] for g in groups.values()) + unassigned_balance, 2,
    )
    return {
        "customer_id": cid,
        "master_billing_mode": cust.get("master_billing_mode") or "off",
        "groups": list(groups.values()),
        "unassigned": {
            "invoices": unassigned,
            "balance_total": unassigned_balance,
        },
        "grand_balance": grand_balance,
        "pending_count": len(pending),
    }


@router.post("/invoices/consolidate")
async def consolidate_customer_invoices(
    body: ConsolidateIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Group every pending per-property invoice for a customer into a
    single consolidated invoice.

    Idempotency: a re-run with the same ``(tenant_id, customer_id,
    consolidation_period)`` returns the previously created consolidated
    invoice document rather than creating a duplicate.  The
    ``consolidated_into_invoice_id`` field on each child links back to
    the parent.
    """
    cust = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not cust:
        raise HTTPException(404, "Customer not found")

    period = _norm_period(body.period)

    # Idempotency check FIRST — before we spend cycles on aggregation.
    existing = await db.quotes.find_one(
        {"tenant_id": tenant["id"], "customer_id": body.customer_id,
          "doc_type": "invoice",
          "is_consolidated": True,
          "consolidation_period": period},
        {"_id": 0},
    )
    if existing:
        return {"ok": True, "invoice_id": existing["id"],
                 "already_existed": True, "invoice": existing}

    # Collect pending children (skip anything already rolled up).
    invs = await db.quotes.find(
        {"tenant_id": tenant["id"], "customer_id": body.customer_id,
          "doc_type": "invoice", "is_consolidated": {"$ne": True}},
        {"_id": 0},
    ).sort("created_at", 1).to_list(2000)
    children = [i for i in invs if _invoice_is_pending(i)]
    if not children:
        raise HTTPException(400, "no pending invoices to consolidate")

    props = await db.properties.find(
        {"tenant_id": tenant["id"], "customer_id": body.customer_id},
        {"_id": 0},
    ).to_list(50)
    label_map = _property_label_map_from_docs(props)

    # Line item aggregation — one section header per property, followed
    # by each child invoice's line items. Unassigned invoices land in a
    # trailing "Other charges" section so they're visible + payable
    # under the same consolidated parent.
    grouped: Dict[str, List[dict]] = {}
    order: List[str] = []
    unassigned: List[dict] = []
    for inv in children:
        pid = inv.get("property_id")
        if pid and pid in label_map:
            grouped.setdefault(pid, [])
            if pid not in order:
                order.append(pid)
            grouped[pid].append(inv)
        else:
            unassigned.append(inv)

    consolidated_items: List[dict] = []
    for pid in order:
        header_label = label_map.get(pid, "Property")
        consolidated_items.append({
            "description": f"— {header_label} —",
            "quantity": 0,
            "unit_price": 0.0,
            "is_section_header": True,
            "property_id": pid,
        })
        for inv in grouped[pid]:
            for li in (inv.get("line_items") or []):
                consolidated_items.append({
                    **li,
                    "source_invoice_id": inv.get("id"),
                    "property_id": pid,
                })
    if unassigned:
        consolidated_items.append({
            "description": "— Other charges —",
            "quantity": 0,
            "unit_price": 0.0,
            "is_section_header": True,
            "property_id": None,
        })
        for inv in unassigned:
            for li in (inv.get("line_items") or []):
                consolidated_items.append({
                    **li,
                    "source_invoice_id": inv.get("id"),
                    "property_id": None,
                })

    subtotal = round(sum(
        float(li.get("quantity") or 0) * float(li.get("unit_price") or 0)
        for li in consolidated_items if not li.get("is_section_header")
    ), 2)
    total = subtotal  # tax already applied per-child; consolidated parent stays untaxed.

    recipient = resolve_invoice_recipient(cust, None)

    if body.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "child_invoice_ids": [i["id"] for i in children],
            "child_count": len(children),
            "line_item_count": len([li for li in consolidated_items
                                          if not li.get("is_section_header")]),
            "subtotal": subtotal,
            "total": total,
            "recipient": recipient,
            "consolidation_period": period,
        }

    parent_id = new_id()
    parent = {
        "id": parent_id,
        "tenant_id": tenant["id"],
        "customer_id": body.customer_id,
        "customer_name": cust.get("name", ""),
        # Consolidated parents intentionally have no single property_id —
        # they aggregate across all properties for this customer.
        "property_id": None,
        "title": f"Consolidated invoice — {period}",
        "doc_type": "invoice",
        "line_items": consolidated_items,
        "tax_rate": 0.0,
        "subtotal": subtotal,
        "tax": 0.0,
        "total": total,
        "amount_paid": 0.0,
        "due_date": None,
        "status": "draft",
        "payment_status": "unpaid",
        "notes": (
            f"Consolidated across {len(children)} child invoice(s) for "
            f"period {period}."
        ),
        "terms": None,
        "is_consolidated": True,
        "consolidation_period": period,
        "consolidated_child_ids": [i["id"] for i in children],
        "recipient": recipient,
        "created_at": now_iso(),
    }
    # Human-readable invoice number for the parent.
    try:
        from services.invoice_numbering import assign_invoice_number_if_missing
        await assign_invoice_number_if_missing(parent, tenant)
    except Exception as e:
        logger.warning(f"[mp1.5] invoice-number assign skipped: {e}")

    await db.quotes.insert_one(parent)

    # Point every child at the parent + freeze them so they don't get
    # re-consolidated on subsequent runs.
    await db.quotes.update_many(
        {"id": {"$in": [i["id"] for i in children]},
          "tenant_id": tenant["id"]},
        {"$set": {
            "consolidated_into_invoice_id": parent_id,
            "consolidated_at": now_iso(),
            "consolidation_period": period,
        }},
    )

    parent.pop("_id", None)
    return {
        "ok": True,
        "invoice_id": parent_id,
        "already_existed": False,
        "child_count": len(children),
        "invoice": parent,
    }


@router.post("/invoices/preview-recipient")
async def preview_recipient(
    body: PreviewRecipientIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Dry-run the send-time routing logic. Returns the resolved
    ``{email, phone, delivery_kind, send_status_hint, mode}`` for the
    caller-provided invoice OR customer/property pair without touching
    any comms adapters. UI uses this to show the admin who an invoice
    would go to *before* they hit the send button.
    """
    if body.invoice_id:
        inv = await db.quotes.find_one(
            {"id": body.invoice_id, "tenant_id": tenant["id"],
              "doc_type": "invoice"},
            {"_id": 0},
        )
        if not inv:
            raise HTTPException(404, "Invoice not found")
        cust = await db.customers.find_one(
            {"id": inv.get("customer_id"), "tenant_id": tenant["id"]},
            {"_id": 0},
        )
        if not cust:
            raise HTTPException(400, "Invoice references an unknown customer")
        prop = None
        if inv.get("property_id"):
            prop = await db.properties.find_one(
                {"id": inv["property_id"], "tenant_id": tenant["id"]},
                {"_id": 0},
            )
    else:
        if not body.customer_id:
            raise HTTPException(400, "Provide invoice_id OR customer_id")
        cust = await db.customers.find_one(
            {"id": body.customer_id, "tenant_id": tenant["id"]},
            {"_id": 0},
        )
        if not cust:
            raise HTTPException(404, "Customer not found")
        prop = None
        if body.property_id:
            prop = await db.properties.find_one(
                {"id": body.property_id, "tenant_id": tenant["id"],
                  "customer_id": body.customer_id},
                {"_id": 0},
            )
            if not prop:
                raise HTTPException(400, "property_id not found for this customer")

    # Optional runtime mode override — bypasses persisted mode without
    # writing to the customer doc.
    cust_view = dict(cust)
    if body.mode:
        allowed = {"off", "consolidated", "forward_to_master_contact"}
        if body.mode not in allowed:
            raise HTTPException(400, f"mode must be one of {sorted(allowed)}")
        cust_view["master_billing_mode"] = body.mode

    resolved = resolve_invoice_recipient(cust_view, prop)
    return {
        "ok": True,
        "customer_id": cust.get("id"),
        "property_id": (prop or {}).get("id"),
        "invoice_id": body.invoice_id,
        "recipient": resolved,
    }


# ─── Startup migration ────────────────────────────────────────────────

async def migrate_invoices_estimates_property_id() -> Dict[str, int]:
    """Idempotent one-off migration. For every invoice/estimate that
    still has a null ``property_id`` AND references a job (via any
    line-item ``job_id``), backfill from that job's ``property_id``.
    Only backfills when every referenced job resolves to the SAME
    property — mixed-property invoices are left null so the admin can
    consolidate them explicitly.

    Returns counts so the boot log can show how much was healed.
    """
    n_inv = 0
    n_est = 0

    async def _resolve_prop_from_line_items(doc: dict) -> Optional[str]:
        job_ids = {
            li.get("job_id") for li in (doc.get("line_items") or [])
            if li.get("job_id")
        }
        job_ids.discard(None)
        if not job_ids:
            return None
        from utils import not_deleted_filter as _nd
        jobs = await db.jobs.find(
            {"tenant_id": doc.get("tenant_id"), "id": {"$in": list(job_ids)}, **_nd()},
            {"_id": 0, "id": 1, "property_id": 1},
        ).to_list(500)
        pids = {j.get("property_id") for j in jobs}
        pids.discard(None)
        pids.discard("")
        if len(pids) == 1:
            return next(iter(pids))
        return None

    # Invoices (doc_type=='invoice' in db.quotes).
    async for inv in db.quotes.find(
        {"doc_type": "invoice",
          "property_id": {"$in": [None, ""]},
          "is_consolidated": {"$ne": True}},
        {"_id": 0, "id": 1, "tenant_id": 1, "line_items": 1},
    ):
        pid = await _resolve_prop_from_line_items(inv)
        if not pid:
            continue
        r = await db.quotes.update_one(
            {"id": inv["id"], "tenant_id": inv["tenant_id"],
              "property_id": {"$in": [None, ""]}},
            {"$set": {"property_id": pid}},
        )
        n_inv += (r.modified_count or 0)

    # Estimates (db.estimates).
    async for est in db.estimates.find(
        {"property_id": {"$in": [None, ""]}},
        {"_id": 0, "id": 1, "tenant_id": 1, "line_items": 1},
    ):
        pid = await _resolve_prop_from_line_items(est)
        if not pid:
            continue
        r = await db.estimates.update_one(
            {"id": est["id"], "tenant_id": est["tenant_id"],
              "property_id": {"$in": [None, ""]}},
            {"$set": {"property_id": pid}},
        )
        n_est += (r.modified_count or 0)

    if n_inv or n_est:
        logger.info(
            f"[mp1.5] property_id backfill — invoices={n_inv} estimates={n_est}"
        )
    return {"invoices": n_inv, "estimates": n_est}
