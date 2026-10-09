"""Phase 53a · Feb-2026 — Editable EBIT computation service.

Business definition
-------------------
    EBIT = Revenue − COGS − OpEx − Depreciation

Data sources (all scoped by ``tenant_id`` + date range):

* **Revenue** — ``db.quotes`` (invoice docs). Two bases:
    - ``cash`` (default):  ``payment_status == "paid"``,
      bucketed on ``paid_at`` (fallback ``created_at``).
    - ``accrual``:  ``status ∈ {paid, partial, sent, overdue}``,
      bucketed on ``created_at``.
  Revenue amount = ``quote.total`` when present, else
  ``Σ (qty × retail_price_snapshot)`` over the line items so
  invoices missing the header total still reconcile.

* **COGS** — ``Σ (qty × wholesale_price_snapshot)`` over the SAME
  invoice line items counted in Revenue. This matches the existing
  ``routers/profit_report`` definition so the two reports reconcile.

* **Depreciation** — non-voided ``db.checks`` rows whose effective
  category (LLM override in ``db.expense_categories`` first, else
  ``checks.category``, lowercased + stripped) is in
  ``DEPRECIATION_CATEGORIES``.

* **OpEx** — all remaining non-voided ``db.checks`` in the range.
  That INCLUDES payroll checks (wages are the biggest slice of
  OpEx for a service company). A payroll-only sub-total is emitted
  in ``breakdown.opex_payroll`` so admins can see the split.

* **Wages-by-role diagnostic** — an ``INFO``-only breakdown
  computed from ``db.time_entries × db.users.hourly_rate``, keyed
  by ``users.role``. Purely diagnostic — NOT added into EBIT.

All amounts are USD floats rounded to 2 dp.

Adjustments vs. Overrides (per locked pick 5C)
----------------------------------------------
Each of ``{revenue, cogs, opex, depreciation}`` has:

* ``line_adjustments[k]`` — additive delta (can be positive or
  negative). Applied on top of the live-computed value.
* ``line_overrides[k]`` — absolute override. When non-null, it
  REPLACES the computed+adjusted value entirely.

Effective value  = override if override is not None else
                    (live + adjustment).

EBIT is recomputed from the effective values so a single override
propagates cleanly.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


DEPRECIATION_CATEGORIES = frozenset({"depreciation", "amortization"})
PAYROLL_CATEGORIES = frozenset({"payroll", "wages", "salary", "salaries"})

_ELIGIBLE_ACCRUAL_STATUSES = ["paid", "partial", "sent", "overdue"]


# ═══════════════════════════════════════════════════════════════════
# Range resolution
# ═══════════════════════════════════════════════════════════════════
def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _month_end(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def resolve_range(
    range_kind: str,
    range_from: Optional[str],
    range_to: Optional[str],
) -> Tuple[str, str]:
    """Return (from, to) as ISO YYYY-MM-DD strings.

    ``range_kind`` accepts the classic ``profit_report`` keys AND
    the Phase 53a additions ``monthly`` / ``quarterly`` (which
    behave like ``this_month`` / ``qtd`` when from/to are absent,
    OR honor the explicit from/to when provided).
    """
    today = datetime.now(timezone.utc).date()
    kind = (range_kind or "").lower().strip()

    if kind == "this_month" or (kind == "monthly" and not range_from):
        start = _month_start(today)
        end = today
    elif kind == "last_month":
        first = _month_start(today)
        end = first - timedelta(days=1)
        start = _month_start(end)
    elif kind == "qtd" or (kind == "quarterly" and not range_from):
        qm = ((today.month - 1) // 3) * 3 + 1
        start = date(today.year, qm, 1)
        end = today
    elif kind == "ytd":
        start = date(today.year, 1, 1)
        end = today
    elif kind in ("custom", "monthly", "quarterly"):
        if not range_from or not range_to:
            raise ValueError(
                f"range_kind={kind} requires explicit from/to")
        try:
            start = date.fromisoformat(range_from)
            end = date.fromisoformat(range_to)
        except ValueError as e:
            raise ValueError("invalid_date_format") from e
        if end < start:
            raise ValueError("to_before_from")
        if (end - start).days > 366:
            raise ValueError("range_too_large")
    else:
        raise ValueError(f"invalid_range_kind: {range_kind!r}")

    return start.isoformat(), end.isoformat()


def _iso_lo(d: str) -> str:
    return f"{d}T00:00:00+00:00"


def _iso_hi(d: str) -> str:
    return f"{d}T23:59:59.999999+00:00"


def _to_float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _line_rev_cogs(li: Dict[str, Any]) -> Tuple[float, float]:
    qty = _to_float(li.get("quantity"))
    retail = li.get("retail_price_snapshot")
    if retail is None:
        retail = li.get("unit_price")
    rev = qty * _to_float(retail)
    cogs = qty * _to_float(li.get("wholesale_price_snapshot"))
    return rev, cogs


# ═══════════════════════════════════════════════════════════════════
# Compute
# ═══════════════════════════════════════════════════════════════════
async def _load_invoices(
    db, tenant_id: str, range_from: str, range_to: str, revenue_basis: str,
) -> List[Dict[str, Any]]:
    if revenue_basis == "cash":
        q = {
            "tenant_id": tenant_id,
            "doc_type": "invoice",
            "payment_status": "paid",
            "paid_at": {"$gte": _iso_lo(range_from), "$lte": _iso_hi(range_to)},
        }
    else:  # accrual
        q = {
            "tenant_id": tenant_id,
            "doc_type": "invoice",
            "status": {"$in": _ELIGIBLE_ACCRUAL_STATUSES},
            "created_at": {"$gte": _iso_lo(range_from), "$lte": _iso_hi(range_to)},
        }
    return await db.quotes.find(
        q,
        {"_id": 0, "id": 1, "total": 1, "line_items": 1,
          "created_at": 1, "paid_at": 1},
    ).to_list(20000)


async def _effective_check_category_map(
    db, tenant_id: str,
) -> Dict[str, str]:
    """checks.id → normalized effective category via LLM override.
    Falls back to raw ``checks.category`` when no override exists."""
    m: Dict[str, str] = {}
    cur = db.expense_categories.find(
        {"tenant_id": tenant_id, "source": "check"},
        {"_id": 0, "transaction_id": 1, "category": 1},
    )
    async for c in cur:
        cat = (c.get("category") or "").strip().lower()
        if cat:
            m[c["transaction_id"]] = cat
    return m


async def _load_checks(
    db, tenant_id: str, range_from: str, range_to: str,
) -> List[Dict[str, Any]]:
    # ``checks.date`` may be a plain YYYY-MM-DD string OR full ISO.
    # We over-fetch by tenant + non-voided and filter in Python
    # because sortable string comparison against YYYY-MM-DD is safe
    # in both storage styles (existing cfo.py does the same).
    rows = await db.checks.find(
        {"tenant_id": tenant_id, "voided_at": None},
        {"_id": 0, "id": 1, "amount": 1, "date": 1, "category": 1},
    ).to_list(50000)
    lo, hi = range_from, range_to
    out = []
    for r in rows:
        d = (r.get("date") or "")[:10]
        if not d:
            continue
        if lo <= d <= hi:
            out.append(r)
    return out


async def _wages_by_role(
    db, tenant_id: str, range_from: str, range_to: str,
) -> Dict[str, Any]:
    """Diagnostic-only breakdown from db.time_entries × users.hourly_rate.
    Aggregated by ``users.role``. Never added into EBIT."""
    lo, hi = range_from, range_to
    entries = await db.time_entries.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "user_id": 1, "duration_minutes": 1, "date": 1,
          "started_at": 1},
    ).to_list(50000)
    per_user: Dict[str, float] = {}
    for e in entries:
        d = (e.get("date") or (e.get("started_at") or "")[:10])[:10]
        if not d or not (lo <= d <= hi):
            continue
        hrs = _to_float(e.get("duration_minutes")) / 60.0
        uid = e.get("user_id") or ""
        if not uid:
            continue
        per_user[uid] = per_user.get(uid, 0.0) + hrs

    if not per_user:
        return {"by_role": [], "total_hours": 0.0, "total_wages": 0.0}

    users = await db.users.find(
        {"id": {"$in": list(per_user.keys())}},
        {"_id": 0, "id": 1, "role": 1, "hourly_rate": 1},
    ).to_list(500)
    umap = {u["id"]: u for u in users}
    by_role: Dict[str, Dict[str, float]] = {}
    total_hours = total_wages = 0.0
    for uid, hrs in per_user.items():
        u = umap.get(uid) or {}
        role = (u.get("role") or "unknown").lower()
        rate = _to_float(u.get("hourly_rate"))
        wage = hrs * rate
        b = by_role.setdefault(role, {"hours": 0.0, "wages": 0.0})
        b["hours"] += hrs
        b["wages"] += wage
        total_hours += hrs
        total_wages += wage
    return {
        "by_role": [
            {"role": k, "hours": round(v["hours"], 2),
              "wages": round(v["wages"], 2)}
            for k, v in sorted(by_role.items(), key=lambda kv: -kv[1]["wages"])
        ],
        "total_hours": round(total_hours, 2),
        "total_wages": round(total_wages, 2),
    }


async def compute_ebit(
    db,
    tenant_id: str,
    range_from: str,
    range_to: str,
    revenue_basis: str = "cash",
) -> Dict[str, Any]:
    """Return the LIVE (unadjusted) EBIT snapshot dict.

    Shape:
        {
          "range_from", "range_to", "revenue_basis",
          "revenue", "cogs", "opex", "depreciation", "ebit",
          "breakdown": {
            "invoice_count", "line_count",
            "opex_payroll", "opex_other",
            "opex_by_category": [{"category", "amount"}, ...],
            "depreciation_by_category": [{"category", "amount"}, ...],
            "wages_by_role": {...},
          },
        }
    """
    if revenue_basis not in ("cash", "accrual"):
        raise ValueError("revenue_basis must be 'cash' or 'accrual'")

    invoices = await _load_invoices(
        db, tenant_id, range_from, range_to, revenue_basis)

    revenue = cogs = 0.0
    line_count = 0
    for inv in invoices:
        header_total = _to_float(inv.get("total"))
        line_rev = 0.0
        line_cogs_sum = 0.0
        for li in (inv.get("line_items") or []):
            r, c = _line_rev_cogs(li)
            line_rev += r
            line_cogs_sum += c
            line_count += 1
        # Prefer the header total when present (matches payments UX);
        # otherwise fall back to per-line revenue.
        revenue += header_total if header_total > 0 else line_rev
        cogs += line_cogs_sum

    cat_override = await _effective_check_category_map(db, tenant_id)
    checks = await _load_checks(db, tenant_id, range_from, range_to)

    depreciation = 0.0
    opex = 0.0
    opex_payroll = 0.0
    opex_other = 0.0
    opex_by_cat: Dict[str, float] = {}
    dep_by_cat: Dict[str, float] = {}

    for ch in checks:
        amt = _to_float(ch.get("amount"))
        raw_cat = (cat_override.get(ch.get("id"))
                    or (ch.get("category") or "other"))
        cat = (raw_cat or "other").strip().lower() or "other"
        if cat in DEPRECIATION_CATEGORIES:
            depreciation += amt
            dep_by_cat[cat] = dep_by_cat.get(cat, 0.0) + amt
        else:
            opex += amt
            opex_by_cat[cat] = opex_by_cat.get(cat, 0.0) + amt
            if cat in PAYROLL_CATEGORIES:
                opex_payroll += amt
            else:
                opex_other += amt

    wages_by_role = await _wages_by_role(
        db, tenant_id, range_from, range_to)

    # Phase 10 · Feb-2026 — labor cost from technician pay rates.
    # Pulls per-tech hours × hourly_rate + pool_jobs_completed ×
    # per_pool_rate via the shared ``services.labor_cost`` helper
    # (same source the ``/reports/labor-cost`` endpoint reads).
    # Phase 10 ADDS the field to the response; Phase 11 will
    # subtract it from the EBIT bottom line (and add recurring
    # labor cost on top). Non-fatal — if the compute fails or no
    # techs have rates set, labor_cost falls back to 0.0 so EBIT
    # stays green.
    labor_cost_amount: float = 0.0
    labor_cost_breakdown: Dict[str, Any] = {
        "by_tech": [],
        "totals":  {"hours_worked": 0.0, "hourly_cost": 0.0,
                    "pool_jobs_completed": 0, "per_pool_cost": 0.0,
                    "total_labor_cost": 0.0},
        "range":   {"start": range_from, "end": range_to},
    }
    try:
        from services.labor_cost import compute_labor_cost
        labor_cost_breakdown = await compute_labor_cost(
            tenant_id, range_from, range_to, db=db)
        labor_cost_amount = float(
            (labor_cost_breakdown.get("totals") or {}).get(
                "total_labor_cost") or 0.0)
    except Exception as _labor_exc:                              # noqa: BLE001
        # Keep EBIT green even if the Phase 10 labor compute throws.
        # Record the exception on the breakdown so operators can
        # grep it from the admin UI; the top-level number stays 0.
        labor_cost_breakdown["error"] = str(_labor_exc)

    # Phase 11 · Feb-2026 — recurring labor cost. Layers salaried /
    # contracted / fixed-monthly cost on top of the Phase 10 hourly
    # + per-pool number. Prorates each ``recurring_labor_costs``
    # entry against the EBIT window using the 30.4375-days average
    # month constant (brief spec). Non-fatal — compute errors keep
    # EBIT green with a 0 recurring contribution.
    recurring_labor_cost_amount: float = 0.0
    recurring_labor_breakdown: Dict[str, Any] = {
        "by_entry": [],
        "total":    0.0,
        "range":    {"start": range_from, "end": range_to},
    }
    try:
        from services.recurring_labor_cost import compute_recurring_labor_cost
        recurring_labor_breakdown = await compute_recurring_labor_cost(
            tenant_id, range_from, range_to, db=db)
        recurring_labor_cost_amount = float(
            recurring_labor_breakdown.get("total") or 0.0)
    except Exception as _rec_exc:                                # noqa: BLE001
        recurring_labor_breakdown["error"] = str(_rec_exc)

    labor_cost_total_amount = labor_cost_amount + recurring_labor_cost_amount

    ebit = revenue - cogs - opex - depreciation - labor_cost_total_amount
    return {
        "range_from": range_from,
        "range_to": range_to,
        "revenue_basis": revenue_basis,
        "revenue": round(revenue, 2),
        "cogs": round(cogs, 2),
        "opex": round(opex, 2),
        "depreciation": round(depreciation, 2),
        "ebit": round(ebit, 2),
        # Phase 10 · Feb-2026 — labor cost from technician pay rates.
        # Top-level number for easy consumption; detailed per-tech
        # breakdown lives on ``breakdown.labor_cost_breakdown``.
        # Phase 11 wires this into the EBIT bottom line + layers in
        # recurring labor costs.
        "labor_cost": round(labor_cost_amount, 2),
        # Phase 11 · Feb-2026 — recurring labor (salaried /
        # contracted / fixed-monthly). Prorates each entry against
        # the EBIT window.
        "recurring_labor_cost": round(recurring_labor_cost_amount, 2),
        # Phase 11 · Feb-2026 — combined labor (Phase 10 hourly +
        # per-pool + Phase 11 recurring). This is the value
        # subtracted from EBIT. Legacy ``labor_cost`` field above
        # stays as the Phase 10 number only for backwards-compat
        # with any pre-Phase-11 downstream reader.
        "labor_cost_total": round(labor_cost_total_amount, 2),
        "breakdown": {
            "invoice_count": len(invoices),
            "line_count": line_count,
            "opex_payroll": round(opex_payroll, 2),
            "opex_other": round(opex_other, 2),
            "opex_by_category": [
                {"category": k, "amount": round(v, 2)}
                for k, v in sorted(opex_by_cat.items(), key=lambda kv: -kv[1])
            ],
            "depreciation_by_category": [
                {"category": k, "amount": round(v, 2)}
                for k, v in sorted(dep_by_cat.items(), key=lambda kv: -kv[1])
            ],
            "wages_by_role": wages_by_role,
            # Phase 10 · Feb-2026 — full per-tech breakdown.
            "labor_cost_breakdown": labor_cost_breakdown,
            # Phase 11 · Feb-2026 — recurring labor cost breakdown
            # (by_entry + total + range), prorated into the window.
            "recurring_labor_breakdown": recurring_labor_breakdown,
        },
    }


# ═══════════════════════════════════════════════════════════════════
# Adjustments + overrides application
# ═══════════════════════════════════════════════════════════════════
_LINE_KEYS = ("revenue", "cogs", "opex", "depreciation")


def blank_adjustments() -> Dict[str, float]:
    return {k: 0.0 for k in _LINE_KEYS}


def blank_overrides() -> Dict[str, Optional[float]]:
    return {k: None for k in _LINE_KEYS}


def _sanitize_adjustments(raw: Optional[Dict[str, Any]]) -> Dict[str, float]:
    out = blank_adjustments()
    if not isinstance(raw, dict):
        return out
    for k in _LINE_KEYS:
        if k in raw and raw[k] is not None:
            try:
                out[k] = float(raw[k])
            except (TypeError, ValueError):
                pass
    return out


def _sanitize_overrides(
    raw: Optional[Dict[str, Any]],
) -> Dict[str, Optional[float]]:
    out = blank_overrides()
    if not isinstance(raw, dict):
        return out
    for k in _LINE_KEYS:
        if k in raw:
            v = raw[k]
            if v is None:
                out[k] = None
            else:
                try:
                    out[k] = float(v)
                except (TypeError, ValueError):
                    pass
    return out


def apply_edits(
    live: Dict[str, Any],
    line_adjustments: Optional[Dict[str, Any]],
    line_overrides: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return a NEW dict with the same shape as ``live`` but with
    ``revenue/cogs/opex/depreciation/ebit`` reflecting the applied
    adjustments + overrides. The original ``live`` dict is not
    mutated; the caller gets a clean immutable-snapshot payload."""
    adj = _sanitize_adjustments(line_adjustments)
    ovr = _sanitize_overrides(line_overrides)

    effective: Dict[str, float] = {}
    for k in _LINE_KEYS:
        base = _to_float(live.get(k))
        if ovr[k] is not None:
            effective[k] = float(ovr[k])
        else:
            effective[k] = base + adj[k]

    ebit = (effective["revenue"] - effective["cogs"]
             - effective["opex"] - effective["depreciation"])

    out = dict(live)
    out.update({k: round(effective[k], 2) for k in _LINE_KEYS})
    out["ebit"] = round(ebit, 2)
    out["line_adjustments"] = adj
    out["line_overrides"] = ovr
    return out
