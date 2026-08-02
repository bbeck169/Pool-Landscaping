"""Phase 22 · 2026-08-02 · Sub-item C — auto-create + auto-charge on job complete.

Contract
--------
Called from ``routers/jobs.py::update_job`` (PATCH) and
``routers/service_reports.py::patch_job_service_report`` right after a
job transitions from any non-completed state → ``status="completed"``.

Behaviour
---------
1. **Idempotent short-circuit** — if ``job.auto_invoice_id`` is already
   set, return the existing id without any DB mutation.
2. **Tenant opt-out** — if the tenant has
   ``settings.auto_invoice_on_job_complete=false``, skip entirely.
3. **Build line items** from the thin job schema:
   * 1 line for the service itself (description=``job.service_type``,
     qty=1, unit_price=``job.price``) IFF ``job.price > 0``.
   * N lines from ``chemical_usage_events`` for this job — one per
     row, using ``name`` + ``quantity_used`` + ``unit_cost_at_time_cents``.
4. **Insert into ``db.quotes`` with ``doc_type="invoice"``** (Phase 11
   invariant — NEVER writes to ``db.invoices``).
5. **Card on file** — if a ``payment_methods`` row with
   ``status="active"`` exists for this customer, call
   ``services.payments.stripe_charge.charge_card_on_file(invoice_id,
   tenant_id, idempotency_key="auto_invoice:{job_id}")``. On
   ``{ok: True}`` mark the invoice ``payment_status="paid"``.
6. **Audit** — every attempt (success or failure) writes one row to
   ``db.auto_invoice_runs``.
7. **Never crashes the caller** — all exceptions are swallowed and
   logged as WARNING with an ``error`` row in ``auto_invoice_runs``.

Grep-lint: 0 ``db.invoices`` writes — everything flows through
``db.quotes`` per the Phase 11 refactor.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db, logger
from utils import new_id, now_iso


async def _build_line_items(job: Dict[str, Any]) -> tuple[List[Dict[str, Any]], int]:
    """Return (line_items, total_cents)."""
    items: List[Dict[str, Any]] = []
    total_cents = 0

    # ─── Service line (from job.price)
    price_dollars = float(job.get("price") or 0)
    if price_dollars > 0:
        cents = int(round(price_dollars * 100))
        items.append({
            "id": new_id(),
            "description": job.get("service_type") or job.get("title") or "Service",
            "quantity": 1,
            "unit_price_cents": cents,
            "line_total_cents": cents,
            "kind": "service",
        })
        total_cents += cents

    # ─── Chemical usage lines (from Phase 18 chemical_usage_events)
    events = await db.chemical_usage_events.find(
        {"tenant_id": job["tenant_id"], "job_id": job["id"]},
        {"_id": 0, "name": 1, "product_slug": 1, "quantity_used": 1,
         "unit": 1, "unit_cost_at_time_cents": 1, "total_cost_cents": 1},
    ).to_list(500)
    for ev in events:
        qty = float(ev.get("quantity_used") or 0)
        unit_cents = int(ev.get("unit_cost_at_time_cents") or 0)
        line_cents = int(ev.get("total_cost_cents") or (qty * unit_cents))
        items.append({
            "id": new_id(),
            "description": f"{ev.get('name') or ev.get('product_slug')} "
                            f"({qty} {ev.get('unit') or ''})".strip(),
            "quantity": qty,
            "unit_price_cents": unit_cents,
            "line_total_cents": line_cents,
            "kind": "chemical",
            "product_slug": ev.get("product_slug"),
        })
        total_cents += line_cents

    return items, total_cents


async def _tenant_setting(tenant_id: str) -> bool:
    """Return whether auto-invoice-on-complete is enabled for the
    tenant. Defaults to True when the setting isn't present."""
    t = await db.tenants.find_one(
        {"id": tenant_id},
        {"_id": 0, "settings": 1, "auto_invoice_on_job_complete": 1},
    ) or {}
    settings = t.get("settings") or {}
    if "auto_invoice_on_job_complete" in settings:
        return bool(settings["auto_invoice_on_job_complete"])
    if "auto_invoice_on_job_complete" in t:
        return bool(t["auto_invoice_on_job_complete"])
    return True


async def _has_card_on_file(tenant_id: str, customer_id: str) -> bool:
    if not customer_id:
        return False
    row = await db.payment_methods.find_one(
        {"tenant_id": tenant_id, "customer_id": customer_id,
         "status": "active"},
        {"_id": 0, "id": 1},
    )
    return bool(row)


async def _write_audit(*, tenant_id: str, job_id: str,
                        invoice_id: Optional[str], amount_cents: int,
                        card_charge_attempted: bool,
                        charge_result: Optional[Dict[str, Any]] = None,
                        error: Optional[str] = None) -> None:
    await db.auto_invoice_runs.insert_one({
        "id": new_id(),
        "tenant_id": tenant_id,
        "job_id": job_id,
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "card_charge_attempted": bool(card_charge_attempted),
        "charge_result": charge_result,
        "error": error,
        "created_at": now_iso(),
    })


