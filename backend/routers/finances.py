from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import get_current_tenant
from models import *

router = APIRouter()

# ----------------------- Auto chemical billing -----------------------
# Billable chemicals a technician can log during a visit. Shock is priced per lb;
# the rest are flat per application. Line items accrue on ONE draft invoice per
# customer per calendar month, then auto-bill on the 1st of the following month.
CHEM_PRICES = {
    "Shock (Cal-Hypo)": {"unit_price": 12.0, "per_unit": True, "label": "Shock"},
    "Phosphate Remover": {"unit_price": 45.0, "per_unit": False, "label": "Phosphate treatment"},
    "Clarifier": {"unit_price": 25.0, "per_unit": False, "label": "Clarifier"},
    "Enzymes": {"unit_price": 25.0, "per_unit": False, "label": "Enzymes"},
}


def _fmt_service_date(d: str | None) -> tuple:
    """Return (billing_month 'YYYY-MM', pretty 'Mon D') from a YYYY-MM-DD date, defaulting to today."""
    dt = None
    if d:
        try:
            dt = datetime.fromisoformat(d[:10])
        except Exception:
            dt = None
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m"), dt.strftime("%b %-d")


def _chem_line_items(job: dict, pretty_date: str) -> list:
    items = []
    for c in (job.get("chemicals_added") or []):
        price = CHEM_PRICES.get(c.get("name"))
        if not price:
            continue
        try:
            amt = float(str(c.get("amount", "")).strip() or 0)
        except (TypeError, ValueError):
            amt = 0
        if amt <= 0:
            continue
        if price["per_unit"]:
            qty, unit_price = amt, price["unit_price"]
            desc = f"{price['label']} ({amt:g} {c.get('unit', 'lbs')}) — {pretty_date}"
        else:
            qty, unit_price = 1, price["unit_price"]
            desc = f"{price['label']} — {pretty_date}"
        items.append({
            "description": desc, "quantity": qty, "unit_price": unit_price,
            "job_id": job.get("id"), "service_date": pretty_date,
        })
    return items


async def accrue_chem_invoice(job: dict):
    """Add/replace this job's chemical charges on the customer's current-month draft invoice."""
    try:
        cid = job.get("customer_id")
        if not cid:
            return
        billing_month, pretty = _fmt_service_date(job.get("scheduled_date"))
        new_items = _chem_line_items(job, pretty)
        cust = await db.customers.find_one({"id": cid}, {"_id": 0})
        cust_name = cust.get("name", "") if cust else ""
        inv = await db.quotes.find_one(
            {"doc_type": "invoice", "auto_chem": True, "customer_id": cid, "billing_month": billing_month, "status": "draft"},
            {"_id": 0},
        )
        if not inv and not new_items:
            return
        # Rebuild line items: drop this job's prior chem lines, add the fresh ones.
        existing = [li for li in (inv.get("line_items", []) if inv else []) if li.get("job_id") != job.get("id")]
        line_items = existing + new_items
        if not line_items:
            if inv:
                await db.quotes.delete_one({"id": inv["id"]})
            return
        subtotal = round(sum(float(li["quantity"]) * float(li["unit_price"]) for li in line_items), 2)
        payload = {
            "customer_id": cid, "customer_name": cust_name,
            "title": f"Chemical Charges — {billing_month}", "doc_type": "invoice",
            "line_items": line_items, "tax_rate": 0, "subtotal": subtotal, "tax": 0.0, "total": subtotal,
            "auto_chem": True, "billing_month": billing_month, "status": "draft",
        }
        if inv:
            await db.quotes.update_one({"id": inv["id"]}, {"$set": payload})
        else:
            payload.update({"id": new_id(), "amount_paid": 0.0, "payment_status": "unpaid", "created_at": now_iso()})
            await db.quotes.insert_one(payload)
    except Exception as e:
        logger.warning(f"accrue_chem_invoice error: {e}")


