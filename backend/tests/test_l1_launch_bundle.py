"""Phase L1 · Feb-2026 — Launch bundle pytest suite.

Covers:
  1.  L1.1 · Categories detail-rename lands: 403
      ``insufficient_role_for_categories`` on the two axis routers.
  2.  L1.1 · Batch reorder — service_categories rearranges rows.
  3.  L1.1 · Batch reorder — income_categories rearranges rows.
  4.  L1.1 · Batch reorder rejects stray tenant ids with 400.
  5.  L1.2 · ``derive_industry_for_job`` — tenant default wins.
  6.  L1.2 · ``derive_industry_for_job`` — keyword fallback fires
      when the tenant has no signal.
  7.  L1.2 · ``derive_industry_for_job`` — returns ``None`` when
      nothing resolves.
  8.  L1.2 · Backward-compat — legacy ``classify_job`` still works.
  9.  L1.5 · ``/api/dashboard/action-cards`` — happy path counts.
  10. L1.5 · ``/api/dashboard/action-cards`` — role gate 403.
  11. L1.5 · Empty tenant → all counts 0, no crash.
  12. L1.6 · Lead hard-delete audit carries a snapshot.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx
import jwt as _jwt
import pytest

from tests._f7_loop_fixture import run_test


API = "/api"


def _get_app():
    from server import app
    return app


def _mint_token(*, uid: str, tid: str, role: str) -> str:
    from config import JWT_SECRET
    payload = {
        "sub":       uid,
        "email":     f"{uid}@ex.test",
        "role":      role,
        "tenant_id": tid,
        "exp":       int((datetime.now(timezone.utc)
                            + timedelta(hours=1)).timestamp()),
    }
    return _jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _iso_now(offset_days: float = 0) -> str:
    return (datetime.now(timezone.utc)
             + timedelta(days=offset_days)).isoformat()


@pytest.fixture
def l1_seed():
    tid = f"l1-tid-{uuid.uuid4()}"
    admin_uid = f"l1-admin-{uuid.uuid4()}"
    tech_uid = f"l1-tech-{uuid.uuid4()}"

    async def _seed(_db):
        await _db.tenants.insert_one({
            "id": tid, "name": "Tenant L1",
            "slug": f"l1-{uuid.uuid4().hex[:8]}",
            "active": True, "settings": {}})
        await _db.users.insert_many([
            {"id": admin_uid, "email": f"admin-{admin_uid}@ex.test",
              "role": "admin", "tenant_id": tid, "name": "Alex Admin"},
            {"id": tech_uid, "email": f"tech-{tech_uid}@ex.test",
              "role": "technician", "tenant_id": tid, "name": "Terry"},
        ])

    async def _teardown(_db):
        await _db.tenants.delete_many({"id": tid})
        await _db.users.delete_many(
            {"id": {"$in": [admin_uid, tech_uid]}})
        await _db.service_categories.delete_many({"tenant_id": tid})
        await _db.income_categories.delete_many({"tenant_id": tid})
        await _db.leads.delete_many({"tenant_id": tid})
        await _db.invoices.delete_many({"tenant_id": tid})
        await _db.jobs.delete_many({"tenant_id": tid})
        await _db.intelligence_alerts.delete_many({"tenant_id": tid})
        await _db.audit_log.delete_many({"tenant_id": tid})

    run_test(_seed)
    yield {
        "tenant_id":     tid,
        "admin_token":   _mint_token(uid=admin_uid, tid=tid,
                                       role="admin"),
        "tech_token":    _mint_token(uid=tech_uid, tid=tid,
                                       role="technician"),
        "admin_uid":     admin_uid,
    }
    run_test(_teardown)


# ═════════════════════════════════════════════════════════════════════
# L1.1 — Categories detail-rename + reorder.
# ═════════════════════════════════════════════════════════════════════
def test_service_categories_403_wording(l1_seed):
    S = l1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            # Trigger seed as admin (implicit on GET).
            await c.get(
                f"{API}/service-categories",
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            r = await c.post(
                f"{API}/service-categories",
                json={"name": "TechAttempt"},
                headers={"Authorization": f"Bearer {S['tech_token']}"})
            result["status"] = r.status_code
            result["detail"] = r.json().get("detail")
        # Tech can't hit reorder either.
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.post(
                f"{API}/income-categories/reorder",
                json={"ordered_ids": []},
                headers={"Authorization": f"Bearer {S['tech_token']}"})
            result["ic_status"] = r.status_code
            result["ic_detail"] = r.json().get("detail")

    run_test(_go)
    assert result["status"] == 403
    assert result["detail"] == "insufficient_role_for_categories"
    assert result["ic_status"] == 403
    assert result["ic_detail"] == "insufficient_role_for_categories"


def test_service_categories_reorder(l1_seed):
    S = l1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            # Seed defaults.
            r = await c.get(
                f"{API}/service-categories",
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            rows = (r.json() or {}).get("items", [])
            assert len(rows) >= 3, rows
            reversed_ids = [row["id"] for row in rows[:3]][::-1]
            r = await c.post(
                f"{API}/service-categories/reorder",
                json={"ordered_ids": reversed_ids},
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            result["status"] = r.status_code
            result["updated"] = r.json().get("updated")
        # Read back and confirm the new sort_order.
        for idx, cid in enumerate(reversed_ids):
            row = await _db.service_categories.find_one(
                {"id": cid, "tenant_id": S["tenant_id"]},
                {"_id": 0, "sort_order": 1})
            assert row["sort_order"] == idx, (idx, row)

    run_test(_go)
    assert result["status"] == 200
    assert result["updated"] == 3


def test_income_categories_reorder(l1_seed):
    S = l1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/income-categories",
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            rows = (r.json() or {}).get("items", [])
            reversed_ids = [row["id"] for row in rows[:2]][::-1]
            r = await c.post(
                f"{API}/income-categories/reorder",
                json={"ordered_ids": reversed_ids},
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            result["status"] = r.status_code

    run_test(_go)
    assert result["status"] == 200


def test_reorder_rejects_stray_ids(l1_seed):
    S = l1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            # Seed then post an id belonging to no tenant.
            await c.get(
                f"{API}/service-categories",
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            r = await c.post(
                f"{API}/service-categories/reorder",
                json={"ordered_ids": ["stray-does-not-exist"]},
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            result["status"] = r.status_code
            body = r.json()
            result["error"] = (body.get("detail") or {}).get("error") \
                                if isinstance(body.get("detail"), dict) \
                                else None

    run_test(_go)
    assert result["status"] == 400
    assert result["error"] == "unknown_ids"


# ═════════════════════════════════════════════════════════════════════
# L1.2 — Industry derivation.
# ═════════════════════════════════════════════════════════════════════
def test_derive_industry_tenant_default_wins():
    from services.industry_derivation import derive_industry_for_job
    tenant = {"id": "t1", "settings": {"default_industry": "pool"}}
    # Generic title that would keyword-classify as "pool" anyway,
    # but the tenant default is the AUTHORITATIVE source.
    job = {"service_type": "General visit"}
    assert derive_industry_for_job(job, tenant) == "pool"

    # And it wins over a competing keyword classifier.
    tenant2 = {"id": "t2",
                "settings": {"default_industry": "landscaping"}}
    job2 = {"service_type": "Pool chemical rebalance"}
    assert derive_industry_for_job(job2, tenant2) == "landscaping"


def test_derive_industry_keyword_fallback_fires():
    from services.industry_derivation import derive_industry_for_job
    tenant = {"id": "t3", "settings": {}}
    # "Landscape maintenance" matches ``landscap`` → landscaping.
    job = {"service_type": "Landscape maintenance"}
    assert derive_industry_for_job(job, tenant) == "landscaping"


def test_derive_industry_returns_none_with_no_signal():
    from services.industry_derivation import derive_industry_for_job
    tenant = {"id": "t4", "settings": {}}
    job = {}
    assert derive_industry_for_job(job, tenant) is None


def test_classify_job_backward_compat():
    from routers.jobs import classify_job
    # Legacy shim still returns exactly one of pool / landscaping.
    assert classify_job("Landscape Cleanup") == "landscaping"
    assert classify_job("Weekly service") == "pool"
    assert classify_job("") == "pool"


def test_derive_industry_single_industry_tenant():
    from services.industry_derivation import derive_industry_for_job
    tenant = {"id": "t5", "industries": ["hvac"], "settings": {}}
    job = {"service_type": "Weekly service"}
    assert derive_industry_for_job(job, tenant) == "hvac"


# ═════════════════════════════════════════════════════════════════════
# L1.5 — /api/dashboard/action-cards.
# ═════════════════════════════════════════════════════════════════════
def test_action_cards_happy(l1_seed):
    S = l1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        now = datetime.now(timezone.utc)
        # Seed a scheduled job today, an overdue invoice, a fresh
        # lead, an open alert, and a missed-service alert.
        await _db.jobs.insert_one({
            "id": f"l1-j-{uuid.uuid4()}", "tenant_id": S["tenant_id"],
            "status": "scheduled",
            "scheduled_date": now.date().isoformat(),
            "technician_id": "l1-tech-x",
            "customer_id": "c",
        })
        await _db.invoices.insert_one({
            "id": f"l1-inv-{uuid.uuid4()}", "tenant_id": S["tenant_id"],
            "status": "overdue", "total_cents": 1000,
        })
        await _db.leads.insert_one({
            "id": f"l1-lead-{uuid.uuid4()}", "tenant_id": S["tenant_id"],
            "status": "new", "created_at": now.isoformat(),
            "name": "Fresh Today",
        })
        await _db.intelligence_alerts.insert_one({
            "tenant_id": S["tenant_id"],
            "alert_key": f"l1-{uuid.uuid4()}",
            "category": "missed_service", "severity": "urgent",
            "title": "Missed today", "body": "test",
            "customer_id": "c", "job_id": None,
            "actor_context": {}, "created_at": now,
            "read_at": None, "dismissed_at": None,
            "acknowledged_by": None,
        })
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/dashboard/action-cards",
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            result["status"] = r.status_code
            result["body"] = r.json()

    run_test(_go)
    assert result["status"] == 200, result
    b = result["body"]
    assert b["today_routes"] >= 1
    assert b["overdue_invoices"] >= 1
    assert b["new_leads_today"] >= 1
    assert b["open_alerts"] >= 1
    assert b["missed_services_today"] >= 1
    assert "generated_at" in b


def test_action_cards_role_gate(l1_seed):
    S = l1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/dashboard/action-cards",
                headers={"Authorization": f"Bearer {S['tech_token']}"})
            result["status"] = r.status_code
            result["detail"] = r.json().get("detail")

    run_test(_go)
    assert result["status"] == 403
    assert result["detail"] == "insufficient_role_for_dashboard"


def test_action_cards_empty_tenant(l1_seed):
    S = l1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/dashboard/action-cards",
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            result["status"] = r.status_code
            result["body"] = r.json()

    run_test(_go)
    assert result["status"] == 200
    b = result["body"]
    for k in ("today_routes", "pending_checkins", "unpaid_invoices",
                "overdue_invoices", "new_leads_today", "open_alerts",
                "missed_services_today"):
        assert b[k] == 0, (k, b[k])


# ═════════════════════════════════════════════════════════════════════
# L1.6 — Lead hard-delete audit snapshot.
# ═════════════════════════════════════════════════════════════════════
def test_lead_hard_delete_audit_carries_snapshot(l1_seed):
    from routers.leads import _hard_delete_lead
    S = l1_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        lid = f"l1-lead-{uuid.uuid4()}"
        await _db.leads.insert_one({
            "id": lid, "tenant_id": S["tenant_id"],
            "status": "new", "name": "Snapshotable Lead",
            "email": "snap@test.io",
            "created_at": _iso_now(-3),
        })
        actor = {"id": S["admin_uid"], "email": "admin@l1.test"}
        r = await _hard_delete_lead(lid, actor, S["tenant_id"])
        # Force await for the fire-and-forget audit insert.
        entry = await _db.audit_log.find_one(
            {"target_id": lid, "tenant_id": S["tenant_id"]},
            {"_id": 0},
        )
        result["hard_delete_ok"] = r.get("ok")
        result["entry"] = entry

    run_test(_go)
    assert result["hard_delete_ok"] is True
    e = result["entry"]
    assert e is not None, "audit_log entry missing"
    assert e["action"] == "lead.hard_delete"
    assert e.get("resource_type") == "lead"
    assert isinstance(e.get("deleted_ids"), list)
    assert isinstance(e.get("snapshot"), list) and len(e["snapshot"]) == 1
    assert e["snapshot"][0]["name"] == "Snapshotable Lead"
    assert e["snapshot"][0].get("email") == "snap@test.io"
