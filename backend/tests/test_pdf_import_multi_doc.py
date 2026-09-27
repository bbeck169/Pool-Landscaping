"""PDF Importer Sub-phase C · Feb-2026 — multi-doc commit tests.

Locks the eight acceptance cases from the PDF-C dispatch:

    (a) Mixed batch (2 invoices + 1 estimate + 1 payment) commits
        with the correct per-type counts in the response.
    (b) Payment matches an existing invoice on doc_number → linked
        via ``payment.invoice_id``.
    (c) Payment with no matching invoice → committed as unlinked
        + ``invoice_link_missing`` warning surfaced.
    (d) Estimate write includes the copy-through fields
        (doc_number, doc_date, customer_name, total_due).
    (e) Idempotent re-commit — same (batch_id, source_doc_index)
        → payment row UPDATED, no duplicates in ``db.payments``.
        Invoice/estimate rows likewise skipped via the existing
        ``already_inserted_indexes`` gate.
    (f) Missing doc_date on invoice → warning surfaced, write
        succeeds anyway (ruling #7: warn, do not block).
    (g) Cross-tenant scoping — a payment's ``invoice_link``
        lookup NEVER resolves to another tenant's invoice.
    (h) Unknown ``mapped_target`` → error entry in warnings,
        other docs still commit.

Testing style mirrors ``test_ldm_jwt_isolation.py`` /
``test_automation_rules.py`` — Motor for the async SUT call,
pymongo for seed + cleanup, per-test asyncio loop. commit_batch
is invoked directly (no TestClient) so the anyio loop-mismatch
gotcha from LDM-E doesn't reappear.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "PDFC_"


def _fresh(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z",
    )


# ═════════════════════════════════════════════════════════════════════
# Fixtures — cleanup fixture tracks every collection touched.
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def seeded(dbc):
    tenants: List[str] = []
    customers: List[str] = []
    batches: List[str] = []
    quotes: List[str] = []
    payments: List[str] = []
    yield {
        "tenants": tenants, "customers": customers,
        "batches": batches, "quotes": quotes,
        "payments": payments,
    }
    if tenants:
        dbc.tenants.delete_many({"id": {"$in": tenants}})
        # Sweep any rows the commit_batch inserted under these
        # tenants — belts and braces because our per-row id
        # tracking may miss the imported quotes/payments.
        dbc.quotes.delete_many({"tenant_id": {"$in": tenants}})
        dbc.payments.delete_many({"tenant_id": {"$in": tenants}})
        dbc.pending_import_customers.delete_many(
            {"tenant_id": {"$in": tenants}},
        )
        dbc.import_batches.delete_many({"tenant_id": {"$in": tenants}})
        dbc.import_audit.delete_many({"tenant_id": {"$in": tenants}})
    if customers:
        dbc.customers.delete_many({"id": {"$in": customers}})
    if batches:
        dbc.import_batches.delete_many({"id": {"$in": batches}})
    if quotes:
        dbc.quotes.delete_many({"id": {"$in": quotes}})
    if payments:
        dbc.payments.delete_many({"id": {"$in": payments}})


# ═════════════════════════════════════════════════════════════════════
# Seed helpers — we skip the extractor entirely and hand-craft the
# ``mapper_previews`` list so the test focuses on commit-path
# behaviour, not on OCR / LLM segmentation quality.
# ═════════════════════════════════════════════════════════════════════
def _seed_tenant(dbc, seeded) -> str:
    tid = _fresh("TEN")
    dbc.tenants.insert_one({
        "id": tid,
        "name": f"PDFC tenant {tid[-6:]}",
    })
    seeded["tenants"].append(tid)
    return tid


def _seed_customer(dbc, seeded, tenant_id: str,
                    *, name: str = "PDFC Customer") -> str:
    cid = _fresh("CUS")
    dbc.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": name, "is_active": True,
    })
    seeded["customers"].append(cid)
    return cid


def _seed_existing_invoice(dbc, seeded, tenant_id: str,
                             customer_id: str, *,
                             doc_number: str,
                             amount: float = 250.0) -> str:
    """Insert a legitimate invoice into ``db.quotes`` — used to
    exercise the payment→invoice link path."""
    qid = _fresh("QUO")
    dbc.quotes.insert_one({
        "id": qid, "tenant_id": tenant_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "doc_number": doc_number,
        "invoice_number": doc_number,
        "total": amount, "status": "sent",
        "created_at": "2026-01-01T00:00:00Z",
    })
    seeded["quotes"].append(qid)
    return qid


def _make_batch(dbc, seeded, tenant_id: str,
                 mapper_previews: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Insert a preview_complete batch row + return the batch
    dict commit_batch expects."""
    batch_id = _fresh("BATCH")
    doc: Dict[str, Any] = {
        "id": batch_id,
        "tenant_id": tenant_id,
        "status": "preview_complete",
        "mapper_previews": mapper_previews,
        "created_at": _iso(datetime.now(timezone.utc)),
    }
    dbc.import_batches.insert_one(doc)
    seeded["batches"].append(batch_id)
    return doc


