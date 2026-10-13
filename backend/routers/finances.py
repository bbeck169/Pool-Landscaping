import re

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import get_current_tenant
# Bucket A2 · Feb-2026 — explicit model imports (was ``from models import *``).
from models import (
    BillingPlanIn,
    BillingPlanUpdate,
    CategoryIn,
    RepairIn,
    RepairUpdate,
    TenantSettingsUpdate,
    TermsSettingsIn,
)

# Feb-2026 · Income-by-Category label resolver — RFC-4122 UUID-shape
# guard. Line item ``category`` fields sometimes carry a raw
# income_categories id (legacy write path) or a pricebook item id
# instead of the display name. ``compute_income_by_category`` below
# resolves ids → names via per-tenant maps and, when unresolved,
# emits a ``Uncategorized (…last-8)`` fallback label so admins can
# trace the specific orphan.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

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
        cust = await db.customers.find_one({"id": cid}, {"_id": 0}) or {}
        # Feb-2026 · Customer Delete UX overhaul — orphan guard.
        # If the customer row has been hard-deleted between the job
        # completing and this accrual running, refuse to mint a
        # fresh invoice for a non-existent customer. Existing draft
        # invoices for the (now-deleted) customer are left in place
        # for the accountant to reconcile — we don't cascade-delete
        # them either.
        if not cust and not (await db.quotes.find_one(
            {"doc_type": "invoice", "auto_chem": True,
             "customer_id": cid, "billing_month": billing_month,
             "status": "draft"},
            {"_id": 0, "id": 1},
        )):
            logger.warning(
                "accrue_chem_invoice skipped for cid=%s — customer not found "
                "(possibly hard-deleted; orphan-safe short-circuit).",
                cid,
            )
            return
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
            "tenant_id": job.get("tenant_id"),
            "title": f"Chemical Charges — {billing_month}", "doc_type": "invoice",
            "line_items": line_items, "tax_rate": 0, "subtotal": subtotal, "tax": 0.0, "total": subtotal,
            "auto_chem": True, "billing_month": billing_month, "status": "draft",
        }
        # Phase 19 — auto-apply any unredeemed referral credit for this customer.
        try:
            from routers.referrals import apply_referral_credits_to_invoice
            payload = await apply_referral_credits_to_invoice(payload)
        except Exception as e:
            logger.warning(f"referral credit apply skipped: {e}")
        if inv:
            await db.quotes.update_one({"id": inv["id"]}, {"$set": payload})
        else:
            payload.update({"id": new_id(), "amount_paid": 0.0, "payment_status": "unpaid", "created_at": now_iso()})
            # Task SS/RR Phase 2 · Feb 2026 — apply cents credits to
            # the freshly-minted chem invoice too.
            try:
                if payload.get("tenant_id"):
                    from services.credits_apply import apply_and_persist
                    payload = await apply_and_persist(
                        db, payload["tenant_id"], payload,
                    )
            except Exception as _e:                                # noqa: BLE001
                pass
            # Feb-2026 · P0 fix — chemical draft invoices were being
            # written with ``invoice_number: null`` because the draft
            # side of this branch skipped the number generator. Chem
            # drafts DO ultimately get sent + charged (see
            # ``run_monthly_chem_billing``), so treat them as
            # first-class invoices from birth.
            try:
                from services.invoice_numbering import insert_invoice
                tenant_doc = await db.tenants.find_one(
                    {"id": payload["tenant_id"]},
                    {"_id": 0, "id": 1, "timezone": 1},
                ) if payload.get("tenant_id") else None
                await insert_invoice(payload, tenant_doc or {"id": payload.get("tenant_id")})
            except Exception as _num_exc:                          # noqa: BLE001
                # Never block the accrue-loop on numbering — the
                # backfill migration will heal any orphan drafts on
                # the next boot. Log so we can surface it in Sentry.
                logger.warning(
                    f"accrue_chem_invoice number-assign failed: {_num_exc}"
                )
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
                    # Feb-2026 · tenant-scope hardening — pass the invoice's
                    # own tenant_id since this is a scheduled background
                    # job with no request auth context.
                    res = await charge_invoice_on_file(
                        inv["id"], tenant_id=inv.get("tenant_id")
                    )
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
    if user.get("role") not in ("admin", "super_admin", "technician"):
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
    """Collected revenue attributed to line-item categories (tenant-scoped).

    Feb-2026 · Bug fix — mobile "Income by Category" was rendering
    raw UUIDs when line items carried a category **id** instead of a
    display name (legacy write path or via ``income_category_id``).
    Resolution ladder per line item:

      1. ``line_item.income_category_id`` → name (canonical newer
         write path; wins over inline ``category`` when both set).
      2. inline ``line_item.category`` — if UUID-shaped, resolve
         via ``income_categories``; else pass through verbatim.
      3. pricebook item ``category`` via ``line_item.item_id``
         (matches ``revenue_by_category`` behaviour).
      4. Unresolved UUIDs collapse to their own bucket labelled
         ``Uncategorized (…last-8)`` so operators can pinpoint the
         specific orphan id.
      5. Otherwise ``"Pool"`` (preserved legacy default).

    Response row shape (additive, backward-compatible):
      - ``category`` — legacy alias == ``label`` (for older callers).
      - ``label`` — canonical display string (never a UUID).
      - ``category_id`` — resolved income_categories id when known,
                          the raw UUID when the row is an orphan
                          fallback, else ``None``.
      - ``amount`` — float, rounded to 2 decimals.
    """
    # Feb-2026 · P2 Item 2 — merge status $or + soft-delete $or via
    # an explicit $and so neither clobbers the other.
    q = {"tenant_id": tenant_id, "doc_type": "invoice",
         "$and": [
             {"$or": [{"amount_paid": {"$gt": 0}}, {"payment_status": "paid"}]},
             {"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]},
         ]}
    if date_from or date_to:
        rng = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to + "T23:59:59"
        q["created_at"] = rng

    # Tenant-scoped id → name maps for the resolution ladder.
    income_cat_by_id: Dict[str, str] = {}
    ic_rows = await db.income_categories.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(5000)
    for row in ic_rows:
        rid = row.get("id")
        name = (row.get("name") or "").strip()
        if rid and name:
            income_cat_by_id[rid] = name

    # Pricebook fallback: item_id → category name.
    item_id_to_category: Dict[str, str] = {}
    pb_rows = await db.items.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "category": 1},
    ).to_list(5000)
    for row in pb_rows:
        cat = (row.get("category") or "").strip()
        if cat and row.get("id"):
            item_id_to_category[row["id"]] = cat

    invoices = await db.quotes.find(q, {"_id": 0}).to_list(5000)

    # Bucket = display label. Each bucket also tracks its resolved
    # category_id (nullable) so the API can return a stable click-
    # through key alongside the human label.
    buckets: dict = {}
    bucket_ids: dict = {}
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

            # Resolution ladder (see docstring).
            label: Optional[str] = None
            resolved_cat_id: Optional[str] = None

            ic_id = (li.get("income_category_id") or "").strip()
            if ic_id:
                name = income_cat_by_id.get(ic_id)
                if name:
                    label = name
                    resolved_cat_id = ic_id
                else:
                    # Orphan id — surface it as its own bucket so
                    # ops can trace the specific broken reference.
                    tail = ic_id[-8:] if len(ic_id) >= 8 else ic_id
                    label = f"Uncategorized ({tail})"
                    resolved_cat_id = ic_id

            if label is None:
                inline = (li.get("category") or "").strip()
                if inline:
                    if _UUID_RE.match(inline):
                        name = income_cat_by_id.get(inline)
                        if name:
                            label = name
                            resolved_cat_id = inline
                        else:
                            tail = inline[-8:]
                            label = f"Uncategorized ({tail})"
                            resolved_cat_id = inline
                    else:
                        # Non-UUID strings pass through verbatim
                        # (well-known enums like "Pool", "Landscape",
                        # or a display-name that was written inline).
                        label = inline

            if label is None:
                pb_cat = item_id_to_category.get(li.get("item_id"))
                if pb_cat:
                    label = pb_cat

            if label is None:
                # Preserved legacy default so the tile total stays
                # stable when neither an id nor an inline category
                # is set (older seed data).
                label = "Pool"

            buckets[label] = buckets.get(label, 0.0) + paid * (amt / subtotal)
            # Prefer the first-seen id per label; a well-known
            # display name may map back to a live income_categories
            # id even if the invoice line carried no id itself.
            if label not in bucket_ids:
                bucket_ids[label] = resolved_cat_id

    # For labels that resolved via pass-through / pricebook / default,
    # try one last name → id lookup so the response carries a stable
    # click-through key when the display name matches a live row.
    name_to_id_ci: Dict[str, str] = {}
    for cid, cname in income_cat_by_id.items():
        name_to_id_ci.setdefault(cname.lower(), cid)

    rows: List[Dict[str, Any]] = []
    for label, amount in buckets.items():
        cat_id = bucket_ids.get(label)
        if not cat_id:
            cat_id = name_to_id_ci.get(label.lower())
        rows.append({
            "category":    label,   # legacy alias — kept for older callers
            "label":       label,   # canonical display string
            "category_id": cat_id,  # nullable stable key
            "amount":      round(amount, 2),
        })
    rows.sort(key=lambda r: r["amount"], reverse=True)
    total = round(sum(r["amount"] for r in rows), 2)
    return {"total": total, "rows": rows, "invoice_count": len(invoices)}


