"""Phase P30 · Feb-2026 — Partial unique index on
``customers.stripe_customer_id``.

Rationale
---------
The P30 card-add flow reconciles a Stripe Checkout Session back to
an internal customer via ``metadata.crm_customer_id``. Once a
customer is minted on Stripe, the ``stripe_customer_id`` MUST be
unique per CRM customer — a duplicate would mean two internal rows
share a Stripe billing identity, which the ``payment_method.detached``
webhook cannot disambiguate (see the ``critical`` log in
``stripe_charge.handle_webhook_event``). This migration installs a
partial unique index that lets ``stripe_customer_id`` be absent /
null / empty (fine — the customer just hasn't been minted yet) but
rejects duplicate non-empty values.

Behavior
--------
* **Pre-flight collision scan** — before creating the index, run a
  duplicate detection aggregate. If any duplicates exist, we DO NOT
  create the index and stamp the migration as ``ERROR`` on the
  ``InitState`` sentinel. Boot never crashes; ops runs a data
  cleanup pass and re-invokes this migration afterwards.
* Idempotent — second run against a fresh (dup-free) DB is a no-op
  because ``create_index`` treats an existing index with the same
  key + options as already-present.

Wire-up
-------
Registered in the P21 STRUCTURAL block via
``_run_structural_migration("p30_customers_stripe_customer_id_unique",
_factory, must_succeed=False)`` — best-effort. A duplicate on
preview data is loud but not fatal.
"""
from __future__ import annotations

from typing import Any, Dict, List

from config import db, logger


MIGRATION_NAME = "p30_customers_stripe_customer_id_unique"
INDEX_NAME = "p30_customers_stripe_customer_id_unique"


async def _scan_duplicates() -> List[Dict[str, Any]]:
    """Return a list of ``{stripe_customer_id, count, ids}`` rows for
    every ``stripe_customer_id`` value shared by 2+ customer rows.
    Empty list ⇒ safe to create the unique index.
    """
    pipeline = [
        {"$match": {"$and": [
            {"stripe_customer_id": {"$exists": True}},
            {"stripe_customer_id": {"$ne": None}},
            {"stripe_customer_id": {"$ne": ""}},
        ]}},
        {"$group": {
            "_id": "$stripe_customer_id",
            "count": {"$sum": 1},
            "ids": {"$push": "$id"},
            "tenants": {"$addToSet": "$tenant_id"},
        }},
        {"$match": {"count": {"$gt": 1}}},
    ]
    dups: List[Dict[str, Any]] = []
    async for row in db.customers.aggregate(pipeline):
        dups.append({
            "stripe_customer_id": row["_id"],
            "count": row["count"],
            "customer_ids": row.get("ids", []),
            "tenant_ids": row.get("tenants", []),
        })
    return dups


async def run() -> Dict[str, Any]:
    """Idempotent structural migration entry point.

    Returns
    -------
    dict
        ``{"ok": bool, "index_created": bool, "duplicates": list,
            "error": str | None}``
    """
    dups = await _scan_duplicates()
    if dups:
        # Loud warn — ops needs to see this in the boot log so the
        # cleanup runbook is unambiguous.
        for d in dups:
            logger.warning(
                "[p30-idx] duplicate stripe_customer_id=%r shared by "
                "%d customer rows across tenants=%s ids=%s. Index "
                "creation SKIPPED — clean up dupes and re-run.",
                d["stripe_customer_id"], d["count"],
                d["tenant_ids"], d["customer_ids"],
            )
        return {
            "ok": False,
            "index_created": False,
            "duplicates": dups,
            "error": (
                f"duplicate stripe_customer_id values detected "
                f"({len(dups)} clusters); unique index NOT created"
            ),
        }

    # Safe to create the partial unique index. ``create_index`` is
    # idempotent on same-shape re-creates.
    #
    # Partial-filter caveat: MongoDB partial indexes do NOT support
    # ``$ne`` inside ``partialFilterExpression``. We use ``$gt: ""``
    # which selects only non-empty strings (empty strings, null,
    # and missing values all evaluate ``false`` against a string
    # ``$gt`` comparison and are therefore excluded from the
    # uniqueness constraint — exactly the semantics we want).
    await db.customers.create_index(
        "stripe_customer_id",
        unique=True,
        partialFilterExpression={"stripe_customer_id": {
            "$exists": True, "$type": "string", "$gt": "",
        }},
        name=INDEX_NAME,
    )
    logger.info(
        "[p30-idx] partial unique index installed on "
        "customers.stripe_customer_id (name=%s)", INDEX_NAME,
    )
    return {
        "ok": True,
        "index_created": True,
        "duplicates": [],
        "error": None,
    }
