"""Phase 47 · Budgeting Suite.

Endpoints (prefix `/api/budgets`):

    GET  /api/budgets/{year}                       — read (admin/super_admin)
    PUT  /api/budgets/{year}                       — upsert
    POST /api/budgets/{year}/copy-from/{prev}      — clone prior year × scale
    GET  /api/budgets/{year}/dashboard             — revenue-target dashboard
    GET  /api/budgets/current/dashboard            — same, using today's year
    GET  /api/budgets/health-summary               — compact widget payload for mobile home
    POST /api/budgets/{year}/wizard/apply          — "Know Your Numbers" wizard

Also (job costing, mounted here so budget context lives together):
    GET  /api/jobs/{jid}/costing                   — live per-job costing snapshot

Storage model (`budgets` collection):
    { _id (mongo), id (uuid), tenant_id, year (int), currency: "USD",
      monthly_targets: { "YYYY-MM": {
          revenue_cents, labor_cents, equipment_cents, materials_cents,
          overhead_cents, insurance_cents, fuel_cents,
          target_net_profit_pct } * 12 },
      labor_burden_pct, equipment_hourly_cents,
      computed: { billable_hourly_cents, markup_pct, break_even_cents },
      wizard_inputs, updated_at, updated_by }

All money persisted as INTEGER cents (long). Percentages as floats
(`0..100`).  Only paid invoices count toward actual revenue.
"""
from __future__ import annotations

from datetime import datetime, timezone, date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter(tags=["budget"])

# Fixed v1 expense categories.
EXPENSE_CATEGORIES = ["labor", "equipment", "materials", "overhead", "insurance", "fuel"]
DEFAULT_MARKUP_PCT = 40.0
BILLABLE_HOURS_PER_YEAR = 1600  # ~2000 raw − 20% non-billable


def _empty_month(revenue_cents: int = 0) -> Dict[str, int]:
    return {
        "revenue_cents": int(revenue_cents),
        "labor_cents": 0,
        "equipment_cents": 0,
        "materials_cents": 0,
        "overhead_cents": 0,
        "insurance_cents": 0,
        "fuel_cents": 0,
        "target_net_profit_pct": 15.0,
    }


def _months_for(year: int) -> list[str]:
    return [f"{year:04d}-{m:02d}" for m in range(1, 13)]


def _sum_cents(monthly: Dict[str, Dict[str, Any]], key: str) -> int:
    return int(sum(int((m or {}).get(key) or 0) for m in monthly.values()))


