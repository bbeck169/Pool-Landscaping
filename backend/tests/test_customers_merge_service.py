"""Feb-2026 · customer-merge service — pytest suite.

15 cases per dispatch spec: happy-path per field type, rollback
on each failure point, 24h recurring block, force override,
Stripe failure rollback, cross-tenant protection, confirm_name
mismatch, credit sum, portal-user soft-delete.

Run:
    cd /app/backend && python -m pytest \\
        tests/test_customers_merge_service.py -x -v
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

from services.customers.merge import (
    MergeError,
    _REWIRE_TARGETS,
    merge_customers,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ═════════════════════════════════════════════════════════════
# Mock DB — one list per collection, minimal query ops.
# ═════════════════════════════════════════════════════════════
class _Cur:
    def __init__(self, rows): self._rows = list(rows)
    def __aiter__(self):
        async def _g():
            for r in self._rows:
                yield r
        return _g()


class _Coll:
    def __init__(self):
        self.rows: List[Dict[str, Any]] = []
        self._fail_update_many = False
    def find(self, q, proj=None):
        return _Cur([r for r in self.rows if _m(r, q)])
    async def find_one(self, q, proj=None):
        for r in self.rows:
            if _m(r, q):
                return dict(r)
        return None
    async def insert_one(self, doc):
        self.rows.append(dict(doc))
        return type("I", (), {"inserted_id": doc.get("id")})()
    async def update_one(self, q, u):
        for r in self.rows:
            if _m(r, q):
                for k, v in (u.get("$set") or {}).items():
                    r[k] = v
                return type("U", (), {"matched_count": 1,
                                         "modified_count": 1})()
        return type("U", (), {"matched_count": 0,
                                 "modified_count": 0})()
    async def update_many(self, q, u):
        if self._fail_update_many:
            raise RuntimeError("simulated collection failure")
        n = 0
        for r in self.rows:
            if _m(r, q):
                for k, v in (u.get("$set") or {}).items():
                    r[k] = v
                n += 1
        return type("U", (), {"matched_count": n,
                                 "modified_count": n})()
    async def delete_one(self, q):
        for i, r in enumerate(self.rows):
            if _m(r, q):
                del self.rows[i]
                return type("D", (), {"deleted_count": 1})()
        return type("D", (), {"deleted_count": 0})()
    async def create_index(self, *a, **k): return "idx"


def _m(row, q):
    for k, v in q.items():
        if isinstance(v, dict):
            if "$in" in v:
                if row.get(k) not in v["$in"]:
                    return False
                continue
            if "$ne" in v:
                if row.get(k) == v["$ne"]:
                    return False
                continue
        else:
            if row.get(k) != v:
                return False
    return True


class _DB:
    def __init__(self):
        # Create a collection object per rewire target + the
        # core ones.  Access via __getitem__ hits a fresh _Coll
        # on miss so unused collections stay empty.
        self._colls: Dict[str, _Coll] = {}
        for name in (
            "customers", "users", "payment_methods",
            "customer_merge_audit", "audit_logs",
            "credit_ledger", "credit_balances",
        ):
            setattr(self, name, _Coll())
            self._colls[name] = getattr(self, name)
    def __getitem__(self, name):
        if not hasattr(self, name):
            setattr(self, name, _Coll())
            self._colls[name] = getattr(self, name)
        return getattr(self, name)
    def __getattr__(self, name):
        # Called ONLY when normal attribute lookup misses (e.g.
        # the merge service does ``db.recurring_job_templates``).
        # Auto-vivify a fresh empty collection so tests don't
        # have to pre-register every rewire target.
        if name.startswith("_"):
            raise AttributeError(name)
        coll = _Coll()
        self.__dict__[name] = coll
        self.__dict__["_colls"][name] = coll
        return coll


def _mkcust(db, **kw):
    base = {
        "tenant_id": "t1", "is_active": True, "is_muted": False,
        "deleted_at": None, "created_at": "2026-02-01T00:00:00Z",
        "name": "", "phone": "", "email": "",
    }
    base.update(kw)
    db.customers.rows.append(base)


# Stub ``compute_customer_balance`` + ``mutate_credit`` so the
# merge path exercises its code without hitting the real ledger
# plumbing.  Shim lives on a mutable dict so tests can tweak
# the loser's balance per scenario.
_BALANCES: Dict[str, int] = {}


@pytest.fixture(autouse=True)
def _patch_balance(monkeypatch):
    from services import customer_balance as cb
    _BALANCES.clear()
    async def _compute(db, *, tenant_id, customer_id):
        return _BALANCES.get(customer_id, 0)
    async def _mutate(db, tenant_id, customer_id, **kw):
        _BALANCES[customer_id] = (
            _BALANCES.get(customer_id, 0) + kw["delta_cents"]
        )
        return {"status": "applied", "balance_cents":
                 _BALANCES[customer_id]}
    monkeypatch.setattr(cb, "compute_customer_balance", _compute)
    monkeypatch.setattr(cb, "mutate_credit", _mutate)
    yield


# ═════════════════════════════════════════════════════════════
# 15 cases
# ═════════════════════════════════════════════════════════════
async def test_01_happy_path_scalar_field_override():
    db = _DB()
    _mkcust(db, id="w", name="Winner")
    _mkcust(db, id="l", name="Loser Ltd")
    res = await merge_customers(
        db=db, tenant_id="t1", winner_id="w", loser_id="l",
        field_overrides={"email": "merged@example.com",
                           "phone": "555-1111"},
        actor={"id": "u1"}, confirm_name="loser ltd",
    )
    winner = next(r for r in db.customers.rows if r["id"] == "w")
    assert winner["email"] == "merged@example.com"
    assert winner["phone"] == "555-1111"
    assert res.audit_id


async def test_02_loser_soft_deleted_with_merged_into():
    db = _DB()
    _mkcust(db, id="w", name="W")
    _mkcust(db, id="l", name="L")
    await merge_customers(
        db=db, tenant_id="t1", winner_id="w", loser_id="l",
        actor={"id": "u1"}, confirm_name="l",
    )
    loser = next(r for r in db.customers.rows if r["id"] == "l")
    assert loser["merged_into"] == "w"
    assert loser["deleted_at"]


async def test_03_confirm_name_mismatch_raises():
    db = _DB()
    _mkcust(db, id="w", name="W")
    _mkcust(db, id="l", name="Loser")
    with pytest.raises(MergeError) as exc:
        await merge_customers(
            db=db, tenant_id="t1", winner_id="w", loser_id="l",
            confirm_name="not matching",
        )
    assert exc.value.error_code == "merge_confirm_name_mismatch"


async def test_04_confirm_name_case_and_ampersand_canonical():
    db = _DB()
    _mkcust(db, id="w", name="W")
    _mkcust(db, id="l", name="Joe & Jane Smith")
    res = await merge_customers(
        db=db, tenant_id="t1", winner_id="w", loser_id="l",
        confirm_name="JOE and JANE SMITH",
    )
    assert res.audit_id


async def test_05_cross_tenant_blocked():
    db = _DB()
    _mkcust(db, id="w", name="W", tenant_id="t1")
    _mkcust(db, id="l", name="L", tenant_id="t2")
    with pytest.raises(MergeError) as exc:
        await merge_customers(
            db=db, tenant_id="t1", winner_id="w", loser_id="l",
            confirm_name="l",
        )
    assert exc.value.error_code == "merge_customer_not_found"


async def test_06_same_customer_rejected():
    db = _DB()
    _mkcust(db, id="w", name="W")
    with pytest.raises(MergeError) as exc:
        await merge_customers(
            db=db, tenant_id="t1", winner_id="w", loser_id="w",
            confirm_name="w",
        )
    assert exc.value.error_code == "merge_invalid_same_customer"


async def test_07_24h_recurring_block_surfaces_template_ids():
    db = _DB()
    _mkcust(db, id="w", name="W")
    _mkcust(db, id="l", name="L")
    today = datetime.now(timezone.utc).date().isoformat()
    db["recurring_job_templates"].rows.append({
        "id": "tpl-1", "tenant_id": "t1", "customer_id": "l",
        "last_generated_through": today, "deleted_at": None,
    })
    with pytest.raises(MergeError) as exc:
        await merge_customers(
            db=db, tenant_id="t1", winner_id="w", loser_id="l",
            confirm_name="l",
        )
    assert exc.value.error_code == "merge_blocked_recent_recurring_activity"
    assert exc.value.detail["blocking_templates"][0]["template_id"] == "tpl-1"
    assert exc.value.detail["override_available"] is True


async def test_08_force_bypasses_24h_block():
    db = _DB()
    _mkcust(db, id="w", name="W")
    _mkcust(db, id="l", name="L")
    today = datetime.now(timezone.utc).date().isoformat()
    db["recurring_job_templates"].rows.append({
        "id": "tpl-1", "tenant_id": "t1", "customer_id": "l",
        "last_generated_through": today, "deleted_at": None,
    })
    res = await merge_customers(
        db=db, tenant_id="t1", winner_id="w", loser_id="l",
        confirm_name="l", force=True,
    )
    assert res.audit_id


async def test_09_child_records_reassigned_to_winner():
    db = _DB()
    _mkcust(db, id="w", name="W")
    _mkcust(db, id="l", name="L")
    db["jobs"].rows.append({"id": "j1", "tenant_id": "t1",
                               "customer_id": "l"})
    db["quotes"].rows.append({"id": "q1", "tenant_id": "t1",
                                 "customer_id": "l",
                                 "doc_type": "invoice"})
    db["payments"].rows.append({"id": "p1", "tenant_id": "t1",
                                   "customer_id": "l"})
    await merge_customers(
        db=db, tenant_id="t1", winner_id="w", loser_id="l",
        confirm_name="l",
    )
    assert db["jobs"].rows[0]["customer_id"] == "w"
    assert db["quotes"].rows[0]["customer_id"] == "w"
    assert db["payments"].rows[0]["customer_id"] == "w"


async def test_10_credit_sum_mutates_both_sides():
    db = _DB()
    _mkcust(db, id="w", name="W")
    _mkcust(db, id="l", name="L")
    _BALANCES["l"] = 500  # loser has $5.00 in credit
    res = await merge_customers(
        db=db, tenant_id="t1", winner_id="w", loser_id="l",
        confirm_name="l",
    )
    assert res.credit_merged_cents == 500
    assert _BALANCES["l"] == 0
    assert _BALANCES["w"] == 500


async def test_11_portal_user_soft_deleted():
    db = _DB()
    _mkcust(db, id="w", name="W")
    _mkcust(db, id="l", name="L")
    db.users.rows.append({"id": "u-portal", "tenant_id": "t1",
                             "customer_id": "l", "deleted_at": None})
    res = await merge_customers(
        db=db, tenant_id="t1", winner_id="w", loser_id="l",
        confirm_name="l",
    )
    assert res.portal_user_soft_deleted is True
    assert db.users.rows[0]["deleted_at"]


async def test_12_collection_failure_triggers_rollback():
    db = _DB()
    _mkcust(db, id="w", name="W")
    _mkcust(db, id="l", name="L")
    db["jobs"].rows.append({"id": "j1", "tenant_id": "t1",
                               "customer_id": "l"})
    # Simulate failure on the ``payments`` collection — jobs
    # was already flipped and MUST be reversed.
    db["payments"].rows.append({"id": "p1", "tenant_id": "t1",
                                   "customer_id": "l"})
    db["payments"]._fail_update_many = True
    with pytest.raises(MergeError) as exc:
        await merge_customers(
            db=db, tenant_id="t1", winner_id="w", loser_id="l",
            confirm_name="l",
        )
    assert exc.value.error_code == "merge_rewire_failed"
    assert exc.value.detail["collection"] == "payments"
    # Rollback flipped jobs back to loser.
    assert db["jobs"].rows[0]["customer_id"] == "l"
    # Audit row was deleted on rollback.
    assert len(db.customer_merge_audit.rows) == 0
    # Loser customer NOT soft-deleted (merge aborted pre-final).
    loser = next(r for r in db.customers.rows if r["id"] == "l")
    assert not loser.get("merged_into")


async def test_13_stripe_remap_failure_full_rollback(monkeypatch):
    db = _DB()
    _mkcust(db, id="w", name="W", stripe_customer_id="cus_w")
    _mkcust(db, id="l", name="L", stripe_customer_id="cus_l")
    db["payment_methods"].rows.append({
        "id": "pm1", "tenant_id": "t1", "customer_id": "l",
        "stripe_payment_method_id": "pm_abc",
    })
    _BALANCES["l"] = 200
    # Patch Stripe modify to raise so the merge rolls back
    # EVERYTHING: credit, overrides, rewire.
    def _fail_stripe_modify(*a, **k):
        raise RuntimeError("stripe boom")
    import services.payments.stripe_charge as sc
    async def _to_thread_async(fn, *a, **k):
        return fn(*a, **k)
    monkeypatch.setattr(sc, "_to_thread", _to_thread_async)
    import stripe as _stripe
    monkeypatch.setattr(
        _stripe.PaymentMethod, "modify", _fail_stripe_modify,
    )
    with pytest.raises(MergeError) as exc:
        await merge_customers(
            db=db, tenant_id="t1", winner_id="w", loser_id="l",
            confirm_name="l",
        )
    assert exc.value.error_code == "merge_stripe_remap_failed"
    # Credit restored.
    assert _BALANCES["l"] == 200
    assert _BALANCES.get("w", 0) == 0
    # Audit row deleted.
    assert len(db.customer_merge_audit.rows) == 0


async def test_14_stripe_remap_blocked_when_winner_missing_sid():
    db = _DB()
    _mkcust(db, id="w", name="W")  # No stripe_customer_id
    _mkcust(db, id="l", name="L", stripe_customer_id="cus_l")
    db["payment_methods"].rows.append({
        "id": "pm1", "tenant_id": "t1", "customer_id": "l",
        "stripe_payment_method_id": "pm_abc",
    })
    with pytest.raises(MergeError) as exc:
        await merge_customers(
            db=db, tenant_id="t1", winner_id="w", loser_id="l",
            confirm_name="l",
        )
    assert exc.value.error_code == "merge_blocked_stripe_winner_missing"


async def test_15_audit_row_carries_full_snapshot_and_expiry():
    db = _DB()
    _mkcust(db, id="w", name="W", email="w@x")
    _mkcust(db, id="l", name="L", email="l@x")
    db["jobs"].rows.append({"id": "j1", "tenant_id": "t1",
                               "customer_id": "l"})
    res = await merge_customers(
        db=db, tenant_id="t1", winner_id="w", loser_id="l",
        actor={"id": "admin1"}, confirm_name="l",
    )
    audit = db.customer_merge_audit.rows[0]
    assert audit["id"] == res.audit_id
    assert audit["winner_id"] == "w"
    assert audit["loser_id"] == "l"
    assert audit["actor_id"] == "admin1"
    assert audit["loser_snapshot"]["email"] == "l@x"
    assert audit["winner_snapshot"]["email"] == "w@x"
    assert audit["child_record_ids"]["jobs"] == ["j1"]
    assert audit["child_record_counts"]["jobs"] == 1
    # 90-day retention — expires_at > merged_at.
    assert audit["expires_at"] > audit["merged_at"]
    # ``customer_merge.executed`` audit_logs row written.
    exec_rows = [r for r in db.audit_logs.rows
                  if r.get("action") == "customer_merge.executed"]
    assert len(exec_rows) == 1
    assert exec_rows[0]["audit_id"] == res.audit_id