@router.get("/billing-plans")
async def list_billing_plans(user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant),
                             include_deleted: bool = False):
    q: dict = {"tenant_id": tenant["id"]}
    # Phase 34 · Task II · Feb 2026 — hide soft-deleted plans by default.
    if not (include_deleted and (user.get("role") or "").lower() == "super_admin"):
        q["$or"] = [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]
    return await db.billing_plans.find(
        q, {"_id": 0}
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
    # Phase 56.18 — number assignment on autobilling-generated invoices.
    from services.invoice_numbering import assign_invoice_number_if_missing
    await assign_invoice_number_if_missing(invoice, tenant)
    # Phase 10 · Feb 2026 — auto-apply available credits BEFORE
    # persisting so the invoice PDF/HTML shows the discount line and
    # the customer balance decrements atomically.
    from services.credits_apply import apply_and_persist
    invoice = await apply_and_persist(db, tenant["id"], invoice)
    await db.quotes.insert_one(invoice)
    new_next = advance_date(plan.get("next_run") or now_iso(), plan.get("frequency", "monthly"))
    await db.billing_plans.update_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"$set": {"next_run": new_next, "last_run": now_iso()}},
    )
    await notify_customer(plan["customer_id"], "New invoice",
                          f"An invoice for {plan.get('service', 'your service')} was issued.")
    # Feb-2026 · Auto-apply credit balance to this customer's OTHER
    # open invoices after autobilling. Non-blocking. The freshly-
    # created invoice is excluded (Model B — line-item credit for
    # this invoice already ran above via apply_and_persist).
    try:
        from services.credit_apply import (
            apply_credit_to_customer_open_invoices,
        )
        await apply_credit_to_customer_open_invoices(
            db, tenant["id"], invoice.get("customer_id"),
            exclude_invoice_ids=[invoice.get("id")],
        )
    except Exception as _ca_exc:  # noqa: BLE001
        logger.warning(
            "credit_apply.failed tenant=%s invoice=%s error=%r",
            tenant["id"], invoice.get("id"), _ca_exc,
        )
    invoice.pop("_id", None)
    return {"ok": True, "invoice_id": invoice["id"], "next_run": new_next}


# ----------------------- Equipment Repair -----------------------
def _strip_cost(doc: dict) -> dict:
    if doc:
        doc.pop("cost", None)
    return doc


@router.get("/repairs")
async def list_repairs(user: dict = Depends(get_current_user), status: Optional[str] = None):
    if user.get("role") not in ("admin", "super_admin", "technician"):
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
    if user.get("role") not in ("admin", "super_admin", "technician"):
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
    if user.get("role") not in ("admin", "super_admin", "technician"):
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
    """Return the two-key terms defaults.

    Feb-2026 · Task 6 · Defect fix — empty-string / cleared values
    are now respected verbatim. Prior behaviour silently substituted
    the built-in seed (``DEFAULT_QUOTE_TERMS`` / ``DEFAULT_INVOICE_TERMS``)
    whenever the stored value was empty or missing, which made it
    impossible for tenants to revoke their default terms via the
    admin UI.

    New contract:
      * First-time read (no doc yet) → seed the row with EMPTY strings
        so an admin who never touched the endpoint sees the "empty
        default with helper text" UX from the frontend.
      * Any subsequent read returns whatever's on the doc verbatim
        (including empty strings). The router callers
        (``routers/quotes.py``, ``routers/estimates.py``,
        ``routers/jobs.py``) treat empty strings as "no pre-fill",
        which matches the product lock.
    """
    doc = await db.settings.find_one({"id": TERMS_SETTINGS_ID}, {"_id": 0})
    if not doc:
        doc = {
            "id": TERMS_SETTINGS_ID,
            "default_quote_terms": "",
            "default_invoice_terms": "",
        }
        await db.settings.insert_one(dict(doc))
    return {
        "default_quote_terms": doc.get("default_quote_terms") or "",
        "default_invoice_terms": doc.get("default_invoice_terms") or "",
    }