def _recompute(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Populate `computed.*` from monthly totals + rates.

    computed:
      billable_hourly_cents = (total_costs + target_profit) / billable_hours
      markup_pct            = (total_revenue - total_costs) / total_costs
                              expressed as percentage, floored at 15%
      break_even_cents      = total_costs
    """
    monthly = doc.get("monthly_targets") or {}
    total_revenue = _sum_cents(monthly, "revenue_cents")
    total_costs = 0
    for cat in EXPENSE_CATEGORIES:
        total_costs += _sum_cents(monthly, f"{cat}_cents")
    labor_burden_pct = float(doc.get("labor_burden_pct") or 25.0)
    labor_total = _sum_cents(monthly, "labor_cents")
    burden = int(round(labor_total * labor_burden_pct / 100.0))
    total_costs += burden
    target_profit_pct = 15.0
    if monthly:
        # avg target profit % across months
        target_profit_pct = round(
            sum(float((m or {}).get("target_net_profit_pct") or 0)
                for m in monthly.values()) / max(1, len(monthly)),
            2,
        )
    target_profit = int(round(total_costs * target_profit_pct / 100.0))
    billable_hourly = 0
    if BILLABLE_HOURS_PER_YEAR > 0:
        billable_hourly = int(round((total_costs + target_profit) / BILLABLE_HOURS_PER_YEAR))
    markup = 0.0
    if total_costs > 0:
        markup = round(((total_revenue - total_costs) / total_costs) * 100.0, 2)
    if markup < 15.0:
        markup = 15.0
    doc["computed"] = {
        "billable_hourly_cents": billable_hourly,
        "markup_pct": markup,
        "break_even_cents": total_costs,
        "labor_burden_cents": burden,
        "target_profit_cents": target_profit,
        "target_profit_pct": target_profit_pct,
        "total_revenue_cents": total_revenue,
        "total_costs_cents": total_costs,
    }
    return doc


# ── Pydantic ─────────────────────────────────────────────────────────
class BudgetIn(BaseModel):
    monthly_targets: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    labor_burden_pct: float = 25.0
    equipment_hourly_cents: int = 0
    wizard_inputs: Optional[Dict[str, Any]] = None


class WizardApplyBody(BaseModel):
    annual_net_profit_cents: Optional[int] = None
    annual_net_profit_pct: Optional[float] = None
    annual_operating_expenses_cents: int
    seasonal_weighting: bool = False


# ── Read ────────────────────────────────────────────────────────────
# NOTE: The literal-path routes (`/budgets/current/*`, `/budgets/health-summary`)
# MUST be declared BEFORE `/budgets/{year}` — FastAPI resolves in decorator
# order and `year: int` will 422 on non-numeric segments like `health-summary`.


@router.get("/budgets/current/markup")
async def current_markup_top(user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    """Estimator + job-costing consumers use this to fetch the active markup."""
    markup, from_budget = await get_current_markup(tenant["id"])
    return {
        "markup_pct": markup,
        "source": "budget" if from_budget else "default",
        "year": datetime.now(timezone.utc).year,
    }


@router.get("/budgets/current/dashboard")
async def current_dashboard_top(user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    year = datetime.now(timezone.utc).year
    return await _dashboard_payload(tenant["id"], year)


@router.get("/budgets/health-summary")
async def health_summary_top(user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    """Compact widget payload for the mobile admin home."""
    year = datetime.now(timezone.utc).year
    dash = await _dashboard_payload(tenant["id"], year)
    return {
        "year": year,
        "this_month": dash["this_month"],
        "ytd": dash["ytd"],
        "annual": dash["annual"],
        "pace": dash["ytd"]["pace"],
        "has_budget": dash["has_budget"],
    }


@router.get("/budgets/{year}")
async def get_budget(year: int,
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    doc = await db.budgets.find_one({"tenant_id": tenant["id"], "year": year}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "no_budget_for_year")
    return doc


@router.put("/budgets/{year}")
async def put_budget(year: int, body: BudgetIn,
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    if year < 2020 or year > 2100:
        raise HTTPException(422, "invalid year")
    months = _months_for(year)
    # Normalize monthly_targets: enforce 12 keys, integer cents, sensible defaults.
    normalized: Dict[str, Dict[str, Any]] = {}
    for m in months:
        raw = body.monthly_targets.get(m) or {}
        row = _empty_month()
        for k in row.keys():
            v = raw.get(k)
            if v is None:
                continue
            if k == "target_net_profit_pct":
                try:
                    row[k] = float(v)
                except (TypeError, ValueError):
                    pass
            else:
                try:
                    row[k] = int(v)
                except (TypeError, ValueError):
                    pass
        normalized[m] = row
    doc = {
        "tenant_id": tenant["id"],
        "year": year,
        "currency": "USD",
        "monthly_targets": normalized,
        "labor_burden_pct": float(body.labor_burden_pct or 0),
        "equipment_hourly_cents": int(body.equipment_hourly_cents or 0),
        "wizard_inputs": body.wizard_inputs,
        "updated_at": now_iso(),
        "updated_by": user["id"],
    }
    _recompute(doc)
    existing = await db.budgets.find_one({"tenant_id": tenant["id"], "year": year}, {"_id": 0, "id": 1, "created_at": 1})
    if existing:
        doc["id"] = existing["id"]
        doc["created_at"] = existing.get("created_at") or now_iso()
        await db.budgets.update_one(
            {"tenant_id": tenant["id"], "year": year},
            {"$set": doc},
        )
    else:
        doc["id"] = new_id()
        doc["created_at"] = now_iso()
        await db.budgets.insert_one(dict(doc))
    # Trigger cascade — recalculate open estimates for this year.
    try:
        await _recalc_open_estimates(tenant["id"], doc["computed"]["markup_pct"])
    except Exception as e:
        logger.warning(f"estimate recalc skipped: {e}")
    return doc


@router.post("/budgets/{year}/copy-from/{prev_year}")
async def copy_budget(year: int, prev_year: int,
                      scale: float = Query(1.0, ge=0.1, le=10.0),
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    prev = await db.budgets.find_one({"tenant_id": tenant["id"], "year": prev_year}, {"_id": 0})
    if not prev:
        raise HTTPException(404, "prev_year_missing")
    new_months: Dict[str, Dict[str, Any]] = {}
    for m in _months_for(year):
        prev_month_key = f"{prev_year:04d}-{m.split('-')[1]}"
        src = (prev.get("monthly_targets") or {}).get(prev_month_key) or _empty_month()
        row = dict(src)
        for k in list(row.keys()):
            if k.endswith("_cents"):
                row[k] = int(round(int(row[k] or 0) * scale))
        new_months[m] = row
    body = BudgetIn(
        monthly_targets=new_months,
        labor_burden_pct=float(prev.get("labor_burden_pct") or 25.0),
        equipment_hourly_cents=int(prev.get("equipment_hourly_cents") or 0),
        wizard_inputs=prev.get("wizard_inputs"),
    )
    return await put_budget(year, body, user, tenant)


# ── Dashboard (actuals) ─────────────────────────────────────────────
async def _actuals_by_month(tenant_id: str, year: int) -> Dict[str, int]:
    """Sum of `total` from paid invoices grouped by paid_at month.
    Falls back to `created_at` when `paid_at` is missing."""
    out: Dict[str, int] = {m: 0 for m in _months_for(year)}
    cur = db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice", "payment_status": "paid"},
        {"_id": 0, "total": 1, "paid_at": 1, "created_at": 1},
    )
    async for q in cur:
        ts = q.get("paid_at") or q.get("created_at") or ""
        m = ts[:7] if isinstance(ts, str) else ""
        if m in out:
            try:
                out[m] += int(round(float(q.get("total") or 0) * 100))
            except (TypeError, ValueError):
                pass
    return out


def _pace_status(ytd_actual: int, ytd_target: int) -> str:
    if ytd_target <= 0:
        return "no_target"
    ratio = ytd_actual / ytd_target
    if ratio >= 1.02:
        return "ahead"
    if ratio >= 0.90:
        return "on_track"
    return "behind"


async def _dashboard_payload(tenant_id: str, year: int) -> Dict[str, Any]:
    doc = await db.budgets.find_one({"tenant_id": tenant_id, "year": year}, {"_id": 0})
    monthly = (doc or {}).get("monthly_targets") or {}
    actuals = await _actuals_by_month(tenant_id, year)
    now = datetime.now(timezone.utc).date()
    current_month = f"{now.year:04d}-{now.month:02d}" if now.year == year else _months_for(year)[0]
    months = _months_for(year)
    rows = []
    total_target = 0
    total_actual = 0
    ytd_target = 0
    ytd_actual = 0
    for m in months:
        tgt = int((monthly.get(m) or {}).get("revenue_cents") or 0)
        act = int(actuals.get(m) or 0)
        rows.append({"month": m, "target_cents": tgt, "actual_cents": act})
        total_target += tgt
        total_actual += act
        if m <= current_month:
            ytd_target += tgt
            ytd_actual += act
    curr_row = next((r for r in rows if r["month"] == current_month), rows[0])
    # Net profit YTD estimate — very rough: actual revenue − target costs pro-rata YTD.
    total_costs_target = 0
    for m in months:
        if m > current_month:
            continue
        for cat in EXPENSE_CATEGORIES:
            total_costs_target += int((monthly.get(m) or {}).get(f"{cat}_cents") or 0)
    ytd_net_pct = 0.0
    if ytd_actual > 0:
        ytd_net_pct = round(((ytd_actual - total_costs_target) / ytd_actual) * 100, 2)
    return {
        "year": year,
        "has_budget": bool(doc),
        "this_month": {
            "month": current_month,
            "target_cents": curr_row["target_cents"],
            "actual_cents": curr_row["actual_cents"],
        },
        "ytd": {
            "target_cents": ytd_target,
            "actual_cents": ytd_actual,
            "pace": _pace_status(ytd_actual, ytd_target),
            "net_profit_pct": ytd_net_pct,
        },
        "annual": {
            "target_cents": total_target,
            "actual_cents": total_actual,
        },
        "months": rows,
        "computed": (doc or {}).get("computed"),
    }


@router.get("/budgets/{year}/dashboard")
async def budget_dashboard(year: int,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    return await _dashboard_payload(tenant["id"], year)


# NOTE: `/budgets/current/dashboard` and `/budgets/health-summary` are declared
# NEAR THE TOP of this file (before `/budgets/{year}`) to prevent FastAPI's
# `year: int` matcher from swallowing them. Do NOT re-add them here.


# ── Wizard ───────────────────────────────────────────────────────────
@router.post("/budgets/{year}/wizard/apply")
async def apply_wizard(year: int, body: WizardApplyBody,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    """Even-split (or seasonal) pre-fill for a 12-month budget from wizard inputs."""
    op_ex = int(body.annual_operating_expenses_cents or 0)
    if op_ex <= 0:
        raise HTTPException(422, "operating_expenses required")
    if body.annual_net_profit_cents is not None and body.annual_net_profit_cents > 0:
        target_profit = int(body.annual_net_profit_cents)
    elif body.annual_net_profit_pct is not None:
        # target profit = pct of (op_ex + target_profit) → target_profit = op_ex * pct / (1 - pct)
        p = max(0.0, min(90.0, float(body.annual_net_profit_pct))) / 100.0
        target_profit = int(round(op_ex * (p / max(1e-6, 1 - p))))
    else:
        raise HTTPException(422, "net_profit_cents or net_profit_pct required")
    required_revenue = op_ex + target_profit
    # Even split by default; simple seasonal weighting adds +20/-20% in summer/winter.
    weights = [1.0] * 12
    if body.seasonal_weighting:
        weights = [0.8, 0.8, 0.9, 1.0, 1.1, 1.2, 1.2, 1.2, 1.1, 1.0, 0.9, 0.8]
    total_w = sum(weights)
    monthly_targets: Dict[str, Dict[str, Any]] = {}
    # Rough per-category apportionment (spread op_ex evenly across 6 categories).
    per_cat_annual = op_ex // len(EXPENSE_CATEGORIES)
    for i, m in enumerate(_months_for(year)):
        w = weights[i] / total_w
        row = _empty_month()
        row["revenue_cents"] = int(round(required_revenue * w))
        for cat in EXPENSE_CATEGORIES:
            row[f"{cat}_cents"] = int(round(per_cat_annual * w))
        row["target_net_profit_pct"] = round(target_profit / required_revenue * 100, 2) if required_revenue else 15.0
        monthly_targets[m] = row
    body_in = BudgetIn(
        monthly_targets=monthly_targets,
        labor_burden_pct=25.0,
        equipment_hourly_cents=0,
        wizard_inputs={
            "annual_net_profit_cents": body.annual_net_profit_cents,
            "annual_net_profit_pct": body.annual_net_profit_pct,
            "annual_operating_expenses_cents": op_ex,
            "seasonal_weighting": body.seasonal_weighting,
            "computed": {
                "required_revenue_cents": required_revenue,
                "target_profit_cents": target_profit,
                "break_even_cents": op_ex,
            },
        },
    )
    return await put_budget(year, body_in, user, tenant)


# ── Estimate recalc ─────────────────────────────────────────────────
async def _recalc_open_estimates(tenant_id: str, markup_pct: float) -> int:
    """When budget saved, refresh markup_pct on all draft/sent estimates.
    Closed/accepted estimates are immutable. Returns number of docs updated
    across BOTH the estimator collection and the legacy estimates one."""
    now = now_iso()
    total = 0
    for coll in ("estimator_estimates", "estimates"):
        res = await db[coll].update_many(
            {"tenant_id": tenant_id, "status": {"$in": ["draft", "sent"]}},
            {"$set": {
                "budget_markup_pct": float(markup_pct),
                "budget_markup_applied_at": now,
            }},
        )
        total += int(res.modified_count or 0)
    return total


async def get_current_markup(tenant_id: str) -> tuple[float, bool]:
    """Return (markup_pct, from_budget). Falls back to default when no budget doc."""
    year = datetime.now(timezone.utc).year
    doc = await db.budgets.find_one({"tenant_id": tenant_id, "year": year}, {"_id": 0, "computed": 1})
    if doc and (doc.get("computed") or {}).get("markup_pct"):
        return float(doc["computed"]["markup_pct"]), True
    return DEFAULT_MARKUP_PCT, False


@router.get("/budgets/current/markup-legacy-shadow")
async def current_markup(user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    """DEPRECATED shadow route retained during Phase 47 refactor. Use
    `/budgets/current/markup` (declared near the top of this module)."""
    markup, from_budget = await get_current_markup(tenant["id"])
    return {
        "markup_pct": markup,
        "source": "budget" if from_budget else "default",
        "year": datetime.now(timezone.utc).year,
    }


# ── Job costing ──────────────────────────────────────────────────────
async def _time_entries_for_job(tenant_id: str, jid: str) -> list[dict]:
    # Reads workforce time-entries first (canonical), then falls back to any
    # collection that stores `job_id` — protects against schema drift.
    entries: list[dict] = []
    async for t in db.time_entries.find(
        {"tenant_id": tenant_id, "job_id": jid}, {"_id": 0}
    ):
        entries.append(t)
    if entries:
        return entries
    async for t in db.timesheets.find(
        {"tenant_id": tenant_id, "job_id": jid}, {"_id": 0}
    ):
        entries.append(t)
    return entries


def _minutes(entry: dict) -> int:
    if entry.get("duration_minutes") is not None:
        try:
            return int(entry["duration_minutes"])
        except (TypeError, ValueError):
            return 0
    ci, co = entry.get("clock_in_at"), entry.get("clock_out_at")
    if isinstance(ci, str) and isinstance(co, str):
        try:
            a = datetime.fromisoformat(ci.replace("Z", "+00:00"))
            b = datetime.fromisoformat(co.replace("Z", "+00:00"))
            return max(0, int((b - a).total_seconds() // 60))
        except Exception:
            return 0
    return 0


@router.get("/jobs/{jid}/costing")
async def job_costing(jid: str,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    """Live job costing snapshot. Reads estimate baseline + actual times/materials."""
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    # Baseline — try attached estimate first.
    est = None
    if job.get("estimate_id"):
        est = await db.estimates.find_one(
            {"id": job["estimate_id"], "tenant_id": tenant["id"]}, {"_id": 0}
        )
    baseline = {
        "labor_cents": int((est or {}).get("labor_cost_cents") or 0),
        "materials_cents": int((est or {}).get("materials_cost_cents") or 0),
        "equipment_cents": int((est or {}).get("equipment_cost_cents") or 0),
        "revenue_cents": int(round(float((est or {}).get("total") or job.get("price") or 0) * 100)),
    }
    # Fallback baseline from `price`.
    if not baseline["revenue_cents"] and job.get("price"):
        baseline["revenue_cents"] = int(round(float(job["price"]) * 100))

    # Actual labor from time entries.
    entries = await _time_entries_for_job(tenant["id"], jid)
    total_minutes = sum(_minutes(e) for e in entries)
    labor_hourly_cents = int((est or {}).get("labor_hourly_cents") or 4000)  # $40/hr default
    actual_labor_cents = int(round(total_minutes / 60 * labor_hourly_cents))
    # Actual materials from service_report chemicals_added.
    rep = await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "job_id": jid}, {"_id": 0, "chemicals_added": 1}
    )
    chem_costs = {}
    async for c in db.chemical_costs.find({"tenant_id": tenant["id"]}, {"_id": 0}):
        chem_costs[str(c.get("slug") or c.get("name") or "").lower()] = int(c.get("unit_cost_cents") or 0)
    actual_materials_cents = 0
    for row in ((rep or {}).get("chemicals_added") or []):
        slug = str(row.get("slug") or row.get("chemical") or row.get("name") or "").lower()
        qty = float(row.get("quantity") or row.get("amount") or 0)
        unit_cost = chem_costs.get(slug, 500)  # default $5 if uncatalogued
        actual_materials_cents += int(round(qty * unit_cost))
    # Actual equipment from inventory reservations (rough: qty * cost).
    actual_equipment_cents = 0
    async for r in db.inventory_reservations.find(
        {"tenant_id": tenant["id"], "job_id": jid}, {"_id": 0, "qty": 1, "cost_cents": 1}
    ):
        actual_equipment_cents += int(r.get("qty") or 0) * int(r.get("cost_cents") or 0)

    actual = {
        "labor_cents": actual_labor_cents,
        "materials_cents": actual_materials_cents,
        "equipment_cents": actual_equipment_cents,
    }
    def pct(a: int, b: int) -> float:
        return round((a / b) * 100, 1) if b > 0 else 0.0
    progress = {
        "labor_pct":     pct(actual["labor_cents"],     baseline["labor_cents"]),
        "materials_pct": pct(actual["materials_cents"], baseline["materials_cents"]),
        "equipment_pct": pct(actual["equipment_cents"], baseline["equipment_cents"]),
    }
    estimated_costs = baseline["labor_cents"] + baseline["materials_cents"] + baseline["equipment_cents"]
    actual_costs = actual["labor_cents"] + actual["materials_cents"] + actual["equipment_cents"]
    estimated_profit = baseline["revenue_cents"] - estimated_costs
    actual_profit = baseline["revenue_cents"] - actual_costs
    estimated_margin_pct = round(estimated_profit / baseline["revenue_cents"] * 100, 2) if baseline["revenue_cents"] > 0 else 0.0
    actual_margin_pct = round(actual_profit / baseline["revenue_cents"] * 100, 2) if baseline["revenue_cents"] > 0 else 0.0
    return {
        "job_id": jid,
        "baseline": baseline,
        "actual": actual,
        "progress": progress,
        "estimated_net_profit_cents": estimated_profit,
        "actual_net_profit_cents": actual_profit,
        "estimated_margin_pct": estimated_margin_pct,
        "actual_margin_pct": actual_margin_pct,
        "time_entries_count": len(entries),
        "total_labor_minutes": total_minutes,
    }


# ── AI CFO context extension ─────────────────────────────────────────
async def build_budget_context(tenant_id: str) -> Dict[str, Any]:
    """Compact JSON blob the CFO Q&A includes in every prompt."""
    year = datetime.now(timezone.utc).year
    dash = await _dashboard_payload(tenant_id, year)
    doc = await db.budgets.find_one({"tenant_id": tenant_id, "year": year}, {"_id": 0})
    computed = (doc or {}).get("computed") or {}
    # Category totals YTD (target vs pro-rated).
    now = datetime.now(timezone.utc).date()
    current_month = f"{now.year:04d}-{now.month:02d}"
    monthly = (doc or {}).get("monthly_targets") or {}
    cat_targets_ytd = {c: 0 for c in EXPENSE_CATEGORIES}
    for m, row in monthly.items():
        if m > current_month:
            continue
        for c in EXPENSE_CATEGORIES:
            cat_targets_ytd[c] += int((row or {}).get(f"{c}_cents") or 0)
    return {
        "year": year,
        "has_budget": bool(doc),
        "annual_target_cents": dash["annual"]["target_cents"],
        "annual_actual_cents": dash["annual"]["actual_cents"],
        "ytd_target_cents": dash["ytd"]["target_cents"],
        "ytd_actual_cents": dash["ytd"]["actual_cents"],
        "pace": dash["ytd"]["pace"],
        "ytd_net_profit_pct": dash["ytd"]["net_profit_pct"],
        "current_month": dash["this_month"],
        "computed": {
            "markup_pct": computed.get("markup_pct"),
            "billable_hourly_cents": computed.get("billable_hourly_cents"),
            "break_even_cents": computed.get("break_even_cents"),
        },
        "expense_targets_ytd_cents": cat_targets_ytd,
    }
