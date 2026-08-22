"""Feb-2026 · P40 — customer-list tab-count == pagination-total consistency.

The prod bug report showed a Muted tab with badge "MUTED 4" while the
list envelope reported "Showing 1-7 of 7". Root cause turned out to
be a frontend cache-staleness issue (tab-count effect fired once on
mount and was never re-invoked after mute actions), NOT a backend
predicate divergence. Both branches of the customers-list endpoint
share the same ``q`` predicate dict, so ``count_documents(q)`` in
the ``count_only=true`` branch and ``count_documents(q)`` in the
pagination-``total`` computation are byte-identical.

This suite pins that invariant so a future refactor can't sneak in a
divergent predicate. For each tab we seed a specific customer mix,
fire the two endpoint shapes, and assert ``count == total``.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"

_TAG = "TEST_p40_"


def _login(email="admin@aquaterra.com", pw="password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]


def _seed(tid: str, *, is_active: bool = True, is_muted: bool = False,
            n: int = 1) -> list[str]:
    """Insert ``n`` customers with the given cohort flags. IDs and
    names are prefixed with ``TEST_p40_`` so the ``search`` filter
    isolates them from other tenants' data."""
    prefix = f"{_TAG}{'act' if is_active else 'inact'}"
    prefix += "_mut" if is_muted else "_nom"
    docs = []
    ids = []
    for i in range(1, n + 1):
        cid = f"{prefix}_{uuid.uuid4().hex[:6]}_{i:03d}"
        ids.append(cid)
        d = {
            "id": cid, "tenant_id": tid,
            "name": f"{prefix}_{i:03d}",
            "is_active": is_active,
            "phone": "+15555550100", "email": f"{cid}@example.com",
            "address": "1 Test Way",
            "created_at": "2026-06-01T09:00:00+00:00",
        }
        if is_muted:
            d["is_muted"] = True
            d["muted_at"] = "2026-06-01T10:00:00+00:00"
        docs.append(d)
    _sync.customers.insert_many(docs)
    return ids


@pytest.fixture(autouse=True)
def _cleanup(aquaterra_tid):
    def _reset():
        _sync.customers.delete_many(
            {"tenant_id": aquaterra_tid, "id": {"$regex": f"^{_TAG}"}})
    _reset()
    yield
    _reset()


