"""Feb-2026 · merge history + rollback — pytest suite.

6 cases: 5 per dispatch spec + 1 operator-locked edge case
(``rollback_preserves_post_merge_activity_on_winner``).

Reuses the merge-service test harness patterns (``_DB``, ``_Coll``,
``_patch_balance`` fixture) via inline duplication so this file
stays runnable standalone.

Run:
    cd /app/backend && python -m pytest \\
        tests/test_customers_merge_history_rollback.py -x -v
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

from services.customers.merge import (
    MergeError,
    merge_customers,
    rollback_merge,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ═════════════════════════════════════════════════════════════
# Mock DB — same shape as test_customers_merge_service.py.
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
        if k == "$or":
            # Any sub-clause match ok.
            if not any(_m(row, sub) for sub in v):
                return False
            continue
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
# Setup helper — perform a merge + return its audit_id so each
# rollback test starts from a known-good forward merge.
# ═════════════════════════════════════════════════════════════
async def _do_merge(db, *, winner_id="w", loser_id="l",
                     loser_name="L", loser_credit=0,
                     winner_name="W",
                     jobs: List[str] = None):
    _mkcust(db, id=winner_id, name=winner_name)
    _mkcust(db, id=loser_id, name=loser_name)
    for jid in (jobs or []):
        db["jobs"].rows.append({
            "id": jid, "tenant_id": "t1", "customer_id": loser_id,
        })
    if loser_credit:
        _BALANCES[loser_id] = loser_credit
    res = await merge_customers(
        db=db, tenant_id="t1", winner_id=winner_id,
        loser_id=loser_id, actor={"id": "admin1"},
        confirm_name=loser_name,
    )
    return res.audit_id


# ═════════════════════════════════════════════════════════════
# 6 cases
# ═════════════════════════════════════════════════════════════
async def test_01_history_fetch_lists_merges_as_winner_or_loser():
    """GET /customers/{id}/merge-history returns rows where the
    customer is winner OR loser, newest-first.
    """
    db = _DB()
    audit_id = await _do_merge(
        db, winner_id="w", loser_id="l", loser_name="L",
    )
    # Simulate the endpoint's query shape directly.
    cursor = db.customer_merge_audit.find(
        {"tenant_id": "t1",
          "$or": [{"winner_id": "w"}, {"loser_id": "w"}]},
    )
    rows = []
    async for r in cursor:
        rows.append(r)
    assert len(rows) == 1
    assert rows[0]["id"] == audit_id
    assert rows[0]["winner_id"] == "w"
    assert rows[0]["loser_id"] == "l"
    # Loser-side query returns the same row.
    cursor = db.customer_merge_audit.find(
        {"tenant_id": "t1",
          "$or": [{"winner_id": "l"}, {"loser_id": "l"}]},
    )
    rows2 = []
    async for r in cursor:
        rows2.append(r)
    assert len(rows2) == 1
    assert rows2[0]["id"] == audit_id


async def test_02_rollback_happy_path_reverses_everything():
    """Rollback within 90d reverses rewire + credit + loser
    customer soft-delete + portal user + marks audit row rolled
    back.
    """
    db = _DB()
    audit_id = await _do_merge(
        db, winner_id="w", loser_id="l", loser_name="L",
        loser_credit=400, jobs=["j1", "j2"],
    )
    # Portal user existed and was soft-deleted by the merge.
    # (The merge test harness handles this when a users row
    # exists; add one BEFORE calling rollback — actually, we
    # need to re-create via the merge path.  Easier: inject a
    # fresh portal user row with the merge's marker so the
    # rollback helper reverses it.)
    db.users.rows.append({
        "id": "u-portal", "tenant_id": "t1", "customer_id": "l",
        "deleted_at": "2026-02-01T00:00:00Z",
        "deleted_by_user_id": "customer_merge",
    })
    # Tell the audit the merge soft-deleted this user so the
    # rollback helper restores it.
    audit = next(r for r in db.customer_merge_audit.rows
                  if r["id"] == audit_id)
    audit["portal_user_soft_deleted"] = True
    res = await rollback_merge(
        db=db, tenant_id="t1", audit_id=audit_id,
        actor={"id": "admin2"},
    )
    # Child records flipped back to loser.
    assert all(r["customer_id"] == "l" for r in db["jobs"].rows)
    # Credit restored.
    assert _BALANCES["l"] == 400
    assert _BALANCES.get("w", 0) == 0
    # Loser customer no longer soft-deleted.
    loser = next(r for r in db.customers.rows if r["id"] == "l")
    assert loser.get("deleted_at") is None
    assert loser.get("merged_into") is None
    # Portal user restored.
    assert res.portal_user_restored is True
    assert db.users.rows[0]["deleted_at"] is None
    # Audit row carries rolled_back_at + rolled_back_by.
    audit_after = next(r for r in db.customer_merge_audit.rows
                        if r["id"] == audit_id)
    assert audit_after["rolled_back_at"]
    assert audit_after["rolled_back_by"] == "admin2"
    # Greppable audit_logs row written.
    rollback_logs = [r for r in db.audit_logs.rows
                       if r.get("action") == "customer_merge.rolled_back"]
    assert len(rollback_logs) == 1


async def test_03_rollback_after_90_days_raises_expired():
    """Rollback outside the 90-day window raises
    ``merge_rollback_expired`` (surfaces as HTTP 403 at the
    router).
    """
    db = _DB()
    audit_id = await _do_merge(
        db, winner_id="w", loser_id="l", loser_name="L",
    )
    # Backdate the audit's expires_at to the past.
    audit = next(r for r in db.customer_merge_audit.rows
                  if r["id"] == audit_id)
    audit["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).isoformat()
    with pytest.raises(MergeError) as exc:
        await rollback_merge(
            db=db, tenant_id="t1", audit_id=audit_id,
            actor={"id": "admin1"},
        )
    assert exc.value.error_code == "merge_rollback_expired"


async def test_04_rollback_on_already_rolled_back_raises():
    """Rollback on an audit row that already carries
    ``rolled_back_at`` raises ``merge_rollback_already_done``
    (HTTP 409).
    """
    db = _DB()
    audit_id = await _do_merge(
        db, winner_id="w", loser_id="l", loser_name="L",
    )
    # First rollback succeeds.
    await rollback_merge(
        db=db, tenant_id="t1", audit_id=audit_id,
        actor={"id": "admin1"},
    )
    # Second rollback is a conflict.
    with pytest.raises(MergeError) as exc:
        await rollback_merge(
            db=db, tenant_id="t1", audit_id=audit_id,
            actor={"id": "admin1"},
        )
    assert exc.value.error_code == "merge_rollback_already_done"


async def test_05_rollback_cross_tenant_returns_not_found():
    """Rollback against the wrong tenant raises
    ``merge_rollback_not_found`` (HTTP 404).  Guards against
    one tenant inadvertently reversing another tenant's merge.
    """
    db = _DB()
    audit_id = await _do_merge(
        db, winner_id="w", loser_id="l", loser_name="L",
    )
    with pytest.raises(MergeError) as exc:
        await rollback_merge(
            db=db, tenant_id="t_OTHER", audit_id=audit_id,
            actor={"id": "admin1"},
        )
    assert exc.value.error_code == "merge_rollback_not_found"


async def test_06_rollback_preserves_post_merge_activity_on_winner():
    """Operator-locked edge case: new activity assigned to the
    winner AFTER the merge stays on the winner on rollback.
    The reverse-rewire ONLY flips the ids captured in the
    audit's ``child_record_ids`` snapshot — anything created
    on the winner post-merge is never in the snapshot.
    """
    db = _DB()
    audit_id = await _do_merge(
        db, winner_id="w", loser_id="l", loser_name="L",
        jobs=["j_pre1", "j_pre2"],
    )
    # Simulate operator creating a NEW job on the winner between
    # the merge and the rollback (e.g. a new invoice for the
    # merged customer's property).  This job's id was NEVER in
    # the audit snapshot.
    db["jobs"].rows.append({
        "id": "j_post_merge", "tenant_id": "t1",
        "customer_id": "w",
    })
    await rollback_merge(
        db=db, tenant_id="t1", audit_id=audit_id,
        actor={"id": "admin1"},
    )
    jobs_by_id = {r["id"]: r for r in db["jobs"].rows}
    # Pre-merge jobs flipped back to loser.
    assert jobs_by_id["j_pre1"]["customer_id"] == "l"
    assert jobs_by_id["j_pre2"]["customer_id"] == "l"
    # Post-merge job STAYS on the winner.
    assert jobs_by_id["j_post_merge"]["customer_id"] == "w"
