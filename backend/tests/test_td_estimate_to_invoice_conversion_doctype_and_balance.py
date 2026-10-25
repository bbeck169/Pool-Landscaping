"""TD-estimate-to-invoice-conversion-doctype-and-balance · Feb-2026
=================================================================

Regression lock for both bugs + the backfill CLI::

  Fix A — convert path normalises placeholder titles to "Invoice"
          and preserves custom titles verbatim
  Fix B — convert path stamps status="issued" + issued_at (was draft)
  Fix C — payments_summary._LIVE_STATUSES now includes "issued"
  Backfill — status-draft→issued + title-placeholder repair,
             --dry-run / --report-only / --apply ladder,
             idempotent sentinel in db._migrations.

Loop-isolation note: this suite mirrors the shim used by
``test_convert_quote_to_invoice.py`` — direct function calls into
``routers/quotes.py``, ``routers/payments_summary.py``, and the
backfill CLI need every module-level ``db`` alias rebound to a
single AsyncIOMotorClient bound to THIS test loop. The
``_patch_db_everywhere`` helper runs under the autouse fixture so
collection-time ordering can't leak the preview loop into this
suite.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db_everywhere():
    """Rebind every module-level ``db`` alias in the convert
    graph + the payments_summary + the backfill CLI to the test
    loop's client.  Must run on every test (autouse fixture)
    because collection-time ordering with other suites can
    clobber either side."""
    import config
    config.db = _DB
    import routers.quotes as _quotes_mod
    _quotes_mod.db = _DB
    import routers.estimates as _estimates_mod
    _estimates_mod.db = _DB
    import routers.payments_summary as _ps_mod
    _ps_mod.db = _DB
    import services.invoice_builder as _ib_mod
    _ib_mod.db = _DB
    import services.invoice_numbering as _inum_mod
    _inum_mod.db = _DB
    import routers.finances as _fin_mod
    _fin_mod.db = _DB
    import migrations.convert_to_invoice_status_backfill_v1 as _bf_mod
    _bf_mod.db = _DB


_PFX = f"TESTtdC2I-{uuid4().hex[:8]}"
TENANT = f"{_PFX}-tenant-a"
TENANT_B = f"{_PFX}-tenant-b"
_ADMIN = {"id": f"{_PFX}-adm", "role": "admin", "tenant_id": TENANT}


# ═══════════════════════════════════════════════════════════════════
# Seed helpers (sync wrappers over Motor on the test loop)
# ═══════════════════════════════════════════════════════════════════
async def _seed_tenant(tid: str) -> None:
    await _DB.tenants.update_one(
        {"id": tid}, {"$set": {"id": tid, "name": f"Tenant {tid}"}},
        upsert=True,
    )


async def _seed_customer(tid: str, cid=None) -> str:
    cid = cid or f"{_PFX}-cust-{uuid4().hex[:8]}"
    await _DB.customers.update_one(
        {"id": cid, "tenant_id": tid},
        {"$set": {"id": cid, "tenant_id": tid,
                  "name": "Peter Test",
                  "email": "peter@test.example"}},
        upsert=True,
    )
    return cid


async def _seed_source_quote(*, tid, cid, title="Pool Repair",
                               doc_type="quote") -> str:
    qid = f"{_PFX}-q-{uuid4().hex[:8]}"
    await _DB.quotes.insert_one({
        "id": qid, "tenant_id": tid, "doc_type": doc_type,
        "customer_id": cid, "customer_name": "Peter Test",
        "title": title, "status": "accepted",
        "line_items": [
            {"id": f"{qid}-li-1", "description": "Service",
             "quantity": 1, "unit_price": 3855.0, "category": "Other"},
        ],
        "tax_rate": 0.0, "subtotal": 3855.0, "tax": 0.0, "total": 3855.0,
        "created_at": "2026-02-10T00:00:00+00:00",
    })
    return qid


async def _seed_converted_invoice(
    *, tid, cid, title="Estimate", status="draft",
    source="convert_from_quote", total=3855.0,
) -> str:
    """Simulate a pre-fix converted invoice: status=draft, placeholder title."""
    inv_id = f"{_PFX}-inv-{uuid4().hex[:8]}"
    await _DB.quotes.insert_one({
        "id": inv_id, "tenant_id": tid, "doc_type": "invoice",
        "customer_id": cid, "customer_name": "Peter Test",
        "title": title, "status": status,
        "payment_status": "unpaid", "amount_paid": 0.0,
        "total": total, "subtotal": total, "tax": 0.0, "tax_rate": 0.0,
        "line_items": [{"id": f"{inv_id}-li-1", "description": "svc",
                        "quantity": 1, "unit_price": total}],
        "source": source,
        "source_quote_id": f"{_PFX}-q-src",
        "invoice_number": f"INV-TEST-{uuid4().hex[:6].upper()}",
        "converted_at": "2026-10-01T00:00:00+00:00",
        "created_at": "2026-10-01T00:00:00+00:00",
    })
    return inv_id


async def _wipe() -> None:
    for coll in ("quotes", "customers", "tenants"):
        await _DB[coll].delete_many({"id": {"$regex": f"^{_PFX}"}})
    await _DB["_migrations"].delete_many(
        {"key": "convert_to_invoice_status_backfill_v1"},
    )


@pytest.fixture(autouse=True)
def _env():
    _patch_db_everywhere()
    _run(_wipe())
    yield
    _run(_wipe())


# ═══════════════════════════════════════════════════════════════════
# §1 · Fix A — placeholder-title normalisation at convert time
# ═══════════════════════════════════════════════════════════════════
def test_convert_quote_placeholder_title_normalises_to_invoice():
    """Source quote with ``title="Estimate"`` → destination invoice
    carries ``title="Invoice"``, not the inherited placeholder."""
    from routers.quotes import convert_quote_to_invoice

    _run(_seed_tenant(TENANT))
    cid = _run(_seed_customer(TENANT))
    qid = _run(_seed_source_quote(tid=TENANT, cid=cid, title="Estimate"))
    out = _run(convert_quote_to_invoice(
        qid, user=_ADMIN, tenant={"id": TENANT},
    ))
    inv = _run(_DB.quotes.find_one({"id": out["invoice_id"]}, {"_id": 0}))
    assert inv["title"] == "Invoice", (
        f"placeholder 'Estimate' should normalise to 'Invoice', "
        f"got title={inv['title']!r}"
    )


def test_convert_quote_custom_title_preserved_verbatim():
    """Custom titles like 'Pool Repair — Main pump' MUST pass through
    unchanged — the placeholder catalogue is deliberately tight."""
    from routers.quotes import convert_quote_to_invoice

    _run(_seed_tenant(TENANT))
    cid = _run(_seed_customer(TENANT))
    qid = _run(_seed_source_quote(
        tid=TENANT, cid=cid, title="Pool Repair — Main pump",
    ))
    out = _run(convert_quote_to_invoice(
        qid, user=_ADMIN, tenant={"id": TENANT},
    ))
    inv = _run(_DB.quotes.find_one({"id": out["invoice_id"]}, {"_id": 0}))
    assert inv["title"] == "Pool Repair — Main pump"


def test_convert_quote_case_insensitive_placeholder_match():
    """Case + whitespace variants ('ESTIMATE', ' estimate ') all
    fold to the same bucket and normalise to 'Invoice'."""
    from routers.quotes import convert_quote_to_invoice

    _run(_seed_tenant(TENANT))
    for variant in ("ESTIMATE", " estimate ", "Quote", "proposal",
                    "New Estimate", "Untitled"):
        cid = _run(_seed_customer(TENANT))
        qid = _run(_seed_source_quote(tid=TENANT, cid=cid, title=variant))
        out = _run(convert_quote_to_invoice(
            qid, user=_ADMIN, tenant={"id": TENANT},
        ))
        inv = _run(_DB.quotes.find_one(
            {"id": out["invoice_id"]}, {"_id": 0},
        ))
        assert inv["title"] == "Invoice", (
            f"variant {variant!r} should normalise to 'Invoice', "
            f"got {inv['title']!r}"
        )


# ═══════════════════════════════════════════════════════════════════
# §2 · Fix B — status flips to "issued" + issued_at stamped
# ═══════════════════════════════════════════════════════════════════
def test_convert_quote_destination_is_issued_not_draft():
    """Converted invoice carries ``status="issued"`` + ``issued_at``.
    The pre-fix contract was ``status="draft"`` which kept converted
    rows out of every Outstanding filter."""
    from routers.quotes import convert_quote_to_invoice

    _run(_seed_tenant(TENANT))
    cid = _run(_seed_customer(TENANT))
    qid = _run(_seed_source_quote(
        tid=TENANT, cid=cid, title="Pool Repair",
    ))
    out = _run(convert_quote_to_invoice(
        qid, user=_ADMIN, tenant={"id": TENANT},
    ))
    inv = _run(_DB.quotes.find_one({"id": out["invoice_id"]}, {"_id": 0}))
    assert inv["status"] == "issued"
    assert inv.get("issued_at"), "issued_at must be stamped"
    assert inv["payment_status"] == "unpaid"
    assert inv["doc_type"] == "invoice"


# ═══════════════════════════════════════════════════════════════════
# §3 · Fix C — payments_summary._LIVE_STATUSES includes "issued"
# ═══════════════════════════════════════════════════════════════════
def test_live_statuses_includes_issued_regression_lock():
    """Source-level invariant on the ``_LIVE_STATUSES`` drift fix."""
    from routers.payments_summary import _LIVE_STATUSES
    assert "issued" in _LIVE_STATUSES
    assert "sent" in _LIVE_STATUSES
    assert "accepted" in _LIVE_STATUSES
    assert "past_due" in _LIVE_STATUSES


def test_converted_invoice_appears_in_payments_summary_outstanding():
    """End-to-end: convert → /api/payments/summary tallies the row
    into outstanding_total + outstanding_count."""
    from routers.payments_summary import payments_summary
    from routers.quotes import convert_quote_to_invoice

    _run(_seed_tenant(TENANT))
    cid = _run(_seed_customer(TENANT))
    qid = _run(_seed_source_quote(
        tid=TENANT, cid=cid, title="Pool Repair",
    ))
    _run(convert_quote_to_invoice(
        qid, user=_ADMIN, tenant={"id": TENANT},
    ))

    res = _run(payments_summary(
        user={"role": "admin", "tenant_id": TENANT},
    ))
    assert res["outstanding_total"] >= 3855.0, (
        f"converted invoice should contribute to outstanding_total "
        f"— got {res['outstanding_total']}"
    )
    assert res["outstanding_count"] >= 1


def test_converted_invoice_appears_in_canonical_outstanding_filter():
    """Canonical AR filter in ``services/reporting/paid_date.py`` MUST
    also pick up the converted row (status=issued is already in its
    allowlist pre-fix; this is a regression lock)."""
    from routers.quotes import convert_quote_to_invoice
    from services.reporting.paid_date import OUTSTANDING_STATUS_FILTER

    _run(_seed_tenant(TENANT))
    cid = _run(_seed_customer(TENANT))
    qid = _run(_seed_source_quote(
        tid=TENANT, cid=cid, title="Pool Repair",
    ))
    out = _run(convert_quote_to_invoice(
        qid, user=_ADMIN, tenant={"id": TENANT},
    ))
    rows = _run(_DB.quotes.find(
        {"tenant_id": TENANT, **OUTSTANDING_STATUS_FILTER},
        {"_id": 0, "id": 1, "status": 1},
    ).to_list(None))
    ids = {r["id"] for r in rows}
    assert out["invoice_id"] in ids


# ═══════════════════════════════════════════════════════════════════
# §4 · Backfill CLI — dry-run / apply / idempotency / scoping
# ═══════════════════════════════════════════════════════════════════
def test_backfill_dry_run_writes_nothing():
    """``--dry-run`` reports candidate counts but makes zero writes
    and does NOT write a sentinel."""
    from migrations.convert_to_invoice_status_backfill_v1 import run

    _run(_seed_tenant(TENANT))
    cid = _run(_seed_customer(TENANT))
    inv_id = _run(_seed_converted_invoice(tid=TENANT, cid=cid))

    res = _run(run(apply=False, tenant_id=TENANT))
    assert res["status"] == "dry-run"
    assert res["stats"]["candidates"] >= 1
    assert res["stats"]["status_moved"] == 0

    inv = _run(_DB.quotes.find_one(
        {"id": inv_id}, {"_id": 0, "status": 1, "title": 1},
    ))
    assert inv["status"] == "draft"
    assert inv["title"] == "Estimate"

    sentinel = _run(_DB["_migrations"].find_one(
        {"key": "convert_to_invoice_status_backfill_v1"},
    ))
    assert sentinel is None


def test_backfill_apply_flips_status_and_repairs_title():
    """``--apply`` flips status to issued, stamps issued_at (prefers
    converted_at), and rewrites placeholder titles."""
    from migrations.convert_to_invoice_status_backfill_v1 import run

    _run(_seed_tenant(TENANT))
    cid = _run(_seed_customer(TENANT))
    inv_est = _run(_seed_converted_invoice(
        tid=TENANT, cid=cid, title="Estimate", status="draft",
    ))
    inv_cust = _run(_seed_converted_invoice(
        tid=TENANT, cid=cid, title="Pool Repair — Main pump",
        status="draft",
    ))

    res = _run(run(apply=True, tenant_id=TENANT, force=True))
    assert res["status"] == "applied"
    assert res["stats"]["status_moved"] >= 2
    assert res["stats"]["title_moved"] >= 1

    i1 = _run(_DB.quotes.find_one({"id": inv_est}, {"_id": 0}))
    assert i1["status"] == "issued"
    assert i1["title"] == "Invoice"
    assert i1["issued_at"] == "2026-10-01T00:00:00+00:00", (
        "issued_at should prefer the row's converted_at stamp"
    )

    i2 = _run(_DB.quotes.find_one({"id": inv_cust}, {"_id": 0}))
    assert i2["status"] == "issued"
    assert i2["title"] == "Pool Repair — Main pump", (
        "custom title must be preserved verbatim"
    )

    sentinel = _run(_DB["_migrations"].find_one(
        {"key": "convert_to_invoice_status_backfill_v1"},
        {"_id": 0},
    ))
    assert sentinel is not None
    assert sentinel["mode"] == "apply"


def test_backfill_apply_is_idempotent_on_rerun():
    """Second apply reports 0 moved."""
    from migrations.convert_to_invoice_status_backfill_v1 import run

    _run(_seed_tenant(TENANT))
    cid = _run(_seed_customer(TENANT))
    _run(_seed_converted_invoice(tid=TENANT, cid=cid))

    res1 = _run(run(apply=True, tenant_id=TENANT, force=True))
    assert res1["stats"]["status_moved"] >= 1

    res2 = _run(run(apply=True, tenant_id=TENANT, force=True))
    assert res2["stats"]["status_moved"] == 0
    assert res2["stats"]["title_moved"] == 0


def test_backfill_skip_title_repair_flag_works():
    """``--skip-title-repair`` flips status but leaves title alone."""
    from migrations.convert_to_invoice_status_backfill_v1 import run

    _run(_seed_tenant(TENANT))
    cid = _run(_seed_customer(TENANT))
    inv_id = _run(_seed_converted_invoice(
        tid=TENANT, cid=cid, title="Estimate", status="draft",
    ))

    res = _run(run(
        apply=True, tenant_id=TENANT, force=True,
        skip_title_repair=True,
    ))
    assert res["stats"]["status_moved"] >= 1
    assert res["stats"]["title_moved"] == 0
    inv = _run(_DB.quotes.find_one({"id": inv_id}, {"_id": 0}))
    assert inv["status"] == "issued"
    assert inv["title"] == "Estimate"   # untouched


def test_backfill_tenant_scope_does_not_bleed():
    """Scoped ``--tenant X`` apply must not touch tenant Y's rows."""
    from migrations.convert_to_invoice_status_backfill_v1 import run

    _run(_seed_tenant(TENANT))
    _run(_seed_tenant(TENANT_B))
    cid_a = _run(_seed_customer(TENANT))
    cid_b = _run(_seed_customer(TENANT_B))
    inv_a = _run(_seed_converted_invoice(
        tid=TENANT, cid=cid_a, title="Estimate", status="draft",
    ))
    inv_b = _run(_seed_converted_invoice(
        tid=TENANT_B, cid=cid_b, title="Estimate", status="draft",
    ))

    res = _run(run(apply=True, tenant_id=TENANT, force=True))

    a = _run(_DB.quotes.find_one({"id": inv_a}, {"_id": 0}))
    assert a["status"] == "issued"
    assert a["title"] == "Invoice"

    b = _run(_DB.quotes.find_one({"id": inv_b}, {"_id": 0}))
    assert b["status"] == "draft", (
        f"tenant isolation leak — tenant B row touched: {b['status']!r}"
    )
    assert b["title"] == "Estimate"

    assert res["stats"]["candidates"] == 1


def test_backfill_mutually_exclusive_flags():
    """``--apply`` + ``--report-only`` MUST raise."""
    from migrations.convert_to_invoice_status_backfill_v1 import run

    with pytest.raises(ValueError):
        _run(run(apply=True, report_only=True))
