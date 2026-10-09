"""Phase 53e · Feb-2026 — EBIT trend endpoint regression suite.

Covers the new ``GET /api/ebit/trend`` endpoint that powers the
dashboard exec-summary tile. Tests:

* Role gate — super_admin + admin + manager can view; tech/customer 403.
* Response shape — ``{months, revenue_basis, series[…]}`` with each
  point exposing ``{month, revenue, cogs, opex, depreciation, ebit}``.
* Series order — oldest → newest, length == months.
* Default month count — 6 when the ``months`` query is omitted.
* Bounds — ``months=0`` rejected (422), ``months=25`` rejected (422).
* Basis validation — ``revenue_basis=banana`` rejected (422).
* Empty state — a tenant with no seeded activity gets an all-zero
  series of the requested length (200, not an error).
* EBIT identity — ``ebit == revenue - cogs - opex - depreciation``
  holds for every returned bucket.

Follows the ``requests`` + PyMongo pattern used by the sibling
``test_phase53a_ebit_backend.py`` suite so both files share the seed
manager and the module-scoped cleanup.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import bcrypt
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
# Phase 53e · Feb-2026 — the ``/ebit/trend`` endpoint fans out into
# 6 sequential ``compute_ebit`` calls per request. Under CI the
# external ingress route occasionally times out on login (Phase 34
# recurrence). Bind directly to the in-cluster backend so we avoid
# the round trip through the kubernetes ingress. Individual tests
# hit ``/ebit/trend`` at most once, so 60s is a generous ceiling.
API = "http://localhost:8001/api"
TIMEOUT = 60


# Phase 15 · Feb-2026 — resolve the aquaterra tenant_id dynamically
# instead of hard-coding the pre-rebrand constant. Mirrors the fix
# in ``test_phase53a_ebit_backend.py``. One-shot sync lookup at
# module import.
def _resolve_aquaterra_tid() -> str:
    be = dotenv_values("/app/backend/.env")
    _db = MongoClient(be["MONGO_URL"])[be["DB_NAME"]]
    doc = _db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    if doc and doc.get("id"):
        return doc["id"]
    return "3814833a-dd0d-4bd9-90ea-351c24924649"


TID = _resolve_aquaterra_tid()

USERS = {
    "super":     "super@aquaterra.com",
    "admin":     "admin@aquaterra.com",
    "manager":   "p53e-manager@aquaterra.com",
    "tech":      "landscaper@aquaterra.com",
    "customer":  "customer@aquaterra.com",
}
PW = "password123"


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def sync_db():
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        yield mc[be["DB_NAME"]]
    finally:
        mc.close()


@pytest.fixture(scope="module", autouse=True)
def _seed_manager(sync_db):
    """Ensure the Phase 53e fixture manager exists (role=manager)."""
    pw_hash = bcrypt.hashpw(PW.encode(), bcrypt.gensalt()).decode()
    sync_db.users.update_one(
        {"email": USERS["manager"]},
        {"$set": {
            "email": USERS["manager"],
            "name": "P53E Manager",
            "role": "manager",
            "tenant_id": TID,
            "active": True,
            "password_hash": pw_hash,
        }, "$setOnInsert": {
            "id": f"p53e-mgr-{uuid.uuid4()}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    yield


_TOKEN_CACHE: dict = {}


def _login(email: str) -> str:
    tok = _TOKEN_CACHE.get(email)
    if tok:
        return tok
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": PW}, timeout=TIMEOUT)
    assert r.status_code == 200, f"login {email} failed: {r.text[:200]}"
    tok = r.json()["access_token"]
    _TOKEN_CACHE[email] = tok
    return tok


def _hdr(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


def _trend(email: str, **params) -> requests.Response:
    return requests.get(f"{API}/ebit/trend",
                        headers=_hdr(email), params=params, timeout=TIMEOUT)


# ═══════════════════════════════════════════════════════════════════
# Role gate — matches Phase 53c-fix viewer-vs-editor split.
# ═══════════════════════════════════════════════════════════════════
def test_trend_super_admin_ok():
    r = _trend(USERS["super"])
    assert r.status_code == 200, r.text


def test_trend_admin_ok():
    r = _trend(USERS["admin"])
    assert r.status_code == 200, r.text


def test_trend_manager_ok():
    """Manager can VIEW the trend endpoint (viewer gate)."""
    r = _trend(USERS["manager"])
    assert r.status_code == 200, r.text


def test_trend_technician_forbidden():
    r = _trend(USERS["tech"])
    assert r.status_code == 403


def test_trend_customer_forbidden():
    # Phase 15 · Feb-2026 — ``customer@aquaterra.com`` scrubbed.
    # The role-gate deny branch is already covered by
    # ``test_trend_technician_forbidden``; skip when the legacy
    # account no longer resolves.
    try:
        tok = _login(USERS["customer"])
    except Exception:
        pytest.skip(
            "legacy customer@aquaterra.com scrubbed; forbidden "
            "branch covered by test_trend_technician_forbidden.",
        )
    r = requests.get(f"{API}/ebit/trend",
                      headers={"Authorization": f"Bearer {tok}"},
                      params={"months": 6, "revenue_basis": "cash"},
                      timeout=TIMEOUT)
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# Response shape + default months
# ═══════════════════════════════════════════════════════════════════
def test_trend_default_months_is_6():
    r = _trend(USERS["admin"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["months"] == 6
    assert body["revenue_basis"] == "cash"
    assert isinstance(body["series"], list)
    assert len(body["series"]) == 6


def test_trend_custom_months_is_honored():
    r = _trend(USERS["admin"], months=3)
    body = r.json()
    assert body["months"] == 3
    assert len(body["series"]) == 3


def test_trend_series_point_shape():
    r = _trend(USERS["admin"], months=2)
    body = r.json()
    for p in body["series"]:
        assert set(p.keys()) >= {"month", "revenue", "cogs", "opex",
                                  "depreciation", "ebit"}
        assert isinstance(p["month"], str)
        # YYYY-MM string
        assert len(p["month"]) == 7 and p["month"][4] == "-"


def test_trend_series_oldest_to_newest():
    r = _trend(USERS["admin"], months=6)
    months = [p["month"] for p in r.json()["series"]]
    assert months == sorted(months), f"trend not sorted asc: {months}"


def test_trend_ebit_identity_holds_per_bucket():
    # Phase 16 · Feb-2026 — RESTORED. Phase 11 subtracted labor_cost
    # from compute_ebit but the trend endpoint did not surface the
    # labor slices per bucket. Phase 16 added ``labor_cost``,
    # ``recurring_labor_cost``, and ``labor_cost_total`` fields to
    # each trend bucket, so the identity is now reconstructible
    # from the payload:
    #
    #     ebit == revenue - cogs - opex - depreciation
    #              - labor_cost_total
    #
    # Older trend payloads that pre-date Phase 16 default the field
    # to 0 via ``.get(..., 0)`` on the server side; this ratchet
    # still passes because an absent field means no labor to
    # subtract.
    r = _trend(USERS["admin"], months=6)
    for p in r.json()["series"]:
        labor = float(p.get("labor_cost_total") or 0)
        expected = (p["revenue"] - p["cogs"]
                     - p["opex"] - p["depreciation"] - labor)
        assert p["ebit"] == pytest.approx(expected, abs=0.01), \
            f"identity fails for {p['month']}: {p}"


# ═══════════════════════════════════════════════════════════════════
# Basis + bounds validation
# ═══════════════════════════════════════════════════════════════════
def test_trend_rejects_zero_months():
    r = _trend(USERS["admin"], months=0)
    assert r.status_code == 422


def test_trend_rejects_over_cap_months():
    r = _trend(USERS["admin"], months=25)
    assert r.status_code == 422


def test_trend_rejects_bad_basis():
    r = _trend(USERS["admin"], revenue_basis="banana")
    assert r.status_code == 422


def test_trend_accrual_basis_ok():
    r = _trend(USERS["admin"], revenue_basis="accrual", months=2)
    assert r.status_code == 200, r.text
    assert r.json()["revenue_basis"] == "accrual"


# ═══════════════════════════════════════════════════════════════════
# Empty state — a fresh manager with no data still gets an all-zero
# series of the requested length. Phase 53e's dashboard tile relies
# on this so the sparkline still renders on a bare tenant.
# ═══════════════════════════════════════════════════════════════════
def test_trend_empty_tenant_returns_zero_series(sync_db):
    """Seed a throwaway tenant with a manager and confirm we still get
    a 200 with an all-zero series of the requested length. The user
    row is torn down at the end."""
    other_tid = f"p53e-empty-{uuid.uuid4()}"
    other_email = f"p53e-empty-{uuid.uuid4()}@aquaterra.com"
    pw_hash = bcrypt.hashpw(PW.encode(), bcrypt.gensalt()).decode()
    sync_db.users.insert_one({
        "id": f"p53e-empty-mgr-{uuid.uuid4()}",
        "email": other_email,
        "name": "P53E Empty",
        "role": "admin",
        "tenant_id": other_tid,
        "active": True,
        "password_hash": pw_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = _trend(other_email, months=4)
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["series"]) == 4
        for p in body["series"]:
            assert p["revenue"] == 0
            assert p["cogs"] == 0
            assert p["opex"] == 0
            assert p["depreciation"] == 0
            assert p["ebit"] == 0
    finally:
        sync_db.users.delete_one({"email": other_email})
        _TOKEN_CACHE.pop(other_email, None)
