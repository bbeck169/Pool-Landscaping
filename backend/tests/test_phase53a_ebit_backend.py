"""Phase 53a · Feb-2026 — Editable EBIT report backend regression suite.

Covers:

* Role gate — super_admin + admin only; manager/tech/customer → 403.
* Compute correctness — revenue, cogs, opex, depreciation, ebit
  identity holds for a hand-seeded fixture (cash + accrual bases).
* Save (POST /ebit/snapshots) — creates v1 on first save, v+1 on
  subsequent saves for the same range.
* Adjustments PATCH — creates NEW version, prior versions
  untouched (immutability + version history).
* Overrides PATCH — creates NEW version; override replaces
  computed+adjusted value; EBIT recomputed from effective values.
* Tenant isolation — snapshots from another tenant are invisible.

Follows the ``requests`` + PyMongo pattern used by
``test_phase51a_walkie_backend.py``.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
TIMEOUT = 30

TID = "3814833a-dd0d-4bd9-90ea-351c24924649"  # aquaterra
OTHER_TID = "phase53a-other-tenant"

USERS = {
    "super":     "super@aquaterra.com",
    "admin":     "admin@aquaterra.com",
    "manager":   "p53a-manager@aquaterra.com",
    "tech":      "landscaper@aquaterra.com",
    "customer":  "customer@aquaterra.com",
}
PW = "password123"

# Hand-seeded fixture range (a fresh isolated month a decade in the past so
# it does not collide with any real invoice/expense data the app may seed).
FIX_FROM = "2016-03-01"
FIX_TO = "2016-03-31"


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


_TOKEN_CACHE: dict = {}


def _login(email: str) -> str:
    tok = _TOKEN_CACHE.get(email)
    if tok:
        return tok
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": PW}, timeout=TIMEOUT)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    tok = r.json()["access_token"]
    _TOKEN_CACHE[email] = tok
    return tok


def _hdr(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


# ═══════════════════════════════════════════════════════════════════
# Fixture seeding
# ═══════════════════════════════════════════════════════════════════
FIX_TAG = "phase53a-fixture"

# Expected values for the seeded fixture:
#   Revenue (cash):  invoice paid_at 2016-03-15 with total 1000
#                    + invoice paid_at 2016-03-20 with total 500
#                    = 1500
#   Revenue (accrual): all invoices with status ∈ {paid, partial, sent, overdue}
#                      created inside window → all 4 seeded invoices count:
#                        1000 + 500 + 500 + 300 = 2300
#   COGS (both bases from cash invoices' line items): 2 lines × (qty × wholesale)
#                    line1: 5 × 40 = 200 ; line2: 1 × 100 = 100 → 300 total
#                    Accrual-only invoices have no wholesale snapshots → 0 extra
#   Depreciation: 1 check on 2016-03-05, amount 200, category "depreciation"
#                 → 200
#   OpEx: 3 non-depreciation checks: 700 (payroll) + 150 (materials) + 50 (tools)
#                                    = 900
#   EBIT (cash):    1500 - 300 - 900 - 200 = 100
#   EBIT (accrual): 2300 - 300 - 900 - 200 = 900
EXPECTED_CASH = {
    "revenue": 1500.0, "cogs": 300.0, "opex": 900.0,
    "depreciation": 200.0, "ebit": 100.0,
}
EXPECTED_ACCRUAL = {
    "revenue": 2300.0, "cogs": 300.0, "opex": 900.0,
    "depreciation": 200.0, "ebit": 900.0,
}


def _iso(day: str, hh: str = "12:00:00") -> str:
    return f"{day}T{hh}+00:00"


def _seed_fixture(sync_db) -> None:
    """Idempotent seed: wipes prior fixture rows first, then inserts."""
    sync_db.quotes.delete_many({"_p53a_tag": FIX_TAG})
    sync_db.checks.delete_many({"_p53a_tag": FIX_TAG})
    sync_db.expense_categories.delete_many({"_p53a_tag": FIX_TAG})
    sync_db.time_entries.delete_many({"_p53a_tag": FIX_TAG})
    sync_db.ebit_snapshots.delete_many({"_p53a_tag": FIX_TAG})
    # Also nuke other-tenant fixture data.
    sync_db.ebit_snapshots.delete_many({"tenant_id": OTHER_TID})

    # ── Seed the fixture manager user (role=manager) with a bcrypt
    # password. Idempotent: only re-upserts to guarantee active + role.
    import bcrypt as _bc
    _pw_hash = _bc.hashpw(PW.encode(), _bc.gensalt()).decode()
    sync_db.users.update_one(
        {"email": USERS["manager"]},
        {"$set": {
            "email": USERS["manager"],
            "name": "P53A Manager",
            "role": "manager",
            "tenant_id": TID,
            "active": True,
            "password_hash": _pw_hash,
        }, "$setOnInsert": {
            "id": f"p53a-mgr-{uuid.uuid4()}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

    # ── 2 CASH invoices with rich line items ──
    sync_db.quotes.insert_many([
        {
            "id": f"p53a-inv-cash-1-{uuid.uuid4()}",
            "_p53a_tag": FIX_TAG,
            "tenant_id": TID,
            "doc_type": "invoice",
            "status": "paid",
            "payment_status": "paid",
            "paid_at": _iso("2016-03-15"),
            "created_at": _iso("2016-03-10"),
            "total": 1000,
            "line_items": [
                {"quantity": 5, "retail_price_snapshot": 100,
                  "wholesale_price_snapshot": 40, "labor_cost_snapshot": 20,
                  "item_id": "svc-a", "income_category_id": "inc-a"},
                {"quantity": 1, "retail_price_snapshot": 500,
                  "wholesale_price_snapshot": 100, "labor_cost_snapshot": 0,
                  "item_id": "svc-b", "income_category_id": "inc-b"},
            ],
        },
        {
            "id": f"p53a-inv-cash-2-{uuid.uuid4()}",
            "_p53a_tag": FIX_TAG,
            "tenant_id": TID,
            "doc_type": "invoice",
            "status": "paid",
            "payment_status": "paid",
            "paid_at": _iso("2016-03-20"),
            "created_at": _iso("2016-03-18"),
            "total": 500,
            "line_items": [],
        },
        # ── 2 accrual-only (issued but not paid inside window) ──
        {
            "id": f"p53a-inv-accr-1-{uuid.uuid4()}",
            "_p53a_tag": FIX_TAG,
            "tenant_id": TID,
            "doc_type": "invoice",
            "status": "sent",
            "payment_status": "unpaid",
            "created_at": _iso("2016-03-10"),
            "total": 500,
            "line_items": [],
        },
        {
            "id": f"p53a-inv-accr-2-{uuid.uuid4()}",
            "_p53a_tag": FIX_TAG,
            "tenant_id": TID,
            "doc_type": "invoice",
            "status": "overdue",
            "payment_status": "unpaid",
            "created_at": _iso("2016-03-25"),
            "total": 300,
            "line_items": [],
        },
    ])

    # ── Checks: 1 depreciation + 3 opex ──
    # Unique-index compound (tenant_id, bank_account_id, check_number)
    # forces us to give each fixture row a distinct bank+number pair.
    _ba = f"p53a-bank-{uuid.uuid4()}"
    sync_db.checks.insert_many([
        {"id": f"p53a-chk-dep-{uuid.uuid4()}",
          "_p53a_tag": FIX_TAG, "tenant_id": TID,
          "bank_account_id": _ba, "check_number": "P53A-1001",
          "amount": 200, "date": "2016-03-05",
          "category": "depreciation", "voided_at": None},
        {"id": f"p53a-chk-pay-{uuid.uuid4()}",
          "_p53a_tag": FIX_TAG, "tenant_id": TID,
          "bank_account_id": _ba, "check_number": "P53A-1002",
          "amount": 700, "date": "2016-03-12",
          "category": "payroll", "voided_at": None},
        {"id": f"p53a-chk-mat-{uuid.uuid4()}",
          "_p53a_tag": FIX_TAG, "tenant_id": TID,
          "bank_account_id": _ba, "check_number": "P53A-1003",
          "amount": 150, "date": "2016-03-18",
          "category": "materials", "voided_at": None},
        {"id": f"p53a-chk-tool-{uuid.uuid4()}",
          "_p53a_tag": FIX_TAG, "tenant_id": TID,
          "bank_account_id": _ba, "check_number": "P53A-1004",
          "amount": 50, "date": "2016-03-22",
          "category": "tools", "voided_at": None},
        # Out-of-window — must be ignored by compute
        {"id": f"p53a-chk-oow-{uuid.uuid4()}",
          "_p53a_tag": FIX_TAG, "tenant_id": TID,
          "bank_account_id": _ba, "check_number": "P53A-1005",
          "amount": 9999, "date": "2016-02-28",
          "category": "materials", "voided_at": None},
    ])


# Module-scoped seed guard: run once per session.
@pytest.fixture(scope="module", autouse=True)
def _seed_once(sync_db):
    _seed_fixture(sync_db)
    yield
    # Cleanup after suite completes.
    sync_db.quotes.delete_many({"_p53a_tag": FIX_TAG})
    sync_db.checks.delete_many({"_p53a_tag": FIX_TAG})
    sync_db.expense_categories.delete_many({"_p53a_tag": FIX_TAG})
    sync_db.time_entries.delete_many({"_p53a_tag": FIX_TAG})
    sync_db.ebit_snapshots.delete_many({"tenant_id": TID})
    sync_db.ebit_snapshots.delete_many({"tenant_id": OTHER_TID})


def _compute(email: str, basis: str = "cash", **extra) -> dict:
    params = {
        "range": "custom",
        "from": FIX_FROM,
        "to": FIX_TO,
        "revenue_basis": basis,
        **extra,
    }
    r = requests.get(f"{API}/ebit/compute", headers=_hdr(email),
                     params=params, timeout=TIMEOUT)
    return r


# ═══════════════════════════════════════════════════════════════════
# Role gate
# ═══════════════════════════════════════════════════════════════════
def test_compute_super_admin_ok():
    r = _compute(USERS["super"])
    assert r.status_code == 200, r.text


def test_compute_admin_ok():
    r = _compute(USERS["admin"])
    assert r.status_code == 200, r.text


def test_compute_manager_forbidden():
    r = _compute(USERS["manager"])
    assert r.status_code == 403


def test_compute_technician_forbidden():
    r = _compute(USERS["tech"])
    assert r.status_code == 403


def test_compute_customer_forbidden():
    r = _compute(USERS["customer"])
    assert r.status_code == 403


def test_snapshots_list_forbidden_for_manager():
    r = requests.get(f"{API}/ebit/snapshots",
                     headers=_hdr(USERS["manager"]), timeout=TIMEOUT)
    assert r.status_code == 403


def test_save_snapshot_forbidden_for_technician():
    r = requests.post(
        f"{API}/ebit/snapshots",
        headers=_hdr(USERS["tech"]),
        json={"range_kind": "custom", "range_from": FIX_FROM,
              "range_to": FIX_TO},
        timeout=TIMEOUT,
    )
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# Compute correctness
# ═══════════════════════════════════════════════════════════════════
def test_compute_cash_basis_matches_expected():
    r = _compute(USERS["admin"], basis="cash")
    assert r.status_code == 200, r.text
    d = r.json()
    for k, v in EXPECTED_CASH.items():
        assert d[k] == pytest.approx(v, abs=0.01), \
            f"cash.{k} expected {v}, got {d[k]}"
    # EBIT identity
    assert d["ebit"] == pytest.approx(
        d["revenue"] - d["cogs"] - d["opex"] - d["depreciation"], abs=0.01)


def test_compute_accrual_basis_matches_expected():
    r = _compute(USERS["admin"], basis="accrual")
    assert r.status_code == 200, r.text
    d = r.json()
    for k, v in EXPECTED_ACCRUAL.items():
        assert d[k] == pytest.approx(v, abs=0.01), \
            f"accrual.{k} expected {v}, got {d[k]}"


def test_compute_returns_breakdown():
    r = _compute(USERS["admin"], basis="cash")
    d = r.json()
    b = d.get("breakdown") or {}
    assert b["invoice_count"] == 2
    assert b["opex_payroll"] == pytest.approx(700.0)
    # Depreciation breakdown must include "depreciation" bucket
    dep_cats = [x["category"] for x in b["depreciation_by_category"]]
    assert "depreciation" in dep_cats
    # OpEx breakdown must NOT include the depreciation bucket
    opex_cats = [x["category"] for x in b["opex_by_category"]]
    assert "depreciation" not in opex_cats


def test_compute_rejects_bad_basis():
    r = _compute(USERS["admin"], basis="banana")
    assert r.status_code == 422


def test_compute_rejects_inverted_range():
    r = requests.get(
        f"{API}/ebit/compute",
        headers=_hdr(USERS["admin"]),
        params={"range": "custom", "from": FIX_TO, "to": FIX_FROM},
        timeout=TIMEOUT,
    )
    assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# Save (POST /ebit/snapshots) + version increment
# ═══════════════════════════════════════════════════════════════════
def test_save_snapshot_creates_v1_then_v2():
    body = {"range_kind": "custom", "range_from": FIX_FROM,
            "range_to": FIX_TO, "revenue_basis": "cash",
            "note": "baseline"}
    r1 = requests.post(f"{API}/ebit/snapshots",
                       headers=_hdr(USERS["admin"]), json=body,
                       timeout=TIMEOUT)
    assert r1.status_code == 200, r1.text
    v1 = r1.json()
    assert v1["version"] == 1
    assert v1["revenue"] == pytest.approx(EXPECTED_CASH["revenue"])
    assert v1["ebit"] == pytest.approx(EXPECTED_CASH["ebit"])

    r2 = requests.post(f"{API}/ebit/snapshots",
                       headers=_hdr(USERS["admin"]), json=body,
                       timeout=TIMEOUT)
    assert r2.status_code == 200, r2.text
    v2 = r2.json()
    assert v2["version"] == 2
    assert v2["id"] != v1["id"]


def test_snapshot_list_returns_versioned_history():
    # Ensure at least v1 exists.
    r_save = requests.post(
        f"{API}/ebit/snapshots",
        headers=_hdr(USERS["admin"]),
        json={"range_kind": "custom", "range_from": FIX_FROM,
              "range_to": FIX_TO, "revenue_basis": "cash",
              "note": "list-test"},
        timeout=TIMEOUT,
    )
    assert r_save.status_code == 200

    r = requests.get(
        f"{API}/ebit/snapshots",
        headers=_hdr(USERS["admin"]),
        params={"range_from": FIX_FROM, "range_to": FIX_TO},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200
    d = r.json()
    assert d["count"] >= 1
    # Newest first
    versions = [s["version"] for s in d["snapshots"]]
    assert versions == sorted(versions, reverse=True)


def test_snapshot_get_by_id():
    r_save = requests.post(
        f"{API}/ebit/snapshots",
        headers=_hdr(USERS["admin"]),
        json={"range_kind": "custom", "range_from": FIX_FROM,
              "range_to": FIX_TO, "revenue_basis": "cash",
              "note": "get-test"},
        timeout=TIMEOUT,
    )
    sid = r_save.json()["id"]
    r = requests.get(f"{API}/ebit/snapshots/{sid}",
                     headers=_hdr(USERS["admin"]), timeout=TIMEOUT)
    assert r.status_code == 200
    assert r.json()["id"] == sid


def test_snapshot_get_404_for_unknown_id():
    r = requests.get(f"{API}/ebit/snapshots/does-not-exist",
                     headers=_hdr(USERS["admin"]), timeout=TIMEOUT)
    assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# Adjustments (delta) + overrides (absolute) — must create NEW version
# and leave prior versions untouched (immutability).
# ═══════════════════════════════════════════════════════════════════
def test_adjustments_patch_creates_new_version_prior_untouched(sync_db):
    r_save = requests.post(
        f"{API}/ebit/snapshots",
        headers=_hdr(USERS["admin"]),
        json={"range_kind": "custom", "range_from": FIX_FROM,
              "range_to": FIX_TO, "revenue_basis": "cash"},
        timeout=TIMEOUT,
    )
    base = r_save.json()
    base_id, base_ver = base["id"], base["version"]
    base_ebit = base["ebit"]

    # Adjust revenue by +50, opex by -20 → new EBIT = base + 70
    r_adj = requests.patch(
        f"{API}/ebit/snapshots/{base_id}/adjustments",
        headers=_hdr(USERS["admin"]),
        json={"line_adjustments": {"revenue": 50, "opex": -20},
              "note": "corrections"},
        timeout=TIMEOUT,
    )
    assert r_adj.status_code == 200, r_adj.text
    new = r_adj.json()
    assert new["id"] != base_id
    assert new["version"] == base_ver + 1
    assert new["ebit"] == pytest.approx(base_ebit + 70, abs=0.01)
    assert new["line_adjustments"]["revenue"] == 50
    assert new["line_adjustments"]["opex"] == -20

    # Prior snapshot doc must be unchanged in DB.
    prior = sync_db.ebit_snapshots.find_one({"id": base_id}, {"_id": 0})
    assert prior is not None
    assert prior["ebit"] == pytest.approx(base_ebit, abs=0.01)
    assert (prior.get("line_adjustments") or {}).get("revenue", 0.0) == 0.0


def test_overrides_patch_replaces_computed_value(sync_db):
    r_save = requests.post(
        f"{API}/ebit/snapshots",
        headers=_hdr(USERS["admin"]),
        json={"range_kind": "custom", "range_from": FIX_FROM,
              "range_to": FIX_TO, "revenue_basis": "cash"},
        timeout=TIMEOUT,
    )
    base_id = r_save.json()["id"]

    # Override depreciation to an absolute 999. All other lines still live.
    r_ovr = requests.patch(
        f"{API}/ebit/snapshots/{base_id}/overrides",
        headers=_hdr(USERS["admin"]),
        json={"line_overrides": {"depreciation": 999}},
        timeout=TIMEOUT,
    )
    assert r_ovr.status_code == 200, r_ovr.text
    new = r_ovr.json()
    assert new["depreciation"] == pytest.approx(999.0, abs=0.01)
    # EBIT identity must still hold using the effective values
    assert new["ebit"] == pytest.approx(
        new["revenue"] - new["cogs"] - new["opex"] - new["depreciation"],
        abs=0.01)
    assert new["line_overrides"]["depreciation"] == 999.0

    # Base snapshot untouched
    base_doc = sync_db.ebit_snapshots.find_one({"id": base_id}, {"_id": 0})
    assert base_doc["depreciation"] == pytest.approx(
        EXPECTED_CASH["depreciation"], abs=0.01)


def test_override_null_falls_back_to_live_and_adjustment(sync_db):
    # 1) Save with an override of opex=500 and an adjustment of opex=+10.
    r_save = requests.post(
        f"{API}/ebit/snapshots",
        headers=_hdr(USERS["admin"]),
        json={"range_kind": "custom", "range_from": FIX_FROM,
              "range_to": FIX_TO, "revenue_basis": "cash",
              "line_adjustments": {"opex": 10},
              "line_overrides": {"opex": 500}},
        timeout=TIMEOUT,
    )
    d = r_save.json()
    assert d["opex"] == pytest.approx(500.0, abs=0.01)

    # 2) PATCH override to null — effective opex reverts to
    #    live+adjustment = 900+10 = 910.
    r_ovr = requests.patch(
        f"{API}/ebit/snapshots/{d['id']}/overrides",
        headers=_hdr(USERS["admin"]),
        json={"line_overrides": {"opex": None}},
        timeout=TIMEOUT,
    )
    new = r_ovr.json()
    assert new["opex"] == pytest.approx(910.0, abs=0.01)


def test_patch_forbidden_for_manager():
    r_save = requests.post(
        f"{API}/ebit/snapshots",
        headers=_hdr(USERS["admin"]),
        json={"range_kind": "custom", "range_from": FIX_FROM,
              "range_to": FIX_TO, "revenue_basis": "cash"},
        timeout=TIMEOUT,
    )
    sid = r_save.json()["id"]
    r = requests.patch(
        f"{API}/ebit/snapshots/{sid}/adjustments",
        headers=_hdr(USERS["manager"]),
        json={"line_adjustments": {"revenue": 1}},
        timeout=TIMEOUT,
    )
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# Tenant isolation
# ═══════════════════════════════════════════════════════════════════
def test_tenant_isolation_snapshots_not_visible_across_tenants(sync_db):
    # Save one under aquaterra
    r_save = requests.post(
        f"{API}/ebit/snapshots",
        headers=_hdr(USERS["admin"]),
        json={"range_kind": "custom", "range_from": FIX_FROM,
              "range_to": FIX_TO, "revenue_basis": "cash",
              "note": "iso-test"},
        timeout=TIMEOUT,
    )
    saved_id = r_save.json()["id"]

    # Directly plant an ebit_snapshot for OTHER tenant
    sync_db.ebit_snapshots.insert_one({
        "id": f"other-{uuid.uuid4()}",
        "tenant_id": OTHER_TID,
        "range_from": FIX_FROM, "range_to": FIX_TO,
        "range_kind": "custom", "revenue_basis": "cash",
        "version": 1,
        "revenue": 99999.0, "cogs": 0.0, "opex": 0.0,
        "depreciation": 0.0, "ebit": 99999.0,
        "breakdown": {},
        "line_adjustments": {}, "line_overrides": {},
        "author_user_id": "other-user",
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "note": "",
    })

    # List call from aquaterra admin must NOT see the other tenant's row
    r = requests.get(
        f"{API}/ebit/snapshots",
        headers=_hdr(USERS["admin"]),
        params={"range_from": FIX_FROM, "range_to": FIX_TO},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200
    tids = {s["tenant_id"] for s in r.json()["snapshots"]}
    assert tids == {TID}, f"cross-tenant leak: {tids}"
    assert saved_id in [s["id"] for s in r.json()["snapshots"]]
