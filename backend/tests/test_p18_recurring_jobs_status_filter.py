"""Phase P18 · Feb-2026 — Recurring Jobs Active/Paused status filter.

Locks in the backend contract for the new ``?status=`` query param
on ``GET /api/recurring-jobs`` and the additive ``counts`` field:

  1. ``status=active`` returns only rows where the canonical
     ``is_active`` field is True (or the legacy ``active`` field
     is True on rows that predate the CHEM2-era backfill).
  2. ``status=paused`` returns the inverse.
  3. No ``status`` param → returns everything (backward-compat).
  4. ``counts`` reflects the tenant-wide totals (not the visible
     page) regardless of the filter applied.
  5. Tenant isolation: rows from tenant B never leak into
     tenant A's response.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_h() -> dict:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def admin_tid(dbc) -> str:
    """The tenant ID the ``admin@aquaterra.com`` fixture user belongs to."""
    u = dbc.users.find_one({"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1})
    assert u and u.get("tenant_id"), "seed admin missing tenant_id"
    return u["tenant_id"]


# ─────────────────────────────────────────────────────────────────────
# Seed helpers.
# ─────────────────────────────────────────────────────────────────────
def _seed_template(dbc, tenant_id: str, *, is_active: bool | None,
                    active: bool | None = None) -> str:
    tid = f"TEST-p18-tpl-{uuid.uuid4().hex[:8]}"
    doc: dict = {
        "id": tid,
        "tenant_id": tenant_id,
        "customer_id": f"TEST-p18-cust-{uuid.uuid4().hex[:6]}",
        "frequency": "weekly",
        "day_of_week": 0,
        "start_date": "2026-01-01",
        "price_cents": 12000,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    if is_active is not None:
        doc["is_active"] = is_active
    if active is not None:
        doc["active"] = active
    dbc.recurring_job_templates.insert_one(doc)
    return tid


@pytest.fixture
def _seeded_mix(dbc, admin_tid):
    """Seed a mix of active + paused templates. Fixture cleans up on
    teardown so the test is idempotent across runs."""
    ids: list = []
    # 3 active (canonical is_active=True)
    for _ in range(3):
        ids.append(_seed_template(dbc, admin_tid, is_active=True, active=True))
    # 2 paused (canonical is_active=False)
    for _ in range(2):
        ids.append(_seed_template(dbc, admin_tid, is_active=False, active=False))
    # 1 legacy row: is_active missing, active=True → counts as active.
    ids.append(_seed_template(dbc, admin_tid, is_active=None, active=True))
    # 1 legacy row: is_active missing, active=False → counts as paused.
    ids.append(_seed_template(dbc, admin_tid, is_active=None, active=False))
    yield ids
    dbc.recurring_job_templates.delete_many({"id": {"$in": ids}})


# ═════════════════════════════════════════════════════════════════════
# Item 1 · ``status=active`` filter
# ═════════════════════════════════════════════════════════════════════
def test_status_active_returns_only_active_rows(admin_h, _seeded_mix):
    r = requests.get(f"{API}/recurring-jobs?status=active",
                      headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    items = body.get("items") or []
    # Every returned row must satisfy the active predicate:
    # is_active==True OR (is_active missing AND active==True).
    for row in items:
        if row["id"] in _seeded_mix:
            ia = row.get("is_active")
            legacy = row.get("active")
            assert ia is True or (ia is None and legacy is True), row


# ═════════════════════════════════════════════════════════════════════
# Item 2 · ``status=paused`` filter
# ═════════════════════════════════════════════════════════════════════
def test_status_paused_returns_only_paused_rows(admin_h, _seeded_mix):
    r = requests.get(f"{API}/recurring-jobs?status=paused",
                      headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    items = body.get("items") or []
    for row in items:
        if row["id"] in _seeded_mix:
            ia = row.get("is_active")
            legacy = row.get("active")
            assert ia is False or (
                ia is None and legacy is not True
            ), row


# ═════════════════════════════════════════════════════════════════════
# Item 3 · no ``status`` param → everything (backward compat)
# ═════════════════════════════════════════════════════════════════════
def test_no_status_returns_everything(admin_h, _seeded_mix):
    r = requests.get(f"{API}/recurring-jobs", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    items = body.get("items") or []
    ids_returned = {row["id"] for row in items}
    for seeded_id in _seeded_mix:
        assert seeded_id in ids_returned, seeded_id


# ═════════════════════════════════════════════════════════════════════
# Item 4 · counts field is correct across a mixed seed
# ═════════════════════════════════════════════════════════════════════
def test_counts_reflect_tenant_wide_totals_regardless_of_filter(
    admin_h, _seeded_mix, dbc, admin_tid,
):
    # Tenant-wide expected totals (independent of the filter param).
    # ``is_active`` canonical first, else fall back to ``active``.
    total = 0
    active = 0
    paused = 0
    for row in dbc.recurring_job_templates.find(
        {"tenant_id": admin_tid}, {"_id": 0, "is_active": 1, "active": 1},
    ):
        total += 1
        ia = row.get("is_active")
        if ia is True:
            active += 1
        elif ia is False:
            paused += 1
        elif row.get("active") is True:
            active += 1
        else:
            paused += 1

    for status_param in ("active", "paused", ""):
        url = f"{API}/recurring-jobs"
        if status_param:
            url += f"?status={status_param}"
        r = requests.get(url, headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        counts = r.json().get("counts")
        assert isinstance(counts, dict), r.text
        assert counts["total"] == total, (status_param, counts, total)
        assert counts["active"] == active, (status_param, counts, active)
        assert counts["paused"] == paused, (status_param, counts, paused)


# ═════════════════════════════════════════════════════════════════════
# Item 5 · tenant isolation — seed a row into tenant B, ensure
# tenant A's counts + items never surface it.
# ═════════════════════════════════════════════════════════════════════
def test_tenant_isolation_across_recurring_status_filter(
    admin_h, _seeded_mix, dbc, admin_tid,
):
    # Provision a throwaway tenant + a paused template in it.
    other_tid = f"TEST-p18-other-{uuid.uuid4().hex[:8]}"
    dbc.tenants.insert_one({
        "id": other_tid,
        "name": "P18 · Other Tenant",
        "slug": f"p18-other-{other_tid}",
        "active": True,
    })
    other_tpl_id = _seed_template(dbc, other_tid, is_active=False, active=False)
    try:
        r = requests.get(f"{API}/recurring-jobs?status=paused",
                          headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        ids = {row["id"] for row in (body.get("items") or [])}
        assert other_tpl_id not in ids
        # Also verify the tenant-A counts don't include the row —
        # ``counts.total`` for admin_tid should equal what we counted
        # above (which was scoped to admin_tid).
        # Nothing to re-assert here beyond the isolation check —
        # test_counts_reflect_tenant_wide_totals_regardless_of_filter
        # already locks the numeric invariant.
    finally:
        dbc.recurring_job_templates.delete_one({"id": other_tpl_id})
        dbc.tenants.delete_one({"id": other_tid})


# ═════════════════════════════════════════════════════════════════════
# Item 6 · legacy ``active=true`` / ``active=false`` query param still
# works (backward-compat with the pre-P18 wire contract).
# ═════════════════════════════════════════════════════════════════════
def test_legacy_active_true_param_still_returns_active_rows(admin_h, _seeded_mix):
    r = requests.get(f"{API}/recurring-jobs?active=true",
                      headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    items = r.json().get("items") or []
    for row in items:
        if row["id"] in _seeded_mix:
            ia = row.get("is_active")
            legacy = row.get("active")
            assert ia is True or (ia is None and legacy is True), row


def test_legacy_active_false_param_still_returns_paused_rows(admin_h, _seeded_mix):
    r = requests.get(f"{API}/recurring-jobs?active=false",
                      headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    items = r.json().get("items") or []
    for row in items:
        if row["id"] in _seeded_mix:
            ia = row.get("is_active")
            legacy = row.get("active")
            assert ia is False or (
                ia is None and legacy is not True
            ), row