def _count(admin_h, params: str) -> int:
    """Fire ``GET /api/customers?...&count_only=true`` and return
    the ``count`` field."""
    sep = "&" if "?" in params else "?"
    url = f"{API}/customers{params}{sep}count_only=true"
    r = requests.get(url, headers=admin_h, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["count"]


def _total(admin_h, params: str) -> tuple[int, int]:
    """Fire ``GET /api/customers?...&page=1&page_size=500`` and
    return ``(total, len(items))``."""
    sep = "&" if "?" in params else "?"
    url = f"{API}/customers{params}{sep}page=1&page_size=500"
    r = requests.get(url, headers=admin_h, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    return body["total"], len(body["items"])


# ═════════════════════════════════════════════════════════════════════
# Per-tab consistency. Seed 2 active+nom, 3 inactive+nom, 5 muted
# (mix of 2 active+muted + 3 inactive+muted). Verify every tab's
# ``count_only`` matches the paginated ``total`` AND the number of
# items returned.
# ═════════════════════════════════════════════════════════════════════
def test_active_tab_count_matches_total(admin_h, aquaterra_tid):
    _seed(aquaterra_tid, is_active=True, is_muted=False, n=2)
    _seed(aquaterra_tid, is_active=False, is_muted=False, n=3)
    _seed(aquaterra_tid, is_active=True, is_muted=True, n=2)
    _seed(aquaterra_tid, is_active=False, is_muted=True, n=3)

    params = f"?search={_TAG}&is_active=true"
    cnt = _count(admin_h, params)
    tot, items = _total(admin_h, params)
    assert cnt == tot == items == 2, (
        f"Active tab drift: count={cnt} total={tot} items={items} "
        f"(expected 2; muted+active rows must NOT leak in)")


def test_inactive_tab_count_matches_total(admin_h, aquaterra_tid):
    _seed(aquaterra_tid, is_active=True, is_muted=False, n=2)
    _seed(aquaterra_tid, is_active=False, is_muted=False, n=3)
    _seed(aquaterra_tid, is_active=True, is_muted=True, n=2)
    _seed(aquaterra_tid, is_active=False, is_muted=True, n=3)

    params = f"?search={_TAG}&is_active=false"
    cnt = _count(admin_h, params)
    tot, items = _total(admin_h, params)
    assert cnt == tot == items == 3, (
        f"Inactive tab drift: count={cnt} total={tot} items={items} "
        f"(expected 3; muted+inactive rows must NOT leak in)")


def test_muted_tab_count_matches_total(admin_h, aquaterra_tid):
    """Prod-bug pin. 5 muted (2 active, 3 inactive) → tab count and
    envelope total must both equal 5."""
    _seed(aquaterra_tid, is_active=True, is_muted=False, n=2)
    _seed(aquaterra_tid, is_active=False, is_muted=False, n=3)
    _seed(aquaterra_tid, is_active=True, is_muted=True, n=2)
    _seed(aquaterra_tid, is_active=False, is_muted=True, n=3)

    params = f"?search={_TAG}&is_muted=true"
    cnt = _count(admin_h, params)
    tot, items = _total(admin_h, params)
    assert cnt == tot == items == 5, (
        f"MUTED TAB DRIFT (the prod bug): count={cnt} total={tot} "
        f"items={items} — count_only branch and pagination branch "
        f"disagree on the muted predicate. Both must return 5 "
        f"(all muted rows regardless of is_active).")


def test_all_tab_count_matches_total(admin_h, aquaterra_tid):
    """"All" tab — no is_active / is_muted filter. Includes muted +
    non-muted, active + inactive. Total should be 2+3+2+3 = 10."""
    _seed(aquaterra_tid, is_active=True, is_muted=False, n=2)
    _seed(aquaterra_tid, is_active=False, is_muted=False, n=3)
    _seed(aquaterra_tid, is_active=True, is_muted=True, n=2)
    _seed(aquaterra_tid, is_active=False, is_muted=True, n=3)

    params = f"?search={_TAG}"
    cnt = _count(admin_h, params)
    tot, items = _total(admin_h, params)
    assert cnt == tot == items == 10, (
        f"All-tab drift: count={cnt} total={tot} items={items} "
        f"(expected 10 with no tab filter)")


# ═════════════════════════════════════════════════════════════════════
# Predicate-share invariant — the count and total branches must call
# ``count_documents`` with an identical predicate. Rather than
# introspecting the router internals, we exercise the "muted +
# search" combination and prove both paths return the same number
# for every seeded distribution.
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("mix", [
    (0, 0, 5, 0),   # only active+muted
    (0, 0, 0, 5),   # only inactive+muted
    (0, 0, 3, 2),   # mixed
    (2, 3, 5, 0),   # every non-muted cohort + active+muted
])
def test_muted_count_and_total_agree_across_mixes(admin_h, aquaterra_tid, mix):
    n_act, n_inact, n_amut, n_imut = mix
    if n_act:
        _seed(aquaterra_tid, is_active=True, is_muted=False, n=n_act)
    if n_inact:
        _seed(aquaterra_tid, is_active=False, is_muted=False, n=n_inact)
    if n_amut:
        _seed(aquaterra_tid, is_active=True, is_muted=True, n=n_amut)
    if n_imut:
        _seed(aquaterra_tid, is_active=False, is_muted=True, n=n_imut)

    expected_muted = n_amut + n_imut
    params = f"?search={_TAG}&is_muted=true"
    cnt = _count(admin_h, params)
    tot, items = _total(admin_h, params)
    assert cnt == tot == items == expected_muted, (
        f"Muted drift on mix={mix}: count={cnt} total={tot} "
        f"items={items} expected={expected_muted}")


def test_active_and_inactive_exclude_muted_rows(admin_h, aquaterra_tid):
    """Directly assert the P32 muted-exclusivity invariant: an
    Active-tab count must equal Inactive-tab count plus muted-tab
    count only if muted rows are exclusive to the muted tab. Here
    we prove non-muted-Active + non-muted-Inactive + muted == total
    (no double counting)."""
    _seed(aquaterra_tid, is_active=True, is_muted=False, n=2)
    _seed(aquaterra_tid, is_active=False, is_muted=False, n=3)
    _seed(aquaterra_tid, is_active=True, is_muted=True, n=2)
    _seed(aquaterra_tid, is_active=False, is_muted=True, n=3)

    active_cnt = _count(admin_h, f"?search={_TAG}&is_active=true")
    inactive_cnt = _count(admin_h, f"?search={_TAG}&is_active=false")
    muted_cnt = _count(admin_h, f"?search={_TAG}&is_muted=true")
    all_cnt = _count(admin_h, f"?search={_TAG}")

    assert active_cnt + inactive_cnt + muted_cnt == all_cnt, (
        f"Cohorts overlap or leak: active={active_cnt} "
        f"inactive={inactive_cnt} muted={muted_cnt} all={all_cnt}")
    # And each individual pair still equals its pagination total.
    assert active_cnt == _total(admin_h, f"?search={_TAG}&is_active=true")[0]
    assert inactive_cnt == _total(admin_h, f"?search={_TAG}&is_active=false")[0]
    assert muted_cnt == _total(admin_h, f"?search={_TAG}&is_muted=true")[0]


# ═════════════════════════════════════════════════════════════════════
# Feb-2026 · P40 addendum — Active-tab positive-path exclusivity,
# soft-delete guard, deactivation flow, and the ultimate math check.
# ═════════════════════════════════════════════════════════════════════
def test_active_tab_exclusivity_across_mute_action(admin_h, aquaterra_tid):
    """Seed A + B active+not-muted and C active+muted. Active tab
    starts at 2 (A + B; C excluded). Mute B via the real endpoint —
    Active drops to 1, Muted rises to 2, and every list envelope
    still equals its count."""
    a_ids = _seed(aquaterra_tid, is_active=True, is_muted=False, n=2)
    _seed(aquaterra_tid, is_active=True, is_muted=True, n=1)

    # Starting cohorts.
    assert _count(admin_h, f"?search={_TAG}&is_active=true") == 2
    assert _count(admin_h, f"?search={_TAG}&is_muted=true") == 1
    active_tot, active_items = _total(admin_h, f"?search={_TAG}&is_active=true")
    assert active_tot == active_items == 2
    muted_tot, muted_items = _total(admin_h, f"?search={_TAG}&is_muted=true")
    assert muted_tot == muted_items == 1

    # Mute customer B via the real ``PATCH /customers/{B}/mute`` path.
    b_id = a_ids[1]
    r = requests.patch(f"{API}/customers/{b_id}/mute",
                          headers=admin_h,
                          json={"muted_reason": "P40 test"},
                          timeout=15)
    assert r.status_code == 200, r.text

    # Post-mute cohorts.
    assert _count(admin_h, f"?search={_TAG}&is_active=true") == 1, (
        "Active count did not decrement after mute — P32 exclusivity broken")
    assert _count(admin_h, f"?search={_TAG}&is_muted=true") == 2, (
        "Muted count did not increment after mute")
    # Pagination totals agree with counts.
    a_tot, a_items = _total(admin_h, f"?search={_TAG}&is_active=true")
    m_tot, m_items = _total(admin_h, f"?search={_TAG}&is_muted=true")
    assert a_tot == a_items == 1
    assert m_tot == m_items == 2


def test_active_tab_excludes_soft_deleted_customers(admin_h, aquaterra_tid):
    """Seed customer D active+not-muted, then soft-delete it. Active
    count must NOT change from pre-delete → post-delete because
    ``not_deleted_filter()`` is applied identically on both count
    and total branches."""
    _seed(aquaterra_tid, is_active=True, is_muted=False, n=1)
    d_ids = _seed(aquaterra_tid, is_active=True, is_muted=False, n=1)

    pre_active = _count(admin_h, f"?search={_TAG}&is_active=true")
    assert pre_active == 2

    # Soft-delete D via the real endpoint. DELETE stamps ``deleted_at``
    # on the customer row.
    d_id = d_ids[0]
    r = requests.delete(f"{API}/customers/{d_id}", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text

    post_active = _count(admin_h, f"?search={_TAG}&is_active=true")
    assert post_active == pre_active - 1, (
        f"Soft-deleted row leaked into Active tab: pre={pre_active} "
        f"post={post_active}")
    # Pagination total agrees.
    a_tot, a_items = _total(admin_h, f"?search={_TAG}&is_active=true")
    assert a_tot == a_items == post_active


def test_active_tab_excludes_deactivated_customer(admin_h, aquaterra_tid):
    """Seed customer E as active, deactivate via the real endpoint,
    then verify E left the Active tab and joined the Inactive tab."""
    e_ids = _seed(aquaterra_tid, is_active=True, is_muted=False, n=1)
    _seed(aquaterra_tid, is_active=False, is_muted=False, n=1)

    pre_active = _count(admin_h, f"?search={_TAG}&is_active=true")
    pre_inactive = _count(admin_h, f"?search={_TAG}&is_active=false")
    assert pre_active == 1
    assert pre_inactive == 1

    # Deactivate E via the P56.2 activation endpoint.
    e_id = e_ids[0]
    r = requests.patch(f"{API}/customers/{e_id}/activation",
                          headers=admin_h,
                          json={"is_active": False},
                          timeout=15)
    assert r.status_code == 200, r.text

    post_active = _count(admin_h, f"?search={_TAG}&is_active=true")
    post_inactive = _count(admin_h, f"?search={_TAG}&is_active=false")
    assert post_active == pre_active - 1, (
        f"Deactivated row still counted as Active: pre={pre_active} "
        f"post={post_active}")
    assert post_inactive == pre_inactive + 1, (
        f"Deactivated row did NOT appear in Inactive: pre={pre_inactive} "
        f"post={post_inactive}")
    # Pagination totals agree with counts.
    a_tot, _ = _total(admin_h, f"?search={_TAG}&is_active=true")
    i_tot, _ = _total(admin_h, f"?search={_TAG}&is_active=false")
    assert a_tot == post_active
    assert i_tot == post_inactive


def test_all_tab_math_check_ultimate_exclusivity_pin(admin_h, aquaterra_tid):
    """The ultimate exclusivity invariant: with no soft-deleted rows
    in the fixture,

        active_count + inactive_count + muted_count == all_count

    If any tab double-counts or loses a row, this equation breaks.
    Run across three different seed distributions to catch off-by-one
    bugs (e.g. a boundary condition where the muted cohort splits
    3/2 vs 2/3 by active flag)."""
    for mix in [
        (2, 3, 2, 3),   # Prod-representative — matches the report.
        (0, 0, 0, 5),   # Only inactive+muted (worst-case muted).
        (5, 0, 5, 0),   # Only active side.
    ]:
        n_act, n_inact, n_amut, n_imut = mix
        _sync.customers.delete_many(
            {"tenant_id": aquaterra_tid, "id": {"$regex": f"^{_TAG}"}})
        if n_act:
            _seed(aquaterra_tid, is_active=True, is_muted=False, n=n_act)
        if n_inact:
            _seed(aquaterra_tid, is_active=False, is_muted=False, n=n_inact)
        if n_amut:
            _seed(aquaterra_tid, is_active=True, is_muted=True, n=n_amut)
        if n_imut:
            _seed(aquaterra_tid, is_active=False, is_muted=True, n=n_imut)

        active_cnt = _count(admin_h, f"?search={_TAG}&is_active=true")
        inactive_cnt = _count(admin_h, f"?search={_TAG}&is_active=false")
        muted_cnt = _count(admin_h, f"?search={_TAG}&is_muted=true")
        all_cnt = _count(admin_h, f"?search={_TAG}")

        assert active_cnt == n_act, (
            f"mix={mix} active drift: got {active_cnt} expected {n_act}")
        assert inactive_cnt == n_inact, (
            f"mix={mix} inactive drift: got {inactive_cnt} expected {n_inact}")
        assert muted_cnt == n_amut + n_imut, (
            f"mix={mix} muted drift: got {muted_cnt} expected "
            f"{n_amut + n_imut}")
        assert active_cnt + inactive_cnt + muted_cnt == all_cnt, (
            f"mix={mix} MATH CHECK BROKEN: "
            f"{active_cnt}+{inactive_cnt}+{muted_cnt} != {all_cnt} "
            f"— some cohort is double-counting or leaking rows")
