"""Phase A1 · Feb-2026 · Proactive Intelligence — alert bell +
missed-service scan pytest suite.

Covers:
  1. ``emit_alert`` deduplicates on ``(tenant_id, alert_key)``.
  2. Alert list is admin+super_admin only; tech → 403 with detail
     ``insufficient_role_for_alerts``.
  3. Alert list is tenant-scoped — never leaks cross-tenant.
  4. Mark-read, dismiss, mark-all-read are all idempotent.
  5. ``unread_count`` reflects read / dismissed transitions.
  6. Missed-service cron happy path — emits urgent alert.
  7. Missed-service cron skips completed / skipped / cancelled jobs.
  8. Missed-service cron is idempotent across re-runs for same date.
  9. Missed-service cron ignores non-recurring jobs.
 10. ``POST /scans/missed-service/run-now`` returns the summary dict.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import httpx
import jwt as _jwt
import pytest

from tests._f7_loop_fixture import run_test


API = "/api"


def _get_app():
    from server import app
    return app


def _mint_token(*, uid: str, tid: str, role: str,
                 email: str = "x@x") -> str:
    from config import JWT_SECRET
    payload = {
        "sub":       uid,
        "email":     email,
        "role":      role,
        "tenant_id": tid,
        "exp":       int((datetime.now(timezone.utc)
                            + timedelta(hours=1)).timestamp()),
    }
    return _jwt.encode(payload, JWT_SECRET, algorithm="HS256")


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture
def a1_seed():
    """Tenant A, tenant B, admin/super/tech users, a customer, an
    author, and 4 jobs (one incomplete recurring for yesterday, one
    completed, one cancelled, one non-recurring) plus a stranger
    tenant's incomplete recurring job for cross-tenant isolation
    testing."""
    from config import db
    from services.intelligence.alerts import ensure_indexes

    tid = f"a1-tid-{uuid.uuid4()}"
    tid_other = f"a1-tid-other-{uuid.uuid4()}"
    admin_uid = f"a1-admin-{uuid.uuid4()}"
    super_uid = f"a1-super-{uuid.uuid4()}"
    tech_uid  = f"a1-tech-{uuid.uuid4()}"
    cid = f"a1-cust-{uuid.uuid4()}"
    cid_other = f"a1-cust-other-{uuid.uuid4()}"

    now = datetime.now(timezone.utc)
    ymd = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    j_incomplete = f"a1-job-incomplete-{uuid.uuid4()}"
    j_completed  = f"a1-job-completed-{uuid.uuid4()}"
    j_cancelled  = f"a1-job-cancelled-{uuid.uuid4()}"
    j_non_recur  = f"a1-job-nonrecurring-{uuid.uuid4()}"
    j_other_ten  = f"a1-job-other-tenant-{uuid.uuid4()}"

    async def _seed(_db):
        await ensure_indexes()
        await _db.tenants.insert_many([
            {"id": tid, "name": "Tenant A1",
             "slug": f"a1-{uuid.uuid4().hex[:8]}", "active": True},
            {"id": tid_other, "name": "Other Tenant A1",
             "slug": f"a1o-{uuid.uuid4().hex[:8]}", "active": True},
        ])
        await _db.users.insert_many([
            {"id": admin_uid, "email": f"admin-{admin_uid}@ex.test",
             "role": "admin", "tenant_id": tid, "name": "Alice Admin"},
            {"id": super_uid, "email": f"super-{super_uid}@ex.test",
             "role": "super_admin", "tenant_id": tid,
             "name": "Sam Super"},
            {"id": tech_uid, "email": f"tech-{tech_uid}@ex.test",
             "role": "technician", "tenant_id": tid,
             "name": "Terry Tech"},
        ])
        await _db.customers.insert_many([
            {"id": cid, "tenant_id": tid, "name": "Alpha Customer"},
            {"id": cid_other, "tenant_id": tid_other,
             "name": "Beta Customer"},
        ])
        # 4 jobs on tenant A, 1 on tenant B. Distinct
        # ``recurring_template_id`` on each row to satisfy the
        # existing unique ``(recurring_template_id, scheduled_date)``
        # index in the ``jobs`` collection.
        await _db.jobs.insert_many([
            {"id": j_incomplete, "tenant_id": tid, "customer_id": cid,
             "recurring_template_id": f"tpl-inc-{uuid.uuid4()}",
             "service_type": "Pool Cleaning",
             "scheduled_date": f"{ymd}T09:00:00+00:00",
             "status":         "pending",
             "assigned_technician_id": tech_uid},
            {"id": j_completed, "tenant_id": tid, "customer_id": cid,
             "recurring_template_id": f"tpl-com-{uuid.uuid4()}",
             "service_type": "Pool Cleaning",
             "scheduled_date": ymd,
             "status":         "completed"},
            {"id": j_cancelled, "tenant_id": tid, "customer_id": cid,
             "recurring_template_id": f"tpl-can-{uuid.uuid4()}",
             "service_type": "Pool Cleaning",
             "scheduled_date": ymd,
             "status":         "cancelled_by_customer"},
            {"id": j_non_recur, "tenant_id": tid, "customer_id": cid,
             # No recurring_template_id — one-off job. Must be
             # ignored by the scan.
             "service_type": "Repair",
             "scheduled_date": ymd,
             "status":         "pending"},
            {"id": j_other_ten, "tenant_id": tid_other,
             "customer_id": cid_other,
             "recurring_template_id": f"tpl-oth-{uuid.uuid4()}",
             "service_type": "Pool Cleaning",
             "scheduled_date": ymd,
             "status":         "pending"},
        ])

    async def _teardown(_db):
        await _db.tenants.delete_many({"id": {"$in": [tid, tid_other]}})
        await _db.users.delete_many({
            "id": {"$in": [admin_uid, super_uid, tech_uid]}})
        await _db.customers.delete_many({
            "id": {"$in": [cid, cid_other]}})
        await _db.jobs.delete_many({"id": {"$in": [
            j_incomplete, j_completed, j_cancelled,
            j_non_recur, j_other_ten]}})
        await _db.intelligence_alerts.delete_many({
            "tenant_id": {"$in": [tid, tid_other]}})

    run_test(_seed)
    yield {
        "tenant_id":      tid,
        "tenant_other":   tid_other,
        "customer_id":    cid,
        "admin_uid":      admin_uid,
        "super_uid":      super_uid,
        "tech_uid":       tech_uid,
        "admin_token":    _mint_token(
            uid=admin_uid, tid=tid, role="admin",
            email=f"admin-{admin_uid}@ex.test"),
        "super_token":    _mint_token(
            uid=super_uid, tid=tid, role="super_admin",
            email=f"super-{super_uid}@ex.test"),
        "tech_token":     _mint_token(
            uid=tech_uid, tid=tid, role="technician",
            email=f"tech-{tech_uid}@ex.test"),
        "yesterday":      ymd,
        "job_incomplete": j_incomplete,
        "job_completed":  j_completed,
        "job_cancelled":  j_cancelled,
        "job_non_recur":  j_non_recur,
        "job_other_ten":  j_other_ten,
    }
    run_test(_teardown)


async def _hdr(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


# ═════════════════════════════════════════════════════════════════════
# 1 · emit_alert dedup contract
# ═════════════════════════════════════════════════════════════════════
def test_emit_alert_dedupes_on_second_write(a1_seed):
    S = a1_seed
    from services.intelligence.alerts import emit_alert

    async def _go(_db):
        # First insert.
        first, _d1 = await emit_alert(
            S["tenant_id"], category="missed_service",
            severity="urgent",
            alert_key="test:dedup:A1",
            title="First", body="First body",
        )
        # Second insert with SAME key.
        second, _d2 = await emit_alert(
            S["tenant_id"], category="missed_service",
            severity="urgent",
            alert_key="test:dedup:A1",
            title="Second", body="Second body",
        )
        assert first is True
        assert second is False
        # Exactly one row on disk.
        cnt = await _db.intelligence_alerts.count_documents({
            "tenant_id": S["tenant_id"],
            "alert_key": "test:dedup:A1",
        })
        assert cnt == 1
    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 2 · role gating: tech → 403 insufficient_role_for_alerts
# ═════════════════════════════════════════════════════════════════════
def test_alert_list_requires_admin_role(a1_seed):
    S = a1_seed

    async def _go(_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            r = await client.get(
                f"{API}/intelligence/alerts",
                headers=await _hdr(S["tech_token"]),
            )
            assert r.status_code == 403, r.text
            assert r.json()["detail"] == "insufficient_role_for_alerts"
    run_test(_go)


def test_super_admin_can_list_alerts(a1_seed):
    S = a1_seed

    async def _go(_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            r = await client.get(
                f"{API}/intelligence/alerts",
                headers=await _hdr(S["super_token"]),
            )
            assert r.status_code == 200, r.text
            assert "items" in r.json()
    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 3 · Tenant isolation
# ═════════════════════════════════════════════════════════════════════
def test_alert_list_is_tenant_scoped(a1_seed):
    S = a1_seed
    from services.intelligence.alerts import emit_alert

    async def _go(_db):
        await emit_alert(
            S["tenant_id"], category="missed_service",
            severity="urgent", alert_key="tenant-scope:A",
            title="A alert", body="")
        await emit_alert(
            S["tenant_other"], category="missed_service",
            severity="urgent", alert_key="tenant-scope:B",
            title="B alert", body="")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            r = await client.get(
                f"{API}/intelligence/alerts",
                headers=await _hdr(S["admin_token"]),
            )
            body = r.json()
            keys = {i["alert_key"] for i in body["items"]}
            assert "tenant-scope:A" in keys
            assert "tenant-scope:B" not in keys
    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 4 · Mark-read / dismiss / mark-all-read idempotency + unread_count
# ═════════════════════════════════════════════════════════════════════
def test_mark_read_and_dismiss_and_bulk_are_idempotent(a1_seed):
    S = a1_seed
    from services.intelligence.alerts import emit_alert

    async def _go(_db):
        # Seed 3 alerts under this tenant.
        alerts = []
        for i in range(3):
            _, doc = await emit_alert(
                S["tenant_id"], category="missed_service",
                severity="urgent",
                alert_key=f"idempotent:{i}",
                title=f"Alert {i}", body="")
            alerts.append(doc)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            # Baseline: unread_count == 3.
            r = await client.get(
                f"{API}/intelligence/alerts",
                headers=await _hdr(S["admin_token"]),
            )
            assert r.json()["unread_count"] == 3
            aid0 = str(alerts[0]["_id"])
            # Mark read (twice) — idempotent.
            r1 = await client.post(
                f"{API}/intelligence/alerts/{aid0}/read",
                headers=await _hdr(S["admin_token"]),
            )
            r1_second = await client.post(
                f"{API}/intelligence/alerts/{aid0}/read",
                headers=await _hdr(S["admin_token"]),
            )
            assert r1.status_code == 200 and r1_second.status_code == 200
            assert r1.json()["read_at"] == r1_second.json()["read_at"]
            # unread_count ticks to 2.
            r2 = await client.get(
                f"{API}/intelligence/alerts",
                headers=await _hdr(S["admin_token"]),
            )
            assert r2.json()["unread_count"] == 2
            # Dismiss alerts[1] — twice.
            aid1 = str(alerts[1]["_id"])
            d1 = await client.post(
                f"{API}/intelligence/alerts/{aid1}/dismiss",
                headers=await _hdr(S["admin_token"]),
            )
            d1_second = await client.post(
                f"{API}/intelligence/alerts/{aid1}/dismiss",
                headers=await _hdr(S["admin_token"]),
            )
            assert d1.json()["dismissed_at"] == \
                d1_second.json()["dismissed_at"]
            # Dismissed drops from default list (dismissed hidden).
            r3 = await client.get(
                f"{API}/intelligence/alerts",
                headers=await _hdr(S["admin_token"]),
            )
            ids_visible = {i["id"] for i in r3.json()["items"]}
            assert aid1 not in ids_visible
            # unread_count now 1 (alerts[2] only).
            assert r3.json()["unread_count"] == 1
            # ``include_dismissed=true`` reveals it.
            r3b = await client.get(
                f"{API}/intelligence/alerts?include_dismissed=true",
                headers=await _hdr(S["admin_token"]),
            )
            assert aid1 in {i["id"] for i in r3b.json()["items"]}
            # Bulk mark-all-read — twice.
            b1 = await client.post(
                f"{API}/intelligence/alerts/mark-all-read",
                headers=await _hdr(S["admin_token"]), json={},
            )
            b2 = await client.post(
                f"{API}/intelligence/alerts/mark-all-read",
                headers=await _hdr(S["admin_token"]), json={},
            )
            assert b1.status_code == 200 and b2.status_code == 200
            # First call marked 1 (the remaining unread); second
            # matches 0 (idempotent).
            assert b2.json()["matched"] == 0
            # unread_count → 0.
            r4 = await client.get(
                f"{API}/intelligence/alerts",
                headers=await _hdr(S["admin_token"]),
            )
            assert r4.json()["unread_count"] == 0
    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 5 · Missed-service scan — happy path + skips + dedup + non-recurring
# ═════════════════════════════════════════════════════════════════════
def test_missed_service_scan_emits_alert_for_incomplete_recurring(a1_seed):
    S = a1_seed
    from services.intelligence.missed_service_scan import (
        run_missed_service_scan,
    )

    async def _go(_db):
        # Reference time so ``_yesterday`` returns the seed's ``ymd``.
        # Set ``now`` to today at 09:00 UTC.
        now = datetime.now(timezone.utc)
        result = await run_missed_service_scan(
            tenant_id=S["tenant_id"], now=now,
        )
        # 4 jobs scanned on tenant A total, but the query filters
        # to recurring only (3: incomplete, completed, cancelled).
        assert result["scanned_jobs"] == 3
        # Only ONE emitted (the incomplete one — completed +
        # cancelled_by_customer are skipped).
        assert result["alerts_emitted"] == 1
        assert result["alerts_deduped"] == 0
        # Verify the alert on disk.
        doc = await _db.intelligence_alerts.find_one({
            "tenant_id": S["tenant_id"],
            "job_id":    S["job_incomplete"],
        })
        assert doc is not None
        assert doc["category"] == "missed_service"
        assert doc["severity"] == "urgent"
        assert doc["customer_id"] == S["customer_id"]
        assert S["yesterday"] in doc["alert_key"]
        assert "Pool Cleaning" in doc["body"]
        assert doc["actor_context"]["assigned_tech_id"] == S["tech_uid"]
    run_test(_go)


def test_missed_service_scan_skips_completed_and_cancelled(a1_seed):
    S = a1_seed
    from services.intelligence.missed_service_scan import (
        run_missed_service_scan,
    )

    async def _go(_db):
        await run_missed_service_scan(
            tenant_id=S["tenant_id"], now=datetime.now(timezone.utc),
        )
        for jid in (S["job_completed"], S["job_cancelled"]):
            doc = await _db.intelligence_alerts.find_one({
                "tenant_id": S["tenant_id"], "job_id": jid,
            })
            assert doc is None, f"job {jid} incorrectly emitted"
    run_test(_go)


def test_missed_service_scan_ignores_non_recurring_jobs(a1_seed):
    S = a1_seed
    from services.intelligence.missed_service_scan import (
        run_missed_service_scan,
    )

    async def _go(_db):
        await run_missed_service_scan(
            tenant_id=S["tenant_id"], now=datetime.now(timezone.utc),
        )
        # Non-recurring job (no ``recurring_template_id``) → no alert.
        doc = await _db.intelligence_alerts.find_one({
            "tenant_id": S["tenant_id"], "job_id": S["job_non_recur"],
        })
        assert doc is None
    run_test(_go)


def test_missed_service_scan_is_idempotent_on_rerun(a1_seed):
    S = a1_seed
    from services.intelligence.missed_service_scan import (
        run_missed_service_scan,
    )

    async def _go(_db):
        now = datetime.now(timezone.utc)
        r1 = await run_missed_service_scan(
            tenant_id=S["tenant_id"], now=now,
        )
        r2 = await run_missed_service_scan(
            tenant_id=S["tenant_id"], now=now,
        )
        # First pass emits 1, second pass dedups 1.
        assert r1["alerts_emitted"] == 1
        assert r1["alerts_deduped"] == 0
        assert r2["alerts_emitted"] == 0
        assert r2["alerts_deduped"] == 1
        # Still exactly ONE alert on disk.
        cnt = await _db.intelligence_alerts.count_documents({
            "tenant_id": S["tenant_id"],
            "job_id":    S["job_incomplete"],
        })
        assert cnt == 1
    run_test(_go)


def test_missed_service_scan_never_leaks_across_tenants(a1_seed):
    S = a1_seed
    from services.intelligence.missed_service_scan import (
        run_missed_service_scan,
    )

    async def _go(_db):
        # Run for tenant A ONLY.
        await run_missed_service_scan(
            tenant_id=S["tenant_id"], now=datetime.now(timezone.utc),
        )
        # Tenant B's incomplete job must NOT surface under tenant A.
        cnt = await _db.intelligence_alerts.count_documents({
            "tenant_id": S["tenant_id"],
            "job_id":    S["job_other_ten"],
        })
        assert cnt == 0
    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 6 · Manual scan endpoint
# ═════════════════════════════════════════════════════════════════════
def test_run_now_endpoint_returns_summary_and_requires_admin(a1_seed):
    S = a1_seed

    async def _go(_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            # tech → 403.
            r_tech = await client.post(
                f"{API}/intelligence/scans/missed-service/run-now",
                headers=await _hdr(S["tech_token"]),
            )
            assert r_tech.status_code == 403
            assert r_tech.json()["detail"] == "insufficient_role_for_alerts"
            # admin → 200 + summary dict.
            r_admin = await client.post(
                f"{API}/intelligence/scans/missed-service/run-now",
                headers=await _hdr(S["admin_token"]),
            )
            assert r_admin.status_code == 200, r_admin.text
            body = r_admin.json()
            for k in ("tenant_id", "date", "scanned_jobs",
                      "alerts_emitted", "alerts_deduped"):
                assert k in body, k
            assert body["scanned_jobs"] == 3
            assert body["alerts_emitted"] == 1
    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 7 · Category filter chip
# ═════════════════════════════════════════════════════════════════════
def test_category_filter_chip(a1_seed):
    S = a1_seed
    from services.intelligence.alerts import emit_alert

    async def _go(_db):
        await emit_alert(S["tenant_id"], category="missed_service",
                          severity="urgent", alert_key="cat:m",
                          title="", body="")
        await emit_alert(S["tenant_id"], category="churn_risk",
                          severity="recommended", alert_key="cat:c",
                          title="", body="")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            r = await client.get(
                f"{API}/intelligence/alerts?category=churn_risk",
                headers=await _hdr(S["admin_token"]),
            )
            keys = {i["alert_key"] for i in r.json()["items"]}
            assert "cat:c" in keys
            assert "cat:m" not in keys
    run_test(_go)
