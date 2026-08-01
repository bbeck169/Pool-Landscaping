"""Phase 17 · Feb-2026 — QBO sync orchestration.

Read-only. Pulls each entity in dependency order and upserts into the
``db.qbo_*`` mirror collections. Records each run into ``db.qbo_sync_runs``.

Delta strategy: after the first successful run, subsequent runs pass
``changed_since = <last successful run's started_at>`` to Intuit so we
only pull records with newer ``Metadata.LastUpdatedTime``. First run and
``force_full=True`` do a full pull.

Concurrency guard: an in-flight run for a given connection blocks a
second run — the router surfaces the existing run_id instead.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db
from services.qbo import client as qbo_client

logger = logging.getLogger("qbo.sync")

# Dependency order matters — accounts + customers + vendors before the
# transactional entities that may reference them via match links.
ENTITY_ORDER: List[str] = [
    "accounts",
    "customers",
    "vendors",
    "invoices",
    "payments",
    "journal_entries",
    "bills",
]

COLLECTION_FOR = {
    "accounts": "qbo_accounts",
    "customers": "qbo_customers",
    "vendors": "qbo_vendors",
    "invoices": "qbo_invoices",
    "payments": "qbo_payments",
    "journal_entries": "qbo_journal_entries",
    "bills": "qbo_bills",
}


def _extract(entity: str, doc: Dict[str, Any]) -> Dict[str, Any]:
    """Denormalize a few common fields per entity for UI filtering. Keep
    the full QBO payload in ``raw``; ``extracted`` never overrides."""
    ex: Dict[str, Any] = {}
    if entity == "customers":
        ex = {
            "display_name": doc.get("DisplayName"),
            "email": (doc.get("PrimaryEmailAddr") or {}).get("Address"),
            "phone": (doc.get("PrimaryPhone") or {}).get("FreeFormNumber"),
            "active": doc.get("Active", True),
            "balance": doc.get("Balance"),
        }
    elif entity == "vendors":
        ex = {
            "display_name": doc.get("DisplayName"),
            "email": (doc.get("PrimaryEmailAddr") or {}).get("Address"),
            "active": doc.get("Active", True),
            "balance": doc.get("Balance"),
        }
    elif entity == "invoices":
        ex = {
            "doc_number": doc.get("DocNumber"),
            "customer_ref_id": (doc.get("CustomerRef") or {}).get("value"),
            "customer_name": (doc.get("CustomerRef") or {}).get("name"),
            "total": doc.get("TotalAmt"),
            "balance": doc.get("Balance"),
            "txn_date": doc.get("TxnDate"),
            "due_date": doc.get("DueDate"),
            "currency": (doc.get("CurrencyRef") or {}).get("value"),
        }
    elif entity == "payments":
        ex = {
            "customer_ref_id": (doc.get("CustomerRef") or {}).get("value"),
            "total": doc.get("TotalAmt"),
            "txn_date": doc.get("TxnDate"),
            "payment_method_id": (doc.get("PaymentMethodRef") or {}).get("value"),
        }
    elif entity == "accounts":
        ex = {
            "name": doc.get("Name"),
            "type": doc.get("AccountType"),
            "sub_type": doc.get("AccountSubType"),
            "active": doc.get("Active", True),
            "balance": doc.get("CurrentBalance"),
        }
    elif entity == "journal_entries":
        ex = {
            "doc_number": doc.get("DocNumber"),
            "txn_date": doc.get("TxnDate"),
            "total": doc.get("TotalAmt"),
            "adjustment": doc.get("Adjustment", False),
        }
    elif entity == "bills":
        ex = {
            "doc_number": doc.get("DocNumber"),
            "vendor_ref_id": (doc.get("VendorRef") or {}).get("value"),
            "vendor_name": (doc.get("VendorRef") or {}).get("name"),
            "total": doc.get("TotalAmt"),
            "balance": doc.get("Balance"),
            "txn_date": doc.get("TxnDate"),
            "due_date": doc.get("DueDate"),
        }
    return ex


async def _upsert(entity: str, tenant_id: str, conn: Dict[str, Any],
                   doc: Dict[str, Any], now_iso: str) -> None:
    coll = COLLECTION_FOR[entity]
    qbo_id = str(doc.get("Id") or "")
    if not qbo_id:
        return
    row = {
        "tenant_id": tenant_id,
        "qbo_connection_id": conn["qbo_connection_id"],
        "qbo_realm_id": conn["qbo_realm_id"],
        "qbo_id": qbo_id,
        "qbo_sync_token": doc.get("SyncToken"),
        "entity_type": entity[:-1] if entity.endswith("s") else entity,
        "raw": doc,
        "extracted": _extract(entity, doc),
        "last_synced_at": now_iso,
    }
    await db[coll].update_one(
        {"tenant_id": tenant_id,
         "qbo_realm_id": conn["qbo_realm_id"], "qbo_id": qbo_id},
        {"$set": row, "$setOnInsert": {"id": str(uuid.uuid4())}},
        upsert=True,
    )


async def sync_tenant(
    *, tenant_id: str, qbo_connection_id: str,
    force_full: bool = False, triggered_by: str = "manual",
) -> Dict[str, Any]:
    """Main entry point. Runs all 7 entity pulls, records the run row,
    and returns the run summary. Never raises to the caller — every
    error is captured on the run doc."""
    # Concurrency guard.
    in_flight = await db.qbo_sync_runs.find_one(
        {"tenant_id": tenant_id, "qbo_connection_id": qbo_connection_id,
         "status": "running"}, {"_id": 0, "run_id": 1, "started_at": 1},
    )
    if in_flight:
        return {"run_id": in_flight["run_id"], "status": "running",
                "already_running": True}

    conn = await db.qbo_connections.find_one(
        {"qbo_connection_id": qbo_connection_id, "status": "active",
         "tenant_id": tenant_id}, {"_id": 0},
    )
    if not conn:
        return {"run_id": None, "status": "failed",
                "error": "connection_not_active"}

    run_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc)
    started_iso = started.isoformat()

    # Delta cursor: last successful run's started_at.
    changed_since: Optional[str] = None
    if not force_full:
        prev = await db.qbo_sync_runs.find_one(
            {"tenant_id": tenant_id,
             "qbo_connection_id": qbo_connection_id,
             "status": {"$in": ["success", "partial_success"]}},
            sort=[("started_at", -1)],
            projection={"_id": 0, "started_at": 1},
        )
        if prev:
            changed_since = prev["started_at"]

    await db.qbo_sync_runs.insert_one({
        "id": run_id,
        "run_id": run_id,
        "tenant_id": tenant_id,
        "qbo_connection_id": qbo_connection_id,
        "triggered_by": triggered_by,
        "status": "running",
        "started_at": started_iso,
        "entities_pulled": {},
        "errors": [],
        "changed_since": changed_since,
        "force_full": force_full,
    })

    entities_pulled: Dict[str, int] = {}
    errors: List[Dict[str, Any]] = []
    t0 = time.monotonic()

    for entity in ENTITY_ORDER:
        try:
            total = 0
            pos = 1
            while True:
                page = await qbo_client.fetch_entity_page(
                    qbo_connection_id, entity,
                    start_position=pos, max_results=1000,
                    changed_since=changed_since,
                )
                if not page:
                    break
                for doc in page:
                    await _upsert(entity, tenant_id, conn, doc, started_iso)
                total += len(page)
                if len(page) < 1000:
                    break
                pos += 1000
            entities_pulled[entity] = total
        except Exception as exc:  # noqa: BLE001
            errors.append({
                "entity": entity,
                "error": str(exc)[:300],
                "at": datetime.now(timezone.utc).isoformat(),
            })
            # Continue with next entity.

    duration_ms = int((time.monotonic() - t0) * 1000)
    completed = datetime.now(timezone.utc).isoformat()
    if errors and entities_pulled:
        status = "partial_success"
    elif errors:
        status = "failed"
    else:
        status = "success"

    await db.qbo_sync_runs.update_one(
        {"run_id": run_id},
        {"$set": {
            "status": status,
            "completed_at": completed,
            "entities_pulled": entities_pulled,
            "errors": errors,
            "duration_ms": duration_ms,
        }},
    )
    await db.qbo_connections.update_one(
        {"qbo_connection_id": qbo_connection_id},
        {"$set": {"last_sync_at": completed, "last_sync_run_id": run_id}},
    )
    return {"run_id": run_id, "status": status,
            "entities_pulled": entities_pulled, "errors": errors,
            "duration_ms": duration_ms}


# ── APScheduler entry point ──────────────────────────────────────────
async def qbo_daily_sync() -> None:
    """APScheduler job — iterate active tenants + connections and run
    ``sync_tenant`` for each with ``triggered_by="cron"``. One tenant's
    failure never blocks another (per-tenant try/except)."""
    cursor = db.qbo_connections.find(
        {"status": "active"}, {"_id": 0, "tenant_id": 1, "qbo_connection_id": 1},
    )
    async for row in cursor:
        try:
            await sync_tenant(
                tenant_id=row["tenant_id"],
                qbo_connection_id=row["qbo_connection_id"],
                triggered_by="cron",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[qbo.cron] tenant %s failed: %s",
                            row.get("tenant_id"), exc)
