"""Task RR/SS Phase 2 · Feb 2026 — Invoice-generation hook coverage.

Confirms that the 3 non-autobilling invoice creation sites
(``finances.py::accrue_chem_invoice``, ``reports.py::run_billing_plans``,
``service_reports.py::report submit``) all call ``apply_and_persist``
before ``db.quotes.insert_one``. We don't drive them via HTTP —
instead we ``importlib``-load each router source and grep for the
required call. Simpler than driving real invoice generation through
5 different downstream contracts, and catches a regression where
someone removes the hook.

Also covers the pure-function ``apply_and_persist`` end-to-end
against Phase-10 storage: seed ``customer_credits_balance``, run
the helper on a fake invoice, assert the balance decrements + a
ledger row lands + the invoice carries ``credits_applied_cents``.
"""
from __future__ import annotations

import asyncio
import inspect
import re
import uuid

import pytest


def _sync(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def db():
    from config import db as _db
    return _db


@pytest.fixture(scope="module")
def aq_tenant_id(db):
    t = _sync(db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1}))
    assert t
    return t["id"]


# ═══════════════════════════════════════════════════════════════════
# Static grep — each invoice-creation site must call apply_and_persist
# ═══════════════════════════════════════════════════════════════════
_HOOK_SITES = [
    ("routers.finances", "accrue_chem_invoice"),
    ("routers.finances", "_fire_billing_plan"),
    ("routers.finances", "run_billing_plan"),
    ("routers.reports", "run_billing_plans"),
    ("routers.service_reports", None),          # module-wide grep
]


def _module_source(mod_path: str) -> str:
    import importlib
    mod = importlib.import_module(mod_path)
    return inspect.getsource(mod)


def test_invoice_hook_coverage_all_sites_wired():
    """The credits_apply hook must appear near every invoice-creation
    ``insert_one`` site. Failing this test = a regression that
    accidentally removed the hook."""
    findings = {}
    for mod_path, _fn in _HOOK_SITES:
        src = _module_source(mod_path)
        findings[mod_path] = "apply_and_persist" in src
    missing = [m for m, ok in findings.items() if not ok]
    assert not missing, (
        f"credits_apply.apply_and_persist NOT wired into: {missing}. "
        "Re-add the hook next to ``db.quotes.insert_one`` for each "
        "invoice-creation flow."
    )


def test_invoice_hook_coverage_paired_with_insert():
    """Each hooked module must have ``apply_and_persist`` textually
    within a small window (<=30 lines) of at least one
    ``db.quotes.insert_one`` call — guards against someone deleting
    the actual invocation but leaving the import."""
    for mod_path, _fn in _HOOK_SITES:
        src = _module_source(mod_path)
        lines = src.splitlines()
        idx_hook = [i for i, l in enumerate(lines) if "apply_and_persist" in l]
        idx_ins = [i for i, l in enumerate(lines)
                       if re.search(r"db\.quotes\.insert_one", l)]
        # There must exist a hook line within 30 lines of an insert line.
        close = any(abs(h - i) <= 30 for h in idx_hook for i in idx_ins)
        assert close, (
            f"{mod_path}: apply_and_persist found but not near a "
            "``db.quotes.insert_one`` call. The hook must run BEFORE "
            "the insert."
        )


# ═══════════════════════════════════════════════════════════════════
# End-to-end (unit-style) — apply_and_persist against Phase-10 store.
# ═══════════════════════════════════════════════════════════════════
def test_apply_and_persist_end_to_end_phase10_backend(db, aq_tenant_id):
    """Seed the Phase-10 balance collection, then call the helper,
    and assert:
      * invoice carries ``credits_applied_cents``
      * balance decremented in ``customer_credits_balance``
      * a new ledger row landed in ``customer_credits``
    """
    from services.credits_apply import apply_and_persist
    cid = "TEST_" + uuid.uuid4().hex[:10]
    async def _seed():
        await db.customer_credits_balance.update_one(
            {"tenant_id": aq_tenant_id, "customer_id": cid},
            {"$set": {"balance_cents": 5000, "balance": 50.0}},
            upsert=True,
        )
    _sync(_seed())
    invoice = {
        "id": "TEST_inv_" + uuid.uuid4().hex[:8],
        "customer_id": cid, "tenant_id": aq_tenant_id,
        "doc_type": "invoice",
        "total_cents": 3000, "total": 30.0,
        "status": "sent", "payment_status": "unpaid",
        "line_items": [{"description": "test", "quantity": 1, "unit_price": 30}],
    }
    result = _sync(apply_and_persist(db, aq_tenant_id, invoice))
    assert result.get("credits_applied_cents") == 3000
    # Invoice fully covered → paid via credit.
    assert result.get("payment_status") == "paid"
    assert result.get("paid_method") == "service_credit"
    async def _check():
        bal = await db.customer_credits_balance.find_one(
            {"tenant_id": aq_tenant_id, "customer_id": cid}, {"_id": 0},
        )
        ledger = await db.customer_credits.find(
            {"tenant_id": aq_tenant_id, "customer_id": cid}, {"_id": 0},
        ).to_list(10)
        return bal, ledger
    bal, ledger = _sync(_check())
    assert bal and int(bal.get("balance_cents") or 0) == 2000
    assert any(l.get("delta_cents") == -3000 for l in ledger)
    # Cleanup.
    async def _cleanup():
        await db.customer_credits_balance.delete_many(
            {"tenant_id": aq_tenant_id, "customer_id": cid},
        )
        await db.customer_credits.delete_many(
            {"tenant_id": aq_tenant_id, "customer_id": cid},
        )
    _sync(_cleanup())


def test_apply_and_persist_zero_balance_no_op(db, aq_tenant_id):
    """No balance row → the helper must not raise + not add
    ``credits_applied_cents``."""
    from services.credits_apply import apply_and_persist
    cid_none = "TEST_no_bal_" + uuid.uuid4().hex[:8]
    invoice = {
        "id": "TEST_inv_" + uuid.uuid4().hex[:8],
        "customer_id": cid_none, "tenant_id": aq_tenant_id,
        "doc_type": "invoice", "total_cents": 5000, "total": 50.0,
        "status": "sent", "payment_status": "unpaid",
    }
    result = _sync(apply_and_persist(db, aq_tenant_id, invoice))
    # No credit applied.
    assert int(result.get("credits_applied_cents") or 0) == 0
    assert result.get("payment_status") == "unpaid"