@router.get("/settings/terms")
async def get_terms_settings(admin: dict = Depends(require_admin)):
    return await get_terms_defaults()


@router.put("/settings/terms")
async def update_terms_settings(body: TermsSettingsIn, request: Request,
                                 admin: dict = Depends(require_admin)):
    """Feb-2026 · Task 6 · Defect fix — distinguish "field not in
    payload" (partial update, skip) from "field is null or empty"
    (explicit clear). Prior behaviour filtered out ``None`` values
    unconditionally and silently substituted the built-in seed on
    the response, so admins could not revoke tenant-level defaults.

    New contract:
      * Only keys that are actually present in the raw JSON body
        are considered for the write. Missing keys leave the stored
        value alone.
      * ``null`` and empty-string values are BOTH treated as an
        explicit clear (persisted as empty string).
      * Non-string values raise 400 so callers can't stash garbage.
    """
    try:
        raw = await request.json()
    except Exception:  # noqa: BLE001
        raw = {}
    if not isinstance(raw, dict):
        raise HTTPException(400, "Body must be a JSON object")
    upd: dict = {}
    for key in ("default_quote_terms", "default_invoice_terms"):
        if key not in raw:
            continue
        val = raw[key]
        if val is None:
            upd[key] = ""
        elif isinstance(val, str):
            upd[key] = val
        else:
            raise HTTPException(400, f"{key} must be a string or null")
    if upd:
        await db.settings.update_one(
            {"id": TERMS_SETTINGS_ID},
            {"$set": {"id": TERMS_SETTINGS_ID, **upd}},
            upsert=True,
        )
    return await get_terms_defaults()


@router.post("/settings/terms/reset")
async def reset_terms_settings(admin: dict = Depends(require_admin)):
    """Feb-2026 · Task 6 · Defect fix — reset clears BOTH default
    terms strings to empty (matching the "empty default with
    helper text" lock). Previously reset restored the built-in
    seed, which prevented admins from removing tenant-level defaults
    entirely.
    """
    await db.settings.update_one(
        {"id": TERMS_SETTINGS_ID},
        {"$set": {
            "id": TERMS_SETTINGS_ID,
            "default_quote_terms": "",
            "default_invoice_terms": "",
        }},
        upsert=True,
    )
    return await get_terms_defaults()



# ═══════════════════════════════════════════════════════════════════
# Phase 56.17 — Autobilling schedule options + daily auto-run
# ═══════════════════════════════════════════════════════════════════
#
# Billing plans grew a `run_schedule` enum (`first_friday`,
# `second_friday`, `third_friday`, `first_of_month`) so admins can
# pick when a monthly cycle fires. The APScheduler used to run this
# every 24 h; it now runs DAILY, computes each plan's anchor date in
# the tenant's timezone, and fires exactly-once per plan per calendar
# month (idempotency: `last_run_month == current YYYY-MM` → skip).
# A grace window of 7 days catches up plans missed due to downtime.

_VALID_SCHEDULES = ("first_friday", "second_friday", "third_friday", "fourth_friday", "first_of_month")


def _default_schedule(plan: dict) -> str:
    """Legacy plans have no `run_schedule` field; default to the old
    behavior (fire on the 1st) so nothing changes for them until an
    admin explicitly picks a new anchor."""
    v = (plan or {}).get("run_schedule")
    if v in _VALID_SCHEDULES:
        return v
    return "first_of_month"


def _tenant_tz(tenant: dict):
    """Return a `zoneinfo.ZoneInfo` for the tenant, defaulting to
    America/Phoenix (Vistancia, AZ — no-DST). Falls back to UTC if
    the stored value can't be parsed (never let scheduling crash on
    a bad string)."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    name = (tenant or {}).get("timezone") or "America/Phoenix"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logger.warning(f"tenant timezone '{name}' not found; falling back to UTC")
        return ZoneInfo("UTC")


def anchor_date_for_month(schedule: str, year: int, month: int):
    """Return the `date` this schedule anchors on for (year, month).
    `first_friday` = first Friday, `second_friday` = second Friday,
    etc. `first_of_month` = day 1. Never raises for the 4 valid
    inputs; raises ValueError for anything else."""
    from datetime import date as _date
    if schedule not in _VALID_SCHEDULES:
        raise ValueError(f"unknown schedule: {schedule}")
    if schedule == "first_of_month":
        return _date(year, month, 1)
    # Find the first Friday of the month (weekday()==4 for Fri).
    first = _date(year, month, 1)
    offset_to_friday = (4 - first.weekday()) % 7  # 0..6
    first_friday = _date(year, month, 1 + offset_to_friday)
    if schedule == "first_friday":
        return first_friday
    if schedule == "second_friday":
        return _date(year, month, first_friday.day + 7)
    if schedule == "third_friday":
        return _date(year, month, first_friday.day + 14)
    if schedule == "fourth_friday":
        # Fourth Friday of the month — always exists because months
        # have at least 28 days AND `first_friday.day` is in 1..7,
        # so first_friday.day + 21 is in 22..28.
        return _date(year, month, first_friday.day + 21)
    raise ValueError(f"unhandled schedule: {schedule}")


def next_fire_preview(schedule: str, today) -> str:
    """ISO date string for the next fire from `today` for `schedule`.
    If today ≤ this month's anchor, use this month's; else next
    month's."""
    from datetime import date as _date
    y, m = today.year, today.month
    this_month = anchor_date_for_month(schedule, y, m)
    if today <= this_month:
        return this_month.isoformat()
    # Roll to next month.
    if m == 12:
        return anchor_date_for_month(schedule, y + 1, 1).isoformat()
    return anchor_date_for_month(schedule, y, m + 1).isoformat()


async def _log_autobilling_run(**row):
    row.setdefault("id", new_id())
    row.setdefault("ts", now_iso())
    await db.autobilling_runs.insert_one(row)


