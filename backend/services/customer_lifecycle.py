"""Feb-2026 · P42 — Customer lifecycle helpers.

Central home for the ``customer_since`` stamp — the "converted"
threshold marker written to a customer doc the first time BOTH of
these are true for that customer:

    1. ``is_active == True``
    2. Has ≥1 job in ``db.jobs`` (any status, not soft-deleted)

Once set, the field is immutable. All triggers should invoke
``stamp_customer_since`` defensively — it's a safe no-op when the
criteria aren't met, so callers don't need to pre-check.

Trigger surfaces (as of P42):
    * ``routers.jobs.create_job`` — right after a successful insert.
    * ``routers.customers._apply_activation_cascade`` — on the
      ``reactivating`` branch (inactive → active flip).

Explicitly NOT stamped from:
    * Customer create (a lead that never converts shouldn't get a
      customer_since date).
    * P41 CSV import (no jobs at import time).
    * Soft-delete / restore of the customer doc itself.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging

from config import db
from utils import new_id, not_deleted_filter

logger = logging.getLogger("pool_crm")


async def stamp_customer_since(customer_id: str, tenant_id: str) -> bool:
    """Idempotently stamp ``customer_since`` on the given customer.

    Returns True if a new stamp was written, False on any no-op branch
    (field already set, customer inactive, no jobs yet, customer not
    found). Never raises — internal errors are logged and swallowed
    so a trigger hook can't take down its host endpoint.
    """
    try:
        cust = await db.customers.find_one(
            {"id": customer_id, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "is_active": 1, "customer_since": 1,
              "name": 1},
        )
        if not cust:
            return False
        if cust.get("customer_since"):
            return False  # immutable — never overwrite
        # Missing ``is_active`` field on legacy rows is treated as
        # active (matches the read-side default in customers.py).
        if cust.get("is_active", True) is False:
            return False

        job_count = await db.jobs.count_documents({
            "customer_id": customer_id,
            "tenant_id": tenant_id,
            **not_deleted_filter(),
        })
        if job_count == 0:
            return False

        stamped_at = datetime.now(timezone.utc).isoformat()
        r = await db.customers.update_one(
            # The ``exists=False``/``null`` guard on the write side
            # keeps the field immutable even under a race (two
            # simultaneous job creates for a newly-active customer).
            {"id": customer_id, "tenant_id": tenant_id,
              "$or": [{"customer_since": None},
                          {"customer_since": {"$exists": False}}]},
            {"$set": {"customer_since": stamped_at}},
        )
        if not r.modified_count:
            return False

        try:
            await db.audit_logs.insert_one({
                "id": new_id(),
                "tenant_id": tenant_id,
                "event": "customer_since_stamped",
                "customer_id": customer_id,
                "customer_name": cust.get("name"),
                "customer_since": stamped_at,
                "job_count_at_stamp": job_count,
                "at": stamped_at,
                "created_at": stamped_at,
            })
        except Exception as exc:  # pragma: no cover — best-effort
            logger.warning("[p42] audit insert failed customer=%s err=%s",
                              customer_id, exc)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[p42] stamp_customer_since failed customer=%s "
                          "err=%s", customer_id, exc)
        return False
