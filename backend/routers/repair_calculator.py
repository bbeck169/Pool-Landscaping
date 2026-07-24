"""Feb-2026 · Pool Repair Pricing Calculator (Ops).

Rebuild of the tenant's spreadsheet-driven repair estimator, extracted
verbatim from `Copy of Sample Repair Pricing Calculator.xlsx`.

### Formulas (mirror .xlsx cells E3..E26)
* ``PARTS_SUBTOTAL     = SUM(parts)``               (spreadsheet E8)
* ``SALES_TAX_ON_PARTS = PARTS_SUBTOTAL * tax``     (E10)
* ``PARTS_TOTAL        = PARTS_SUBTOTAL + tax``     (E11 — tax on parts ONLY)
* ``MARKUP             = PARTS_SUBTOTAL * markup``  (E13 — markup on parts ONLY)
* ``LABOR              = hours * customer_rate``    (E15 — customer_rate = $175/hr)
* ``MERCHANT_FEES      = (PARTS_TOTAL + MARKUP + LABOR) * merchant`` (E17)
* ``ESTIMATE_TOTAL     = SUBTOTAL + TAX + MARKUP + LABOR + MERCHANT_FEES`` (E18)
* ``COMPANY_COST       = PARTS_TOTAL + MERCHANT_FEES + (hours * internal_rate)`` (E24)
* ``PROFIT_MARGIN      = 1 - COMPANY_COST / ESTIMATE_TOTAL``  (E26)

### Defaults (spreadsheet-verified — NOT the brief's 0.5%)
| field                 | default |
|-----------------------|---------|
| sales_tax_pct         | 0.07 (7% AZ)           |
| parts_markup_pct      | 0.50 (50%)             |
| merchant_fees_pct     | **0.03 (3% — NOT 0.5%)**|
| customer_labor_rate   | 175                    |
| internal_labor_rate   | 75  (profit-margin cost basis, hardcoded in E24) |
| profit_margin_floor   | 0.30 (green ≥30, yellow 20-29, red <20) |

Persisted per-tenant at ``tenant.settings.repair_calculator_defaults``.

### Endpoints
* ``POST /api/ops/repair-calculator/quote`` — pure computation (no persistence)
* ``GET  /api/ops/repair-calculator/config``
* ``PATCH /api/ops/repair-calculator/config``
* ``POST /api/ops/repair-calculator/email`` — Resend + log to communications_log
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, now_iso, new_id

router = APIRouter(tags=["Repair Calculator"])


DEFAULT_CONFIG = {
    "sales_tax_pct": 0.07,
    "parts_markup_pct": 0.50,
    "merchant_fees_pct": 0.03,
    "customer_labor_rate": 175.0,
    "internal_labor_rate": 75.0,
    "profit_margin_floor": 0.30,
}


def _admin_or_403(user: dict):
    if (user or {}).get("role") not in {"admin", "super_admin"}:
        raise HTTPException(403, "Admin only")


async def _load_defaults(tenant_id: str) -> Dict[str, Any]:
    t = await db.tenants.find_one(
        {"id": tenant_id},
        {"_id": 0, "settings.repair_calculator_defaults": 1},
    )
    persisted = ((t or {}).get("settings") or {}).get(
        "repair_calculator_defaults", {}
    ) or {}
    return {**DEFAULT_CONFIG, **persisted}


class PartLine(BaseModel):
    name: Optional[str] = ""
    cost: float = 0.0


class QuoteBody(BaseModel):
    parts: List[PartLine] = Field(default_factory=list)
    labor_hours: float = 0.0
    # Optional per-quote overrides (all default to tenant config on None).
    sales_tax_pct: Optional[float] = None
    parts_markup_pct: Optional[float] = None
    merchant_fees_pct: Optional[float] = None
    customer_labor_rate: Optional[float] = None
    internal_labor_rate: Optional[float] = None


def compute_quote(parts: List[Dict[str, Any]], labor_hours: float,
                    cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Pure function — verified against xlsx: 247/1.5h/50%/7%/3%/175/75
    → estimate 669.7987, margin 40.83%. Uses banker rounds to 2 dp only
    on the API boundary; internal maths stays float for the profit margin.
    """
    parts_subtotal = sum(float(p.get("cost") or 0) for p in parts)
    tax = parts_subtotal * float(cfg["sales_tax_pct"])
    parts_total = parts_subtotal + tax
    markup = parts_subtotal * float(cfg["parts_markup_pct"])
    labor = float(labor_hours) * float(cfg["customer_labor_rate"])
    merchant = (parts_total + markup + labor) * float(cfg["merchant_fees_pct"])
    estimate_total = parts_subtotal + tax + markup + labor + merchant
    company_cost = (
        parts_total + merchant
        + float(labor_hours) * float(cfg["internal_labor_rate"])
    )
    profit_margin = (
        1 - (company_cost / estimate_total) if estimate_total > 0 else 0.0
    )
    floor = float(cfg.get("profit_margin_floor") or 0.30)
    if profit_margin >= floor:
        tier = "green"
    elif profit_margin >= 0.20:
        tier = "yellow"
    else:
        tier = "red"
    return {
        "line_items": [
            {"name": p.get("name") or "", "cost": float(p.get("cost") or 0)}
            for p in parts
        ],
        "parts_subtotal": round(parts_subtotal, 2),
        "sales_tax": round(tax, 2),
        "parts_total": round(parts_total, 2),
        "markup": round(markup, 2),
        "labor": round(labor, 2),
        "merchant_fees": round(merchant, 4),
        "estimate_total": round(estimate_total, 4),
        "company_cost": round(company_cost, 4),
        "profit_margin": round(profit_margin, 4),
        "profit_margin_pct": round(profit_margin * 100, 2),
        "profit_margin_tier": tier,
        "config_used": cfg,
    }


