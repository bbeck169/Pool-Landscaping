"""Feb-2026 · Marketing Slice M4 — Segment evaluator.

Compiles a v1 AND-only condition list into a Mongo query against the
``customers`` collection.  Derived predicates (past-due, last-service,
etc.) resolve via side lookups against ``quotes``/``jobs``/
``properties`` first, then intersect with the base query.

Schema-authoritative: ``FIELD_SCHEMA`` is the whitelist the router
serves to the frontend AND the source of truth the evaluator uses to
validate + dispatch conditions.  Adding a new predicate = one entry.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import db


# ── Whitelist of supported fields + their allowed ops + value shape ────────
FIELD_SCHEMA: List[Dict[str, Any]] = [
    {"field": "vip",                    "ops": ["eq"], "value_shape": "boolean"},
    {"field": "tags",                   "ops": ["contains_any", "contains_all", "none_of"], "value_shape": "string_list"},
    {"field": "has_past_due",           "ops": ["eq"], "value_shape": "boolean"},
    {"field": "balance_due",            "ops": ["gt", "lt", "between"], "value_shape": "number"},
    {"field": "pool_size_gallons",      "ops": ["gt", "lt", "between"], "value_shape": "number"},
    {"field": "last_service_days_ago",  "ops": ["gt", "lt", "between"], "value_shape": "int_days"},
    {"field": "created_days_ago",       "ops": ["gt", "lt", "between"], "value_shape": "int_days"},
    {"field": "city",                   "ops": ["in", "not_in"], "value_shape": "string_list"},
    {"field": "zip",                    "ops": ["in", "not_in"], "value_shape": "string_list"},
    {"field": "channel_opt_in.email",   "ops": ["eq"], "value_shape": "boolean"},
    {"field": "channel_opt_in.sms",     "ops": ["eq"], "value_shape": "boolean"},
    {"field": "has_property_with_pool", "ops": ["eq"], "value_shape": "boolean"},
    {"field": "next_service_within_days", "ops": ["lt"], "value_shape": "int_days"},
]
_ALLOWED: Dict[str, set] = {s["field"]: set(s["ops"]) for s in FIELD_SCHEMA}


def validate_conditions(conds: List[Dict[str, Any]]) -> None:
    """Raise ``ValueError`` on any malformed / disallowed condition."""
    if not isinstance(conds, list):
        raise ValueError("conditions must be a list")
    for i, c in enumerate(conds):
        if not isinstance(c, dict):
            raise ValueError(f"condition[{i}] is not an object")
        field = c.get("field"); op = c.get("op")
        if field not in _ALLOWED:
            raise ValueError(f"condition[{i}]: unknown field {field!r}")
        if op not in _ALLOWED[field]:
            raise ValueError(
                f"condition[{i}]: op {op!r} not allowed on {field!r} "
                f"(allowed: {sorted(_ALLOWED[field])})"
            )
        if "value" not in c:
            raise ValueError(f"condition[{i}]: value missing")


# ── Helpers ────────────────────────────────────────────────────────────────
def _num(x: Any) -> float:
    try: return float(x or 0)
    except (TypeError, ValueError): return 0.0


def _range_expr(op: str, value: Any) -> Dict[str, Any]:
    """Translate a numeric op → Mongo comparison operator dict."""
    if op == "gt":
        return {"$gt": _num(value)}
    if op == "lt":
        return {"$lt": _num(value)}
    if op == "between":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("between requires [min, max]")
        lo, hi = sorted([_num(value[0]), _num(value[1])])
        return {"$gte": lo, "$lte": hi}
    raise ValueError(f"unsupported numeric op {op!r}")


async def _customer_ids_with_past_due(tenant_id: str) -> List[str]:
    today = datetime.now(timezone.utc).date().isoformat()
    rows = await db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0, "customer_id": 1, "total": 1, "amount_paid": 1, "due_date": 1},
    ).to_list(50000)
    out = set()
    for r in rows:
        remaining = _num(r.get("total")) - _num(r.get("amount_paid"))
        due = str(r.get("due_date") or "")[:10]
        if remaining > 0 and due and due < today:
            out.add(r.get("customer_id"))
    out.discard(None)
    return list(out)


async def _customer_ids_balance_map(tenant_id: str) -> Dict[str, float]:
    """{customer_id: outstanding_balance} across open invoices."""
    rows = await db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0, "customer_id": 1, "total": 1, "amount_paid": 1},
    ).to_list(50000)
    out: Dict[str, float] = {}
    for r in rows:
        remaining = _num(r.get("total")) - _num(r.get("amount_paid"))
        if remaining <= 0: continue
        cid = r.get("customer_id")
        if not cid: continue
        out[cid] = out.get(cid, 0.0) + remaining
    return out


async def _customer_ids_by_last_service(tenant_id: str, op: str, value: Any) -> List[str]:
    """Customers whose most-recent completed job matches the age predicate."""
    rows = await db.jobs.find(
        {"tenant_id": tenant_id, "status": "completed"},
        {"_id": 0, "customer_id": 1, "scheduled_start": 1, "completed_at": 1},
    ).to_list(50000)
    latest: Dict[str, str] = {}
    for r in rows:
        cid = r.get("customer_id"); dt = r.get("completed_at") or r.get("scheduled_start")
        if not cid or not dt: continue
        if cid not in latest or str(dt) > latest[cid]:
            latest[cid] = str(dt)
    now = datetime.now(timezone.utc)
    out = []
    for cid, dt in latest.items():
        try: days = (now - datetime.fromisoformat(dt.replace("Z", "+00:00"))).days
        except Exception: continue
        expr = _range_expr(op, value)
        ok = True
        for k, v in expr.items():
            if k == "$gt" and not days > v: ok = False
            elif k == "$lt" and not days < v: ok = False
            elif k == "$gte" and not days >= v: ok = False
            elif k == "$lte" and not days <= v: ok = False
        if ok: out.append(cid)
    return out


async def _customer_ids_next_service_within(tenant_id: str, value: Any) -> List[str]:
    """Customers with a scheduled job within N days from now."""
    days = int(_num(value))
    now = datetime.now(timezone.utc)
    cutoff = (now + timedelta(days=days)).isoformat()
    rows = await db.jobs.find(
        {"tenant_id": tenant_id,
         "status": {"$in": ["scheduled", "active", "pending", "requested"]},
         "scheduled_start": {"$gte": now.isoformat(), "$lte": cutoff}},
        {"_id": 0, "customer_id": 1},
    ).to_list(20000)
    return list({r["customer_id"] for r in rows if r.get("customer_id")})


async def _customer_ids_with_pool_property(tenant_id: str) -> List[str]:
    rows = await db.properties.find(
        {"tenant_id": tenant_id,
         "$or": [
             {"pool_size_gallons": {"$gt": 0}},
             {"has_pool": True},
         ]},
        {"_id": 0, "customer_id": 1},
    ).to_list(50000)
    return list({r["customer_id"] for r in rows if r.get("customer_id")})


# ── Main evaluator ─────────────────────────────────────────────────────────
async def evaluate_conditions(
    conditions: List[Dict[str, Any]], tenant_id: str, *, sample_size: int = 10,
    cap: int = 10000,
) -> Dict[str, Any]:
    validate_conditions(conditions)
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    # Every condition either mutates ``q`` (direct field) or narrows an
    # ``id ∈ {...}`` set built from a derived side-collection lookup.
    id_gates: List[set] = []

    for c in conditions:
        field, op, val = c["field"], c["op"], c["value"]

        if field == "vip":
            q["vip"] = bool(val)
        elif field == "tags":
            if op == "contains_any":
                q["tags"] = {"$in": list(val or [])}
            elif op == "contains_all":
                q["tags"] = {"$all": list(val or [])}
            elif op == "none_of":
                q["tags"] = {"$nin": list(val or [])}
        elif field == "balance_due":
            bal_map = await _customer_ids_balance_map(tenant_id)
            expr = _range_expr(op, val)
            keep = set()
            for cid, bal in bal_map.items():
                ok = True
                for k, v in expr.items():
                    if k == "$gt" and not bal > v: ok = False
                    elif k == "$lt" and not bal < v: ok = False
                    elif k == "$gte" and not bal >= v: ok = False
                    elif k == "$lte" and not bal <= v: ok = False
                if ok: keep.add(cid)
            id_gates.append(keep)
        elif field == "has_past_due":
            past = set(await _customer_ids_with_past_due(tenant_id))
            id_gates.append(past if val else _AllExcept(past))
        elif field == "pool_size_gallons":
            props = await db.properties.find(
                {"tenant_id": tenant_id,
                 "pool_size_gallons": _range_expr(op, val)},
                {"_id": 0, "customer_id": 1},
            ).to_list(50000)
            id_gates.append({p["customer_id"] for p in props if p.get("customer_id")})
        elif field == "last_service_days_ago":
            id_gates.append(set(await _customer_ids_by_last_service(tenant_id, op, val)))
        elif field == "created_days_ago":
            cutoff_hi = datetime.now(timezone.utc) - timedelta(days=_num(val))
            cutoff_hi_str = cutoff_hi.isoformat()
            if op == "gt":
                q["created_at"] = {"$lt": cutoff_hi_str}   # "> N days ago" = created BEFORE N days ago
            elif op == "lt":
                q["created_at"] = {"$gt": cutoff_hi_str}   # "< N days ago" = created AFTER
            elif op == "between":
                if not isinstance(val, (list, tuple)) or len(val) != 2:
                    raise ValueError("between requires [min, max] days")
                a, b = sorted([_num(val[0]), _num(val[1])])
                lo = (datetime.now(timezone.utc) - timedelta(days=b)).isoformat()
                hi = (datetime.now(timezone.utc) - timedelta(days=a)).isoformat()
                q["created_at"] = {"$gte": lo, "$lte": hi}
        elif field == "city":
            q["city"] = {"$in" if op == "in" else "$nin": list(val or [])}
        elif field == "zip":
            q["zip"] = {"$in" if op == "in" else "$nin": list(val or [])}
        elif field in ("channel_opt_in.email", "channel_opt_in.sms"):
            q[field] = bool(val)
        elif field == "has_property_with_pool":
            pool_ids = set(await _customer_ids_with_pool_property(tenant_id))
            id_gates.append(pool_ids if val else _AllExcept(pool_ids))
        elif field == "next_service_within_days":
            id_gates.append(set(await _customer_ids_next_service_within(tenant_id, val)))

    # Materialise base query.
    rows = await db.customers.find(
        q, {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "vip": 1, "tags": 1},
    ).to_list(cap)
    # Apply id_gates intersection (empty gate → empty result).
    if id_gates:
        base_ids = {r["id"] for r in rows}
        for gate in id_gates:
            if isinstance(gate, _AllExcept):
                base_ids -= gate.excluded
            else:
                base_ids &= gate
        rows = [r for r in rows if r["id"] in base_ids]

    sample = rows[:sample_size]
    return {
        "count": len(rows),
        "sample": sample,
        "matched_ids": [r["id"] for r in rows],
    }


class _AllExcept:
    """Sentinel for a NEGATIVE gate (everyone except a set) used by
    boolean-false derived predicates.  Intersection against base ids
    is `base - excluded` (see evaluator apply loop)."""
    def __init__(self, excluded: set):
        self.excluded = excluded