# ─────────────────────────────────────────────────────────────────
# Preview builders — mirror what pdf_mapper emits without the
# fuzzy-match / LLM stack.
# ─────────────────────────────────────────────────────────────────
def _preview_invoice(idx: int, *, customer_id: str,
                       doc_number: Optional[str] = "INV-1001",
                       doc_date: Optional[str] = "2026-02-01",
                       total_due: Optional[float] = 200.0,
                       ) -> Dict[str, Any]:
    return {
        "source_doc_index": idx,
        "doc_kind": "invoice",
        "mapped_target": "quote_in",
        "customer_resolution": "matched",
        "matched_customer_id": customer_id,
        "quote_in": {
            "customer_id": customer_id,
            "customer_name": "PDFC Customer",
            "title": f"Import #{doc_number}",
            "doc_type": "invoice",
            "doc_number": doc_number,
            "doc_date": doc_date,
            "line_items": [
                {"item_name": "Filter cleaning", "description": "Filter clean",
                 "quantity": 1, "unit_price": total_due or 0.0},
            ],
            "tax_rate": 0.0,
            "total_due": total_due,
            "amount_paid": None,
            "payment_method": None,
            "notes": None,
            "import_batch_id": "<filled_by_test>",
        },
        "errors": [],
        "warnings": [],
        "pending_payment_actions": [],
    }


def _preview_estimate(idx: int, *, customer_id: str,
                        doc_number: str = "EST-2001",
                        doc_date: str = "2026-02-05",
                        total_due: float = 500.0,
                        ) -> Dict[str, Any]:
    p = _preview_invoice(
        idx, customer_id=customer_id,
        doc_number=doc_number, doc_date=doc_date, total_due=total_due,
    )
    p["doc_kind"] = "estimate"
    p["quote_in"]["doc_type"] = "quote"
    p["quote_in"]["title"] = f"Estimate #{doc_number}"
    return p


def _preview_payment(idx: int, *, customer_id: str,
                       doc_number: Optional[str] = "INV-1001",
                       amount_paid: Optional[float] = 200.0,
                       paid_at: Optional[str] = "2026-02-10",
                       payment_method: Optional[str] = "check",
                       ) -> Dict[str, Any]:
    return {
        "source_doc_index": idx,
        "doc_kind": "payment_receipt",
        "mapped_target": "payment_in",
        "customer_resolution": "matched",
        "matched_customer_id": customer_id,
        "payment_in": {
            "customer_id": customer_id,
            "customer_name": "PDFC Customer",
            "doc_number": doc_number,
            "paid_at": paid_at,
            "amount_paid": amount_paid,
            "payment_method": payment_method,
            "payment_reference": None,
            "notes": None,
            "import_batch_id": "<filled_by_test>",
        },
        "errors": [],
        "warnings": [],
        "pending_payment_actions": [],
    }