async def run_monthly_chem_billing():
    """On/after the 1st, finalize (bill) any chemical draft invoices for months that have ended."""
    try:
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        due = (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat()
        drafts = await db.quotes.find(
            {"doc_type": "invoice", "auto_chem": True, "status": "draft", "billing_month": {"$lt": current_month}},
            {"_id": 0},
        ).to_list(1000)
        for inv in drafts:
            if not inv.get("line_items"):
                await db.quotes.delete_one({"id": inv["id"]})
                continue
            await db.quotes.update_one({"id": inv["id"]}, {"$set": {"status": "sent", "due_date": due}})
            cid = inv.get("customer_id")
            total = inv.get("total", 0)
            # Fully hands-off: charge the card/ACH on file if present, else send a payable invoice.
            charged = False
            cust = await db.customers.find_one({"id": cid}, {"_id": 0}) if cid else None
            if cust and cust.get("default_payment_method_id"):
                try:
                    from routers.payments import charge_invoice_on_file
                    res = await charge_invoice_on_file(inv["id"])
                    status = res.get("status")
                    if status == "succeeded":
                        charged = True  # customer already notified by the charge helper
                    elif status == "processing":
                        charged = True
                        if cid:
                            await notify_customer(cid, "Payment processing",
                                                  f"Your chemical service payment for {inv['billing_month']} (${total:,.2f}) is processing via bank transfer.")
                except Exception as e:
                    logger.warning(f"auto-charge chem invoice {inv['id']} failed: {e}")
            if not charged and cid:
                await notify_customer(
                    cid, "New invoice",
                    f"Your chemical service invoice for {inv['billing_month']} (${total:,.2f}) is ready. View and pay it in your portal.",
                    sms=False,
                )
            logger.info(f"Auto-billed chem invoice {inv['id']} for {inv['billing_month']} (charged={charged})")
    except Exception as e:
        logger.warning(f"run_monthly_chem_billing error: {e}")




# ----------------------- Finances: Auto Billing -----------------------
FREQ_DAYS = {"weekly": 7, "monthly": 30, "quarterly": 90}


def advance_date(iso: str, freq: str) -> str:
    base = datetime.fromisoformat(iso) if iso else datetime.now(timezone.utc)
    return (base + timedelta(days=FREQ_DAYS.get(freq, 30))).date().isoformat()


# ----------------------- Income categories -----------------------
INCOME_CATEGORIES_ID = "income_categories"
DEFAULT_INCOME_CATEGORIES = ["Pool", "Landscaping", "Labor"]


async def get_income_categories() -> list:
    doc = await db.settings.find_one({"id": INCOME_CATEGORIES_ID}, {"_id": 0})
    if not doc:
        doc = {"id": INCOME_CATEGORIES_ID, "values": list(DEFAULT_INCOME_CATEGORIES)}
        await db.settings.insert_one(dict(doc))
    return doc.get("values", DEFAULT_INCOME_CATEGORIES)


@router.get("/income-categories")
async def list_income_categories(user: dict = Depends(get_current_user)):
    if user.get("role") not in ("admin", "technician"):
        raise HTTPException(403, "Not allowed")
    return {"categories": await get_income_categories()}


@router.post("/income-categories")
async def add_income_category(body: CategoryIn, admin: dict = Depends(require_admin)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Category name required")
    cats = await get_income_categories()
    if any(c.lower() == name.lower() for c in cats):
        raise HTTPException(400, "That category already exists")
    cats.append(name)
    await db.settings.update_one({"id": INCOME_CATEGORIES_ID}, {"$set": {"values": cats}}, upsert=True)
    return {"categories": cats}


@router.delete("/income-categories/{name}")
async def delete_income_category(name: str, admin: dict = Depends(require_admin)):
    cats = await get_income_categories()
    remaining = [c for c in cats if c.lower() != name.lower()]
    if len(remaining) == len(cats):
        raise HTTPException(404, "Category not found")
    if not remaining:
        raise HTTPException(400, "Keep at least one category")
    await db.settings.update_one({"id": INCOME_CATEGORIES_ID}, {"$set": {"values": remaining}}, upsert=True)
    return {"categories": remaining}


@router.get("/finances/income-by-category")
async def income_by_category(date_from: Optional[str] = Query(None),
                             date_to: Optional[str] = Query(None),
                             admin: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    return await compute_income_by_category(tenant["id"], date_from, date_to)


async def compute_income_by_category(tenant_id: str,
                                     date_from: Optional[str] = None,
                                     date_to: Optional[str] = None):
    """Collected revenue attributed to line-item categories (tenant-scoped)."""
    q = {"tenant_id": tenant_id, "doc_type": "invoice",
         "$or": [{"amount_paid": {"$gt": 0}}, {"payment_status": "paid"}]}
    if date_from or date_to:
        rng = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to + "T23:59:59"
        q["created_at"] = rng
    invoices = await db.quotes.find(q, {"_id": 0}).to_list(5000)
    buckets: dict = {}
    for inv in invoices:
        lines = inv.get("line_items", [])
        subtotal = sum((li.get("quantity") or 0) * (li.get("unit_price") or 0) for li in lines)
        if subtotal <= 0:
            continue
        # Fully-paid invoices may not carry an explicit amount_paid; fall back to total.
        paid = inv.get("amount_paid")
        if not paid:
            paid = inv.get("total", 0) if inv.get("payment_status") == "paid" else 0
        paid = float(paid or 0)
        if paid <= 0:
            continue
        for li in lines:
            amt = (li.get("quantity") or 0) * (li.get("unit_price") or 0)
            cat = li.get("category") or "Pool"
            buckets[cat] = buckets.get(cat, 0.0) + paid * (amt / subtotal)
    rows = [{"category": k, "amount": round(v, 2)} for k, v in buckets.items()]
    rows.sort(key=lambda r: r["amount"], reverse=True)
    total = round(sum(r["amount"] for r in rows), 2)
    return {"total": total, "rows": rows, "invoice_count": len(invoices)}


@router.get("/billing-plans")
async def list_billing_plans(user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    return await db.billing_plans.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("next_run", 1).to_list(1000)


@router.post("/billing-plans")
async def create_billing_plan(body: BillingPlanIn,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    cust = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not cust:
        raise HTTPException(400, "Customer not found")
    doc = body.dict()
    doc.update({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_name": cust["name"],
        "next_run": body.next_run or advance_date(now_iso(), body.frequency or "monthly"),
        "created_at": now_iso(),
    })
    await db.billing_plans.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/billing-plans/{pid}")
async def update_billing_plan(pid: str, body: BillingPlanUpdate,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if upd:
        await db.billing_plans.update_one(
            {"id": pid, "tenant_id": tenant["id"]}, {"$set": upd}
        )
    return await db.billing_plans.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.post("/billing-plans/{pid}/run")
async def run_billing_plan(pid: str,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    plan = await db.billing_plans.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not plan:
        raise HTTPException(404, "Plan not found")
    amount = plan.get("amount", 0.0)
    tax = round(amount * 0.08, 2)
    invoice = {
        "id": new_id(), "tenant_id": tenant["id"],
        "customer_id": plan["customer_id"], "customer_name": plan["customer_name"],
        "title": plan.get("service", "Recurring Service"), "doc_type": "invoice",
        "line_items": [{"description": plan.get("service", "Recurring Service"), "quantity": 1, "unit_price": amount}],
        "tax_rate": 8.0, "subtotal": amount, "tax": tax, "total": round(amount + tax, 2),
        "amount_paid": 0.0, "due_date": (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat(),
        "status": "sent", "payment_status": "unpaid", "notes": "Auto-generated from billing plan",
        "billing_plan_id": pid, "created_at": now_iso(),
    }
    await db.quotes.insert_one(invoice)
    new_next = advance_date(plan.get("next_run") or now_iso(), plan.get("frequency", "monthly"))
    await db.billing_plans.update_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"$set": {"next_run": new_next, "last_run": now_iso()}},
    )
    await notify_customer(plan["customer_id"], "New invoice",
                          f"An invoice for {plan.get('service', 'your service')} was issued.")
    invoice.pop("_id", None)
    return {"ok": True, "invoice_id": invoice["id"], "next_run": new_next}


# ----------------------- Equipment Repair -----------------------
def _strip_cost(doc: dict) -> dict:
    if doc:
        doc.pop("cost", None)
    return doc


@router.get("/repairs")
async def list_repairs(user: dict = Depends(get_current_user), status: Optional[str] = None):
    if user.get("role") not in ("admin", "technician"):
        raise HTTPException(403, "Not allowed")
    q = {} if not status or status == "all" else {"status": status}
    if user.get("role") == "technician":
        q["technician_id"] = user.get("technician_id")
    repairs = await db.repairs.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    if user.get("role") == "technician":
        repairs = [_strip_cost(r) for r in repairs]
    return repairs


@router.post("/repairs")
async def create_repair(body: RepairIn, user: dict = Depends(get_current_user)):
    if user.get("role") not in ("admin", "technician"):
        raise HTTPException(403, "Not allowed")
    cust = await db.customers.find_one({"id": body.customer_id}, {"_id": 0})
    if not cust:
        raise HTTPException(400, "Customer not found")
    doc = body.dict()
    doc["customer_name"] = cust["name"]
    if user.get("role") == "technician":
        # Techs report issues but never set pricing; ticket is assigned to them.
        doc["cost"] = None
        doc["technician_id"] = user.get("technician_id")
    if doc.get("technician_id"):
        tech = await db.technicians.find_one({"id": doc["technician_id"]}, {"_id": 0})
        doc["technician_name"] = tech["name"] if tech else None
    else:
        doc["technician_name"] = None
    doc.update({"id": new_id(), "created_at": now_iso()})
    await db.repairs.insert_one(doc)
    doc.pop("_id", None)
    return _strip_cost(doc) if user.get("role") == "technician" else doc


@router.put("/repairs/{rid}")
async def update_repair(rid: str, body: RepairUpdate, user: dict = Depends(get_current_user)):
    if user.get("role") not in ("admin", "technician"):
        raise HTTPException(403, "Not allowed")
    existing = await db.repairs.find_one({"id": rid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Repair not found")
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if user.get("role") == "technician":
        if existing.get("technician_id") != user.get("technician_id"):
            raise HTTPException(403, "Not your repair ticket")
        upd.pop("cost", None)  # techs cannot change pricing
    if "technician_id" in upd:
        tech = await db.technicians.find_one({"id": upd["technician_id"]}, {"_id": 0})
        upd["technician_name"] = tech["name"] if tech else None
    if upd:
        await db.repairs.update_one({"id": rid}, {"$set": upd})
    doc = await db.repairs.find_one({"id": rid}, {"_id": 0})
    return _strip_cost(doc) if user.get("role") == "technician" else doc




# ────────────────────────── Automatic late fees ──────────────────────────────
# Daily job assesses a one-time flat late fee on any unpaid/partial invoice whose
# due_date is more than `grace_days` (default 30) days ago. Idempotent via the
# `is_late_fee: true` marker on the line item.
LATE_FEES_SETTINGS_ID = "late_fees_settings"
LATE_FEE_DEFAULTS = {"enabled": True, "amount": 15.0, "grace_days": 30}


async def _get_late_fee_settings() -> dict:
    doc = await db.settings.find_one({"id": LATE_FEES_SETTINGS_ID}, {"_id": 0}) or {}
    return {
        "enabled": bool(doc.get("enabled", LATE_FEE_DEFAULTS["enabled"])),
        "amount": float(doc.get("amount", LATE_FEE_DEFAULTS["amount"])),
        "grace_days": int(doc.get("grace_days", LATE_FEE_DEFAULTS["grace_days"])),
    }


def _has_late_fee(inv: dict) -> bool:
    return any(bool(li.get("is_late_fee")) for li in (inv.get("line_items") or []))


async def _log_invoice_activity(invoice_id: str, kind: str, msg: str, meta: dict | None = None):
    try:
        await db.activity_logs.insert_one({
            "id": new_id(),
            "entity": "invoice",
            "entity_id": invoice_id,
            "type": kind,
            "message": msg,
            "meta": meta or {},
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.warning(f"activity_log insert failed for invoice {invoice_id}: {e}")


async def run_late_fee_assessment() -> dict:
    """Scan invoices, add one $amount late fee to any past-due-by-grace_days doc.

    Called by the daily scheduler AND by the manual admin endpoint. Idempotent.
    Master invoices live in a separate collection (db.master_invoices) and are
    aggregations over children — each *child* invoice gets its own late fee
    (children are still tracked/paid individually). Master rollup totals are
    not mutated by this job.
    """
    cfg = await _get_late_fee_settings()
    if not cfg["enabled"]:
        return {"assessed": 0, "invoice_ids": [], "skipped": "disabled"}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=cfg["grace_days"])).date().isoformat()
    amount = round(float(cfg["amount"]), 2)

    q = {
        "doc_type": "invoice",
        "payment_status": {"$in": ["unpaid", "partial", "overdue"]},
        "due_date": {"$exists": True, "$ne": None, "$lt": cutoff},
    }
    invs = await db.quotes.find(q, {"_id": 0}).to_list(5000)
    assessed_ids: list[str] = []
    for inv in invs:
        if _has_late_fee(inv):
            continue
        line_items = list(inv.get("line_items") or [])
        fee_line = {
            "description": f"Late fee ({cfg['grace_days']}+ days past due)",
            "quantity": 1,
            "unit_price": amount,
            "line_total": amount,
            "category": "Late fee",
            "is_late_fee": True,
        }
        line_items.append(fee_line)
        subtotal = round(sum(float(li.get("quantity") or 0) * float(li.get("unit_price") or 0)
                              for li in line_items), 2)
        tax_rate = float(inv.get("tax_rate") or 0)
        tax = round(subtotal * tax_rate / 100.0, 2)
        total = round(subtotal + tax, 2)
        amount_paid = float(inv.get("amount_paid") or 0)
        remaining = round(max(total - amount_paid, 0.0), 2)
        await db.quotes.update_one(
            {"id": inv["id"]},
            {"$set": {
                "line_items": line_items,
                "subtotal": subtotal,
                "tax": tax,
                "total": total,
                "remaining_balance": remaining,
                "late_fee_assessed_at": now_iso(),
            }},
        )
        assessed_ids.append(inv["id"])
        await _log_invoice_activity(
            inv["id"], "late-fee-assessed",
            f"${amount:.2f} late fee added — {cfg['grace_days']}+ days past due",
            {"amount": amount, "grace_days": cfg["grace_days"]},
        )
        try:
            await notify_customer(inv.get("customer_id"), "Late fee added",
                                  f"A late fee of ${amount:.2f} has been added to invoice {inv.get('title', '')}.")
        except Exception as e:
            logger.warning(f"notify_customer skipped for late fee on {inv['id']}: {e}")
    logger.info(f"Late-fee run: assessed {len(assessed_ids)} invoice(s) (cutoff before {cutoff}).")
    # Auto-enroll customers with 30+ day past-due invoices into the seeded
    # "Overdue Invoice Sequence" (idempotent).
    try:
        enrolled = await auto_enroll_overdue_sequence(cutoff)
    except Exception as e:
        logger.warning(f"overdue-sequence auto-enroll skipped: {e}")
        enrolled = {"enrolled": 0, "customer_ids": []}
    return {
        "assessed": len(assessed_ids),
        "invoice_ids": assessed_ids,
        "sequence_auto_enroll": enrolled,
    }


async def auto_enroll_overdue_sequence(cutoff: Optional[str] = None) -> dict:
    """Auto-enroll customers whose invoices crossed the 30-day past-due threshold
    into the seeded ``overdue-invoice-sequence``. Idempotent — skips customers
    already actively enrolled; re-enrolls customers whose prior enrollment was
    unenrolled/completed.
    """
    if cutoff is None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    seq = await db.sequences.find_one({"slug": "overdue-invoice-sequence"}, {"_id": 0})
    if not seq:
        return {"enrolled": 0, "customer_ids": [], "reason": "sequence not found"}
    if not seq.get("active", True):
        return {"enrolled": 0, "customer_ids": [], "reason": "sequence paused"}

    q = {
        "doc_type": "invoice",
        "payment_status": {"$in": ["unpaid", "partial", "overdue"]},
        "due_date": {"$exists": True, "$ne": None, "$lt": cutoff},
    }
    invs = await db.quotes.find(q, {"_id": 0}).to_list(5000)
    seen_customers: set[str] = set()
    enrolled_ids: list[str] = []
    today = datetime.now(timezone.utc).date()

    steps = seq.get("steps") or []
    if not steps:
        return {"enrolled": 0, "customer_ids": [], "reason": "sequence has no steps"}

    for inv in invs:
        cid = inv.get("customer_id")
        if not cid or cid in seen_customers:
            continue
        seen_customers.add(cid)
        active = await db.sequence_enrollments.find_one(
            {"sequence_id": seq["id"], "customer_id": cid, "status": "active"}, {"_id": 0}
        )
        if active:
            continue
        # ─── Fast-forward: if the invoice is already past later step thresholds,
        # skip those steps so the escalation fires on the very next tick.
        try:
            days_past = (today - datetime.fromisoformat(inv["due_date"][:10]).date()).days
        except Exception:
            days_past = 30
        cumulative = 0
        current_step = 0
        skipped_log: list[dict] = []
        for i, s in enumerate(steps):
            delay = int((s or {}).get("delay_days") or 0)
            cumulative += delay
            # Do not fast-forward THROUGH an escalation step — we want the tick to
            # actually fire it. Stop here so it becomes `current_step` and next_at=now.
            if (s or {}).get("action_type") == "escalation_task":
                break
            if cumulative <= days_past:
                skipped_log.append({
                    "step": i, "action_type": (s or {}).get("action_type"),
                    "fired_at": now_iso(),
                    "notes": f"Fast-forwarded on enrollment (invoice already {days_past} days past due)",
                    "fast_forwarded": True,
                })
                current_step = i + 1
            else:
                break
        # If ALL steps are past — enrollment is effectively completed; still record it
        # so we don't re-enroll, but mark next_action_at to now so tick can close it.
        if current_step >= len(steps):
            next_at = now_iso()
        else:
            # Fire the first non-elapsed step immediately (its threshold is already the
            # next-in-line but the customer has been waiting past all prior steps).
            next_at = now_iso()
        enrollment = {
            "id": new_id(),
            "sequence_id": seq["id"],
            "customer_id": cid,
            "status": "active",
            "current_step": current_step,
            "next_action_at": next_at,
            "started_at": now_iso(),
            "log": skipped_log,
            "auto_enrolled": True,
            "trigger_invoice_id": inv.get("id"),
        }
        await db.sequence_enrollments.insert_one(enrollment)
        # Compute days past due for the log message.
        days = days_past
        await _log_invoice_activity(
            inv["id"], "sequence-auto-enrolled",
            f"Auto-enrolled in Overdue Invoice Sequence — invoice {days} days past due",
            {"sequence_id": seq["id"], "customer_id": cid, "days_past_due": days},
        )
        enrolled_ids.append(cid)
    if enrolled_ids:
        logger.info(f"overdue-invoice auto-enroll: {len(enrolled_ids)} customer(s) enrolled.")
    return {"enrolled": len(enrolled_ids), "customer_ids": enrolled_ids}


@router.post("/sequences/auto-enroll/overdue-run")
async def run_overdue_auto_enroll(admin: dict = Depends(require_admin)):
    """Manual trigger for the overdue-invoice auto-enroll pass."""
    return await auto_enroll_overdue_sequence()


# ─── settings endpoints ─────────────────────────────────────────────────────
class LateFeeSettingsIn(BaseModel):
    enabled: Optional[bool] = None
    amount: Optional[float] = None
    grace_days: Optional[int] = None


@router.get("/settings/late-fees")
async def get_late_fee_settings(admin: dict = Depends(require_admin)):
    return await _get_late_fee_settings()


@router.put("/settings/late-fees")
async def update_late_fee_settings(body: LateFeeSettingsIn, admin: dict = Depends(require_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if "amount" in upd and float(upd["amount"]) < 0:
        raise HTTPException(400, "amount must be >= 0")
    if "grace_days" in upd and int(upd["grace_days"]) < 0:
        raise HTTPException(400, "grace_days must be >= 0")
    await db.settings.update_one(
        {"id": LATE_FEES_SETTINGS_ID},
        {"$set": {"id": LATE_FEES_SETTINGS_ID, **upd}},
        upsert=True,
    )
    return await _get_late_fee_settings()


@router.post("/finances/late-fees/run")
async def run_late_fees(admin: dict = Depends(require_admin)):
    """Manually trigger the same late-fee assessment the daily scheduler runs."""
    return await run_late_fee_assessment()

# ────────────────────────── Terms & Conditions ──────────────────────────────
# Global defaults applied when a new quote/invoice/estimate is created without
# an explicit `terms` value. Also editable via the /settings/terms admin page.
TERMS_SETTINGS_ID = "terms_defaults"

DEFAULT_QUOTE_TERMS = (
    "Estimate valid for 30 days from date of issue. Prices are subject to change "
    "if scope changes. All work is performed by licensed and insured technicians. "
    "A 50% deposit may be required to schedule."
)
DEFAULT_INVOICE_TERMS = (
    "Payment is due within 30 days of invoice date. Invoices past due may incur "
    "a $15 late fee. Please make checks payable to Pool & Landscaping of "
    "Vistancia. For questions, contact billing@aquaterra.com."
)


async def get_terms_defaults() -> dict:
    """Return the two-key terms defaults. Seed on first read."""
    doc = await db.settings.find_one({"id": TERMS_SETTINGS_ID}, {"_id": 0})
    if not doc:
        doc = {
            "id": TERMS_SETTINGS_ID,
            "default_quote_terms": DEFAULT_QUOTE_TERMS,
            "default_invoice_terms": DEFAULT_INVOICE_TERMS,
        }
        await db.settings.insert_one(dict(doc))
    return {
        "default_quote_terms": doc.get("default_quote_terms") or DEFAULT_QUOTE_TERMS,
        "default_invoice_terms": doc.get("default_invoice_terms") or DEFAULT_INVOICE_TERMS,
    }


@router.get("/settings/terms")
async def get_terms_settings(admin: dict = Depends(require_admin)):
    return await get_terms_defaults()


@router.put("/settings/terms")
async def update_terms_settings(body: TermsSettingsIn, admin: dict = Depends(require_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if upd:
        await db.settings.update_one(
            {"id": TERMS_SETTINGS_ID},
            {"$set": {"id": TERMS_SETTINGS_ID, **upd}},
            upsert=True,
        )
    return await get_terms_defaults()


@router.post("/settings/terms/reset")
async def reset_terms_settings(admin: dict = Depends(require_admin)):
    """Reset both default terms strings back to their seeded values."""
    await db.settings.update_one(
        {"id": TERMS_SETTINGS_ID},
        {"$set": {
            "id": TERMS_SETTINGS_ID,
            "default_quote_terms": DEFAULT_QUOTE_TERMS,
            "default_invoice_terms": DEFAULT_INVOICE_TERMS,
        }},
        upsert=True,
    )
    return await get_terms_defaults()

