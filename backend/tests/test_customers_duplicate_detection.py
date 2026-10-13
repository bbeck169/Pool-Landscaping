"""Feb-2026 · duplicate-customer detection — pytest suite.

10 cases per dispatch spec covering each match criterion + group
formation + tenant isolation + perf WARN threshold.

Run:
    cd /app/backend && python -m pytest \\
        tests/test_customers_duplicate_detection.py -x -v
"""
from __future__ import annotations

import logging

import pytest

from services.customers.duplicate_detection import (
    _FUZZY_SWEEP_CUSTOMER_CEILING,
    detect_duplicates,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ═════════════════════════════════════════════════════════════
# Mock DB — minimum-viable, mirrors the ladder test's shape.
# ═════════════════════════════════════════════════════════════
class _MockCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def __aiter__(self):
        async def _gen():
            for r in self._rows:
                yield r
        return _gen()


class _MockCollection:
    def __init__(self):
        self.rows = []

    def find(self, query, projection=None):
        return _MockCursor([r for r in self.rows if _match(r, query)])


def _match(row, query):
    for k, v in query.items():
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


class _MockDB:
    def __init__(self):
        self.customers = _MockCollection()


def _add(db, *, cid, name="", email="", phone="", tenant_id="t1",
          is_active=True, is_muted=False, deleted_at=None,
          created_at="2026-02-01T00:00:00Z"):
    db.customers.rows.append({
        "id": cid, "tenant_id": tenant_id, "name": name,
        "email": email, "phone": phone,
        "is_active": is_active, "is_muted": is_muted,
        "deleted_at": deleted_at, "created_at": created_at,
    })


# ═════════════════════════════════════════════════════════════
# 10 cases
# ═════════════════════════════════════════════════════════════
async def test_01_exact_name_match_groups_two():
    db = _MockDB()
    _add(db, cid="a", name="Joe Kail")
    _add(db, cid="b", name="joe  kail")  # case + whitespace variant
    groups = await detect_duplicates(db=db, tenant_id="t1")
    assert len(groups) == 1
    assert "name_exact" in groups[0].match_reasons
    assert {c.id for c in groups[0].customers} == {"a", "b"}


async def test_02_exact_phone_normalizes_formats():
    db = _MockDB()
    _add(db, cid="a", name="Alice",   phone="(555) 123-4567")
    _add(db, cid="b", name="Diff Name", phone="555.123.4567")
    groups = await detect_duplicates(db=db, tenant_id="t1")
    assert len(groups) == 1
    assert groups[0].match_reasons == ["phone"]


async def test_03_exact_email_case_insensitive():
    db = _MockDB()
    _add(db, cid="a", name="X", email="Joe@Example.COM")
    _add(db, cid="b", name="Y", email="joe@example.com")
    groups = await detect_duplicates(db=db, tenant_id="t1")
    assert len(groups) == 1
    assert groups[0].match_reasons == ["email"]


async def test_04_fuzzy_name_one_edit_groups():
    db = _MockDB()
    _add(db, cid="a", name="Joe Kail")
    _add(db, cid="b", name="Joe Kayl")  # 1-char typo
    groups = await detect_duplicates(db=db, tenant_id="t1")
    assert len(groups) == 1
    assert "name_fuzzy" in groups[0].match_reasons


async def test_05_substring_name_fuzzy_matches():
    db = _MockDB()
    _add(db, cid="a", name="Joe Kail")
    _add(db, cid="b", name="Joe Kail Pool Service")
    groups = await detect_duplicates(db=db, tenant_id="t1")
    assert len(groups) == 1
    assert "name_fuzzy" in groups[0].match_reasons


async def test_06_three_customers_linked_via_different_predicates():
    """A linked to B by email, B linked to C by phone — all three
    collapse into one group via union-find."""
    db = _MockDB()
    _add(db, cid="a", name="Joe K", email="shared@example.com")
    _add(db, cid="b", name="Joe K2", email="shared@example.com",
            phone="555-111-2222")
    _add(db, cid="c", name="Joe K3", phone="(555) 111-2222")
    groups = await detect_duplicates(db=db, tenant_id="t1")
    assert len(groups) == 1
    assert {c.id for c in groups[0].customers} == {"a", "b", "c"}
    # Group carries BOTH reasons that linked members pairs.
    assert "email" in groups[0].match_reasons
    assert "phone" in groups[0].match_reasons


async def test_07_tenant_isolation():
    """Customers in different tenants never co-group."""
    db = _MockDB()
    _add(db, cid="a", name="Joe Kail", tenant_id="t1")
    _add(db, cid="b", name="Joe Kail", tenant_id="t2")
    groups_t1 = await detect_duplicates(db=db, tenant_id="t1")
    groups_t2 = await detect_duplicates(db=db, tenant_id="t2")
    assert groups_t1 == []
    assert groups_t2 == []


async def test_08_soft_deleted_excluded():
    """Soft-deleted rows never anchor or join a group."""
    db = _MockDB()
    _add(db, cid="a", name="Joe Kail")
    _add(db, cid="b", name="Joe Kail", deleted_at="2026-01-01T00:00:00Z")
    groups = await detect_duplicates(db=db, tenant_id="t1")
    assert groups == []


async def test_09_inactive_and_muted_included_by_default():
    """Default status_scope covers all three — Duplicates tab
    surfaces every lifecycle flag so operators can clean up
    legacy duplicates."""
    db = _MockDB()
    _add(db, cid="a", name="Joe Kail", is_active=True)
    _add(db, cid="b", name="Joe Kail", is_active=False)   # inactive
    _add(db, cid="c", name="Joe Kail", is_muted=True)     # muted
    groups = await detect_duplicates(db=db, tenant_id="t1")
    assert len(groups) == 1
    ids = {c.id for c in groups[0].customers}
    assert ids == {"a", "b", "c"}
    status_by_id = {c.id: c.status for c in groups[0].customers}
    assert status_by_id == {"a": "active", "b": "inactive",
                             "c": "muted"}


async def test_10_perf_warn_above_fuzzy_ceiling(caplog):
    """>10K customers skips the fuzzy sweep + logs a WARN.
    Exact tiers still run.  The WARN carries the structured
    kind= prefix the ops runbook greps for.
    """
    db = _MockDB()
    N = _FUZZY_SWEEP_CUSTOMER_CEILING + 2
    # First N-2 customers all share a unique name so they never
    # exact-collide.  Last two share a phone so we assert the
    # exact tier still ran.
    for i in range(N - 2):
        _add(db, cid=f"c{i}", name=f"Unique Name {i}")
    _add(db, cid="phoneA", name="Alice",   phone="555-999-0000")
    _add(db, cid="phoneB", name="Bob",     phone="(555) 999-0000")
    with caplog.at_level(logging.WARNING,
                          logger="customers.duplicate_detection"):
        groups = await detect_duplicates(db=db, tenant_id="t1")
    assert any("kind=perf.fuzzy_skipped" in rec.message
                for rec in caplog.records)
    # Exact tiers still produced the phone group.
    assert len(groups) == 1
    assert groups[0].match_reasons == ["phone"]
    assert {c.id for c in groups[0].customers} == {"phoneA", "phoneB"}
