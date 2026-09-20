"""Phase A2 · Feb-2026 · Proactive Intelligence — chemistry-upsell
scan pytest suite.

Covers:
  1. Happy: 3 consecutive high-salt readings → 1 alert emitted
     with correct title / body / actor_context.
  2. Happy: 3 consecutive low calcium_hardness readings → 1 alert,
     direction=low, action=water_treatment.
  3. Mixed direction (2 high + 1 low) → NO alert.
  4. Only 2 consecutive out-of-band → NO alert.
  5. 3 consecutive out-of-band with a 4th (older) in-band still
     emits (only last 3 matter).
  6. Tenant with no chemistry targets configured → NO alerts, no
     crash.
  7. Measurement not in the RECO dict but IS in tenant targets →
     emits with the ``chemistry_review`` fallback.
  8. Dedup: rerun with the same trio → 0 new emits, deduped
     counter increments.
  9. Shift: adding a fresh out-of-band visit shifts the trio → a
     new alert emits (old alert remains untouched).
 10. Multiple measurements out-of-band on the same trio → one
     alert per measurement.
 11. Tenant isolation — tenant B's out-of-band visits do NOT
     surface to tenant A admin.
 12. ``POST /scans/chemistry-upsell/run-now`` requires admin /
     super_admin; tech gets 403 ``insufficient_role_for_alerts``.
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
# Fixture — a tenant with configured chemistry targets + a second
# tenant for isolation, plus admin / super / tech user rows.
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture
def a2_seed():
    tid   = f"a2-tid-{uuid.uuid4()}"
    tid_b = f"a2-tid-b-{uuid.uuid4()}"
    admin_uid = f"a2-admin-{uuid.uuid4()}"
    super_uid = f"a2-super-{uuid.uuid4()}"
    tech_uid  = f"a2-tech-{uuid.uuid4()}"

    async def _seed(_db):
        from services.intelligence.alerts import ensure_indexes
        await ensure_indexes()
        await _db.tenants.insert_many([
            {
                "id": tid, "name": "Tenant A2",
                "slug": f"a2-{uuid.uuid4().hex[:8]}", "active": True,
                "settings": {"chemistry": {"targets": {
                    "salt":             {"min": 2700, "max": 3400, "unit": "ppm"},
                    "calcium_hardness": {"min": 200,  "max": 400,  "unit": "ppm"},
                    "ph":               {"min": 7.2,  "max": 7.6,  "unit": ""},
                    "cyanuric_acid":    {"min": 30,   "max": 50,   "unit": "ppm"},
                    # A "future" measurement that's NOT in the RECO
                    # dict — should fall back to chemistry_review.
                    "iron":             {"min": 0,    "max": 3,    "unit": "ppm"},
                }}},
            },
            {
                "id": tid_b, "name": "Tenant B A2",
                "slug": f"a2b-{uuid.uuid4().hex[:8]}", "active": True,
                "settings": {"chemistry": {"targets": {
                    "salt": {"min": 2700, "max": 3400, "unit": "ppm"},
                }}},
            },
        ])
        await _db.users.insert_many([
            {"id": admin_uid, "email": f"admin-{admin_uid}@ex.test",
             "role": "admin", "tenant_id": tid, "name": "Alex Admin"},
            {"id": super_uid, "email": f"super-{super_uid}@ex.test",
             "role": "super_admin", "tenant_id": tid, "name": "Sam Super"},
            {"id": tech_uid, "email": f"tech-{tech_uid}@ex.test",
             "role": "technician", "tenant_id": tid, "name": "Tammy Tech"},
        ])

    async def _teardown(_db):
        await _db.tenants.delete_many({"id": {"$in": [tid, tid_b]}})
        await _db.users.delete_many({"id": {"$in": [
            admin_uid, super_uid, tech_uid]}})
        await _db.intelligence_alerts.delete_many({
            "tenant_id": {"$in": [tid, tid_b]}})

    run_test(_seed)
    yield {
        "tenant_id":   tid,
        "tenant_b":    tid_b,
        "admin_uid":   admin_uid,
        "admin_token": _mint_token(
            uid=admin_uid, tid=tid, role="admin",
            email=f"admin-{admin_uid}@ex.test"),
        "tech_token":  _mint_token(
            uid=tech_uid, tid=tid, role="technician",
            email=f"tech-{tech_uid}@ex.test"),
    }
    run_test(_teardown)


async def _mk_customer(_db, tid: str) -> str:
    cid = f"a2-cust-{uuid.uuid4()}"
    await _db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": f"Cust {cid[:8]}",
    })
    return cid


async def _mk_job(_db, tid: str, cid: str) -> str:
    jid = f"a2-job-{uuid.uuid4()}"
    await _db.jobs.insert_one({
        "id": jid, "tenant_id": tid, "customer_id": cid,
        "service_type": "Pool Cleaning",
        "status": "completed",
    })
    return jid


async def _mk_report(
    _db, tid: str, cid: str, submitted_at: datetime,
    readings: Dict[str, float],
) -> str:
    """Seed a submitted service_report with chemical_readings."""
    jid = await _mk_job(_db, tid, cid)
    chem_readings = [
        {"key": k, "name": k, "value": v, "unit": ""}
        for k, v in readings.items()
    ]
    res = await _db.service_reports.insert_one({
        "job_id":            jid,
        "submitted_at":      submitted_at,
        "chemical_readings": chem_readings,
    })
    return str(res.inserted_id)


async def _cleanup_customer_inner(_db, cid: str) -> None:
    jobs = await _db.jobs.find(
        {"customer_id": cid}, {"_id": 0, "id": 1}).to_list(500)
    jids = [j["id"] for j in jobs]
    if jids:
        await _db.service_reports.delete_many(
            {"job_id": {"$in": jids}})
    await _db.jobs.delete_many({"customer_id": cid})
    await _db.customers.delete_many({"id": cid})
    await _db.intelligence_alerts.delete_many({"customer_id": cid})


# ═════════════════════════════════════════════════════════════════════
# 1 · Happy path — 3 consecutive high salt readings.
# ═════════════════════════════════════════════════════════════════════
def test_high_salt_trio_emits_filter_clean_alert(a2_seed):
    S = a2_seed
    result_holder: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.chemistry_upsell_scan import (
            run_chemistry_upsell_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result_holder["cid"] = cid
        now = datetime.now(timezone.utc)
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=1),  {"salt": 4600})
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=8),  {"salt": 4400})
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=15), {"salt": 4200})
        summary = await run_chemistry_upsell_scan(tenant_id=S["tenant_id"])
        result_holder["summary"] = summary
        result_holder["alert"] = await _db.intelligence_alerts.find_one(
            {"tenant_id": S["tenant_id"], "customer_id": cid,
             "category":  "chemistry_upsell"})
        await _cleanup_customer_inner(_db, cid)

    run_test(_go)
    summary = result_holder["summary"]
    assert summary["alerts_emitted"] == 1, summary
    assert summary["scanned_customers"] >= 1
    assert summary["alerts_deduped"] == 0
    alert = result_holder["alert"]
    assert alert is not None
    assert alert["severity"] == "recommended"
    assert alert["category"] == "chemistry_upsell"
    assert "salt" in alert["title"].lower()
    assert "filter clean" in alert["title"].lower()
    assert "4600" in alert["body"] and "2700-3400" in alert["body"]
    ctx = alert["actor_context"]
    assert ctx["measurement"] == "salt"
    assert ctx["direction"] == "high"
    assert ctx["readings"] == [4600, 4400, 4200]
    assert ctx["target_min"] == 2700 and ctx["target_max"] == 3400
    assert ctx["recommended_action"] == "filter_clean"
    assert ctx["suggested_service_type"] == "filter_clean"
    assert len(ctx["visit_ids"]) == 3
    assert alert["job_id"] is not None


# ═════════════════════════════════════════════════════════════════════
# 2 · Happy path — 3 consecutive low calcium_hardness readings.
# ═════════════════════════════════════════════════════════════════════
def test_low_hardness_trio_emits_water_treatment_alert(a2_seed):
    S = a2_seed
    result_holder: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.chemistry_upsell_scan import (
            run_chemistry_upsell_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result_holder["cid"] = cid
        now = datetime.now(timezone.utc)
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=1),
                          {"calcium_hardness": 150})
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=8),
                          {"calcium_hardness": 120})
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=15),
                          {"calcium_hardness": 100})
        result_holder["summary"] = await run_chemistry_upsell_scan(
            tenant_id=S["tenant_id"])
        result_holder["alert"] = await _db.intelligence_alerts.find_one(
            {"tenant_id": S["tenant_id"], "customer_id": cid})
        await _cleanup_customer_inner(_db, cid)

    run_test(_go)
    assert result_holder["summary"]["alerts_emitted"] == 1
    alert = result_holder["alert"]
    ctx = alert["actor_context"]
    assert ctx["direction"] == "low"
    assert ctx["measurement"] == "calcium_hardness"
    assert ctx["recommended_action"] == "water_treatment"


# ═════════════════════════════════════════════════════════════════════
# 3 · Mixed direction (2 high + 1 low) → NO alert.
# ═════════════════════════════════════════════════════════════════════
def test_mixed_direction_emits_no_alert(a2_seed):
    S = a2_seed
    result_holder: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.chemistry_upsell_scan import (
            run_chemistry_upsell_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result_holder["cid"] = cid
        now = datetime.now(timezone.utc)
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=1),  {"salt": 4600})
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=8),  {"salt": 2500})
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=15), {"salt": 4200})
        result_holder["summary"] = await run_chemistry_upsell_scan(
            tenant_id=S["tenant_id"])
        result_holder["alert"] = await _db.intelligence_alerts.find_one(
            {"tenant_id": S["tenant_id"], "customer_id": cid})
        await _cleanup_customer_inner(_db, cid)

    run_test(_go)
    assert result_holder["summary"]["alerts_emitted"] == 0
    assert result_holder["alert"] is None


# ═════════════════════════════════════════════════════════════════════
# 4 · Only 2 consecutive out-of-band → NO alert.
# ═════════════════════════════════════════════════════════════════════
def test_only_two_visits_no_alert(a2_seed):
    S = a2_seed
    result_holder: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.chemistry_upsell_scan import (
            run_chemistry_upsell_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result_holder["cid"] = cid
        now = datetime.now(timezone.utc)
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=1), {"salt": 4600})
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=8), {"salt": 4400})
        result_holder["summary"] = await run_chemistry_upsell_scan(
            tenant_id=S["tenant_id"])
        result_holder["alert"] = await _db.intelligence_alerts.find_one(
            {"tenant_id": S["tenant_id"], "customer_id": cid})
        await _cleanup_customer_inner(_db, cid)

    run_test(_go)
    assert result_holder["summary"]["alerts_emitted"] == 0
    assert result_holder["alert"] is None


# ═════════════════════════════════════════════════════════════════════
# 5 · 3 consecutive high but a 4th (older) reading was in-band.
#     Only the trailing three matter → alert emits.
# ═════════════════════════════════════════════════════════════════════
def test_older_in_band_reading_ignored(a2_seed):
    S = a2_seed
    result_holder: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.chemistry_upsell_scan import (
            run_chemistry_upsell_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result_holder["cid"] = cid
        now = datetime.now(timezone.utc)
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=1),  {"salt": 4600})
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=8),  {"salt": 4400})
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=15), {"salt": 4200})
        # 4th (oldest) in-band — should NOT change the outcome.
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=22), {"salt": 3000})
        result_holder["summary"] = await run_chemistry_upsell_scan(
            tenant_id=S["tenant_id"])
        await _cleanup_customer_inner(_db, cid)

    run_test(_go)
    assert result_holder["summary"]["alerts_emitted"] == 1


# ═════════════════════════════════════════════════════════════════════
# 6 · Tenant with no chemistry targets → NO alerts, no crash.
# ═════════════════════════════════════════════════════════════════════
def test_tenant_without_targets_emits_nothing(a2_seed):
    S = a2_seed  # noqa: F841
    tid_no = f"a2-tid-notarg-{uuid.uuid4()}"
    result_holder: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.chemistry_upsell_scan import (
            run_chemistry_upsell_scan,
        )
        await _db.tenants.insert_one({
            "id": tid_no, "name": "No Targets",
            "slug": f"nt-{uuid.uuid4().hex[:8]}", "active": True,
        })
        cid = await _mk_customer(_db, tid_no)
        result_holder["cid"] = cid
        now = datetime.now(timezone.utc)
        for i, val in enumerate([4600, 4400, 4200]):
            await _mk_report(_db, tid_no, cid,
                              now - timedelta(days=1 + 7 * i),
                              {"salt": val})
        result_holder["summary"] = await run_chemistry_upsell_scan(
            tenant_id=tid_no)
        await _cleanup_customer_inner(_db, cid)
        await _db.tenants.delete_many({"id": tid_no})

    run_test(_go)
    assert result_holder["summary"]["alerts_emitted"] == 0


# ═════════════════════════════════════════════════════════════════════
# 7 · Measurement configured but not in RECO dict → fallback.
# ═════════════════════════════════════════════════════════════════════
def test_fallback_chemistry_review_for_unknown_measurement(a2_seed):
    S = a2_seed
    result_holder: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.chemistry_upsell_scan import (
            run_chemistry_upsell_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result_holder["cid"] = cid
        now = datetime.now(timezone.utc)
        # ``iron`` was seeded with targets 0-3 ppm. All three
        # readings are > 3 → high but no RECO row → fallback.
        for i, val in enumerate([5, 6, 7]):
            await _mk_report(_db, S["tenant_id"], cid,
                              now - timedelta(days=1 + 7 * i),
                              {"iron": val})
        await run_chemistry_upsell_scan(tenant_id=S["tenant_id"])
        result_holder["alert"] = await _db.intelligence_alerts.find_one(
            {"tenant_id": S["tenant_id"], "customer_id": cid,
             "category":  "chemistry_upsell"})
        await _cleanup_customer_inner(_db, cid)

    run_test(_go)
    alert = result_holder["alert"]
    assert alert is not None
    ctx = alert["actor_context"]
    assert ctx["measurement"] == "iron"
    assert ctx["recommended_action"] == "chemistry_review"
    assert ctx["suggested_service_type"] == "chemistry_review"


# ═════════════════════════════════════════════════════════════════════
# 8 · Dedup — rerun with same trio → 0 new emits, deduped increments.
# ═════════════════════════════════════════════════════════════════════
def test_rerun_same_trio_dedups(a2_seed):
    S = a2_seed
    result_holder: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.chemistry_upsell_scan import (
            run_chemistry_upsell_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result_holder["cid"] = cid
        now = datetime.now(timezone.utc)
        for i, val in enumerate([4600, 4400, 4200]):
            await _mk_report(_db, S["tenant_id"], cid,
                              now - timedelta(days=1 + 7 * i),
                              {"salt": val})
        result_holder["first"] = await run_chemistry_upsell_scan(
            tenant_id=S["tenant_id"])
        result_holder["second"] = await run_chemistry_upsell_scan(
            tenant_id=S["tenant_id"])
        await _cleanup_customer_inner(_db, cid)

    run_test(_go)
    assert result_holder["first"]["alerts_emitted"] == 1
    assert result_holder["first"]["alerts_deduped"] == 0
    assert result_holder["second"]["alerts_emitted"] == 0
    assert result_holder["second"]["alerts_deduped"] == 1


# ═════════════════════════════════════════════════════════════════════
# 9 · Shift — new visit pushes out the oldest. New trio (still
#     out-of-band) emits a fresh alert; original stays.
# ═════════════════════════════════════════════════════════════════════
def test_window_shift_emits_new_alert(a2_seed):
    S = a2_seed
    result_holder: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.chemistry_upsell_scan import (
            run_chemistry_upsell_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result_holder["cid"] = cid
        now = datetime.now(timezone.utc)
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=8),  {"salt": 4600})
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=15), {"salt": 4400})
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=22), {"salt": 4200})
        result_holder["first"] = await run_chemistry_upsell_scan(
            tenant_id=S["tenant_id"])
        # Newer visit slides in — still high.
        await _mk_report(_db, S["tenant_id"], cid,
                          now - timedelta(days=1),  {"salt": 4800})
        result_holder["second"] = await run_chemistry_upsell_scan(
            tenant_id=S["tenant_id"])
        result_holder["alerts_count"] = (
            await _db.intelligence_alerts.count_documents(
                {"tenant_id": S["tenant_id"], "customer_id": cid,
                 "category":  "chemistry_upsell"})
        )
        await _cleanup_customer_inner(_db, cid)

    run_test(_go)
    assert result_holder["first"]["alerts_emitted"] == 1
    assert result_holder["second"]["alerts_emitted"] == 1
    assert result_holder["second"]["alerts_deduped"] == 0
    assert result_holder["alerts_count"] == 2


# ═════════════════════════════════════════════════════════════════════
# 10 · Multiple measurements on same trio → one alert per measurement.
# ═════════════════════════════════════════════════════════════════════
def test_multi_measurement_out_of_band_emits_one_per_key(a2_seed):
    S = a2_seed
    result_holder: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.chemistry_upsell_scan import (
            run_chemistry_upsell_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result_holder["cid"] = cid
        now = datetime.now(timezone.utc)
        readings_seq: List[Dict[str, float]] = [
            {"salt": 4600, "cyanuric_acid": 90},
            {"salt": 4400, "cyanuric_acid": 80},
            {"salt": 4200, "cyanuric_acid": 70},
        ]
        for i, r in enumerate(readings_seq):
            await _mk_report(_db, S["tenant_id"], cid,
                              now - timedelta(days=1 + 7 * i), r)
        result_holder["summary"] = await run_chemistry_upsell_scan(
            tenant_id=S["tenant_id"])
        result_holder["alerts_count"] = (
            await _db.intelligence_alerts.count_documents(
                {"tenant_id": S["tenant_id"], "customer_id": cid,
                 "category":  "chemistry_upsell"})
        )
        result_holder["measurements"] = (
            await _db.intelligence_alerts.distinct(
                "actor_context.measurement",
                {"tenant_id": S["tenant_id"], "customer_id": cid})
        )
        await _cleanup_customer_inner(_db, cid)

    run_test(_go)
    assert result_holder["summary"]["alerts_emitted"] == 2
    assert result_holder["alerts_count"] == 2
    assert set(result_holder["measurements"]) == {"salt", "cyanuric_acid"}


# ═════════════════════════════════════════════════════════════════════
# 11 · Tenant isolation — tenant B's readings never leak.
# ═════════════════════════════════════════════════════════════════════
def test_tenant_isolation_no_cross_tenant_leaks(a2_seed):
    S = a2_seed
    result_holder: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.chemistry_upsell_scan import (
            run_chemistry_upsell_scan,
        )
        cb = await _mk_customer(_db, S["tenant_b"])
        result_holder["cb"] = cb
        now = datetime.now(timezone.utc)
        for i, val in enumerate([4800, 4600, 4400]):
            await _mk_report(_db, S["tenant_b"], cb,
                              now - timedelta(days=1 + 7 * i),
                              {"salt": val})
        result_holder["summary_a"] = await run_chemistry_upsell_scan(
            tenant_id=S["tenant_id"])
        result_holder["alert_leak"] = await _db.intelligence_alerts.find_one(
            {"tenant_id": S["tenant_id"], "customer_id": cb})
        await _cleanup_customer_inner(_db, cb)

    run_test(_go)
    assert result_holder["summary_a"]["alerts_emitted"] == 0
    assert result_holder["alert_leak"] is None


# ═════════════════════════════════════════════════════════════════════
# 12 · Manual scan-run-now route — admin OK, tech 403.
# ═════════════════════════════════════════════════════════════════════
def test_scan_run_now_route_role_gate(a2_seed):
    S = a2_seed
    app = _get_app()
    result_holder: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            # Admin OK.
            r = await client.post(
                f"{API}/intelligence/scans/chemistry-upsell/run-now",
                headers={"Authorization": f"Bearer {S['admin_token']}"},
                json={})
            result_holder["admin_status"] = r.status_code
            result_holder["admin_body"] = r.json() if r.status_code == 200 else r.text

            # Tech forbidden.
            r = await client.post(
                f"{API}/intelligence/scans/chemistry-upsell/run-now",
                headers={"Authorization": f"Bearer {S['tech_token']}"},
                json={})
            result_holder["tech_status"] = r.status_code
            result_holder["tech_detail"] = (r.json() or {}).get("detail")

    run_test(_go)
    assert result_holder["admin_status"] == 200, result_holder
    body = result_holder["admin_body"]
    assert "alerts_emitted" in body
    assert "scanned_customers" in body
    assert "alerts_deduped" in body
    assert result_holder["tech_status"] == 403
    assert result_holder["tech_detail"] == "insufficient_role_for_alerts"