@router.post("/ops/repair-calculator/quote",
              operation_id="ops.repairCalculator.quote")
async def quote(body: QuoteBody,
                  user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id")
    cfg = await _load_defaults(tid)
    overrides = {k: v for k, v in {
        "sales_tax_pct": body.sales_tax_pct,
        "parts_markup_pct": body.parts_markup_pct,
        "merchant_fees_pct": body.merchant_fees_pct,
        "customer_labor_rate": body.customer_labor_rate,
        "internal_labor_rate": body.internal_labor_rate,
    }.items() if v is not None}
    cfg = {**cfg, **overrides}
    parts = [{"name": p.name, "cost": p.cost} for p in body.parts]
    computed = compute_quote(parts, body.labor_hours, cfg)
    return computed


@router.get("/ops/repair-calculator/config",
             operation_id="ops.repairCalculator.getConfig")
async def get_config(user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id")
    return await _load_defaults(tid)


class ConfigPatch(BaseModel):
    sales_tax_pct: Optional[float] = None
    parts_markup_pct: Optional[float] = None
    merchant_fees_pct: Optional[float] = None
    customer_labor_rate: Optional[float] = None
    internal_labor_rate: Optional[float] = None
    profit_margin_floor: Optional[float] = None


@router.patch("/ops/repair-calculator/config",
                operation_id="ops.repairCalculator.patchConfig")
async def patch_config(body: ConfigPatch,
                         user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id")
    updates = {k: v for k, v in body.dict().items() if v is not None}
    # Bound-check the pct fields so admins can't wedge 5000% markup.
    for k in ("sales_tax_pct", "parts_markup_pct", "merchant_fees_pct",
               "profit_margin_floor"):
        if k in updates and (updates[k] < 0 or updates[k] > 5):
            raise HTTPException(422, f"{k} out of range")
    for k in ("customer_labor_rate", "internal_labor_rate"):
        if k in updates and (updates[k] < 0 or updates[k] > 10000):
            raise HTTPException(422, f"{k} out of range")
    if updates:
        set_ops = {
            f"settings.repair_calculator_defaults.{k}": v
            for k, v in updates.items()
        }
        await db.tenants.update_one({"id": tid}, {"$set": set_ops})
    return await _load_defaults(tid)


class EmailQuoteBody(BaseModel):
    customer_id: Optional[str] = None
    ad_hoc_email: Optional[str] = None
    subject: str = "Your repair estimate"
    quote_snapshot: Dict[str, Any]
    note: Optional[str] = None


@router.post("/ops/repair-calculator/email",
              operation_id="ops.repairCalculator.email")
async def email_quote(body: EmailQuoteBody,
                        user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id")

    # Resolve recipient.
    to_email = (body.ad_hoc_email or "").strip()
    customer_doc = None
    if body.customer_id:
        customer_doc = await db.customers.find_one(
            {"id": body.customer_id, "tenant_id": tid}, {"_id": 0},
        )
        if not customer_doc:
            raise HTTPException(404, "Unknown customer")
        to_email = to_email or (customer_doc.get("email") or "")
    if not to_email:
        raise HTTPException(422, "No recipient email supplied")

    tenant = await db.tenants.find_one(
        {"id": tid}, {"_id": 0, "settings.business_card": 1, "name": 1},
    )
    card = ((tenant or {}).get("settings") or {}).get("business_card") or {}
    company_name = card.get("company_name") or (tenant or {}).get("name") or "Our team"

    snap = body.quote_snapshot or {}
    line_items = snap.get("line_items") or []
    line_rows = "".join([
        f'<tr><td style="padding:6px 12px">{(li.get("name") or "Part").strip() or "Part"}</td>'
        f'<td style="padding:6px 12px;text-align:right">${float(li.get("cost") or 0):.2f}</td></tr>'
        for li in line_items
    ]) or '<tr><td colspan="2" style="padding:6px 12px;color:#64748B">No parts.</td></tr>'

    html = f"""
    <div style="font-family:system-ui,Arial,sans-serif;max-width:600px;margin:auto;color:#0F172A">
      <h2 style="margin:0 0 4px 0">Repair estimate</h2>
      <div style="color:#64748B;font-size:12px">From {company_name}</div>
      {f'<p>{body.note}</p>' if body.note else ''}
      <table style="width:100%;border-collapse:collapse;margin-top:12px;font-size:14px">
        <thead><tr style="background:#F1F5F9"><th style="text-align:left;padding:6px 12px">Part</th><th style="text-align:right;padding:6px 12px">Cost</th></tr></thead>
        <tbody>{line_rows}</tbody>
      </table>
      <table style="width:100%;border-collapse:collapse;margin-top:12px;font-size:14px">
        <tbody>
          <tr><td style="padding:4px 12px">Parts subtotal</td><td style="padding:4px 12px;text-align:right">${snap.get('parts_subtotal',0):.2f}</td></tr>
          <tr><td style="padding:4px 12px">Sales tax</td><td style="padding:4px 12px;text-align:right">${snap.get('sales_tax',0):.2f}</td></tr>
          <tr><td style="padding:4px 12px">Markup</td><td style="padding:4px 12px;text-align:right">${snap.get('markup',0):.2f}</td></tr>
          <tr><td style="padding:4px 12px">Labor</td><td style="padding:4px 12px;text-align:right">${snap.get('labor',0):.2f}</td></tr>
          <tr><td style="padding:4px 12px">Merchant fees</td><td style="padding:4px 12px;text-align:right">${snap.get('merchant_fees',0):.2f}</td></tr>
          <tr style="border-top:2px solid #0F172A"><td style="padding:8px 12px;font-weight:700">Total</td><td style="padding:8px 12px;text-align:right;font-weight:700">${snap.get('estimate_total',0):.2f}</td></tr>
        </tbody>
      </table>
      <p style="font-size:12px;color:#64748B;margin-top:16px">This estimate is valid for 30 days.</p>
    </div>
    """.strip()

    # Send via existing Resend wrapper. Import lazily so this module
    # imports even if the wrapper is unavailable in a test env.
    delivered = False
    delivery_error: Optional[str] = None
    try:
        from services.email_client import send_email as _send_email  # type: ignore
        await _send_email(
            to=to_email, subject=body.subject, html=html,
            tenant_id=tid, template="repair_quote_email",
        )
        delivered = True
    except Exception as e:  # pragma: no cover — external service
        delivery_error = str(e)
        logger.warning(f"[repair-calc] email send failed: {e}")

    # Persist to communications_log so the customer's timeline shows it.
    log_id = new_id()
    quote_id = new_id()
    await db.communications_log.insert_one({
        "id": log_id,
        "tenant_id": tid,
        "created_at": now_iso(),
        "created_by_user_id": user.get("id"),
        "channel": "email",
        "direction": "outbound",
        "to": to_email,
        "subject": body.subject,
        "trigger_entity": {
            "kind": "repair_quote",
            "id": quote_id,
        },
        "customer_id": body.customer_id,
        "template": "repair_quote_email",
        "delivered": delivered,
        "delivery_error": delivery_error,
    })

    # Save the quote itself for admin review later.
    await db.repair_calculator_quotes.insert_one({
        "id": quote_id,
        "tenant_id": tid,
        "created_at": now_iso(),
        "created_by_user_id": user.get("id"),
        "customer_id": body.customer_id,
        "ad_hoc_email": body.ad_hoc_email,
        "recipient": to_email,
        "subject": body.subject,
        "note": body.note,
        "quote_snapshot": snap,
        "communications_log_id": log_id,
    })

    return {
        "ok": True,
        "delivered": delivered,
        "delivery_error": delivery_error,
        "quote_id": quote_id,
        "communications_log_id": log_id,
    }
