"""Phase 32 · AI CFO backend spine.

Read-only aggregations over existing collections + LLM-powered
auto-categorization for uncategorized expenses. No new schemas beyond
three side-tables:

  • expense_categories  — index (tenant_id, transaction_id)
  • expense_anomalies   — index (tenant_id, detected_at)
  • cfo_llm_usage       — index (tenant_id, date)  (soft daily quota)

Discovery pass (Feb 15 2026) — this router adapts to what actually
exists in Mongo. See openapi.json + HANDOFF Phase 32 note for the full
picture. Sources wired here:

  Revenue in
    - quotes  where doc_type=="invoice" AND payment_status=="paid"
                → total, keyed by paid_at ISO string
    - warranty_contracts  → price_paid, keyed by start_date
  Expenses out
    - checks  → amount, keyed by date (excludes voided)
    - stock_movements outbound → COGS is mocked (items don't ship a
      cost field on this environment)
  Cash on hand
    - bank_accounts  → sum(current_balance) per tenant
  AR aging
    - master_invoices  → balance + due_date
  AP aging
    - no ap_bills collection → mocked with reason
  Payroll
    - time_entries has no rate field → labor spend is derived from
      checks with category "labor" once LLM categorizer has run.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger, EMERGENT_LLM_KEY
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter(prefix="/cfo")

# ─── Constants ────────────────────────────────────────────────────────
_EXPENSE_CATEGORIES = [
    "labor", "chemicals", "fuel", "equipment", "marketing",
    "insurance", "subscription", "tax", "other",
]
_LLM_BATCH_SIZE = 25
_LLM_MAX_OUTPUT_TOKENS = 4000
_LLM_DAILY_SOFT_QUOTA = 100
_MODEL = ("anthropic", "claude-sonnet-4-6")

# ─── Small helpers ────────────────────────────────────────────────────
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _parse_dt(v: Any) -> Optional[datetime]:
    """Accepts either a datetime or an ISO string. Returns UTC-aware or None."""
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        s = v.replace("Z", "+00:00")
        try:
            d = datetime.fromisoformat(s)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            # Fall back to date-only ISO
            try:
                d = datetime.fromisoformat(f"{s}T00:00:00+00:00")
                return d
            except ValueError:
                return None
    return None

def _to_float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0

def _period_bounds(period: str, start: Optional[str], end: Optional[str]) -> Tuple[datetime, datetime]:
    """Resolve MTD / QTD / YTD / custom into concrete UTC bounds."""
    now = _now_utc()
    if period == "custom":
        s = _parse_dt(start) or (now - timedelta(days=30))
        e = _parse_dt(end) or now
        return s, e
    y, m = now.year, now.month
    if period == "mtd":
        s = datetime(y, m, 1, tzinfo=timezone.utc)
    elif period == "qtd":
        qm = ((m - 1) // 3) * 3 + 1
        s = datetime(y, qm, 1, tzinfo=timezone.utc)
    else:  # ytd default
        s = datetime(y, 1, 1, tzinfo=timezone.utc)
    return s, now

def _bucket_age(days: int) -> str:
    if days <= 30: return "0_30"
    if days <= 60: return "31_60"
    if days <= 90: return "61_90"
    return "90_plus"

# ─── Aggregations ─────────────────────────────────────────────────────
async def _revenue(tenant_id: str, s: datetime, e: datetime) -> Dict[str, Any]:
    total = 0.0
    by_source: Dict[str, float] = {"paid_invoices": 0.0, "warranty_contracts": 0.0}

    cur = db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice", "payment_status": "paid"},
        {"_id": 0, "total": 1, "paid_at": 1, "created_at": 1},
    )
    async for q in cur:
        d = _parse_dt(q.get("paid_at")) or _parse_dt(q.get("created_at"))
        if not d or not (s <= d <= e):
            continue
        v = _to_float(q.get("total"))
        total += v; by_source["paid_invoices"] += v

    cur = db.warranty_contracts.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "price_paid": 1, "start_date": 1},
    )
    async for w in cur:
        d = _parse_dt(w.get("start_date"))
        if not d or not (s <= d <= e):
            continue
        v = _to_float(w.get("price_paid"))
        total += v; by_source["warranty_contracts"] += v

    return {
        "total": round(total, 2),
        "by_source": [{"source": k, "total": round(v, 2)}
                       for k, v in by_source.items()],
        "mocked": False,
    }

async def _expenses(tenant_id: str, s: datetime, e: datetime) -> Dict[str, Any]:
    total = 0.0
    by_cat: Dict[str, float] = {}
    # Prefer the LLM-derived category from expense_categories when present,
    # then fall back to `checks.category`, then "other". Keeps the
    # dashboard honest once the categorizer has run.
    cat_map: Dict[str, str] = {}
    async for c in db.expense_categories.find(
        {"tenant_id": tenant_id, "source": "check"},
        {"_id": 0, "transaction_id": 1, "category": 1},
    ):
        cat_map[c["transaction_id"]] = c["category"]

    cur = db.checks.find(
        {"tenant_id": tenant_id, "voided_at": None},
        {"_id": 0, "amount": 1, "date": 1, "category": 1, "id": 1},
    )
    async for ch in cur:
        d = _parse_dt(ch.get("date"))
        if not d or not (s <= d <= e):
            continue
        v = _to_float(ch.get("amount"))
        total += v
        cat = (cat_map.get(ch["id"])
               or (ch.get("category") or "other")).lower()
        by_cat[cat] = by_cat.get(cat, 0.0) + v

    return {
        "total": round(total, 2),
        "by_category": [{"category": k, "total": round(v, 2)}
                         for k, v in sorted(by_cat.items(),
                                            key=lambda kv: -kv[1])],
        "mocked": False,
    }

async def _cash_on_hand(tenant_id: str) -> Dict[str, Any]:
    total = 0.0
    n = 0
    async for b in db.bank_accounts.find({"tenant_id": tenant_id},
                                          {"_id": 0, "current_balance": 1}):
        total += _to_float(b.get("current_balance"))
        n += 1
    if n == 0:
        return {"value": 0.0, "mocked": True,
                "reason": "no bank_accounts wired for tenant"}
    return {"value": round(total, 2), "mocked": False}

async def _ar_aging(tenant_id: str) -> Dict[str, Any]:
    buckets = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}
    today = _now_utc().date()
    cur = db.master_invoices.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "balance": 1, "due_date": 1, "payment_status": 1},
    )
    async for inv in cur:
        bal = _to_float(inv.get("balance"))
        if bal <= 0:
            continue
        due = _parse_dt(inv.get("due_date"))
        if not due:
            buckets["0_30"] += bal
            continue
        days = max(0, (today - due.date()).days)
        buckets[_bucket_age(days)] += bal
    return {k: round(v, 2) for k, v in buckets.items()}

def _ap_aging_placeholder() -> Dict[str, Any]:
    return {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0,
            "mocked": True, "reason": "no ap_bills collection wired"}

# ─── /dashboard ───────────────────────────────────────────────────────
@router.get("/dashboard")
async def dashboard(
    period: str = Query("ytd", pattern="^(mtd|qtd|ytd|custom)$"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    tid = tenant["id"]
    s, e = _period_bounds(period, start, end)
    revenue = await _revenue(tid, s, e)
    expenses = await _expenses(tid, s, e)
    cash = await _cash_on_hand(tid)
    ar = await _ar_aging(tid)
    ap = _ap_aging_placeholder()
    gross = round(revenue["total"] - expenses["total"], 2)
    margin = round((gross / revenue["total"]) * 100, 2) if revenue["total"] else 0.0
    return {
        "period": {"key": period, "start": s.isoformat(), "end": e.isoformat()},
        "revenue": {"total": revenue["total"], "mocked": revenue["mocked"]},
        "expenses": {"total": expenses["total"], "mocked": expenses["mocked"]},
        "gross_profit": gross,
        "profit_margin_pct": margin,
        "cash_on_hand": cash,
        "ar_aging": ar,
        "ap_aging": ap,
        "revenue_by_source": revenue["by_source"],
        "expense_by_category": expenses["by_category"],
    }

# ─── /forecast ────────────────────────────────────────────────────────
async def _tenant_history_days(tenant_id: str) -> int:
    """Days between earliest revenue/expense event and now for tenant."""
    earliest: Optional[datetime] = None
    async for q in db.quotes.find({"tenant_id": tenant_id, "doc_type": "invoice"},
                                   {"_id": 0, "created_at": 1}).sort("created_at", 1).limit(1):
        d = _parse_dt(q.get("created_at"))
        if d and (earliest is None or d < earliest): earliest = d
    async for ch in db.checks.find({"tenant_id": tenant_id},
                                    {"_id": 0, "date": 1}).sort("date", 1).limit(1):
        d = _parse_dt(ch.get("date"))
        if d and (earliest is None or d < earliest): earliest = d
    if not earliest: return 0
    return (_now_utc() - earliest).days

@router.get("/forecast")
async def forecast(
    horizon: int = Query(30, ge=7, le=180),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    tid = tenant["id"]
    hist_days = await _tenant_history_days(tid)
    now = _now_utc()

    # Weekly buckets from now → now + horizon.
    n_weeks = (horizon + 6) // 7
    week_starts = [now + timedelta(days=7 * i) for i in range(n_weeks)]

    if hist_days < 30:
        return {
            "horizon_days": horizon,
            "buckets": [{"week_start": w.date().isoformat(),
                          "cash_in": 0.0, "cash_out": 0.0, "net": 0.0}
                         for w in week_starts],
            "net_projected": 0.0,
            "runway_days_if_negative": None,
            "mocked": True,
            "reason": f"insufficient history (<30d; have {hist_days}d)",
        }

    # Cash-in: future jobs.price grouped by scheduled_date, plus warranty
    # renewals bucketed by end_date within horizon (treated as auto-renew).
    cash_in_by_week = [0.0] * n_weeks
    async for j in db.jobs.find(
        {"tenant_id": tid, "status": {"$in": ["scheduled", "pending", "active"]}},
        {"_id": 0, "price": 1, "scheduled_date": 1},
    ):
        d = _parse_dt(j.get("scheduled_date"))
        if not d or d < now or d > now + timedelta(days=horizon): continue
        idx = min(n_weeks - 1, (d - now).days // 7)
        cash_in_by_week[idx] += _to_float(j.get("price"))
    async for w in db.warranty_contracts.find(
        {"tenant_id": tid},
        {"_id": 0, "price_paid": 1, "end_date": 1},
    ):
        d = _parse_dt(w.get("end_date"))
        if not d or d < now or d > now + timedelta(days=horizon): continue
        idx = min(n_weeks - 1, (d - now).days // 7)
        cash_in_by_week[idx] += _to_float(w.get("price_paid"))

    # Cash-out: average weekly check outflow over last 90 days, applied flat.
    ninety = now - timedelta(days=90)
    out_total = 0.0
    async for ch in db.checks.find(
        {"tenant_id": tid, "voided_at": None},
        {"_id": 0, "amount": 1, "date": 1},
    ):
        d = _parse_dt(ch.get("date"))
        if d and ninety <= d <= now:
            out_total += _to_float(ch.get("amount"))
    weekly_avg_out = out_total / max(1, 90 / 7)  # ~= out_total / 12.857
    cash_out_by_week = [round(weekly_avg_out, 2)] * n_weeks

    buckets = []
    for i, w in enumerate(week_starts):
        cin = round(cash_in_by_week[i], 2)
        cout = round(cash_out_by_week[i], 2)
        buckets.append({"week_start": w.date().isoformat(),
                         "cash_in": cin, "cash_out": cout,
                         "net": round(cin - cout, 2)})

    net = round(sum(b["net"] for b in buckets), 2)
    runway = None
    if net < 0:
        cash = await _cash_on_hand(tid)
        if not cash.get("mocked") and weekly_avg_out > 0:
            runway = int(round((cash["value"] / weekly_avg_out) * 7, 0))
    return {
        "horizon_days": horizon,
        "buckets": buckets,
        "net_projected": net,
        "runway_days_if_negative": runway,
        "mocked": False,
    }

# ─── /anomalies ───────────────────────────────────────────────────────
@router.get("/anomalies")
async def anomalies(
    window_days: int = Query(90, ge=14, le=365),
    z: float = Query(2.0, ge=0.5, le=5.0),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    tid = tenant["id"]
    now = _now_utc()
    since = now - timedelta(days=window_days)
    # Effective category — prefer expense_categories.category if categorized.
    cat_map: Dict[str, str] = {}
    async for c in db.expense_categories.find(
        {"tenant_id": tid, "source": "check"},
        {"_id": 0, "transaction_id": 1, "category": 1},
    ):
        cat_map[c["transaction_id"]] = c["category"]

    # Group check amounts by category across weekly buckets.
    per_cat_buckets: Dict[str, List[float]] = {}
    async for ch in db.checks.find(
        {"tenant_id": tid, "voided_at": None},
        {"_id": 0, "id": 1, "amount": 1, "date": 1, "category": 1},
    ):
        d = _parse_dt(ch.get("date"))
        if not d or d < since or d > now: continue
        cat = cat_map.get(ch["id"]) or (ch.get("category") or "other").lower()
        weeks_ago = (now - d).days // 7
        buckets = per_cat_buckets.setdefault(cat, [0.0] * ((window_days + 6) // 7))
        if 0 <= weeks_ago < len(buckets):
            buckets[weeks_ago] += _to_float(ch.get("amount"))

    out = []
    detected: List[Dict[str, Any]] = []
    for cat, buckets in per_cat_buckets.items():
        if not buckets or len(buckets) < 2: continue
        cur = buckets[0]
        prior = buckets[1:]
        m = mean(prior) if prior else 0.0
        sd = pstdev(prior) if len(prior) > 1 else 0.0
        threshold = m + z * sd
        is_anom = bool(sd > 0 and cur > threshold and cur > 0)
        item = {
            "category": cat,
            "current_period_total": round(cur, 2),
            "mean": round(m, 2),
            "stddev": round(sd, 2),
            "threshold": round(threshold, 2),
            "z": z,
            "is_anomaly": is_anom,
            "source": "checks",
        }
        out.append(item)
        if is_anom:
            detected.append({
                "id": new_id(), "tenant_id": tid,
                "detected_at": now_iso(), **item,
            })
    if detected:
        await db.expense_anomalies.insert_many(detected)
    return {"window_days": window_days, "z": z, "items": out}

# ─── /categorize ──────────────────────────────────────────────────────
class CategorizeBody(BaseModel):
    limit: int = 100  # cap tx per call
    sources: List[str] = ["check"]

async def _bump_llm_usage(tenant_id: str, tokens: int) -> Dict[str, int]:
    today = _now_utc().date().isoformat()
    doc = await db.cfo_llm_usage.find_one_and_update(
        {"tenant_id": tenant_id, "date": today},
        {"$inc": {"request_count": 1, "tokens_used": max(0, tokens)}},
        upsert=True, return_document=True,
    )
    return {
        "request_count": (doc or {}).get("request_count", 1),
        "tokens_used":  (doc or {}).get("tokens_used", max(0, tokens)),
    }

async def _read_llm_usage(tenant_id: str) -> Dict[str, int]:
    today = _now_utc().date().isoformat()
    doc = await db.cfo_llm_usage.find_one(
        {"tenant_id": tenant_id, "date": today}, {"_id": 0}
    )
    return {
        "request_count": (doc or {}).get("request_count", 0),
        "tokens_used":  (doc or {}).get("tokens_used", 0),
        "quota": _LLM_DAILY_SOFT_QUOTA,
        "date": today,
    }

_LLM_SYSTEM = (
    "You are an expense classifier for a US pool & landscaping company. "
    f"Return JSON only. Each item must be classified into ONE of: "
    f"{', '.join(_EXPENSE_CATEGORIES)}."
)

def _build_prompt(items: List[Dict[str, str]]) -> str:
    return (
        "Classify each transaction into a category. "
        "Reply with a JSON array `[{\"id\": \"...\", \"category\": \"...\","
        " \"confidence\": 0.0-1.0}, ...]`. No prose.\n\n"
        + json.dumps(items, ensure_ascii=False)
    )

async def _llm_classify(items: List[Dict[str, str]]) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str], int]:
    """Returns (results, error_reason, tokens_used_estimate)."""
    if not EMERGENT_LLM_KEY:
        return None, "EMERGENT_LLM_KEY not configured", 0
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        return None, f"llm import failed: {e}", 0
    try:
        chat = (LlmChat(api_key=EMERGENT_LLM_KEY, session_id=new_id(),
                         system_message=_LLM_SYSTEM)
                .with_model(*_MODEL)
                .with_params(max_tokens=_LLM_MAX_OUTPUT_TOKENS))
        raw = await chat.send_message(UserMessage(text=_build_prompt(items)))
        text = raw if isinstance(raw, str) else str(raw)
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            data = json.loads(text)
        except Exception:
            m = re.search(r"(\[.*\])", text, re.S)
            data = json.loads(m.group(1)) if m else []
        # Estimate tokens ~ len(text) / 4 (rough) for usage bookkeeping.
        tokens = int(len(text) / 4)
        cleaned: List[Dict[str, Any]] = []
        for row in (data or []):
            cat = str(row.get("category") or "").lower().strip()
            if cat not in _EXPENSE_CATEGORIES: cat = "other"
            cleaned.append({
                "id": row.get("id"),
                "category": cat,
                "confidence": max(0.0, min(1.0, float(row.get("confidence") or 0.0))),
            })
        return cleaned, None, tokens
    except Exception as e:
        logger.warning(f"CFO LLM classify failed: {e}")
        return None, f"llm error: {e}", 0

@router.post("/categorize")
async def categorize(
    body: Optional[CategorizeBody] = Body(default=None),
    dry_run: bool = Query(False),
    force: bool = Query(False),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    tid = tenant["id"]
    usage = await _read_llm_usage(tid)
    if not force and usage["request_count"] >= _LLM_DAILY_SOFT_QUOTA:
        logger.warning(f"CFO LLM soft quota hit tenant={tid} count={usage['request_count']}")
        return {
            "error": "quota_exceeded", "soft": True,
            "usage": usage,
            "hint": "Pass ?force=true to override (still logged).",
        }
    body = body or CategorizeBody()

    # Find uncategorized checks — those without an expense_categories row.
    categorized_ids = set()
    async for c in db.expense_categories.find(
        {"tenant_id": tid, "source": "check"}, {"_id": 0, "transaction_id": 1},
    ):
        categorized_ids.add(c["transaction_id"])

    pool: List[Dict[str, str]] = []
    async for ch in db.checks.find(
        {"tenant_id": tid, "voided_at": None},
        {"_id": 0, "id": 1, "memo": 1, "payee_name_snapshot": 1, "amount": 1, "category": 1},
    ).limit(body.limit * 3):
        if ch["id"] in categorized_ids: continue
        if ch.get("category") in _EXPENSE_CATEGORIES: continue
        pool.append({
            "id": ch["id"],
            "description": f"{ch.get('payee_name_snapshot') or ''} | {ch.get('memo') or ''}",
            "amount": _to_float(ch.get("amount")),
        })
        if len(pool) >= body.limit: break

    total_scanned = len(pool)
    categorized = 0
    tokens_total = 0
    reasons: List[str] = []

    for start in range(0, len(pool), _LLM_BATCH_SIZE):
        batch = pool[start:start + _LLM_BATCH_SIZE]
        rows, err, tokens = await _llm_classify(batch)
        tokens_total += tokens
        if err or rows is None:
            reasons.append(err or "unknown")
            continue
        if dry_run:
            categorized += len(rows)
            continue
        for row in rows:
            if not row.get("id"): continue
            await db.expense_categories.update_one(
                {"tenant_id": tid, "transaction_id": row["id"], "source": "check"},
                {"$set": {
                    "id": new_id(),
                    "tenant_id": tid,
                    "transaction_id": row["id"],
                    "source": "check",
                    "category": row["category"],
                    "confidence": row["confidence"],
                    "categorized_at": now_iso(),
                    "method": "llm",
                }},
                upsert=True,
            )
            categorized += 1

    # Bookkeeping — one request bump per /categorize call regardless of batches.
    updated = await _bump_llm_usage(tid, tokens_total)
    return {
        "scanned": total_scanned,
        "categorized": categorized,
        "dry_run": dry_run,
        "tokens_used": tokens_total,
        "usage": {**usage, **updated},
        "mocked": bool(reasons),
        "reasons": reasons[:3],
    }

# ─── /llm-usage ───────────────────────────────────────────────────────
@router.get("/llm-usage")
async def llm_usage(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    return await _read_llm_usage(tenant["id"])

# ═══════════════════════════════════════════════════════════════════════
# Phase 33 · Wave 3 — NL Q&A + Scenario Planning
# ═══════════════════════════════════════════════════════════════════════

_QNA_MAX_TOKENS = 1500
_SCENARIO_MAX_TOKENS = 2000

_QNA_SYSTEM = (
    "You are the AI CFO for a US pool & landscaping company. Answer the "
    "user's question using ONLY the provided financial context JSON. "
    "If the question requires data not in context, say so honestly. "
    "If any context fields carry `mocked:true`, qualify your answer "
    "accordingly. Cite specific numbers. Keep answers concise (≤180 words)."
)

_SCENARIO_SYSTEM = (
    "You are the AI CFO for a US pool & landscaping company. Project a "
    "12-month P&L delta for the given scenario using the provided "
    "financial context JSON. Reply with valid JSON only, no prose, matching "
    "this schema exactly:\n"
    "{\n"
    '  "assumptions": [str],\n'
    '  "monthly_delta": [{"month": int (1..12), "revenue_delta": number, '
    '"expense_delta": number, "net_delta": number}],\n'
    '  "annual": {"revenue_delta": number, "expense_delta": number, '
    '"net_delta": number, "margin_delta_pct": number},\n'
    '  "confidence": "low"|"medium"|"high",\n'
    '  "caveats": [str],\n'
    '  "mocked": bool,\n'
    '  "reason": str\n'
    "}\n"
    "Cite which context fields drove the projection under `assumptions`. "
    "If context is too sparse, set mocked=true and explain in reason."
)


async def _top_customers_by_revenue(tenant_id: str, s: datetime, e: datetime,
                                     limit: int = 5) -> List[Dict[str, Any]]:
    totals: Dict[str, Dict[str, Any]] = {}
    async for q in db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice", "payment_status": "paid"},
        {"_id": 0, "customer_id": 1, "customer_name": 1, "total": 1, "paid_at": 1, "created_at": 1},
    ):
        d = _parse_dt(q.get("paid_at")) or _parse_dt(q.get("created_at"))
        if not d or not (s <= d <= e):
            continue
        cid = q.get("customer_id") or q.get("customer_name") or "unknown"
        cur = totals.setdefault(cid, {
            "customer_id": q.get("customer_id"),
            "customer_name": q.get("customer_name") or "Unknown",
            "total": 0.0,
        })
        cur["total"] += _to_float(q.get("total"))
    ranked = sorted(totals.values(), key=lambda r: -r["total"])[:limit]
    return [{**r, "total": round(r["total"], 2)} for r in ranked]


async def _build_financial_context(
    tenant_id: str, period: str = "ytd",
    start: Optional[str] = None, end: Optional[str] = None,
) -> Dict[str, Any]:
    """Compact JSON financial snapshot for LLM prompts. Targeted <1500 tokens."""
    s, e = _period_bounds(period, start, end)
    rev = await _revenue(tenant_id, s, e)
    exp = await _expenses(tenant_id, s, e)
    cash = await _cash_on_hand(tenant_id)
    ar = await _ar_aging(tenant_id)
    ap = _ap_aging_placeholder()
    top_customers = await _top_customers_by_revenue(tenant_id, s, e)
    active_jobs = await db.jobs.count_documents({
        "tenant_id": tenant_id,
        "status": {"$in": ["scheduled", "pending", "active"]},
    })
    active_warranties = await db.warranty_contracts.count_documents({
        "tenant_id": tenant_id
    })
    # Warranty ARR = sum(price_paid) for active contracts (best-effort).
    warranty_arr = 0.0
    async for w in db.warranty_contracts.find(
        {"tenant_id": tenant_id}, {"_id": 0, "price_paid": 1, "end_date": 1}
    ):
        end_dt = _parse_dt(w.get("end_date"))
        if end_dt and end_dt >= _now_utc():
            warranty_arr += _to_float(w.get("price_paid"))

    gross = round(rev["total"] - exp["total"], 2)
    margin = round((gross / rev["total"]) * 100, 2) if rev["total"] else 0.0

    mocked_fields: List[str] = ["ap_aging"]
    if cash.get("mocked"): mocked_fields.append("cash_on_hand")
    # Track other mocked signals if present:
    if not exp.get("by_category"):
        mocked_fields.append("expense_by_category (empty — categorizer not run)")

    # Phase 47.6 — Budget + actuals context for questions like "on track?"
    try:
        from routers.budgets import build_budget_context
        budget_ctx = await build_budget_context(tenant_id)
    except Exception as _e:
        budget_ctx = {"has_budget": False, "note": f"budget context skipped: {_e}"}

    return {
        "period": {"key": period, "start": s.isoformat(), "end": e.isoformat()},
        "revenue": {"total": rev["total"], "by_source": rev["by_source"]},
        "expenses": {"total": exp["total"], "by_category": exp["by_category"][:5]},
        "gross_profit": gross,
        "profit_margin_pct": margin,
        "cash_on_hand": cash,
        "ar_aging": ar,
        "ap_aging": ap,
        "top_customers": top_customers,
        "active_jobs_pipeline": active_jobs,
        "active_warranty_contracts": active_warranties,
        "warranty_arr_estimate": round(warranty_arr, 2),
        "budget": budget_ctx,
        "mocked_fields": mocked_fields,
    }


async def _call_llm_text(system_prompt: str, user_prompt: str,
                          max_tokens: int) -> Tuple[Optional[str], Optional[str], int]:
    """Returns (text, error_reason, tokens_used_estimate)."""
    if not EMERGENT_LLM_KEY:
        return None, "EMERGENT_LLM_KEY not configured", 0
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        return None, f"llm import failed: {e}", 0
    try:
        chat = (LlmChat(api_key=EMERGENT_LLM_KEY, session_id=new_id(),
                         system_message=system_prompt)
                .with_model(*_MODEL)
                .with_params(max_tokens=max_tokens))
        raw = await chat.send_message(UserMessage(text=user_prompt))
        text = raw if isinstance(raw, str) else str(raw)
        tokens = int(len(text) / 4)
        return text.strip(), None, tokens
    except Exception as e:
        logger.warning(f"CFO LLM call failed: {e}")
        return None, f"llm error: {e}", 0


# ─── /qna ─────────────────────────────────────────────────────────────
class QnaBody(BaseModel):
    question: str
    period: str = "ytd"
    start: Optional[str] = None
    end: Optional[str] = None


@router.post("/qna")
async def qna(
    body: QnaBody,
    force: bool = Query(False),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if not body.question or not body.question.strip():
        raise HTTPException(status_code=422, detail="question is required")
    if body.period not in ("mtd", "qtd", "ytd", "custom"):
        raise HTTPException(status_code=422, detail="invalid period")

    tid = tenant["id"]
    usage = await _read_llm_usage(tid)
    if not force and usage["request_count"] >= _LLM_DAILY_SOFT_QUOTA:
        logger.warning(f"CFO Q&A quota soft-hit tenant={tid}")
        return {"error": "quota_exceeded", "soft": True, "usage": usage,
                "hint": "Pass ?force=true to override."}

    ctx = await _build_financial_context(tid, body.period, body.start, body.end)
    prompt = (
        f"Question: {body.question.strip()}\n\n"
        f"Financial context (JSON):\n{json.dumps(ctx, default=str)}"
    )
    text, err, tokens = await _call_llm_text(_QNA_SYSTEM, prompt, _QNA_MAX_TOKENS)

    mocked = bool(err) or not text
    answer = text or ""
    hid = new_id()
    await db.cfo_qna_history.insert_one({
        "id": hid, "tenant_id": tid,
        "actor_user_id": user["id"], "actor_role": user.get("role"),
        "question": body.question.strip(),
        "answer": answer,
        "context_snapshot": ctx,
        "tokens_used": tokens,
        "created_at": now_iso(),
        "mocked": mocked,
        "reason": err,
    })
    updated = await _bump_llm_usage(tid, tokens)
    return {
        "history_id": hid,
        "answer": answer,
        "tokens_used": tokens,
        "mocked": mocked,
        "reason": err,
        "usage": {**usage, **updated},
        "context_snapshot": ctx,
    }


@router.get("/qna/history")
async def qna_history(
    limit: int = Query(20, ge=1, le=200),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    cur = db.cfo_qna_history.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).limit(limit)
    return await cur.to_list(limit)


# ─── /scenario ────────────────────────────────────────────────────────
class ScenarioBody(BaseModel):
    prompt: str
    structured: Optional[Dict[str, Any]] = None


def _empty_scenario(reason: str) -> Dict[str, Any]:
    return {
        "assumptions": [],
        "monthly_delta": [
            {"month": m, "revenue_delta": 0.0, "expense_delta": 0.0,
              "net_delta": 0.0} for m in range(1, 13)
        ],
        "annual": {"revenue_delta": 0.0, "expense_delta": 0.0,
                    "net_delta": 0.0, "margin_delta_pct": 0.0},
        "confidence": "low",
        "caveats": ["LLM output unavailable — projection zeroed."],
        "mocked": True,
        "reason": reason,
    }


@router.post("/scenario")
async def scenario(
    body: ScenarioBody,
    force: bool = Query(False),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if not body.prompt or not body.prompt.strip():
        raise HTTPException(status_code=422, detail="prompt is required")

    tid = tenant["id"]
    usage = await _read_llm_usage(tid)
    if not force and usage["request_count"] >= _LLM_DAILY_SOFT_QUOTA:
        return {"error": "quota_exceeded", "soft": True, "usage": usage,
                "hint": "Pass ?force=true to override."}

    ctx = await _build_financial_context(tid, "ytd")
    struct = body.structured or {}
    prompt = (
        f"Scenario prompt: {body.prompt.strip()}\n\n"
        f"Structured params: {json.dumps(struct)}\n\n"
        f"Financial context (JSON):\n{json.dumps(ctx, default=str)}"
    )
    text, err, tokens = await _call_llm_text(_SCENARIO_SYSTEM, prompt,
                                                _SCENARIO_MAX_TOKENS)

    result: Dict[str, Any]
    if err or not text:
        result = _empty_scenario(err or "empty LLM response")
    else:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", cleaned).strip()
        try:
            result = json.loads(cleaned)
            # Fill missing months if the LLM was lazy.
            months = result.get("monthly_delta") or []
            if len(months) < 12:
                have = {m.get("month"): m for m in months if isinstance(m, dict)}
                result["monthly_delta"] = [
                    have.get(i, {"month": i, "revenue_delta": 0.0,
                                  "expense_delta": 0.0, "net_delta": 0.0})
                    for i in range(1, 13)
                ]
            result.setdefault("mocked", False)
            result.setdefault("reason", None)
        except Exception as e:
            result = _empty_scenario(f"llm json parse error: {e}")

    hid = new_id()
    await db.cfo_scenarios.insert_one({
        "id": hid, "tenant_id": tid,
        "actor_user_id": user["id"], "actor_role": user.get("role"),
        "prompt": body.prompt.strip(),
        "structured": struct,
        "result": result,
        "tokens_used": tokens,
        "created_at": now_iso(),
        "favorite": False,
    })
    updated = await _bump_llm_usage(tid, tokens)
    return {
        "history_id": hid,
        "result": result,
        "tokens_used": tokens,
        "usage": {**usage, **updated},
    }


@router.get("/scenario/history")
async def scenario_history(
    limit: int = Query(20, ge=1, le=200),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    cur = db.cfo_scenarios.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).limit(limit)
    return await cur.to_list(limit)


@router.post("/scenario/{sid}/save-as-favorite")
async def save_scenario_favorite(
    sid: str,
    favorite: bool = Query(True),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    res = await db.cfo_scenarios.update_one(
        {"id": sid, "tenant_id": tenant["id"]},
        {"$set": {"favorite": bool(favorite)}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="scenario not found")
    return {"id": sid, "favorite": bool(favorite)}

