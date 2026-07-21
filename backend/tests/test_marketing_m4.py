"""Feb-2026 · Marketing Slice M4 — Segment tests."""
from __future__ import annotations

import asyncio, os, uuid
from datetime import datetime, timedelta, timezone

import pytest, requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(): return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}
@pytest.fixture(scope="module")
def tech_headers(): return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}
@pytest.fixture(scope="module")
def customer_headers(): return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro): return asyncio.new_event_loop().run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════════
# Schema + RBAC
# ═══════════════════════════════════════════════════════════════════════
def test_schema_admin_only(admin_headers, tech_headers, customer_headers):
    r = requests.get(f"{API}/marketing/audience-segments/schema", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    fields = r.json()["fields"]
    assert len(fields) >= 10
    for f in fields:
        assert "field" in f and "ops" in f and f["ops"]
    for h in (tech_headers, customer_headers):
        assert requests.get(f"{API}/marketing/audience-segments/schema", headers=h,
                             timeout=15).status_code in (401, 403)


def test_list_seeded(admin_headers):
    r = requests.get(f"{API}/marketing/audience-segments", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["segments"]}
    for expected in ("VIP customers", "Past-due customers",
                      "Inactive 90+ days", "New customers (last 30 days)"):
        assert expected in names, f"seed missing {expected}"


def test_crud_rbac_non_admin_blocked(tech_headers, customer_headers):
    for h in (tech_headers, customer_headers):
        assert requests.get(f"{API}/marketing/audience-segments", headers=h,
                             timeout=15).status_code in (401, 403)
        assert requests.post(f"{API}/marketing/audience-segments", headers=h,
                              json={"name": "x", "conditions": []},
                              timeout=15).status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════
# CRUD + adhoc preview
# ═══════════════════════════════════════════════════════════════════════
def test_crud_flow(admin_headers):
    conds = [{"field": "vip", "op": "eq", "value": True}]
    r = requests.post(f"{API}/marketing/audience-segments", headers=admin_headers,
                       json={"name": "M4 crud", "conditions": conds}, timeout=15)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    assert requests.get(f"{API}/marketing/audience-segments/{sid}", headers=admin_headers,
                         timeout=15).status_code == 200

    r = requests.patch(f"{API}/marketing/audience-segments/{sid}", headers=admin_headers,
                        json={"description": "updated"}, timeout=15)
    assert r.status_code == 200 and r.json()["description"] == "updated"

    r = requests.post(f"{API}/marketing/audience-segments/{sid}/preview",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "count" in body and "sample" in body

    # Cached second time
    r2 = requests.post(f"{API}/marketing/audience-segments/{sid}/preview",
                        headers=admin_headers, timeout=15)
    assert r2.json().get("cached") is True

    # Refresh forces re-eval
    r3 = requests.post(f"{API}/marketing/audience-segments/{sid}/preview?refresh=true",
                        headers=admin_headers, timeout=15)
    assert r3.json().get("cached") is False

    # Soft-delete
    assert requests.delete(f"{API}/marketing/audience-segments/{sid}",
                            headers=admin_headers, timeout=15).status_code == 204
    got = requests.get(f"{API}/marketing/audience-segments/{sid}",
                        headers=admin_headers, timeout=15).json()
    assert got["active"] is False


def test_invalid_condition_rejected(admin_headers):
    for bad in [
        {"conditions": [{"field": "nope", "op": "eq", "value": 1}]},
        {"conditions": [{"field": "vip", "op": "gt", "value": True}]},
        {"conditions": [{"field": "vip", "op": "eq"}]},   # missing value
    ]:
        r = requests.post(f"{API}/marketing/audience-segments", headers=admin_headers,
                           json={"name": "bad", **bad}, timeout=15)
        assert r.status_code == 422, f"expected 422 for {bad}: {r.text}"


def test_adhoc_preview(admin_headers):
    r = requests.post(f"{API}/marketing/audience-segments/preview-adhoc",
                       headers=admin_headers,
                       json={"conditions": [{"field": "vip", "op": "eq", "value": True}]},
                       timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "count" in body and "sample" in body
    for row in body["sample"]:
        assert row.get("vip") is True


# ═══════════════════════════════════════════════════════════════════════
# Evaluator correctness — seed a mixed customer set + assert each predicate
# ═══════════════════════════════════════════════════════════════════════
def test_evaluator_matches_expected_customers():
    """Seed 4 customers with distinct profiles and assert each predicate
    picks the right subset."""
    from services.marketing.segments import evaluate_conditions

    async def _go():
        from config import db as _db
        u = await _db.users.find_one({"email": "admin@aquaterra.com"},
                                      {"_id": 0, "tenant_id": 1})
        tenant_id = u["tenant_id"]
        now = datetime.now(timezone.utc)

        seed_ids = {
            "vip":   f"m4-vip-{uuid.uuid4().hex[:6]}",
            "pd":    f"m4-pd-{uuid.uuid4().hex[:6]}",
            "old":   f"m4-old-{uuid.uuid4().hex[:6]}",
            "new":   f"m4-new-{uuid.uuid4().hex[:6]}",
        }
        # Customers
        await _db.customers.insert_many([
            {"id": seed_ids["vip"], "tenant_id": tenant_id, "name": "M4Vip",
             "vip": True, "created_at": (now - timedelta(days=200)).isoformat(),
             "city": "Peoria"},
            {"id": seed_ids["pd"], "tenant_id": tenant_id, "name": "M4PastDue",
             "vip": False, "created_at": (now - timedelta(days=200)).isoformat(),
             "city": "Peoria"},
            {"id": seed_ids["old"], "tenant_id": tenant_id, "name": "M4Old",
             "vip": False, "created_at": (now - timedelta(days=200)).isoformat(),
             "city": "Vistancia"},
            {"id": seed_ids["new"], "tenant_id": tenant_id, "name": "M4New",
             "vip": False,
             "created_at": (now - timedelta(days=10)).isoformat(),
             "city": "Peoria"},
        ])
        # Past-due invoice for M4PastDue
        await _db.quotes.insert_one({
            "id": f"m4-inv-{seed_ids['pd']}", "tenant_id": tenant_id,
            "customer_id": seed_ids["pd"], "doc_type": "invoice",
            "total": 500, "amount_paid": 0, "due_date": "2020-01-01",
        })
        # M4Old had a completed service 200 days ago; M4New had one 5 days ago
        await _db.jobs.insert_many([
            {"id": f"m4-job-old-{seed_ids['old']}", "tenant_id": tenant_id,
             "customer_id": seed_ids["old"], "status": "completed",
             "completed_at": (now - timedelta(days=200)).isoformat()},
            {"id": f"m4-job-new-{seed_ids['new']}", "tenant_id": tenant_id,
             "customer_id": seed_ids["new"], "status": "completed",
             "completed_at": (now - timedelta(days=5)).isoformat()},
        ])

        try:
            # VIP
            r = await evaluate_conditions(
                [{"field": "vip", "op": "eq", "value": True}], tenant_id,
            )
            assert seed_ids["vip"] in r["matched_ids"]
            assert seed_ids["pd"] not in r["matched_ids"]

            # Past-due
            r = await evaluate_conditions(
                [{"field": "has_past_due", "op": "eq", "value": True}], tenant_id,
            )
            assert seed_ids["pd"] in r["matched_ids"]
            assert seed_ids["vip"] not in r["matched_ids"]

            # Balance_due > 100 → M4PastDue only
            r = await evaluate_conditions(
                [{"field": "balance_due", "op": "gt", "value": 100}], tenant_id,
            )
            assert seed_ids["pd"] in r["matched_ids"]

            # last_service_days_ago > 90 → M4Old
            r = await evaluate_conditions(
                [{"field": "last_service_days_ago", "op": "gt", "value": 90}],
                tenant_id,
            )
            assert seed_ids["old"] in r["matched_ids"]
            assert seed_ids["new"] not in r["matched_ids"]

            # created_days_ago < 30 → M4New only
            r = await evaluate_conditions(
                [{"field": "created_days_ago", "op": "lt", "value": 30}], tenant_id,
            )
            assert seed_ids["new"] in r["matched_ids"]
            assert seed_ids["vip"] not in r["matched_ids"]

            # city in [Peoria] excludes M4Old (Vistancia)
            r = await evaluate_conditions(
                [{"field": "city", "op": "in", "value": ["Peoria"]}], tenant_id,
            )
            assert seed_ids["old"] not in r["matched_ids"]
            assert seed_ids["vip"] in r["matched_ids"]

            # AND compound: VIP=true AND city=Peoria → M4Vip only from our seeds
            r = await evaluate_conditions(
                [{"field": "vip", "op": "eq", "value": True},
                 {"field": "city", "op": "in", "value": ["Peoria"]}],
                tenant_id,
            )
            assert seed_ids["vip"] in r["matched_ids"]
            for other in ("pd", "old", "new"):
                assert seed_ids[other] not in r["matched_ids"]
        finally:
            await _db.customers.delete_many({"id": {"$in": list(seed_ids.values())}})
            await _db.quotes.delete_many({"id": f"m4-inv-{seed_ids['pd']}"})
            await _db.jobs.delete_many(
                {"id": {"$in": [f"m4-job-old-{seed_ids['old']}",
                                 f"m4-job-new-{seed_ids['new']}"]}},
            )

    _run(_go())


def test_delete_guard_with_live_campaign(admin_headers):
    r = requests.post(f"{API}/marketing/audience-segments", headers=admin_headers,
                       json={"name": "M4 guard",
                             "conditions": [{"field": "vip", "op": "eq", "value": True}]},
                       timeout=15)
    sid = r.json()["id"]

    async def _inject():
        db = _db()
        u = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "tenant_id": 1})
        cid = f"m4-guard-camp-{sid[:6]}"
        await db.marketing_campaigns.insert_one({
            "id": cid, "tenant_id": u["tenant_id"],
            "name": "M4 seg guard camp", "status": "scheduled",
            "segment_id": sid,
        })
        return cid
    cid = _run(_inject())
    try:
        r = requests.delete(f"{API}/marketing/audience-segments/{sid}",
                             headers=admin_headers, timeout=15)
        assert r.status_code == 409, r.text
    finally:
        async def _clean():
            await _db().marketing_campaigns.delete_one({"id": cid})
        _run(_clean())
    # Cleanup — delete works now
    assert requests.delete(f"{API}/marketing/audience-segments/{sid}",
                            headers=admin_headers, timeout=15).status_code == 204


def test_cross_tenant_isolation(admin_headers):
    async def _seed_foreign():
        db = _db()
        u = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "tenant_id": 1})
        others = await db.tenants.find(
            {"id": {"$ne": u["tenant_id"]}}, {"_id": 0, "id": 1},
        ).to_list(1)
        assert others
        sid = f"m4-cross-{uuid.uuid4().hex[:8]}"
        await db.marketing_audience_segments.insert_one({
            "id": sid, "tenant_id": others[0]["id"],
            "name": "foreign", "description": "", "conditions": [],
            "active": True, "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        })
        return sid
    sid = _run(_seed_foreign())
    try:
        assert requests.get(f"{API}/marketing/audience-segments/{sid}",
                             headers=admin_headers, timeout=15).status_code == 404
        assert requests.patch(f"{API}/marketing/audience-segments/{sid}",
                               headers=admin_headers, json={"name": "hijack"},
                               timeout=15).status_code == 404
        assert requests.delete(f"{API}/marketing/audience-segments/{sid}",
                                headers=admin_headers, timeout=15).status_code == 404
    finally:
        async def _clean():
            await _db().marketing_segments.delete_one({"id": sid})
        _run(_clean())