def _run(coro_factory):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    adb = client[DB_NAME]
    try:
        return loop.run_until_complete(coro_factory(adb))
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass


def _commit(adb, batch, tenant_id):
    from services.imports.pdf_commit import commit_batch
    return commit_batch(
        batch=batch, tenant_id=tenant_id,
        operator={"id": "op-1", "email": "op@pdfc.test"},
        on_duplicate="skip", db=adb,
    )


# ═════════════════════════════════════════════════════════════════════
# (a) Mixed batch: 2 invoices + 1 estimate + 1 payment.
# ═════════════════════════════════════════════════════════════════════
def test_a_mixed_batch_commits_with_correct_per_type_counts(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cust = _seed_customer(dbc, seeded, tid)
    # Seed an invoice that the payment can link to.
    _seed_existing_invoice(dbc, seeded, tid, cust,
                             doc_number="INV-1001", amount=200.0)
    previews = [
        _preview_invoice(0, customer_id=cust, doc_number="INV-1002"),
        _preview_invoice(1, customer_id=cust, doc_number="INV-1003"),
        _preview_estimate(2, customer_id=cust),
        _preview_payment(3, customer_id=cust, doc_number="INV-1001"),
    ]
    batch = _make_batch(dbc, seeded, tid, previews)

    async def _apply(adb):
        return await _commit(adb, batch, tid)

    res = _run(_apply)
    assert res.invoices_created == 2
    assert res.estimates_created == 1
    assert res.payments_created == 1
    assert res.payments_updated == 0
    assert res.payments_unlinked == 0
    # Total quote-family rows equals invoices + estimates.
    assert res.quotes_created == 3
    # Per-type DB counts match.
    assert dbc.quotes.count_documents({
        "tenant_id": tid, "import_batch_id": batch["id"],
        "doc_type": "invoice",
    }) == 2
    assert dbc.quotes.count_documents({
        "tenant_id": tid, "import_batch_id": batch["id"],
        "doc_type": "quote",
    }) == 1
    assert dbc.payments.count_documents({
        "tenant_id": tid, "import_batch_id": batch["id"],
    }) == 1


# ═════════════════════════════════════════════════════════════════════
# (b) Payment links to an existing invoice on doc_number match.
# ═════════════════════════════════════════════════════════════════════
def test_b_payment_links_to_matching_invoice(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cust = _seed_customer(dbc, seeded, tid)
    inv_id = _seed_existing_invoice(dbc, seeded, tid, cust,
                                       doc_number="INV-7777")
    previews = [
        _preview_payment(0, customer_id=cust, doc_number="INV-7777"),
    ]
    batch = _make_batch(dbc, seeded, tid, previews)

    async def _apply(adb):
        return await _commit(adb, batch, tid)

    res = _run(_apply)
    assert res.payments_created == 1
    assert res.payments_unlinked == 0
    payment = dbc.payments.find_one(
        {"tenant_id": tid, "import_batch_id": batch["id"]},
        {"_id": 0},
    )
    assert payment is not None
    assert payment["invoice_id"] == inv_id
    assert payment["invoice_number"] == "INV-7777"


# ═════════════════════════════════════════════════════════════════════
# (c) Payment with no matching invoice → unlinked + warning.
# ═════════════════════════════════════════════════════════════════════
def test_c_payment_without_matching_invoice_unlinked_with_warning(
        dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cust = _seed_customer(dbc, seeded, tid)
    # Deliberately do NOT seed a matching invoice.
    previews = [
        _preview_payment(0, customer_id=cust, doc_number="INV-NO-MATCH"),
    ]
    batch = _make_batch(dbc, seeded, tid, previews)

    async def _apply(adb):
        return await _commit(adb, batch, tid)

    res = _run(_apply)
    assert res.payments_created == 1
    assert res.payments_unlinked == 1
    payment = dbc.payments.find_one(
        {"tenant_id": tid, "import_batch_id": batch["id"]},
        {"_id": 0},
    )
    assert payment["invoice_id"] is None
    # Warning surfaced.
    codes = {w.get("code") for w in res.warnings}
    assert "invoice_link_missing" in codes


# ═════════════════════════════════════════════════════════════════════
# (d) Estimate write includes copy-through fields.
# ═════════════════════════════════════════════════════════════════════
def test_d_estimate_write_includes_copy_through_fields(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cust = _seed_customer(dbc, seeded, tid)
    previews = [
        _preview_estimate(
            0, customer_id=cust,
            doc_number="EST-5000", doc_date="2026-02-14",
            total_due=1200.50,
        ),
    ]
    batch = _make_batch(dbc, seeded, tid, previews)

    async def _apply(adb):
        return await _commit(adb, batch, tid)

    res = _run(_apply)
    assert res.estimates_created == 1
    est = dbc.quotes.find_one(
        {"tenant_id": tid, "import_batch_id": batch["id"],
         "doc_type": "quote"},
        {"_id": 0},
    )
    assert est is not None
    assert est["import_source_doc_number"] == "EST-5000"
    # customer_name copied through from the quote_in preview.
    assert est["customer_name"] == "PDFC Customer"
    # total recomputed from line items so it matches the extractor's
    # per-line math. Line: qty=1 * unit_price=1200.50 = 1200.50.
    assert est["total"] == 1200.5


# ═════════════════════════════════════════════════════════════════════
# (e) Idempotent re-commit — payment row updated, not duplicated.
# ═════════════════════════════════════════════════════════════════════
def test_e_idempotent_recommit_updates_payment_no_duplicate(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cust = _seed_customer(dbc, seeded, tid)
    _seed_existing_invoice(dbc, seeded, tid, cust,
                             doc_number="INV-IDEM")
    previews = [
        _preview_invoice(0, customer_id=cust, doc_number="INV-XX"),
        _preview_payment(1, customer_id=cust, doc_number="INV-IDEM",
                            amount_paid=100.0),
    ]
    batch = _make_batch(dbc, seeded, tid, previews)

    async def _apply(adb):
        r1 = await _commit(adb, batch, tid)
        # Rerun on the same batch — commit_batch is expected to
        # short-circuit invoices via already_inserted_indexes and
        # UPDATE the payment row in place (per ruling #5).
        r2 = await _commit(adb, batch, tid)
        return r1, r2

    r1, r2 = _run(_apply)
    # First run — fresh writes.
    assert r1.invoices_created == 1
    assert r1.payments_created == 1
    assert r1.payments_updated == 0
    # Second run — invoice already inserted, payment updated.
    assert r2.invoices_created == 0
    assert r2.payments_created == 0
    assert r2.payments_updated == 1
    assert r2.quotes_skipped_idempotent >= 1
    # Exactly one payment row exists, not two.
    assert dbc.payments.count_documents(
        {"tenant_id": tid, "import_batch_id": batch["id"]},
    ) == 1
    # And exactly one invoice.
    assert dbc.quotes.count_documents(
        {"tenant_id": tid, "import_batch_id": batch["id"]},
    ) == 1


# ═════════════════════════════════════════════════════════════════════
# (f) Missing doc_date on invoice → warning, write still succeeds.
# ═════════════════════════════════════════════════════════════════════
def test_f_missing_doc_date_on_invoice_warns_but_commits(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cust = _seed_customer(dbc, seeded, tid)
    previews = [
        _preview_invoice(0, customer_id=cust,
                            doc_number="INV-NODATE", doc_date=None),
    ]
    batch = _make_batch(dbc, seeded, tid, previews)

    async def _apply(adb):
        return await _commit(adb, batch, tid)

    res = _run(_apply)
    assert res.invoices_created == 1
    codes = {w.get("code") for w in res.warnings}
    assert "doc_date_missing" in codes
    # Invoice landed in db.quotes.
    inv = dbc.quotes.find_one(
        {"tenant_id": tid, "import_batch_id": batch["id"],
         "doc_type": "invoice"},
        {"_id": 0},
    )
    assert inv is not None


# ═════════════════════════════════════════════════════════════════════
# (g) Cross-tenant scoping — payment link never crosses tenants.
# ═════════════════════════════════════════════════════════════════════
def test_g_payment_invoice_link_scoped_to_caller_tenant(dbc, seeded):
    """Tenant B has an invoice with doc_number ``INV-CROSS`` for
    a completely unrelated customer. Tenant A commits a payment
    referring to the SAME doc_number. The link lookup must NOT
    resolve to tenant B's invoice — the payment lands as unlinked."""
    tid_a = _seed_tenant(dbc, seeded)
    tid_b = _seed_tenant(dbc, seeded)
    a_cust = _seed_customer(dbc, seeded, tid_a, name="A Customer")
    b_cust = _seed_customer(dbc, seeded, tid_b, name="B Customer")
    # Tenant B has the invoice with the shared doc_number.
    _seed_existing_invoice(dbc, seeded, tid_b, b_cust,
                             doc_number="INV-CROSS")
    # Tenant A does NOT.
    previews = [
        _preview_payment(0, customer_id=a_cust,
                            doc_number="INV-CROSS"),
    ]
    batch = _make_batch(dbc, seeded, tid_a, previews)

    async def _apply(adb):
        return await _commit(adb, batch, tid_a)

    res = _run(_apply)
    assert res.payments_created == 1
    assert res.payments_unlinked == 1
    payment = dbc.payments.find_one(
        {"tenant_id": tid_a, "import_batch_id": batch["id"]},
        {"_id": 0},
    )
    # Zero cross-tenant leak — invoice_id null, tenant_id A.
    assert payment["invoice_id"] is None
    assert payment["tenant_id"] == tid_a
    # And tenant B's invoice is UNTOUCHED.
    assert dbc.quotes.count_documents(
        {"tenant_id": tid_b, "doc_number": "INV-CROSS"},
    ) == 1


# ═════════════════════════════════════════════════════════════════════
# (h) Unknown mapped_target → error warning, other docs still commit.
# ═════════════════════════════════════════════════════════════════════
def test_h_unknown_mapped_target_emits_warning_others_commit(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cust = _seed_customer(dbc, seeded, tid)
    # Preview 0 has a garbage mapped_target — should surface a
    # warning; preview 1 is a legitimate invoice that must still
    # commit.
    bad_preview: Dict[str, Any] = {
        "source_doc_index": 0,
        "doc_kind": "invoice",
        # Hand-crafted invalid mapped_target (bypasses the mapper's
        # Literal guard by using the raw dict shape commit_batch
        # actually consumes).
        "mapped_target": "malformed_outer_space_value",
        "customer_resolution": "unresolved",
        "errors": [],
        "warnings": [],
        "pending_payment_actions": [],
    }
    good_preview = _preview_invoice(1, customer_id=cust,
                                        doc_number="INV-GOOD")
    batch = _make_batch(dbc, seeded, tid, [bad_preview, good_preview])

    async def _apply(adb):
        return await _commit(adb, batch, tid)

    res = _run(_apply)
    # The legitimate invoice committed.
    assert res.invoices_created == 1
    # The malformed preview surfaced as a warning.
    codes = {w.get("code") for w in res.warnings}
    assert "unknown_mapped_target" in codes
    # Malformed preview did NOT create a quotes row.
    assert dbc.quotes.count_documents(
        {"tenant_id": tid, "import_batch_id": batch["id"]},
    ) == 1
