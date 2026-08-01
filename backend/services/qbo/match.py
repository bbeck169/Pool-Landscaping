"""Phase 17 · Feb-2026 — QBO ↔ CRM match-suggestion heuristics.

Read-only scoring. The user always confirms links explicitly — this
module only suggests candidates ranked by confidence.

Invoice matching (the highest-value case):
* Amount within ±1% (weight 0.5)
* Txn date within ±7 days (weight 0.3)
* Fuzzy customer-name match (weight 0.2)

Customer matching:
* Fuzzy display-name match (weight 0.7)
* Email exact match (weight 0.3)

All scores in [0, 1]. We return the top 5 above 0.2 confidence.
"""

from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from config import db


def _fuzzy(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _parse_date(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10])
    except Exception:
        return None


async def _invoice_suggestions(
    tenant_id: str, qbo_doc: Dict[str, Any]
) -> List[Dict[str, Any]]:
    ex = qbo_doc.get("extracted") or {}
    qbo_total = float(ex.get("total") or 0)
    qbo_name = ex.get("customer_name") or ""
    qbo_date = _parse_date(ex.get("txn_date"))
    if qbo_total <= 0:
        return []

    lo = qbo_total * 0.99
    hi = qbo_total * 1.01
    cursor = db.quotes.find({
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "total": {"$gte": lo, "$lte": hi},
    }, {"_id": 0, "id": 1, "total": 1, "customer_id": 1,
        "customer_name": 1, "issued_at": 1, "created_at": 1,
        "invoice_number": 1}).limit(50)

    hits: List[Dict[str, Any]] = []
    async for c in cursor:
        c_date = _parse_date(c.get("issued_at") or c.get("created_at"))
        d_days = 999
        if qbo_date and c_date:
            d_days = abs((qbo_date - c_date).days)
        amt_score = 1.0 - min(abs((c.get("total") or 0) - qbo_total) / qbo_total, 1.0)
        date_score = max(0.0, 1.0 - (d_days / 7.0))
        name_score = _fuzzy(qbo_name, c.get("customer_name") or "")
        conf = 0.5 * amt_score + 0.3 * date_score + 0.2 * name_score
        if conf < 0.2:
            continue
        hits.append({
            "crm_id": c["id"],
            "crm_entity_type": "invoice",
            "confidence": round(conf, 3),
            "matched_on": {
                "amount": round(amt_score, 3),
                "date": round(date_score, 3),
                "customer_name": round(name_score, 3),
            },
            "preview": {
                "invoice_number": c.get("invoice_number"),
                "total": c.get("total"),
                "customer_name": c.get("customer_name"),
            },
        })
    hits.sort(key=lambda r: r["confidence"], reverse=True)
    return hits[:5]


async def _customer_suggestions(
    tenant_id: str, qbo_doc: Dict[str, Any]
) -> List[Dict[str, Any]]:
    ex = qbo_doc.get("extracted") or {}
    qbo_name = ex.get("display_name") or ""
    qbo_email = (ex.get("email") or "").lower()

    hits: List[Dict[str, Any]] = []
    cursor = db.customers.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "email": 1},
    ).limit(500)
    async for c in cursor:
        name_score = _fuzzy(qbo_name, c.get("name") or "")
        email_score = 1.0 if (c.get("email") or "").lower() == qbo_email and qbo_email else 0.0
        conf = 0.7 * name_score + 0.3 * email_score
        if conf < 0.2:
            continue
        hits.append({
            "crm_id": c["id"],
            "crm_entity_type": "customer",
            "confidence": round(conf, 3),
            "matched_on": {"name": round(name_score, 3), "email": email_score},
            "preview": {"name": c.get("name"), "email": c.get("email")},
        })
    hits.sort(key=lambda r: r["confidence"], reverse=True)
    return hits[:5]


async def suggest(
    *, tenant_id: str, qbo_entity_type: str, qbo_id: str,
) -> List[Dict[str, Any]]:
    coll = {
        "invoice": "qbo_invoices",
        "customer": "qbo_customers",
    }.get(qbo_entity_type)
    if not coll:
        return []
    doc = await db[coll].find_one(
        {"tenant_id": tenant_id, "qbo_id": qbo_id}, {"_id": 0}
    )
    if not doc:
        return []
    if qbo_entity_type == "invoice":
        return await _invoice_suggestions(tenant_id, doc)
    return await _customer_suggestions(tenant_id, doc)
