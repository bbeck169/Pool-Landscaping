"""CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — contract pytest.

Locks the four pillars of the ticket:

  1. Toggle endpoint (``POST /customers/{cid}/account-correction``):
     role matrix, idempotency, audit trail shape, OFF-cycle metadata
     unset.
  2. Retroactive exclusion: a flagged customer drops from EVERY period's
     Gained count on the very next call (no cache invalidation).
  3. Lost tile: flagged customer whose activation event is in the
     window also drops.
  4. Drill-down endpoints: ``gained-list`` + ``lost-list`` return the
     paginated ``{items, total, has_more, page, limit}`` envelope,
     include MRR per row (current-snapshot sum of active billing_plans),
     and omit flagged customers by default.

Harness mirrors ``test_crew_schedule_visibility.py`` — sync PyMongo
for setup/cleanup + live HTTP against the preview backend (signed JWTs
bypass the auth round-trip).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values
from tests._shared_mongo import shared_db as _shared_db


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = "HS256"


def _tok(uid, email, tid, role):
    return jwt.encode(
        {"sub": uid, "email": email, "role": role, "tenant_id": tid,
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )


def _auth(token, tenant_id):
    return {"Authorization": f"Bearer {token}", "X-Tenant-Id": tenant_id}


def _seed_user(tenant_id, role, email_prefix="u"):
    uid = f"{email_prefix}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@carac.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"CARAC {role}", "email": email,
    })
    return {"id": uid, "email": email, "token": _tok(uid, email, tenant_id, role),
            "tenant_id": tenant_id, "role": role}


def _seed_customer(tenant_id, created_at_iso, is_active=True, name=None):
    cid = f"cust-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": name or f"Customer {cid[-4:]}",
        "first_name": "Test", "last_name": cid[-4:],
        "created_at": created_at_iso,
        "is_active": is_active,
    })
    return cid


def _seed_billing_plan(tenant_id, customer_id, amount, frequency="monthly", active=True):
    _sync.billing_plans.insert_one({
        "id": f"bp-{uuid.uuid4().hex[:8]}",
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "service": "Monthly Pool Service",
        "frequency": frequency,
        "amount": float(amount),
        "active": active,
    })


def _seed_activation_event(tenant_id, customer_id, changed_at_iso,
                            to_status="inactive"):
    _sync.customer_activation_events.insert_one({
        "id": f"ev-{uuid.uuid4().hex[:8]}",
        "tenant_id": tenant_id, "customer_id": customer_id,
        "from_status": "active", "to_status": to_status,
        "changed_at": changed_at_iso,
    })


@pytest.fixture
def tenant_id():
    tid = f"carac-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": "CARAC smoke", "slug": tid, "active": True,
    })
    yield tid
    # Teardown — everything we touched.
    for col in ("tenants", "users", "customers", "customer_activation_events",
                 "customer_account_correction_audit", "billing_plans"):
        _sync[col].delete_many({"tenant_id": tid})


# ══════════════════════════════════════════════════════════════════
# 1 · Toggle endpoint — role matrix + idempotency + audit shape
# ══════════════════════════════════════════════════════════════════
def test_toggle_endpoint_admin_200_writes_audit_and_sets_metadata(tenant_id):
    admin = _seed_user(tenant_id, "admin")
    cid = _seed_customer(tenant_id, "2025-01-15T00:00:00+00:00")

    r = requests.post(
        f"{API}/customers/{cid}/account-correction",
        json={"active": True, "note": "test account"},
        headers=_auth(admin["token"], tenant_id),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["no_change"] is False
    assert body["account_correction"] is True
    assert body["account_correction_at"]
    assert body["account_correction_by"] == admin["id"]

    # Customer row has the stamp.
    row = _sync.customers.find_one({"id": cid})
    assert row["account_correction"] is True
    assert row["account_correction_by"] == admin["id"]
    assert row["account_correction_note"] == "test account"

    # Audit row written with full shape.
    audits = list(_sync.customer_account_correction_audit.find(
        {"customer_id": cid, "tenant_id": tenant_id}))
    assert len(audits) == 1
    a = audits[0]
    assert a["event"] == "toggle"
    assert a["from_state"] is False
    assert a["to_state"] is True
    assert a["actor_user_id"] == admin["id"]
    assert a["actor_role"] == "admin"
    assert a["note"] == "test account"
    assert a["at"]


def test_toggle_endpoint_manager_role_200(tenant_id):
    mgr = _seed_user(tenant_id, "manager")
    cid = _seed_customer(tenant_id, "2025-01-15T00:00:00+00:00")
    r = requests.post(
        f"{API}/customers/{cid}/account-correction",
        json={"active": True},
        headers=_auth(mgr["token"], tenant_id),
    )
    assert r.status_code == 200, r.text
    assert r.json()["account_correction"] is True


def test_toggle_endpoint_owner_role_200(tenant_id):
    own = _seed_user(tenant_id, "owner")
    cid = _seed_customer(tenant_id, "2025-01-15T00:00:00+00:00")
    r = requests.post(
        f"{API}/customers/{cid}/account-correction",
        json={"active": True},
        headers=_auth(own["token"], tenant_id),
    )
    assert r.status_code == 200, r.text


def test_toggle_endpoint_super_admin_role_200(tenant_id):
    sa = _seed_user(tenant_id, "super_admin")
    cid = _seed_customer(tenant_id, "2025-01-15T00:00:00+00:00")
    r = requests.post(
        f"{API}/customers/{cid}/account-correction",
        json={"active": True},
        headers=_auth(sa["token"], tenant_id),
    )
    assert r.status_code == 200, r.text


def test_toggle_endpoint_technician_role_403(tenant_id):
    tech = _seed_user(tenant_id, "technician")
    cid = _seed_customer(tenant_id, "2025-01-15T00:00:00+00:00")
    r = requests.post(
        f"{API}/customers/{cid}/account-correction",
        json={"active": True},
        headers=_auth(tech["token"], tenant_id),
    )
    assert r.status_code == 403, r.text


def test_toggle_endpoint_customer_role_403(tenant_id):
    cu = _seed_user(tenant_id, "customer")
    cid = _seed_customer(tenant_id, "2025-01-15T00:00:00+00:00")
    r = requests.post(
        f"{API}/customers/{cid}/account-correction",
        json={"active": True},
        headers=_auth(cu["token"], tenant_id),
    )
    assert r.status_code == 403, r.text


def test_toggle_endpoint_idempotent_no_audit_on_no_change(tenant_id):
    admin = _seed_user(tenant_id, "admin")
    cid = _seed_customer(tenant_id, "2025-01-15T00:00:00+00:00")
    _sync.customers.update_one(
        {"id": cid}, {"$set": {"account_correction": True}})

    r = requests.post(
        f"{API}/customers/{cid}/account-correction",
        json={"active": True},
        headers=_auth(admin["token"], tenant_id),
    )
    assert r.status_code == 200
    assert r.json()["no_change"] is True
    audits = list(_sync.customer_account_correction_audit.find(
        {"customer_id": cid, "tenant_id": tenant_id}))
    assert audits == []


def test_toggle_endpoint_off_cycle_clears_metadata(tenant_id):
    admin = _seed_user(tenant_id, "admin")
    cid = _seed_customer(tenant_id, "2025-01-15T00:00:00+00:00")
    # ON then OFF.
    requests.post(
        f"{API}/customers/{cid}/account-correction",
        json={"active": True, "note": "will unset"},
        headers=_auth(admin["token"], tenant_id),
    )
    r = requests.post(
        f"{API}/customers/{cid}/account-correction",
        json={"active": False},
        headers=_auth(admin["token"], tenant_id),
    )
    assert r.status_code == 200
    assert r.json()["account_correction"] is False
    row = _sync.customers.find_one({"id": cid})
    assert row["account_correction"] is False
    # Metadata keys MUST be unset (not just set to None).
    assert "account_correction_at" not in row
    assert "account_correction_by" not in row
    assert "account_correction_note" not in row


# ══════════════════════════════════════════════════════════════════
# 2 · Retroactive exclusion — Gained + Lost tiles drop flagged rows
# ══════════════════════════════════════════════════════════════════
def test_retention_gained_tile_excludes_flagged_customer(tenant_id):
    admin = _seed_user(tenant_id, "admin")
    today = datetime.now(timezone.utc)
    # 3 customers created in the last 30 days.
    c1 = _seed_customer(tenant_id, (today - timedelta(days=5)).isoformat())
    c2 = _seed_customer(tenant_id, (today - timedelta(days=10)).isoformat())
    _c3_flagged = _seed_customer(tenant_id, (today - timedelta(days=15)).isoformat())
    _sync.customers.update_one(
        {"id": _c3_flagged},
        {"$set": {"account_correction": True,
                   "account_correction_at": today.isoformat()}})

    r = requests.get(
        f"{API}/reports/customer-retention?period=month",
        headers=_auth(admin["token"], tenant_id),
    )
    assert r.status_code == 200
    totals = r.json()["totals"]
    # Only c1 + c2 count — c3 was flagged, so it's excluded.
    assert totals["gained"] == 2, f"expected 2, got {totals['gained']}; {r.json()}"


def test_retention_lost_tile_excludes_flagged_customer(tenant_id):
    admin = _seed_user(tenant_id, "admin")
    today = datetime.now(timezone.utc)
    # Two customers created outside the window + deactivated inside.
    c_live = _seed_customer(tenant_id, (today - timedelta(days=400)).isoformat())
    c_flag = _seed_customer(tenant_id, (today - timedelta(days=400)).isoformat())
    _seed_activation_event(tenant_id, c_live,
                             (today - timedelta(days=5)).isoformat())
    _seed_activation_event(tenant_id, c_flag,
                             (today - timedelta(days=10)).isoformat())
    _sync.customers.update_one(
        {"id": c_flag}, {"$set": {"account_correction": True}})

    r = requests.get(
        f"{API}/reports/customer-retention?period=month",
        headers=_auth(admin["token"], tenant_id),
    )
    assert r.status_code == 200
    totals = r.json()["totals"]
    assert totals["lost"] == 1, f"expected 1 (flagged excluded), got {totals['lost']}; {r.json()}"


# ══════════════════════════════════════════════════════════════════
# 3 · MRR tiles — current-snapshot sum of billing_plans
# ══════════════════════════════════════════════════════════════════
def test_retention_mrr_gained_sums_current_billing_plans(tenant_id):
    admin = _seed_user(tenant_id, "admin")
    today = datetime.now(timezone.utc)
    cA = _seed_customer(tenant_id, (today - timedelta(days=5)).isoformat())
    cB = _seed_customer(tenant_id, (today - timedelta(days=8)).isoformat())
    # cA: $100 monthly + $100 weekly = $100 + $433.30 = $533.30
    _seed_billing_plan(tenant_id, cA, 100, "monthly", True)
    _seed_billing_plan(tenant_id, cA, 100, "weekly",  True)
    # cB: $300 quarterly = $100.00 (×1/3) + inactive $999 should NOT count
    _seed_billing_plan(tenant_id, cB, 300, "quarterly", True)
    _seed_billing_plan(tenant_id, cB, 999, "monthly",   False)

    r = requests.get(
        f"{API}/reports/customer-retention?period=month",
        headers=_auth(admin["token"], tenant_id),
    )
    assert r.status_code == 200
    totals = r.json()["totals"]
    assert totals["gained"] == 2
    # $533.30 + $100.00 = $633.30 (allow 1-cent float drift)
    assert abs(totals["recurring_revenue_gained"] - 633.30) < 0.02, totals


# ══════════════════════════════════════════════════════════════════
# 4 · Drill-down endpoints — envelope + MRR per row + pagination
# ══════════════════════════════════════════════════════════════════
def test_gained_list_drilldown_envelope_shape_and_mrr(tenant_id):
    admin = _seed_user(tenant_id, "admin")
    today = datetime.now(timezone.utc)
    c1 = _seed_customer(tenant_id, (today - timedelta(days=3)).isoformat(),
                          name="Alpha")
    c2 = _seed_customer(tenant_id, (today - timedelta(days=4)).isoformat(),
                          name="Bravo")
    _seed_billing_plan(tenant_id, c1, 150.0, "monthly", True)
    _seed_billing_plan(tenant_id, c2, 50.0,  "monthly", True)

    r = requests.get(
        f"{API}/reports/customer-retention/gained-list?period=month&page=1&limit=50",
        headers=_auth(admin["token"], tenant_id),
    )
    assert r.status_code == 200, r.text
    env = r.json()
    assert env["total"] == 2
    assert env["has_more"] is False
    assert env["page"] == 1
    assert env["limit"] == 50
    rows_by_id = {row["customer_id"]: row for row in env["items"]}
    assert rows_by_id[c1]["mrr"] == 150.0
    assert rows_by_id[c2]["mrr"] == 50.0
    assert rows_by_id[c1]["name"] == "Alpha"
    assert rows_by_id[c1]["account_correction"] is False


def test_lost_list_drilldown_date_is_change_event_timestamp(tenant_id):
    admin = _seed_user(tenant_id, "admin")
    today = datetime.now(timezone.utc)
    c1 = _seed_customer(tenant_id, (today - timedelta(days=400)).isoformat())
    change_iso = (today - timedelta(days=7)).isoformat()
    _seed_activation_event(tenant_id, c1, change_iso)

    r = requests.get(
        f"{API}/reports/customer-retention/lost-list?period=month&page=1&limit=50",
        headers=_auth(admin["token"], tenant_id),
    )
    assert r.status_code == 200, r.text
    env = r.json()
    assert env["total"] == 1
    assert env["items"][0]["date"] == change_iso


def test_drilldown_list_pagination_has_more_flag(tenant_id):
    admin = _seed_user(tenant_id, "admin")
    today = datetime.now(timezone.utc)
    # Seed 5 customers; ask for page 1 limit 3 → has_more=True.
    for i in range(5):
        _seed_customer(tenant_id, (today - timedelta(days=i + 1)).isoformat())
    r = requests.get(
        f"{API}/reports/customer-retention/gained-list?period=month&page=1&limit=3",
        headers=_auth(admin["token"], tenant_id),
    )
    assert r.status_code == 200
    env = r.json()
    assert env["total"] == 5
    assert len(env["items"]) == 3
    assert env["has_more"] is True
    # Page 2 — 2 remaining, has_more=False.
    r2 = requests.get(
        f"{API}/reports/customer-retention/gained-list?period=month&page=2&limit=3",
        headers=_auth(admin["token"], tenant_id),
    )
    assert r2.status_code == 200
    env2 = r2.json()
    assert len(env2["items"]) == 2
    assert env2["has_more"] is False
