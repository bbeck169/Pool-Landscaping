"""Phase 1 · Feb-2026 — Convert-to-Invoice pytest suite.

Covers both endpoints added in this phase:
    * POST /api/quotes/{qid}/convert-to-invoice
    * POST /api/estimates/{eid}/convert-to-invoice

**Loop-isolation note (2026-10-02):** This codebase binds its
Motor client at ``config`` module-import time to whatever event
loop happens to be current then. That loop is NOT the loop
``asyncio.new_event_loop()`` creates in the test module. So we
monkeypatch ``config.db`` + every module-level ``db`` alias the
handler + its downstream helpers reach, pointing all of them at
a single ``AsyncIOMotorClient`` bound to the test loop. Without
this patch, every DB-touching call raises
``RuntimeError: got Future ... attached to a different loop``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


# ─── Loop-isolation monkeypatch — runs ONCE at module import ──
# Patch every module-level ``db`` reference the handler + its
# downstream helpers reach, so they ALL hit the test's loop-bound
# client (``_DB``) rather than the config-module client (bound to
# a different loop).
def _patch_db_everywhere():
    import config
    config.db = _DB
    # Reach into every importer that aliased ``db`` at module load.
    import routers.quotes as _quotes_mod
    _quotes_mod.db = _DB
    import routers.estimates as _estimates_mod
    _estimates_mod.db = _DB
    import services.invoice_builder as _ib_mod
    _ib_mod.db = _DB
    import services.invoice_numbering as _inum_mod
    _inum_mod.db = _DB
    import routers.finances as _fin_mod
    _fin_mod.db = _DB


# NOTE: Phase 2 isolation fix (Feb-2026) — the module-scope
# ``_patch_db_everywhere()`` call used to live right here. It was
# hoisted into the ``_clean`` autouse fixture below (same pattern as
# the three Phase 2 B1 test files) so that running this file in the
# SAME pytest invocation as ``test_quote_lead_recipient.py`` et al.
# no longer clobbers either side's module-level ``db`` aliases at
# collection time. See the "RuntimeError: got Future … attached to
# a different loop" post-mortem.


PREFIX = f"testconvinv-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
TENANT_B = f"{PREFIX}-tenant-b"


# ─── Seed / cleanup helpers ─────────────────────────────────────
async def _seed_tenant(tid: str) -> None:
    await _DB.tenants.insert_one({
        "id": tid, "name": f"Tenant {tid}",
        "timezone": "America/Phoenix", "settings": {},
    })


async def _seed_customer(cid: str, tid: str, name: str = "Jane Doe") -> None:
    await _DB.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": name,
        "email": f"{cid}@example.com",
    })


async def _seed_quote(*, qid: str, tenant_id: str, customer_id: str,
                      status: str = "accepted", line_items=None,
                      scheduled_job_id=None,
                      converted_invoice_id=None) -> None:
    doc = {
        "id": qid, "tenant_id": tenant_id, "customer_id": customer_id,
        "customer_name": "Jane Doe",
        "doc_type": "quote",
        "title": "Weekly pool service",
        "status": status, "payment_status": "unpaid",
        "line_items": line_items if line_items is not None else [
            {"id": f"{qid}-li-1", "description": "Weekly service",
             "quantity": 4, "unit_price": 55.00, "category": "Labor"},
            {"id": f"{qid}-li-2", "description": "Chlorine",
             "quantity": 2, "unit_price": 25.50, "category": "Chemical"},
        ],
        "tax_rate": 8.0,
        "subtotal": 271.00, "tax": 21.68, "total": 292.68,
        "amount_paid": 0.0, "notes": "Monthly plan",
        "terms": "Due on receipt",
        "scheduled_job_id": scheduled_job_id,
        "converted_invoice_id": converted_invoice_id,
    }
    await _DB.quotes.insert_one(doc)


async def _seed_estimate(*, eid: str, tenant_id: str, customer_id: str,
                         sell_price: float = 450.00,
                         converted_invoice_id=None) -> None:
    await _DB.estimates.insert_one({
        "id": eid, "tenant_id": tenant_id, "customer_id": customer_id,
        "customer_name": "Jane Doe", "title": "Pump replacement",
        "line_items": [], "status": "draft",
        "sell_price": sell_price,
        "direct_cost": 300.0, "overhead_amount": 45.0,
        "total_cost": 345.0, "profit_amount": 105.0,
        "gross_margin_pct": 23.33,
        "overhead_pct": 15.0, "margin_pct": 30.0,
        "notes": "", "terms": "Net 30",
        "converted_invoice_id": converted_invoice_id,
    })


async def _seed_job_with_invoice(*, qid: str, job_id: str, inv_id: str,
                                   tenant_id: str, customer_id: str) -> None:
    """Simulate the auto-invoice pipeline tail: a job scheduled from
    the quote + an invoice linked via scheduled_job_id."""
    await _DB.jobs.insert_one({
        "id": job_id, "tenant_id": tenant_id,
        "customer_id": customer_id,
        "source_quote_id": qid,
        "auto_invoice_id": inv_id,
        "status": "completed",
    })
    await _DB.quotes.insert_one({
        "id": inv_id, "tenant_id": tenant_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "scheduled_job_id": job_id, "job_id": job_id,
        "status": "issued", "payment_status": "unpaid",
        "line_items": [], "total": 0.0,
    })


async def _cleanup() -> None:
    rx = {"$regex": f"^{PREFIX}"}
    await _DB.quotes.delete_many({"$or": [{"id": rx}, {"tenant_id": rx}]})
    await _DB.estimates.delete_many({"$or": [{"id": rx}, {"tenant_id": rx}]})
    await _DB.customers.delete_many({"id": rx})
    await _DB.tenants.delete_many({"id": rx})
    await _DB.jobs.delete_many({"$or": [{"id": rx}, {"tenant_id": rx}]})
    await _DB.audit_logs.delete_many({"tenant_id": rx})
    await _DB.invoice_number_sequences.delete_many({"tenant_id": rx})
    await _DB.settings.delete_many({"tenant_id": rx})


@pytest.fixture(autouse=True)
def _clean():
    # Re-pin loop-bound ``db`` aliases on every test — otherwise a
    # cross-file pytest collection can leave ``config.db`` + its
    # module-level aliases pointing at a client bound to another
    # file's event loop (see note above).
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


# ─── Users for role-matrix tests ────────────────────────────────
_ADMIN = {"id": f"{PREFIX}-user-admin", "role": "admin"}
_MANAGER = {"id": f"{PREFIX}-user-manager", "role": "manager"}
_OWNER = {"id": f"{PREFIX}-user-owner", "role": "owner"}
_SUPER_ADMIN = {"id": f"{PREFIX}-user-sadmin", "role": "super_admin"}
_TECH = {"id": f"{PREFIX}-user-tech", "role": "technician"}
_CUSTOMER = {"id": f"{PREFIX}-user-cust", "role": "customer"}


# ═══════════════════════════════════════════════════════════════════
# 1 · require_admin_or_manager role matrix (unit)
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("user,should_pass", [
    (_ADMIN, True),
    (_MANAGER, True),
    (_OWNER, True),
    (_SUPER_ADMIN, True),
    (_TECH, False),
    (_CUSTOMER, False),
    ({"id": "u-no-role"}, False),
])
def test_require_admin_or_manager_role_matrix(user, should_pass):
    from utils import require_admin_or_manager
    if should_pass:
        assert require_admin_or_manager(user) is user
    else:
        with pytest.raises(HTTPException) as exc:
            require_admin_or_manager(user)
        assert exc.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# 2 · Quote happy path — creates invoice + marks source
# ═══════════════════════════════════════════════════════════════════
def test_quote_happy_path_creates_invoice_and_marks_source():
    qid = f"{PREFIX}-q-happy"
    cid = f"{PREFIX}-cust-happy"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(cid, TENANT_A))
    _run(_seed_quote(qid=qid, tenant_id=TENANT_A, customer_id=cid))

    from routers.quotes import convert_quote_to_invoice
    out = _run(convert_quote_to_invoice(
        qid, user=_ADMIN, tenant={"id": TENANT_A},
    ))
    assert "invoice_id" in out
    assert out["invoice_id"]
    assert out["invoice_number"]
    assert out["invoice_number"].startswith("INV-")

    inv = _run(_DB.quotes.find_one({"id": out["invoice_id"]}, {"_id": 0}))
    assert inv["doc_type"] == "invoice"
    assert inv["tenant_id"] == TENANT_A
    assert inv["customer_id"] == cid
    assert inv["source"] == "convert_from_quote"
    assert inv["source_quote_id"] == qid
    # TD-estimate-to-invoice-conversion-doctype-and-balance · Feb-2026
    # — converted invoices now carry status="issued" (was "draft")
    # so they land in the Outstanding tile immediately. See
    # ``services/invoice_builder.py`` Fix B.
    assert inv["status"] == "issued"
    assert inv["issued_at"]
    assert inv["payment_status"] == "unpaid"
    assert len(inv["line_items"]) == 2
    assert inv["tax_rate"] == 8.0
    assert abs(inv["subtotal"] - 271.00) < 0.01
    assert abs(inv["tax"] - 21.68) < 0.01
    assert abs(inv["total"] - 292.68) < 0.01
    src_line_ids = {f"{qid}-li-1", f"{qid}-li-2"}
    inv_line_ids = {li["id"] for li in inv["line_items"]}
    assert src_line_ids.isdisjoint(inv_line_ids)

    src_after = _run(_DB.quotes.find_one({"id": qid}, {"_id": 0}))
    assert src_after["converted_invoice_id"] == out["invoice_id"]
    assert src_after["converted_by"] == _ADMIN["id"]
    assert src_after["converted_at"]
    assert src_after["status"] == "accepted"


# ═══════════════════════════════════════════════════════════════════
# 3 · Direct double-conversion returns 409
# ═══════════════════════════════════════════════════════════════════
def test_quote_direct_double_conversion_returns_409():
    qid = f"{PREFIX}-q-dbldir"
    cid = f"{PREFIX}-cust-dbldir"
    existing_inv = f"{PREFIX}-inv-existing-direct"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(cid, TENANT_A))
    _run(_seed_quote(qid=qid, tenant_id=TENANT_A, customer_id=cid,
                     converted_invoice_id=existing_inv))

    from routers.quotes import convert_quote_to_invoice
    with pytest.raises(HTTPException) as exc:
        _run(convert_quote_to_invoice(
            qid, user=_ADMIN, tenant={"id": TENANT_A},
        ))
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "already_converted"
    assert detail["invoice_id"] == existing_inv


# ═══════════════════════════════════════════════════════════════════
# 4 · Indirect double-conversion via job pipeline returns 409
# ═══════════════════════════════════════════════════════════════════
def test_quote_indirect_double_conversion_via_job_returns_409():
    qid = f"{PREFIX}-q-dblind"
    cid = f"{PREFIX}-cust-dblind"
    sched_job_id = f"{PREFIX}-job-sched"
    pipeline_inv_id = f"{PREFIX}-inv-pipeline"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(cid, TENANT_A))
    _run(_seed_quote(qid=qid, tenant_id=TENANT_A, customer_id=cid,
                     scheduled_job_id=sched_job_id))
    _run(_seed_job_with_invoice(
        qid=qid, job_id=sched_job_id, inv_id=pipeline_inv_id,
        tenant_id=TENANT_A, customer_id=cid,
    ))

    from routers.quotes import convert_quote_to_invoice
    with pytest.raises(HTTPException) as exc:
        _run(convert_quote_to_invoice(
            qid, user=_ADMIN, tenant={"id": TENANT_A},
        ))
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert detail["code"] == "already_converted"
    assert detail["invoice_id"] == pipeline_inv_id


# ═══════════════════════════════════════════════════════════════════
# 5 · Cross-tenant returns 404
# ═══════════════════════════════════════════════════════════════════
def test_quote_cross_tenant_returns_404():
    qid = f"{PREFIX}-q-xten"
    cid = f"{PREFIX}-cust-xten"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_tenant(TENANT_B))
    _run(_seed_customer(cid, TENANT_A))
    _run(_seed_quote(qid=qid, tenant_id=TENANT_A, customer_id=cid))

    from routers.quotes import convert_quote_to_invoice
    with pytest.raises(HTTPException) as exc:
        _run(convert_quote_to_invoice(
            qid, user=_ADMIN, tenant={"id": TENANT_B},
        ))
    assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 6 · Not-found returns 404
# ═══════════════════════════════════════════════════════════════════
def test_quote_not_found_returns_404():
    _run(_seed_tenant(TENANT_A))
    from routers.quotes import convert_quote_to_invoice
    with pytest.raises(HTTPException) as exc:
        _run(convert_quote_to_invoice(
            f"{PREFIX}-q-does-not-exist",
            user=_ADMIN, tenant={"id": TENANT_A},
        ))
    assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 7 · Converting a doc already of type "invoice" returns 400
# ═══════════════════════════════════════════════════════════════════
def test_quote_converting_an_invoice_returns_400():
    qid = f"{PREFIX}-q-isinv"
    cid = f"{PREFIX}-cust-isinv"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(cid, TENANT_A))
    _run(_DB.quotes.insert_one({
        "id": qid, "tenant_id": TENANT_A, "customer_id": cid,
        "doc_type": "invoice", "status": "issued",
        "line_items": [], "total": 0.0,
    }))

    from routers.quotes import convert_quote_to_invoice
    with pytest.raises(HTTPException) as exc:
        _run(convert_quote_to_invoice(
            qid, user=_ADMIN, tenant={"id": TENANT_A},
        ))
    assert exc.value.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# 8 · Estimate happy path — single-line sell_price collapse
# ═══════════════════════════════════════════════════════════════════
def test_estimate_happy_path_single_line_collapse_sell_price():
    eid = f"{PREFIX}-e-happy"
    cid = f"{PREFIX}-cust-eha"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(cid, TENANT_A))
    _run(_seed_estimate(eid=eid, tenant_id=TENANT_A,
                        customer_id=cid, sell_price=1250.0))

    from routers.estimates import convert_estimate_to_invoice
    out = _run(convert_estimate_to_invoice(
        eid, user=_ADMIN, tenant={"id": TENANT_A},
    ))
    assert out["invoice_id"]
    assert out["invoice_number"].startswith("INV-")

    inv = _run(_DB.quotes.find_one({"id": out["invoice_id"]}, {"_id": 0}))
    assert inv["doc_type"] == "invoice"
    assert inv["source"] == "convert_from_estimate"
    assert inv["source_estimate_id"] == eid
    assert len(inv["line_items"]) == 1
    li = inv["line_items"][0]
    assert li["description"] == "Pump replacement"
    assert li["quantity"] == 1
    assert li["unit_price"] == 1250.0
    assert inv["tax_rate"] == 0.0
    assert abs(inv["subtotal"] - 1250.0) < 0.01
    assert abs(inv["tax"] - 0.0) < 0.01
    assert abs(inv["total"] - 1250.0) < 0.01

    src_after = _run(_DB.estimates.find_one({"id": eid}, {"_id": 0}))
    assert src_after["converted_invoice_id"] == out["invoice_id"]


# ═══════════════════════════════════════════════════════════════════
# 9 · Estimate double-conversion returns 409 (same shape as quotes)
# ═══════════════════════════════════════════════════════════════════
def test_estimate_double_conversion_returns_409_same_shape():
    eid = f"{PREFIX}-e-dbl"
    cid = f"{PREFIX}-cust-edbl"
    existing_inv = f"{PREFIX}-inv-existing-est"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(cid, TENANT_A))
    _run(_seed_estimate(eid=eid, tenant_id=TENANT_A, customer_id=cid,
                        converted_invoice_id=existing_inv))

    from routers.estimates import convert_estimate_to_invoice
    with pytest.raises(HTTPException) as exc:
        _run(convert_estimate_to_invoice(
            eid, user=_ADMIN, tenant={"id": TENANT_A},
        ))
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "already_converted"
    assert detail["invoice_id"] == existing_inv


# ═══════════════════════════════════════════════════════════════════
# 10 · Estimate with no sell_price returns 400
# ═══════════════════════════════════════════════════════════════════
def test_estimate_zero_sell_price_returns_400():
    eid = f"{PREFIX}-e-zero"
    cid = f"{PREFIX}-cust-ezero"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(cid, TENANT_A))
    _run(_seed_estimate(eid=eid, tenant_id=TENANT_A, customer_id=cid,
                        sell_price=0.0))

    from routers.estimates import convert_estimate_to_invoice
    with pytest.raises(HTTPException) as exc:
        _run(convert_estimate_to_invoice(
            eid, user=_ADMIN, tenant={"id": TENANT_A},
        ))
    assert exc.value.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# 11 · Estimate cross-tenant returns 404
# ═══════════════════════════════════════════════════════════════════
def test_estimate_cross_tenant_returns_404():
    eid = f"{PREFIX}-e-xten"
    cid = f"{PREFIX}-cust-exten"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_tenant(TENANT_B))
    _run(_seed_customer(cid, TENANT_A))
    _run(_seed_estimate(eid=eid, tenant_id=TENANT_A, customer_id=cid))

    from routers.estimates import convert_estimate_to_invoice
    with pytest.raises(HTTPException) as exc:
        _run(convert_estimate_to_invoice(
            eid, user=_ADMIN, tenant={"id": TENANT_B},
        ))
    assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 12 · Line-item fidelity — tax + subtotal + total copied accurately
# ═══════════════════════════════════════════════════════════════════
def test_quote_line_item_fidelity_totals_and_tax():
    qid = f"{PREFIX}-q-fid"
    cid = f"{PREFIX}-cust-fid"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(cid, TENANT_A))
    custom_lines = [
        {"id": f"{qid}-l1", "description": "Install pump",
         "quantity": 1, "unit_price": 650.00, "category": "Labor"},
        {"id": f"{qid}-l2", "description": "Variable-speed pump",
         "quantity": 1, "unit_price": 850.00, "category": "Equipment"},
        {"id": f"{qid}-l3", "description": "Fittings",
         "quantity": 5, "unit_price": 12.50, "category": "Material"},
    ]
    _run(_seed_quote(qid=qid, tenant_id=TENANT_A, customer_id=cid,
                     line_items=custom_lines))
    _run(_DB.quotes.update_one(
        {"id": qid},
        {"$set": {"tax_rate": 7.0, "subtotal": 1562.50,
                   "tax": 109.38, "total": 1671.88}},
    ))

    from routers.quotes import convert_quote_to_invoice
    out = _run(convert_quote_to_invoice(
        qid, user=_ADMIN, tenant={"id": TENANT_A},
    ))
    inv = _run(_DB.quotes.find_one({"id": out["invoice_id"]}, {"_id": 0}))
    assert len(inv["line_items"]) == 3
    assert inv["tax_rate"] == 7.0
    assert abs(inv["subtotal"] - 1562.50) < 0.01
    assert abs(inv["tax"] - 109.38) < 0.02
    assert abs(inv["total"] - 1671.88) < 0.02
    descs = {li["description"] for li in inv["line_items"]}
    assert "Install pump" in descs
    assert "Variable-speed pump" in descs
    assert "Fittings" in descs


# ═══════════════════════════════════════════════════════════════════
# 13 · Manager role allowed on the live endpoint
# ═══════════════════════════════════════════════════════════════════
def test_quote_manager_role_allowed():
    qid = f"{PREFIX}-q-mgr"
    cid = f"{PREFIX}-cust-mgr"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(cid, TENANT_A))
    _run(_seed_quote(qid=qid, tenant_id=TENANT_A, customer_id=cid))

    from routers.quotes import convert_quote_to_invoice
    out = _run(convert_quote_to_invoice(
        qid, user=_MANAGER, tenant={"id": TENANT_A},
    ))
    assert out["invoice_id"]
    inv = _run(_DB.quotes.find_one({"id": out["invoice_id"]}, {"_id": 0}))
    assert inv["doc_type"] == "invoice"


# ═══════════════════════════════════════════════════════════════════
# 14 · Audit log row written on successful convert
# ═══════════════════════════════════════════════════════════════════
def test_quote_convert_writes_audit_log_row():
    qid = f"{PREFIX}-q-audit"
    cid = f"{PREFIX}-cust-audit"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(cid, TENANT_A))
    _run(_seed_quote(qid=qid, tenant_id=TENANT_A, customer_id=cid))

    from routers.quotes import convert_quote_to_invoice
    out = _run(convert_quote_to_invoice(
        qid, user=_ADMIN, tenant={"id": TENANT_A},
    ))
    audit = _run(_DB.audit_logs.find_one({
        "event": "quote.convert_to_invoice",
        "source_id": qid,
        "tenant_id": TENANT_A,
    }, {"_id": 0}))
    assert audit is not None
    assert audit["invoice_id"] == out["invoice_id"]
    assert audit["actor_id"] == _ADMIN["id"]
