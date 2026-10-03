"""Phase 2 · Feb-2026 · Quote-to-Lead Recipient — shared resolver."""
from __future__ import annotations
from typing import Dict, Any, Optional
from config import db


def effective_recipient_fields(quote_doc: dict) -> Dict[str, Optional[str]]:
    rtype = (quote_doc.get("recipient_type") or "").strip().lower()
    rid = quote_doc.get("recipient_id")
    if rtype in ("customer", "lead") and rid:
        return {"kind": rtype, "id": rid}
    if quote_doc.get("customer_id"):
        return {"kind": "customer", "id": quote_doc["customer_id"]}
    return {"kind": None, "id": None}


async def resolve_quote_recipient(quote_doc: dict, tenant_id: str) -> Dict[str, Any]:
    pk = effective_recipient_fields(quote_doc)
    if pk["kind"] == "customer":
        row = await db.customers.find_one(
            {"id": pk["id"], "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "address": 1},
        ) or {}
        return {
            "kind": "customer", "id": pk["id"],
            "name": row.get("name") or quote_doc.get("customer_name") or "",
            "email": row.get("email") or quote_doc.get("customer_email") or "",
            "phone": row.get("phone") or "",
            "address": row.get("address") or quote_doc.get("customer_address") or "",
        }
    if pk["kind"] == "lead":
        row = await db.leads.find_one(
            {"id": pk["id"], "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1,
             "address": 1, "service_address": 1},
        ) or {}
        return {
            "kind": "lead", "id": pk["id"],
            "name": row.get("name") or quote_doc.get("customer_name") or "",
            "email": row.get("email") or quote_doc.get("customer_email") or "",
            "phone": row.get("phone") or "",
            "address": (row.get("service_address") or row.get("address")
                         or quote_doc.get("customer_address") or ""),
        }
    return {
        "kind": None, "id": None,
        "name": quote_doc.get("customer_name") or "",
        "email": quote_doc.get("customer_email") or "",
        "phone": "", "address": quote_doc.get("customer_address") or "",
    }