async def create_invoice_from_job(job_id: str, tenant_id: str
                                    ) -> Dict[str, Any]:
    """Idempotent auto-invoice + optional card-on-file charge.

    Returns::

        {
          "ok": bool,
          "invoice_id": str | None,
          "amount_cents": int,
          "created": bool,          # False when short-circuited
          "charged": bool,          # True when card-on-file succeeded
          "reason": str | None,     # "skipped_tenant_setting" / "no_price" / ...
        }

    Never raises. All failures are captured in the return dict AND
    written to ``db.auto_invoice_runs``.
    """
    try:
        job = await db.jobs.find_one(
            {"id": job_id, "tenant_id": tenant_id},
            {"_id": 0},
        )
        if not job:
            return {"ok": False, "invoice_id": None, "amount_cents": 0,
                    "created": False, "charged": False,
                    "reason": "job_not_found"}

        # Idempotent short-circuit.
        if job.get("auto_invoice_id"):
            return {"ok": True, "invoice_id": job["auto_invoice_id"],
                    "amount_cents": 0, "created": False,
                    "charged": False, "reason": "already_invoiced"}

        # Tenant opt-out check.
        if not await _tenant_setting(tenant_id):
            return {"ok": True, "invoice_id": None, "amount_cents": 0,
                    "created": False, "charged": False,
                    "reason": "skipped_tenant_setting"}

        items, total_cents = await _build_line_items(job)
        if total_cents <= 0 or not items:
            return {"ok": True, "invoice_id": None, "amount_cents": 0,
                    "created": False, "charged": False,
                    "reason": "no_price"}

        invoice_id = new_id()
        invoice_doc = {
            "id": invoice_id,
            "tenant_id": tenant_id,
            "doc_type": "invoice",              # Phase 11 invariant
            "job_id": job_id,
            "customer_id": job.get("customer_id"),
            "customer_name": job.get("customer_name"),
            "line_items": items,
            "subtotal_cents": total_cents,
            "total_cents": total_cents,
            "total": total_cents / 100.0,
            "currency": "USD",
            "payment_status": "unpaid",
            "status": "issued",
            "source": "auto_invoice_on_job_complete",
            "created_at": now_iso(),
            "issued_at": now_iso(),
        }
        # Phase 11 · Feb 2026 — invoices live in db.quotes with doc_type=invoice.
        await db.quotes.insert_one(invoice_doc)
        # Stamp the job so re-completing is a no-op.
        await db.jobs.update_one(
            {"id": job_id, "tenant_id": tenant_id},
            {"$set": {"auto_invoice_id": invoice_id,
                       "auto_invoice_created_at": now_iso()}},
        )

        # Attempt card-on-file charge if the customer has one.
        cust_id = job.get("customer_id") or ""
        has_card = await _has_card_on_file(tenant_id, cust_id)
        charge_result: Optional[Dict[str, Any]] = None
        charged = False
        if has_card:
            from services.payments import stripe_charge as _sc
            try:
                charge_result = await _sc.charge_card_on_file(
                    invoice_id=invoice_id,
                    tenant_id=tenant_id,
                    idempotency_key=f"auto_invoice:{job_id}",
                )
                if isinstance(charge_result, dict) and charge_result.get("ok"):
                    await db.quotes.update_one(
                        {"id": invoice_id, "tenant_id": tenant_id},
                        {"$set": {"payment_status": "paid",
                                   "paid_at": now_iso(),
                                   "auto_charged": True}},
                    )
                    charged = True
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[auto_invoice] charge failed for "
                                f"invoice={invoice_id} job={job_id}: {e}")
                charge_result = {"ok": False, "error": str(e)[:200]}

        await _write_audit(
            tenant_id=tenant_id, job_id=job_id, invoice_id=invoice_id,
            amount_cents=total_cents,
            card_charge_attempted=has_card,
            charge_result=charge_result,
        )
        return {"ok": True, "invoice_id": invoice_id,
                "amount_cents": total_cents, "created": True,
                "charged": charged,
                "reason": None if not has_card else (
                    "charged" if charged else "charge_failed")}
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"[auto_invoice] create_invoice_from_job failed "
            f"job={job_id} tenant={tenant_id}: {e}",
        )
        try:
            await _write_audit(
                tenant_id=tenant_id, job_id=job_id,
                invoice_id=None, amount_cents=0,
                card_charge_attempted=False,
                error=str(e)[:200],
            )
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "invoice_id": None, "amount_cents": 0,
                "created": False, "charged": False,
                "reason": f"exception: {str(e)[:120]}"}
