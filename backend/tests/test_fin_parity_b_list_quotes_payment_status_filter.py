"""FIN-PARITY-B · Feb-2026 — ``list_quotes`` server-side
``payment_status`` filter.

Locks:

  * payment_status=unpaid returns only unpaid rows.
  * payment_status=partial returns only partial rows.
  * payment_status=paid returns only paid rows.
  * payment_status=all returns everything (sentinel = no filter).
  * payment_status=garbage returns HTTP 400 with a stable
    ``error_code=invalid_payment_status`` in the response body.
  * No param → no filter (current behavior preserved).
  * Soft-delete filter still applies (HD-A).
  * Tenant isolation — never returns another tenant's rows.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import HTTPException

_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(MONGO_URL, io_loop=_LOOP)
_DB = _MC[DB_NAME]

# The list_quotes handler imports its ``db`` from ``config`` at
# module load. To exercise it against our test DB, monkey-patch
# ``routers.quotes.db`` in every test call.
PFX = "TESTfpBq_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _seed_invoice(
    *,
    tenant_id: str,
    payment_status: str,
    doc_type: str = "invoice",
    deleted_at: Optional[str] = None,
) -> str:
    inv_id = f"{PFX}inv_{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": inv_id,
        "tenant_id": tenant_id,
        "doc_type": doc_type,
        "total": 100.0,
        "amount_paid": {
            "unpaid": 0.0, "partial": 25.0, "paid": 100.0,
        }.get(payment_status, 0.0),
        "payment_status": payment_status,
        "status": "sent" if payment_status != "paid" else "accepted",
        "customer_id": f"{PFX}cust_{uuid.uuid4().hex[:6]}",
        "customer_name": "Test Customer",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if deleted_at:
        doc["deleted_at"] = deleted_at
    await _DB.quotes.insert_one(doc)
    return inv_id


async def _wipe():
    await _DB.quotes.delete_many({"id": {"$regex": f"^{PFX}"}})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


TENANT = f"{PFX}tenant_A"
TENANT_B = f"{PFX}tenant_B"


def _call_list_quotes(
    *,
    tenant_id: str,
    payment_status: Optional[str],
    role: str = "admin",
    include_deleted: bool = False,
) -> Any:
    """Direct call into the handler with monkey-patched ``db``."""
    from routers import quotes as quotes_mod

    orig_db = quotes_mod.db
    quotes_mod.db = _DB
    try:
        user = {
            "id": "user_test",
            "role": role,
            "tenant_id": tenant_id,
        }
        tenant = {"id": tenant_id}
        return _run(quotes_mod.list_quotes(
            user=user,
            tenant=tenant,
            doc_type="invoice",
            include_deleted=include_deleted,
            category=None,
            card_on_file=None,
            customer_id=None,
            payment_status=payment_status,
        ))
    finally:
        quotes_mod.db = orig_db


# ═══════════════════════════════════════════════════════════════════
# §1 · Each enum value narrows correctly
# ═══════════════════════════════════════════════════════════════════
def test_payment_status_unpaid_returns_only_unpaid():
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="partial"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="paid"))
    rows = _call_list_quotes(tenant_id=TENANT, payment_status="unpaid")
    assert len(rows) == 1
    assert rows[0]["payment_status"] == "unpaid"


def test_payment_status_partial_returns_only_partial():
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="partial"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="paid"))
    rows = _call_list_quotes(tenant_id=TENANT, payment_status="partial")
    assert len(rows) == 1
    assert rows[0]["payment_status"] == "partial"


def test_payment_status_paid_returns_only_paid():
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="partial"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="paid"))
    rows = _call_list_quotes(tenant_id=TENANT, payment_status="paid")
    assert len(rows) == 1
    assert rows[0]["payment_status"] == "paid"


def test_payment_status_all_returns_every_state():
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="partial"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="paid"))
    rows = _call_list_quotes(tenant_id=TENANT, payment_status="all")
    statuses = sorted(r["payment_status"] for r in rows)
    assert statuses == ["paid", "partial", "unpaid"]


def test_no_payment_status_param_preserves_prior_behavior():
    """Regression guard: omitting the param must return every row
    (identical to ``all``) so pre-FIN-PARITY-B callers keep working."""
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="paid"))
    rows = _call_list_quotes(tenant_id=TENANT, payment_status=None)
    assert len(rows) == 2


# ═══════════════════════════════════════════════════════════════════
# §2 · Garbage input → 400 with stable error_code
# ═══════════════════════════════════════════════════════════════════
def test_payment_status_garbage_raises_400_with_stable_error_code():
    with pytest.raises(HTTPException) as exc_info:
        _call_list_quotes(tenant_id=TENANT, payment_status="garbage")
    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["error_code"] == "invalid_payment_status"
    # Response must expose the accepted enum values so the FE can
    # render a deterministic error toast.
    assert detail["accepted_values"] == ["all", "paid", "partial", "unpaid"]


def test_payment_status_empty_string_rejected():
    """The empty string is NOT one of the enum values — reject with
    the same 400 as any other invalid input (guard against a bug
    where empty query param silently no-ops)."""
    with pytest.raises(HTTPException) as exc_info:
        _call_list_quotes(tenant_id=TENANT, payment_status="")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error_code"] == "invalid_payment_status"


def test_payment_status_case_sensitivity_rejects_uppercase():
    """Enum is lowercase; ``UNPAID`` / ``Paid`` must not sneak
    through. Locks the enum surface."""
    for bad in ("UNPAID", "Paid", "PARTIAL"):
        with pytest.raises(HTTPException) as exc_info:
            _call_list_quotes(tenant_id=TENANT, payment_status=bad)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["error_code"] == "invalid_payment_status"


# ═══════════════════════════════════════════════════════════════════
# §3 · Soft-delete filter still applies (HD-A regression guard)
# ═══════════════════════════════════════════════════════════════════
def test_payment_status_filter_still_hides_soft_deleted_rows():
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(
        tenant_id=TENANT, payment_status="unpaid",
        deleted_at=datetime.now(timezone.utc).isoformat(),
    ))
    rows = _call_list_quotes(tenant_id=TENANT, payment_status="unpaid")
    # Only the non-deleted row lands.
    assert len(rows) == 1
    assert rows[0].get("deleted_at") is None


def test_super_admin_include_deleted_opt_in_still_works():
    """super_admin + include_deleted=1 must return soft-deleted rows
    alongside the filtered payment_status matches."""
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(
        tenant_id=TENANT, payment_status="unpaid",
        deleted_at=datetime.now(timezone.utc).isoformat(),
    ))
    rows = _call_list_quotes(
        tenant_id=TENANT, payment_status="unpaid",
        role="super_admin", include_deleted=True,
    )
    assert len(rows) == 2


# ═══════════════════════════════════════════════════════════════════
# §4 · Tenant isolation
# ═══════════════════════════════════════════════════════════════════
def test_payment_status_filter_respects_tenant_scope():
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(tenant_id=TENANT_B, payment_status="unpaid"))
    rows_a = _call_list_quotes(tenant_id=TENANT, payment_status="unpaid")
    rows_b = _call_list_quotes(tenant_id=TENANT_B, payment_status="unpaid")
    assert all(r["tenant_id"] == TENANT for r in rows_a)
    assert all(r["tenant_id"] == TENANT_B for r in rows_b)
    assert len(rows_a) == 1
    assert len(rows_b) == 1


def test_technician_role_still_forbidden_regardless_of_filter():
    """FIN-PARITY-B does NOT relax the tech-forbidden guard on
    list_quotes. Techs get 403, filter or no filter."""
    with pytest.raises(HTTPException) as exc_info:
        _call_list_quotes(
            tenant_id=TENANT, payment_status="unpaid", role="technician",
        )
    assert exc_info.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# §5 · Filter composes with other list_quotes params
# ═══════════════════════════════════════════════════════════════════
def test_payment_status_composes_with_customer_id_filter():
    """Adding payment_status must not clobber other filter branches."""
    from routers import quotes as quotes_mod

    async def _seed_targeted(customer_id: str, payment_status: str):
        doc = {
            "id": f"{PFX}inv_{uuid.uuid4().hex[:10]}",
            "tenant_id": TENANT,
            "doc_type": "invoice",
            "total": 100.0,
            "amount_paid": 0.0 if payment_status == "unpaid" else 100.0,
            "payment_status": payment_status,
            "status": "sent",
            "customer_id": customer_id,
            "customer_name": "T",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await _DB.quotes.insert_one(doc)

    cid_target = f"{PFX}cust_target"
    cid_other = f"{PFX}cust_other"
    _run(_seed_targeted(cid_target, "unpaid"))
    _run(_seed_targeted(cid_target, "paid"))
    _run(_seed_targeted(cid_other, "unpaid"))

    orig_db = quotes_mod.db
    quotes_mod.db = _DB
    try:
        rows = _run(quotes_mod.list_quotes(
            user={"id": "u", "role": "admin", "tenant_id": TENANT},
            tenant={"id": TENANT},
            doc_type="invoice",
            include_deleted=False,
            category=None,
            card_on_file=None,
            customer_id=cid_target,
            payment_status="unpaid",
        ))
    finally:
        quotes_mod.db = orig_db

    # Composite match: cid_target + unpaid → exactly ONE row.
    assert len(rows) == 1
    assert rows[0]["customer_id"] == cid_target
    assert rows[0]["payment_status"] == "unpaid"
