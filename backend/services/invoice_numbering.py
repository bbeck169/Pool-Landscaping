"""Phase 56.18 — Human-readable invoice numbers.

Format: `INV-{YYYY}-{NNNNNN}` for invoices, `MINV-{YYYY}-{NNNNNN}`
for master invoices. Per-tenant, per-year, per-prefix sequential
counter with atomic increment (no duplicates under concurrency).

Stored in the new `invoice_number_sequences` collection:
    { tenant_id, year, prefix, next_seq }
"""
import re
from datetime import datetime
from typing import Optional

from config import db, logger

INVOICE_PREFIX = "INV"
MASTER_INVOICE_PREFIX = "MINV"
NUMBER_REGEX = re.compile(r"^(INV|MINV)-\d{4}-\d{6}$")


def _year_in_tz(tz_name: Optional[str]) -> int:
    """Compute current calendar year in the tenant's timezone. Falls
    back to America/Phoenix (matches Phase 56.17's default) if the
    tenant has no `timezone` field, and to UTC on parse failure."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    name = tz_name or "America/Phoenix"
    try:
        tz = ZoneInfo(name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).year


async def _next_seq(tenant_id: str, year: int, prefix: str,
                    reserve_at_least: int = 0) -> int:
    """Atomically bump the per-tenant/year/prefix counter and return
    the new value. When `reserve_at_least > 0`, bumps to at least
    that value (used by backfill so already-assigned numbers stay
    consistent with the sequence)."""
    if reserve_at_least > 0:
        # First read/upsert to guarantee `next_seq >= reserve_at_least`.
        await db.invoice_number_sequences.update_one(
            {"tenant_id": tenant_id, "year": year, "prefix": prefix},
            {"$max": {"next_seq": reserve_at_least}, "$setOnInsert": {}},
            upsert=True,
        )
    res = await db.invoice_number_sequences.find_one_and_update(
        {"tenant_id": tenant_id, "year": year, "prefix": prefix},
        {"$inc": {"next_seq": 1}},
        upsert=True,
        return_document=True,
    )
    if res and res.get("next_seq"):
        return int(res["next_seq"])
    # First-time upsert path — find_one_and_update on Motor may return
    # None on the upsert branch depending on version. Read back.
    row = await db.invoice_number_sequences.find_one(
        {"tenant_id": tenant_id, "year": year, "prefix": prefix}
    )
    return int(row["next_seq"])


async def generate_invoice_number(tenant_id: str, tenant_tz: Optional[str] = None,
                                  master: bool = False) -> str:
    """Public API — returns the next formatted invoice number."""
    year = _year_in_tz(tenant_tz)
    prefix = MASTER_INVOICE_PREFIX if master else INVOICE_PREFIX
    n = await _next_seq(tenant_id, year, prefix)
    return f"{prefix}-{year}-{n:06d}"


async def assign_invoice_number_if_missing(doc: dict, tenant: dict,
                                           master: bool = False) -> dict:
    """Mutate & return `doc` in place: assigns `invoice_number` (or
    `master_invoice_number`) only if the field isn't already set.
    Immutability is enforced HERE — every invoice-birth path calls
    this helper, and the field is never re-generated on updates."""
    field = "master_invoice_number" if master else "invoice_number"
    if doc.get(field):
        return doc
    tenant_id = tenant.get("id") if tenant else None
    if not tenant_id:
        logger.warning("[56.18] assign_invoice_number: missing tenant.id")
        return doc
    tz = tenant.get("timezone") if tenant else None
    doc[field] = await generate_invoice_number(tenant_id, tz, master=master)
    return doc


async def assign_by_tenant_id(doc: dict, tenant_id: str,
                              master: bool = False) -> dict:
    """Convenience: assigns a number when only the tenant_id is
    available (autobilling scheduler, backfill migration). Looks up
    the tenant's timezone once per call."""
    field = "master_invoice_number" if master else "invoice_number"
    if doc.get(field):
        return doc
    tenant = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "id": 1, "timezone": 1}
    ) or {"id": tenant_id}
    return await assign_invoice_number_if_missing(doc, tenant, master=master)