async def _fire_billing_plan(plan: dict, tenant: dict, current_month: str,
                             anchor: str, reason: str = "scheduled") -> dict:
    """Do the same invoice-creation work `run_billing_plan` does, but
    write to `autobilling_runs` too. Idempotent when combined with the
    `last_run_month` guard at the caller."""
    amount = float(plan.get("amount") or 0.0)
    tax = round(amount * 0.08, 2)
    invoice = {
        "id": new_id(), "tenant_id": tenant["id"],
        "customer_id": plan["customer_id"],
        "customer_name": plan.get("customer_name") or "",
        "title": plan.get("service", "Recurring Service"), "doc_type": "invoice",
        "line_items": [{"description": plan.get("service", "Recurring Service"),
                        "quantity": 1, "unit_price": amount}],
        "tax_rate": 8.0, "subtotal": amount, "tax": tax,
        "total": round(amount + tax, 2), "amount_paid": 0.0,
        "due_date": (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat(),
        "status": "sent", "payment_status": "unpaid",
        "notes": f"Auto-generated from billing plan ({reason}).",
        "billing_plan_id": plan["id"], "created_at": now_iso(),
    }
    # Phase 56.18 — number assignment on autobilling-generated invoices.
    from services.invoice_numbering import assign_invoice_number_if_missing
    await assign_invoice_number_if_missing(invoice, tenant)
    # Phase 10 · Feb 2026 — auto-apply available credits BEFORE
    # persisting so the invoice PDF/HTML shows the discount line and
    # the customer balance decrements atomically.
    from services.credits_apply import apply_and_persist
    invoice = await apply_and_persist(db, tenant["id"], invoice)
    await db.quotes.insert_one(invoice)
    # Feb-2026 · Auto-apply credit balance to this customer's OTHER
    # open invoices after monthly billing. Non-blocking.
    try:
        from services.credit_apply import (
            apply_credit_to_customer_open_invoices,
        )
        await apply_credit_to_customer_open_invoices(
            db, tenant["id"], invoice.get("customer_id"),
            exclude_invoice_ids=[invoice.get("id")],
        )
    except Exception as _ca_exc:  # noqa: BLE001
        logger.warning(
            "credit_apply.failed tenant=%s invoice=%s error=%r",
            tenant["id"], invoice.get("id"), _ca_exc,
        )
    await db.billing_plans.update_one(
        {"id": plan["id"], "tenant_id": tenant["id"]},
        {"$set": {"last_run": now_iso(), "last_run_month": current_month}},
    )
    await _log_autobilling_run(
        tenant_id=tenant["id"], plan_id=plan["id"],
        plan_name=plan.get("service") or plan.get("customer_name") or plan["id"],
        run_schedule=_default_schedule(plan),
        anchor_date=anchor, current_month=current_month,
        status="fired", message=f"Invoice {invoice['id']} created ({reason}).",
        invoice_id=invoice["id"],
    )
    try:
        await notify_customer(plan["customer_id"], "New invoice",
                              f"An invoice for {plan.get('service', 'your service')} was issued.")
    except Exception as e:
        logger.warning(f"notify_customer skipped on plan {plan['id']}: {e}")
    return {"ok": True, "invoice_id": invoice["id"]}


async def run_daily_autobilling() -> dict:
    """DAILY APScheduler tick. Iterates active billing plans across
    every tenant, computes today's anchor for each in tenant TZ,
    fires if today >= anchor AND we're still inside the 7-day grace
    window AND `last_run_month != YYYY-MM`. Returns a summary dict."""
    from datetime import date as _date
    summary = {"fired": [], "skipped": 0, "late_missed": 0, "errors": 0}
    tenants = await db.tenants.find({}, {"_id": 0}).to_list(500)
    for tenant in tenants:
        try:
            tz = _tenant_tz(tenant)
            today = datetime.now(tz).date()
            ym = today.strftime("%Y-%m")
            plans = await db.billing_plans.find(
                {"tenant_id": tenant["id"], "active": {"$ne": False}}, {"_id": 0},
            ).to_list(2000)
            for plan in plans:
                sched = _default_schedule(plan)
                anchor = anchor_date_for_month(sched, today.year, today.month)
                delta = (today - anchor).days  # negative until anchor
                if delta < 0:
                    summary["skipped"] += 1
                    continue
                if plan.get("last_run_month") == ym:
                    summary["skipped"] += 1
                    continue
                if delta > 7:
                    # More than 7 days past the anchor — don't
                    # backfire; log the miss and let the admin
                    # manually run.
                    await _log_autobilling_run(
                        tenant_id=tenant["id"], plan_id=plan["id"],
                        plan_name=plan.get("service") or plan.get("customer_name"),
                        run_schedule=sched,
                        anchor_date=anchor.isoformat(), current_month=ym,
                        status="late_missed",
                        message=f"{delta} days past anchor — outside 7-day grace window; manual run required.",
                    )
                    summary["late_missed"] += 1
                    continue
                try:
                    await _fire_billing_plan(
                        plan, tenant, ym, anchor.isoformat(),
                        reason="scheduled_catchup" if delta > 0 else "scheduled",
                    )
                    summary["fired"].append(plan["id"])
                except Exception as e:
                    summary["errors"] += 1
                    await _log_autobilling_run(
                        tenant_id=tenant["id"], plan_id=plan["id"],
                        plan_name=plan.get("service"),
                        run_schedule=sched,
                        anchor_date=anchor.isoformat(), current_month=ym,
                        status="error", message=f"Fire failed: {e}",
                    )
                    logger.warning(f"autobilling fire error plan={plan['id']}: {e}")
        except Exception as e:
            logger.warning(f"autobilling tenant loop error tenant={tenant.get('id')}: {e}")
    logger.info(f"[phase56.17] autobilling daily tick summary={summary}")
    return summary


# ─── Endpoints ─────────────────────────────────────────────────────────

@router.get("/billing-plans/{pid}/next-fire")
async def get_next_fire(pid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    """Preview when a plan will next fire, in tenant timezone.
    Returns `{ next_fire_date, run_schedule, last_run_month, in_grace_window }`."""
    plan = await db.billing_plans.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not plan:
        raise HTTPException(404, "Plan not found")
    tz = _tenant_tz(tenant)
    today = datetime.now(tz).date()
    sched = _default_schedule(plan)
    return {
        "next_fire_date": next_fire_preview(sched, today),
        "run_schedule": sched,
        "last_run_month": plan.get("last_run_month"),
        "timezone": (tenant or {}).get("timezone") or "America/Phoenix",
    }


@router.post("/billing-plans/{pid}/run-now")
async def run_now(pid: str,
                  user: dict = Depends(require_admin),
                  tenant: dict = Depends(get_current_tenant)):
    """Manual admin action — fires the billing cycle immediately and
    marks `last_run_month = current YYYY-MM` so the daily scheduler
    won't double-fire in the same month."""
    plan = await db.billing_plans.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not plan:
        raise HTTPException(404, "Plan not found")
    tz = _tenant_tz(tenant)
    today = datetime.now(tz).date()
    ym = today.strftime("%Y-%m")
    if plan.get("last_run_month") == ym:
        raise HTTPException(409, "Plan already ran this calendar month; skip or wait for next month.")
    sched = _default_schedule(plan)
    anchor = anchor_date_for_month(sched, today.year, today.month).isoformat()
    res = await _fire_billing_plan(plan, tenant, ym, anchor, reason="manual_run_now")
    return {"ok": True, "invoice_id": res["invoice_id"], "last_run_month": ym}


@router.get("/autobilling-runs")
async def list_autobilling_runs(
    plan_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="ISO date lower bound."),
    include_deleted: bool = Query(
        False,
        description=(
            "Aug-2026 · Soft-delete surface — when True, soft-deleted "
            "rows (``deleted_at`` set) are included in the response. "
            "Only ``admin`` / ``super_admin`` / ``owner`` roles are "
            "allowed to opt in; the guard is already enforced by "
            "``require_admin`` on this endpoint. Defaults to False so "
            "the audit view hides deleted rows unless the operator "
            "explicitly asks to see them."
        ),
    ),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Admin audit log of every autobilling fire attempt in this
    tenant. Filter by plan_id / status / since (ISO date)."""
    q: dict = {"tenant_id": tenant["id"]}
    if plan_id:
        q["plan_id"] = plan_id
    if status:
        q["status"] = status
    if since:
        q["ts"] = {"$gte": since}
    if not include_deleted:
        # Default view hides soft-deleted rows. ``None`` / missing key
        # / ``False`` all count as "not deleted"; only a truthy
        # ``deleted_at`` string is treated as deleted.
        q["deleted_at"] = {"$in": [None, ""]}
    rows = await db.autobilling_runs.find(q, {"_id": 0}).sort("ts", -1).to_list(2000)
    return rows


@router.patch("/tenant/settings")
async def patch_tenant_settings(
    body: TenantSettingsUpdate,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Admin-editable tenant settings (Phase 56.17 — timezone only,
    for now)."""
    upd = {}
    if body.timezone is not None:
        # Validate IANA name — fail fast on typos.
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(body.timezone)
        except ZoneInfoNotFoundError:
            raise HTTPException(400, f"unknown IANA timezone: {body.timezone}")
        upd["timezone"] = body.timezone
    if not upd:
        return {"ok": True, "unchanged": True}
    await db.tenants.update_one({"id": tenant["id"]}, {"$set": upd})
    doc = await db.tenants.find_one({"id": tenant["id"]}, {"_id": 0})
    return doc



# ═════════════════════════════════════════════════════════════════════════
# Phase 34 · Task II · Feb 2026 — Autobilling (billing_plans) bulk-delete.
# Soft-delete pattern matching Task BB. Locked states:
#   * plans with a Stripe subscription id → reversal must run through the
#     Stripe dashboard.
#   * plans with a `next_run` inside the next 24h → cancel the imminent
#     charge manually first so admins don't accidentally miss a
#     scheduled billing.
# Every bulk-delete row still writes an audit log entry so the archive
# view can attribute the delete back to its actor.
# ═════════════════════════════════════════════════════════════════════════
from pydantic import BaseModel as _AutobillingBulkBase


class _AutobillingBulkDeleteIn(_AutobillingBulkBase):
    ids: Optional[List[str]] = None
    # Task EE compatibility hooks — accepted but not yet resolved
    # server-side on this endpoint (leads is the only surface that
    # ships selector resolution today).
    query_selector: Optional[Dict[str, Any]] = None
    exclude_ids: Optional[List[str]] = None


_AUTOBILLING_BULK_DELETE_CAP = 400


def _plan_locked_reason(plan: dict) -> Optional[str]:
    if plan.get("stripe_subscription_id"):
        return "Linked Stripe Subscription must be cancelled via Stripe dashboard"
    next_run = plan.get("next_run")
    if next_run:
        try:
            # ``next_run`` is stored as an ISO date string in this codebase.
            from datetime import datetime, timezone, timedelta
            when = datetime.fromisoformat(str(next_run).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when - datetime.now(timezone.utc) < timedelta(hours=24):
                return "Charge scheduled within 24h — cancel manually first"
        except Exception:                                       # noqa: BLE001
            pass
    return None


async def _perform_soft_delete_plan(pid: str, user: dict, tenant: dict) -> dict:
    plan = await db.billing_plans.find_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "deleted_at": 1, "stripe_subscription_id": 1,
         "next_run": 1},
    )
    if not plan:
        raise HTTPException(404, "Autobilling plan not found")
    if plan.get("deleted_at"):
        return {"ok": True, "id": pid, "already_deleted": True}
    lock_reason = _plan_locked_reason(plan)
    if lock_reason:
        raise HTTPException(409, lock_reason)
    deleted_at = now_iso()
    await db.billing_plans.update_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": deleted_at,
                    "deleted_by_user_id": user.get("id"),
                    "active": False}},
    )
    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "autobilling.soft_delete",
            "target_id": pid,
            "at": deleted_at,
        })
    except Exception as e:                                       # noqa: BLE001
        logger.warning(f"autobilling.soft_delete audit failed: {e}")
    return {"ok": True, "id": pid, "deleted_at": deleted_at}


