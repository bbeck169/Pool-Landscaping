"""Phase H6 · Feb-2026 — /api/admin/analytics/monthly tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


async def _admin_ctx(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                          {"_id": 0, "id": 1})
    tid = tenant["id"]
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                       {"_id": 0, "id": 1, "role": 1})
    return tid, admin


def _in_month_iso(year=2026, month=2, day=15):
    return datetime(year, month, day, 12, 0, tzinfo=timezone.utc).isoformat()


def _out_of_month_iso():
    return datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc).isoformat()


async def _cleanup(db, tid, prefix):
    await db.soshie_moderation_results.delete_many(
        {"tenant_id": tid, "id": {"$regex": f"^{prefix}"}},
    )
    await db.charge_templates.delete_many(
        {"tenant_id": tid, "id": {"$regex": f"^{prefix}"}},
    )
    await db.jobs.delete_many(
        {"tenant_id": tid, "id": {"$regex": f"^{prefix}"}},
    )
    await db.audit_events.delete_many(
        {"tenant_id": tid, "id": {"$regex": f"^{prefix}"}},
    )
    await db.ai_employee_actions.delete_many(
        {"tenant_id": tid, "id": {"$regex": f"^{prefix}"}},
    )


def test_h6_happy_path_aggregates_all_four_streams():
    from routers.analytics_monthly import analytics_monthly

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        prefix = f"TEST_H6_HP_{uuid.uuid4().hex[:6]}_"
        await _cleanup(db, tid, prefix)
        # Soshie moderation: 3 in window (2 approve, 1 flag, 1 cached), 1 out of window.
        # Phase H7 · Feb-2026 — one row carries ``regex_short_circuit=True``
        # to lock the new H6 counter contract.
        in_month = _in_month_iso()
        out_month = _out_of_month_iso()
        await db.soshie_moderation_results.insert_many([
            {"id": f"{prefix}m1", "tenant_id": tid,
             "decision": "approve", "cost_estimate_usd": 0.02,
             "from_cache": False, "regex_short_circuit": False,
             "created_at": in_month},
            {"id": f"{prefix}m2", "tenant_id": tid,
             "decision": "approve", "cost_estimate_usd": 0.00,
             "from_cache": True, "regex_short_circuit": False,
             "created_at": in_month},
            {"id": f"{prefix}m3", "tenant_id": tid,
             "decision": "flag", "cost_estimate_usd": 0.03,
             "from_cache": False, "regex_short_circuit": False,
             "created_at": in_month},
            {"id": f"{prefix}m4", "tenant_id": tid,
             "decision": "approve", "cost_estimate_usd": 0.10,
             "from_cache": False, "regex_short_circuit": False,
             "created_at": out_month},
            # H7 short-circuit row (in window, $0, model=regex-p1).
            {"id": f"{prefix}m5", "tenant_id": tid,
             "decision": "block", "cost_estimate_usd": 0.0,
             "from_cache": False, "regex_short_circuit": True,
             "model": "regex-p1", "created_at": in_month},
        ])
        # Charge templates: 2 rows, one used in window one not.
        await db.charge_templates.insert_many([
            {"id": f"{prefix}t1", "tenant_id": tid,
             "name": "Weekly svc", "apply_count": 5,
             "created_at": "2025-12-01T00:00:00+00:00",
             "last_used_at": in_month},
            {"id": f"{prefix}t2", "tenant_id": tid,
             "name": "Old add-on", "apply_count": 0,
             "created_at": "2025-10-01T00:00:00+00:00"},
        ])
        # A job with 1 line_item stamped with the applied-from-template id
        # so revenue contribution is non-zero.
        await db.jobs.insert_one({
            "id": f"{prefix}j1", "tenant_id": tid,
            "updated_at": in_month, "status": "completed",
            "line_items": [{
                "applied_from_template_id": f"{prefix}t1",
                "subtotal": 250.0,
            }],
        })
        # Drift alerts: 3 dispatched, 1 clean heartbeat, worst day
        # carries dangling_refs_total=42.
        await db.audit_events.insert_many([
            {"id": f"{prefix}a1", "tenant_id": tid,
             "event_type": "data_integrity_digest",
             "timestamp": in_month,
             "payload": {"date": "2026-02-01",
                            "dispatched": True,
                            "dangling_refs_total": 7}},
            {"id": f"{prefix}a2", "tenant_id": tid,
             "event_type": "data_integrity_digest",
             "timestamp": in_month,
             "payload": {"date": "2026-02-02",
                            "dispatched": False,
                            "dangling_refs_total": 0}},
            {"id": f"{prefix}a3", "tenant_id": tid,
             "event_type": "data_integrity_digest",
             "timestamp": in_month,
             "payload": {"date": "2026-02-15",
                            "dispatched": True,
                            "dangling_refs_total": 42}},
            {"id": f"{prefix}a4", "tenant_id": tid,
             "event_type": "data_integrity_digest",
             "timestamp": in_month,
             "payload": {"date": "2026-02-16",
                            "dispatched": True,
                            "dangling_refs_total": 3}},
        ])
        # Manual conversion: 4 generated across Facebook + Instagram,
        # 2 marked-posted → 50%. Facebook 2/2 = 100%, IG 0/2 = 0%.
        await db.ai_employee_actions.insert_many([
            {"id": f"{prefix}act_fb1", "tenant_id": tid,
             "manual_only_platform": "facebook",
             "manual_ready_at": in_month, "created_at": in_month,
             "status": "awaiting_manual"},
            {"id": f"{prefix}act_fb2", "tenant_id": tid,
             "manual_only_platform": "facebook",
             "manual_ready_at": in_month, "created_at": in_month,
             "status": "awaiting_manual"},
            {"id": f"{prefix}act_ig1", "tenant_id": tid,
             "manual_only_platform": "instagram",
             "manual_ready_at": in_month, "created_at": in_month,
             "status": "awaiting_manual"},
            {"id": f"{prefix}act_ig2", "tenant_id": tid,
             "manual_only_platform": "instagram",
             "manual_ready_at": in_month, "created_at": in_month,
             "status": "awaiting_manual"},
        ])
        await db.audit_events.insert_many([
            {"id": f"{prefix}mp1", "tenant_id": tid,
             "event_type": "soshie_manual_mark_posted",
             "timestamp": in_month,
             "payload": {"platform": "facebook"}},
            {"id": f"{prefix}mp2", "tenant_id": tid,
             "event_type": "soshie_manual_mark_posted",
             "timestamp": in_month,
             "payload": {"platform": "facebook"}},
        ])
        try:
            r = await analytics_monthly(
                month="2026-02", user=admin,
                tenant={"id": tid, "timezone": "UTC"},
            )
            # Soshie: 4 in-window calls (3 LLM + 1 regex short-circuit),
            # cost = $0.05, cache-hit 1/4, decisions = 2 approve + 1 flag + 1 block.
            m = r["soshie_moderation"]
            assert m["calls_total"] == 4, m
            assert abs(m["cost_estimate_usd"] - 0.05) < 1e-6, m
            assert m["decisions"]["approve"] == 2
            assert m["decisions"]["flag"] == 1
            assert m["decisions"]["block"] == 1
            assert abs(m["cache_hit_rate"] - round(1 / 4, 4)) < 1e-4
            # H7 · regex_short_circuits counter
            assert m["regex_short_circuits"] == 1
            # Templates: at least our 2 prefix rows are counted;
            # the tenant may carry other seed templates that bump
            # the totals. Our slice is verifiable via
            # top_templates + unused_templates.
            t = r["charge_templates"]
            assert t["total_templates"] >= 2
            assert t["total_applies"] >= 5
            tid_top = {row["template_id"]: row
                          for row in t["top_templates"]}
            assert f"{prefix}t1" in tid_top
            assert tid_top[f"{prefix}t1"]["revenue_contribution_usd"] == 250.0
            assert any(u["template_id"] == f"{prefix}t2"
                       for u in t["unused_templates"])
            # Drift: 3 dispatched, 3 days with drift, worst = 42.
            d = r["drift_alerts"]
            assert d["dispatches_total"] == 3
            assert d["days_with_drift"] == 3
            assert d["worst_day"]["dangling_refs_total"] == 42
            assert d["clean_heartbeats"] == 1
            # Manual: 4 generated, 2 marked → 50%.
            mc = r["soshie_manual_conversion"]
            assert mc["posts_generated_total"] == 4
            assert mc["posts_marked_posted_total"] == 2
            assert abs(mc["conversion_rate"] - 0.5) < 1e-6
            by = {row["platform"]: row for row in mc["by_platform"]}
            assert by["facebook"]["conversion_rate"] == 1.0
            assert by["instagram"]["conversion_rate"] == 0.0
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_h6_tenant_isolation_prevents_leak():
    from routers.analytics_monthly import analytics_monthly

    async def _go(db):
        tid_a, admin_a = await _admin_ctx(db)
        tid_b = f"h6-alt-{uuid.uuid4().hex[:6]}"
        await db.tenants.insert_one({
            "id": tid_b, "slug": tid_b, "name": "H6 alt",
        })
        prefix = f"TEST_H6_ISO_{uuid.uuid4().hex[:6]}_"
        in_month = _in_month_iso()
        try:
            # Tenant B has 10 expensive moderation calls this month.
            docs = [
                {"id": f"{prefix}b{i}", "tenant_id": tid_b,
                 "decision": "approve", "cost_estimate_usd": 5.0,
                 "from_cache": False, "created_at": in_month}
                for i in range(10)
            ]
            await db.soshie_moderation_results.insert_many(docs)
            r = await analytics_monthly(
                month="2026-02", user=admin_a,
                tenant={"id": tid_a, "timezone": "UTC"},
            )
            # None of tenant B's rows leak into tenant A's numbers
            # (tenant A may have other data; we only assert no
            # leakage of the specific $50 spend).
            assert r["tenant_id"] == tid_a
            assert r["soshie_moderation"]["cost_estimate_usd"] < 50.0
        finally:
            await db.soshie_moderation_results.delete_many(
                {"tenant_id": tid_b},
            )
            await db.tenants.delete_one({"id": tid_b})

    run_test(_go)


def test_h6_month_boundary_february_28_or_29():
    """February window must span the whole month regardless of
    28/29 days. 2026 is not a leap year, so Feb has 28 days."""
    from routers.analytics_monthly import analytics_monthly

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        prefix = f"TEST_H6_MB_{uuid.uuid4().hex[:6]}_"
        await _cleanup(db, tid, prefix)
        # A moderation call on Feb 28 must be INCLUDED. A call on
        # Mar 1 must be EXCLUDED.
        feb28 = datetime(2026, 2, 28, 23, 30, tzinfo=timezone.utc).isoformat()
        mar1 = datetime(2026, 3, 1, 0, 30, tzinfo=timezone.utc).isoformat()
        await db.soshie_moderation_results.insert_many([
            {"id": f"{prefix}m1", "tenant_id": tid,
             "decision": "approve", "cost_estimate_usd": 1.0,
             "from_cache": False, "created_at": feb28},
            {"id": f"{prefix}m2", "tenant_id": tid,
             "decision": "approve", "cost_estimate_usd": 999.0,
             "from_cache": False, "created_at": mar1},
        ])
        try:
            r = await analytics_monthly(
                month="2026-02", user=admin,
                tenant={"id": tid, "timezone": "UTC"},
            )
            # Feb 28 in, Mar 1 out.
            m = r["soshie_moderation"]
            # There may be other Feb rows in the seed set — just
            # assert the March row didn't leak.
            assert m["cost_estimate_usd"] < 999.0
            assert m["calls_total"] >= 1
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_h6_rejects_bogus_month():
    from routers.analytics_monthly import analytics_monthly

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        with pytest.raises(HTTPException) as ei:
            await analytics_monthly(
                month="not-a-date", user=admin,
                tenant={"id": tid, "timezone": "UTC"},
            )
        assert ei.value.status_code == 400
        assert ei.value.detail.get("detail") == "invalid_month"

    run_test(_go)


def test_h6_rbac_tech_role_blocked():
    from utils import require_admin

    tech = {"id": "test-h6-tech", "role": "technician"}
    with pytest.raises(HTTPException) as ei:
        require_admin(user=tech)
    assert ei.value.status_code == 403


def test_h6_empty_tenant_returns_zeros_without_error():
    from routers.analytics_monthly import analytics_monthly

    async def _go(db):
        _, admin = await _admin_ctx(db)
        empty_tid = f"h6-empty-{uuid.uuid4().hex[:6]}"
        await db.tenants.insert_one({
            "id": empty_tid, "slug": empty_tid, "name": "H6 empty",
        })
        try:
            r = await analytics_monthly(
                month="2026-02", user=admin,
                tenant={"id": empty_tid, "timezone": "UTC"},
            )
            assert r["soshie_moderation"]["calls_total"] == 0
            assert r["soshie_moderation"]["cost_estimate_usd"] == 0
            assert r["charge_templates"]["total_templates"] == 0
            assert r["charge_templates"]["total_applies"] == 0
            assert r["drift_alerts"]["dispatches_total"] == 0
            assert r["drift_alerts"]["dispatch_success_rate"] == 0.0
            assert r["soshie_manual_conversion"]["posts_generated_total"] == 0
            assert r["soshie_manual_conversion"]["conversion_rate"] == 0.0
        finally:
            await db.tenants.delete_one({"id": empty_tid})

    run_test(_go)