# ═════════════════════════════════════════════════════════════════════
# Canonical write path — Feb-2026 P0 hardening.
#
# Prior state: eight scattered call sites created invoice docs and
# THEN called ``assign_invoice_number_if_missing`` (or forgot to).
# Three paths skipped the helper entirely — ``service_reports.py``
# auto-invoice, ``finances.py::accrue_chem_invoice`` chem drafts,
# and the legacy ``reports.py::run_all_due_billing_plans`` handler
# — which is how Hector Guerrero's "Service — Filter Service" ended
# up on the invoices list with ``invoice_number: null``.
#
# The fix is one canonical helper every write path calls. It:
#   1. Refuses to persist a doc that isn't ``doc_type: 'invoice'``
#      (guards against a copy-paste that would number a quote).
#   2. Assigns a number if the caller didn't (idempotent — the
#      helper short-circuits when ``invoice_number`` is already
#      populated).
#   3. Validates the number matches the ``NUMBER_REGEX`` before
#      the ``insert_one`` fires — a schema-level guard so a new
#      code path can't slip a null past it.
#   4. Delegates the actual insert to Motor, returning the doc
#      with any Motor-added ``_id`` stripped for the caller.
# ═════════════════════════════════════════════════════════════════════
class InvoiceValidationError(ValueError):
    """Raised when ``insert_invoice`` receives a doc that would produce
    an invalid invoice row. Never caught inside the helper — the
    caller must fix the doc before it hits the database."""


async def insert_invoice(doc: dict, tenant: dict,
                          *, master: bool = False) -> dict:
    """Canonical invoice-birth path. See module docstring above.

    ``tenant`` — the caller's tenant doc (must carry ``id`` at
    minimum; ``timezone`` is used to compute the year segment).
    ``master`` — set to True for master-invoice rows (``MINV-…``
    prefix); defaults to False (``INV-…`` prefix).
    """
    field = "master_invoice_number" if master else "invoice_number"
    if doc.get("doc_type") not in (None, "invoice"):
        raise InvoiceValidationError(
            f"insert_invoice refuses doc_type={doc.get('doc_type')!r} "
            f"— only 'invoice' docs may pass this helper."
        )
    doc.setdefault("doc_type", "invoice")
    if not (tenant or {}).get("id"):
        raise InvoiceValidationError(
            "insert_invoice requires tenant.id to assign the invoice "
            "number sequence."
        )
    doc.setdefault("tenant_id", tenant["id"])
    await assign_invoice_number_if_missing(doc, tenant, master=master)
    num = doc.get(field)
    if not num or not NUMBER_REGEX.match(num):
        raise InvoiceValidationError(
            f"insert_invoice produced an invalid {field}={num!r}; "
            f"expected {NUMBER_REGEX.pattern!r}."
        )
    await db.quotes.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def ensure_uniqueness_indexes():
    """Idempotent — creates the uniqueness guards on the two number
    columns and the counter table itself. Called once at startup and
    from every service call path in test scaffolding."""
    try:
        await db.quotes.create_index(
            [("tenant_id", 1), ("invoice_number", 1)],
            partialFilterExpression={"invoice_number": {"$exists": True}},
            unique=True, name="tenant_invoice_number_unique",
        )
        await db.master_invoices.create_index(
            [("tenant_id", 1), ("master_invoice_number", 1)],
            partialFilterExpression={"master_invoice_number": {"$exists": True}},
            unique=True, name="tenant_master_invoice_number_unique",
        )
        await db.invoice_number_sequences.create_index(
            [("tenant_id", 1), ("year", 1), ("prefix", 1)],
            unique=True, name="tenant_year_prefix_unique",
        )
    except Exception as e:
        logger.warning(f"[56.18] ensure_uniqueness_indexes: {e}")