@router.post("/billing-plans/{pid}/soft-delete",
              operation_id="billingPlans.softDelete")
async def soft_delete_billing_plan(pid: str,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    return await _perform_soft_delete_plan(pid, user, tenant)


@router.post("/billing-plans/bulk-delete",
              operation_id="billingPlans.bulkDelete")
async def bulk_delete_billing_plans(body: _AutobillingBulkDeleteIn,
                                       user: dict = Depends(require_admin),
                                       tenant: dict = Depends(get_current_tenant)):
    ids = list(body.ids or [])
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _AUTOBILLING_BULK_DELETE_CAP:
        raise HTTPException(400, f"bulk-delete capped at {_AUTOBILLING_BULK_DELETE_CAP} rows per call")
    deleted: List[str] = []
    failed: List[dict] = []
    for pid in ids:
        try:
            r = await _perform_soft_delete_plan(pid, user, tenant)
            deleted.append(r["id"])
        except HTTPException as e:
            failed.append({"id": pid, "reason": str(e.detail),
                              "status_code": e.status_code})
        except Exception as e:                                       # noqa: BLE001
            failed.append({"id": pid, "reason": str(e), "status_code": 500})
    return {"ok": True, "deleted_count": len(deleted),
              "deleted": deleted, "failed": failed}


# Alias route under /autobilling/bulk-delete for consistency with the
# admin nav (both /billing-plans and /autobilling refer to the same
# resource — the frontend calls whichever it happens to use).
@router.post("/autobilling/bulk-delete",
              operation_id="autobilling.bulkDelete")
async def bulk_delete_autobilling_alias(body: _AutobillingBulkDeleteIn,
                                            user: dict = Depends(require_admin),
                                            tenant: dict = Depends(get_current_tenant)):
    return await bulk_delete_billing_plans(body, user, tenant)


# ═════════════════════════════════════════════════════════════════════════
# Phase AB1 · Feb 2026 — Autobilling bulk-cancel.
# ═════════════════════════════════════════════════════════════════════════
# Soft cancel of billing_plans rows: flip ``active=False`` and stamp
# ``cancelled_at`` + ``cancelled_by_user_id`` + ``cancel_reason`` without
# removing the row (bulk-delete already covers the archival flow). This
# is the sibling operation admins reach for when a customer pauses a
# recurring plan indefinitely but the row itself should stay in place
# for reporting continuity.
#
# The parallel ``autobilling/runs/bulk-cancel`` endpoint operates on
# ``db.autobilling_runs``. That collection is an *audit log* of past
# run events today (statuses today = ``fired|manual|skipped|error|
# late_missed``), but Phase AB1 anticipates future schema growth
# where scheduled/queued rows will land there. The endpoint therefore
# accepts requests and returns per-id skip reasons for anything
# outside the eligible-statuses list — safe & idempotent regardless
# of current data.
class _AutobillingBulkCancelIn(_AutobillingBulkBase):
    ids: List[str]
    reason: Optional[str] = None


_AUTOBILLING_BULK_CANCEL_CAP = 500

_RUN_STATUSES_ELIGIBLE_FOR_CANCEL = {"pending", "scheduled", "queued"}


async def _write_bulk_cancel_audit(*, kind: str, target_id: str,
                                     user: dict, tenant: dict,
                                     reason: Optional[str]) -> None:
    try:
        await db.audits.insert_one({
            "id": new_id(),
            "kind": kind,
            "tenant_id": tenant["id"],
            "target_id": target_id,
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "cancel_reason": reason or "",
            "at": now_iso(),
        })
    except Exception as e:                                            # noqa: BLE001
        logger.warning(f"{kind} audit failed for {target_id}: {e}")


@router.post("/billing-plans/bulk-cancel",
              operation_id="billingPlans.bulkCancel")
async def bulk_cancel_billing_plans(body: _AutobillingBulkCancelIn,
                                       user: dict = Depends(require_admin),
                                       tenant: dict = Depends(get_current_tenant)):
    ids = list(body.ids or [])
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _AUTOBILLING_BULK_CANCEL_CAP:
        raise HTTPException(
            400,
            f"bulk-cancel capped at {_AUTOBILLING_BULK_CANCEL_CAP} rows per call",
        )

    cancelled: List[str] = []
    skipped: List[dict] = []
    results: List[dict] = []
    when = now_iso()

    for pid in ids:
        plan = await db.billing_plans.find_one(
            {"id": pid, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "active": 1, "cancelled_at": 1,
              "deleted_at": 1},
        )
        if not plan:
            entry = {"id": pid, "status": "skipped", "reason": "not_found"}
            skipped.append(entry)
            results.append(entry)
            continue
        # Already cancelled or deleted → skip idempotently.
        if plan.get("cancelled_at") or plan.get("deleted_at") \
                or plan.get("active") is False:
            entry = {"id": pid, "status": "skipped",
                      "reason": "already_cancelled_or_inactive"}
            skipped.append(entry)
            results.append(entry)
            continue
        try:
            await db.billing_plans.update_one(
                {"id": pid, "tenant_id": tenant["id"]},
                {"$set": {"active": False,
                            "cancelled_at": when,
                            "cancelled_by_user_id": user.get("id"),
                            "cancel_reason": (body.reason or "")}},
            )
            await _write_bulk_cancel_audit(
                kind="autobilling_bulk_cancel", target_id=pid,
                user=user, tenant=tenant, reason=body.reason,
            )
            cancelled.append(pid)
            results.append({"id": pid, "status": "cancelled", "reason": None})
        except Exception as e:                                        # noqa: BLE001
            entry = {"id": pid, "status": "skipped",
                      "reason": f"error: {e}"}
            skipped.append(entry)
            results.append(entry)

    return {"cancelled": len(cancelled), "skipped": len(skipped),
              "results": results}


# Alias — mirror the /autobilling/bulk-delete naming convention so the
# admin frontend can call whichever URL it prefers.
@router.post("/autobilling/bulk-cancel",
              operation_id="autobilling.bulkCancel")
async def bulk_cancel_autobilling_alias(body: _AutobillingBulkCancelIn,
                                            user: dict = Depends(require_admin),
                                            tenant: dict = Depends(get_current_tenant)):
    return await bulk_cancel_billing_plans(body, user, tenant)


@router.post("/autobilling/runs/bulk-cancel",
              operation_id="autobillingRuns.bulkCancel")
async def bulk_cancel_autobilling_runs(body: _AutobillingBulkCancelIn,
                                            user: dict = Depends(require_admin),
                                            tenant: dict = Depends(get_current_tenant)):
    """Bulk-cancel scheduled runs in ``db.autobilling_runs``.

    Only rows whose ``status`` (or legacy ``run_status``) is
    ``pending`` / ``scheduled`` / ``queued`` are eligible. Everything
    else — ``fired`` / ``completed`` / ``failed`` / ``error`` /
    ``late_missed`` / already ``cancelled`` — is left untouched and
    returned in ``skipped`` with a machine-readable reason so the
    frontend can surface it verbatim in the result summary.
    """
    ids = list(body.ids or [])
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _AUTOBILLING_BULK_CANCEL_CAP:
        raise HTTPException(
            400,
            f"bulk-cancel capped at {_AUTOBILLING_BULK_CANCEL_CAP} rows per call",
        )

    cancelled: List[str] = []
    skipped: List[dict] = []
    results: List[dict] = []
    when = now_iso()

    for rid in ids:
        row = await db.autobilling_runs.find_one(
            {"id": rid, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "status": 1, "run_status": 1,
              "cancelled_at": 1},
        )
        if not row:
            entry = {"id": rid, "status": "skipped", "reason": "not_found"}
            skipped.append(entry)
            results.append(entry)
            continue
        if row.get("cancelled_at"):
            entry = {"id": rid, "status": "skipped",
                      "reason": "already_cancelled"}
            skipped.append(entry)
            results.append(entry)
            continue
        current = (row.get("status") or row.get("run_status") or "").lower()
        if current not in _RUN_STATUSES_ELIGIBLE_FOR_CANCEL:
            entry = {"id": rid, "status": "skipped",
                      "reason": f"not_eligible: current_status={current or 'unknown'}"}
            skipped.append(entry)
            results.append(entry)
            continue
        try:
            await db.autobilling_runs.update_one(
                {"id": rid, "tenant_id": tenant["id"]},
                {"$set": {"status": "cancelled",
                            "cancelled_at": when,
                            "cancelled_by_user_id": user.get("id"),
                            "cancel_reason": (body.reason or "")}},
            )
            await _write_bulk_cancel_audit(
                kind="autobilling_runs_bulk_cancel", target_id=rid,
                user=user, tenant=tenant, reason=body.reason,
            )
            cancelled.append(rid)
            results.append({"id": rid, "status": "cancelled", "reason": None})
        except Exception as e:                                        # noqa: BLE001
            entry = {"id": rid, "status": "skipped",
                      "reason": f"error: {e}"}
            skipped.append(entry)
            results.append(entry)

    return {"cancelled": len(cancelled), "skipped": len(skipped),
              "results": results}



# ═════════════════════════════════════════════════════════════════════════
# Aug-2026 · Autobilling Runs — SOFT-DELETE (admin + super_admin).
#
# Distinct from the /autobilling/runs/bulk-cancel endpoint above:
#   * bulk-cancel  — state-machine transition on eligible statuses
#                    (pending/scheduled/queued) so a run doesn't fire.
#   * soft-delete  — audit-preserving hide from the default list view.
#     Applies to ANY status including fired/completed/failed. No
#     "running soon" guard for admin/super_admin — the entire point
#     is that these roles can hide historical clutter without losing
#     it for auditors. Restore is symmetric and role-gated the same
#     way.
# ═════════════════════════════════════════════════════════════════════════
_AUTOBILLING_RUNS_BULK_DELETE_CAP = 500


class _AutobillingRunsBulkDeleteIn(_AutobillingBulkBase):
    ids: List[str]


async def _write_runs_softdelete_audit(*, kind: str, target_id: str,
                                       user: dict, tenant: dict) -> None:
    try:
        await db.audits.insert_one({
            "id": new_id(),
            "kind": kind,
            "tenant_id": tenant["id"],
            "target_id": target_id,
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "at": now_iso(),
        })
    except Exception as e:                                            # noqa: BLE001
        logger.warning(f"{kind} audit failed for {target_id}: {e}")


@router.post("/autobilling/runs/bulk-delete",
              operation_id="autobillingRuns.bulkDelete")
async def bulk_delete_autobilling_runs(
    body: _AutobillingRunsBulkDeleteIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Bulk soft-delete autobilling audit rows.

    Sets ``deleted_at``, ``deleted_by_user_id`` on each matched row.
    Idempotent — a row already marked ``deleted_at`` is returned as
    ``skipped: already_deleted``. No status/eligibility guards — the
    audit log entry exists forever regardless of what state the run
    itself was in when the operator hid it.
    """
    ids = list(body.ids or [])
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _AUTOBILLING_RUNS_BULK_DELETE_CAP:
        raise HTTPException(
            400,
            f"bulk-delete capped at {_AUTOBILLING_RUNS_BULK_DELETE_CAP} rows per call",
        )

    deleted: List[str] = []
    skipped: List[dict] = []
    results: List[dict] = []
    when = now_iso()

    for rid in ids:
        row = await db.autobilling_runs.find_one(
            {"id": rid, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "deleted_at": 1},
        )
        if not row:
            entry = {"id": rid, "status": "skipped", "reason": "not_found"}
            skipped.append(entry)
            results.append(entry)
            continue
        if row.get("deleted_at"):
            entry = {"id": rid, "status": "skipped",
                      "reason": "already_deleted"}
            skipped.append(entry)
            results.append(entry)
            continue
        try:
            await db.autobilling_runs.update_one(
                {"id": rid, "tenant_id": tenant["id"]},
                {"$set": {"deleted_at": when,
                            "deleted_by_user_id": user.get("id")}},
            )
            await _write_runs_softdelete_audit(
                kind="autobilling_runs_soft_delete", target_id=rid,
                user=user, tenant=tenant,
            )
            deleted.append(rid)
            results.append({"id": rid, "status": "deleted", "reason": None})
        except Exception as e:                                        # noqa: BLE001
            entry = {"id": rid, "status": "skipped",
                      "reason": f"error: {e}"}
            skipped.append(entry)
            results.append(entry)

    return {"deleted": len(deleted), "skipped": len(skipped),
              "results": results}


@router.delete("/autobilling/runs/{rid}",
                operation_id="autobillingRuns.softDelete")
async def soft_delete_autobilling_run(
    rid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Per-row soft-delete convenience — wraps the same code path as
    the bulk endpoint, returning a single-row result envelope for the
    admin UI's trash-icon flow."""
    body = _AutobillingRunsBulkDeleteIn(ids=[rid])
    envelope = await bulk_delete_autobilling_runs(body, user=user, tenant=tenant)
    result = (envelope.get("results") or [{}])[0]
    if result.get("status") == "skipped" and result.get("reason") == "not_found":
        raise HTTPException(404, "Autobilling run not found")
    return {"ok": True, "id": rid, "result": result}


@router.post("/autobilling/runs/{rid}/restore",
              operation_id="autobillingRuns.restore")
async def restore_autobilling_run(
    rid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Undo a prior soft-delete. Only ``admin`` / ``super_admin`` /
    ``owner`` per ``require_admin``. Idempotent — a row that is NOT
    currently deleted is returned as ``already_active`` with no DB
    write."""
    row = await db.autobilling_runs.find_one(
        {"id": rid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "deleted_at": 1},
    )
    if not row:
        raise HTTPException(404, "Autobilling run not found")
    if not row.get("deleted_at"):
        return {"ok": True, "id": rid, "already_active": True}
    await db.autobilling_runs.update_one(
        {"id": rid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": None,
                    "restored_at": now_iso(),
                    "restored_by_user_id": user.get("id")},
          "$unset": {"deleted_by_user_id": ""}},
    )
    await _write_runs_softdelete_audit(
        kind="autobilling_runs_restore", target_id=rid,
        user=user, tenant=tenant,
    )
    return {"ok": True, "id": rid, "restored": True}


# ═════════════════════════════════════════════════════════════════════════
# Phase P41 · Feb-2026 — Autobilling Runs · HARD DELETE (single + bulk).
#
# Physical removal of the audit document from ``db.autobilling_runs``.
# Distinct from the soft-delete surface above:
#   * soft-delete (``DELETE /autobilling/runs/{rid}``)  → sets
#     ``deleted_at`` + hides from default list; preserved for audit.
#   * hard-delete (``DELETE /autobilling-runs/{run_id}``) → physical
#     ``delete_one`` on the row; cannot be undone.
#
# Security invariants (do NOT drift):
#   1. Tenant scoping is mandatory on EVERY query. Cross-tenant
#      delete returns 404 (existence-hiding) — never 403.
#   2. Admin / super_admin / owner only (require_admin).
#   3. In-progress runs (``status in {running, in_progress}``) are
#      NOT hard-blocked — deletion proceeds, but a WARN is logged
#      so operations can audit dangerous deletes later.
#   4. Cascade behavior deferred — grep of the backend confirmed
#      no other collection back-references ``autobilling_run_id``,
#      so the physical delete has zero orphan risk today. If a
#      future collection adds that FK, extend this handler to also
#      purge those docs OR keep the row soft-only.
# ═════════════════════════════════════════════════════════════════════════
_AUTOBILLING_RUNS_HARD_DELETE_CAP = 500
_IN_PROGRESS_STATUSES = {"running", "in_progress"}


class _AutobillingRunsHardDeleteBulkIn(_AutobillingBulkBase):
    ids: List[str]


async def _write_runs_harddelete_audit(*, target_id: str,
                                        user: dict, tenant: dict,
                                        prior_status: Optional[str],
                                        prior_ts: Optional[str]) -> None:
    """Best-effort audit trail for a PHYSICAL delete. The row itself
    is gone after the ``delete_one``, so we snapshot ``prior_status``
    + ``prior_ts`` into the audit event for forensics."""
    try:
        await db.audits.insert_one({
            "id": new_id(),
            "kind": "autobilling_runs_hard_delete",
            "tenant_id": tenant["id"],
            "target_id": target_id,
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "prior_status": prior_status,
            "prior_ts": prior_ts,
            "at": now_iso(),
        })
    except Exception as e:                                            # noqa: BLE001
        logger.warning(
            f"[p41] hard-delete audit failed for {target_id}: {e}",
        )


@router.delete("/autobilling-runs/{run_id}",
                operation_id="autobillingRuns.hardDelete")
async def hard_delete_autobilling_run(
    run_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase P41 — physical removal of a single autobilling audit
    row. Tenant-scoped. 404 (existence-hiding) when the row belongs
    to another tenant OR does not exist at all."""
    # Fetch (tenant-scoped) so we can (a) return 404 for cross-tenant
    # / unknown ids and (b) snapshot the prior status for the WARN
    # log + audit event before the physical delete.
    row = await db.autobilling_runs.find_one(
        {"id": run_id, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "status": 1, "ts": 1},
    )
    if not row:
        raise HTTPException(404, "Autobilling run not found")

    prior_status = row.get("status")
    if prior_status in _IN_PROGRESS_STATUSES:
        logger.warning(
            "[p41] hard-delete of active autobilling_run "
            f"id={run_id} tenant={tenant['id']} status={prior_status}",
        )

    res = await db.autobilling_runs.delete_one(
        {"id": run_id, "tenant_id": tenant["id"]},
    )
    if res.deleted_count == 0:
        # Between the find_one and delete_one another admin deleted
        # the row. Existence-hide with 404 to match the spec.
        raise HTTPException(404, "Autobilling run not found")

    await _write_runs_harddelete_audit(
        target_id=run_id, user=user, tenant=tenant,
        prior_status=prior_status, prior_ts=row.get("ts"),
    )
    return {"deleted": True, "id": run_id}


@router.post("/autobilling-runs/hard-delete-bulk",
              operation_id="autobillingRuns.hardDeleteBulk")
async def hard_delete_autobilling_runs_bulk(
    body: _AutobillingRunsHardDeleteBulkIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase P41 — physical removal of many autobilling audit rows
    in one call. Tenant-scoped. Ids that don't exist for this tenant
    are reported in ``not_found`` (deleted_count may be < requested).
    Always returns 200 — the caller uses the counts to decide UX.
    """
    ids = list(body.ids or [])
    requested_count = len(ids)
    if requested_count == 0:
        # Empty is legal — return zero counts rather than a 400 so
        # the FE doesn't have to special-case pre-flight validation.
        return {"deleted_count": 0, "requested_count": 0, "not_found": []}
    if requested_count > _AUTOBILLING_RUNS_HARD_DELETE_CAP:
        raise HTTPException(
            400,
            "hard-delete-bulk capped at "
            f"{_AUTOBILLING_RUNS_HARD_DELETE_CAP} rows per call",
        )

    # De-dup while preserving order (a caller sending the same id
    # twice should count as a single delete + a single audit).
    seen: set = set()
    deduped: List[str] = []
    for rid in ids:
        if rid not in seen:
            seen.add(rid)
            deduped.append(rid)

    # Fetch existing rows in one round-trip (tenant-scoped). Rows
    # that come back are safe to delete; ids missing from the set
    # roll into ``not_found``. This keeps the bulk call at 2 DB
    # ops (find + delete_many) instead of N.
    existing_docs = await db.autobilling_runs.find(
        {"tenant_id": tenant["id"], "id": {"$in": deduped}},
        {"_id": 0, "id": 1, "status": 1, "ts": 1},
    ).to_list(_AUTOBILLING_RUNS_HARD_DELETE_CAP)
    existing_by_id = {d["id"]: d for d in existing_docs}
    not_found = [rid for rid in deduped if rid not in existing_by_id]

    # WARN on any in-progress runs BEFORE the physical delete.
    for rid, doc in existing_by_id.items():
        if doc.get("status") in _IN_PROGRESS_STATUSES:
            logger.warning(
                "[p41] hard-delete of active autobilling_run "
                f"id={rid} tenant={tenant['id']} "
                f"status={doc.get('status')} (bulk)",
            )

    deleted_count = 0
    if existing_by_id:
        res = await db.autobilling_runs.delete_many(
            {"tenant_id": tenant["id"],
              "id": {"$in": list(existing_by_id.keys())}},
        )
        deleted_count = res.deleted_count

    # Best-effort audit per row (each hard-delete gets its own audit
    # event so forensics stays granular).
    for rid, doc in existing_by_id.items():
        await _write_runs_harddelete_audit(
            target_id=rid, user=user, tenant=tenant,
            prior_status=doc.get("status"), prior_ts=doc.get("ts"),
        )

    return {
        "deleted_count": deleted_count,
        "requested_count": requested_count,
        "not_found": not_found,
    }
