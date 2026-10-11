"""Feb-2026 · Pool Service Report drill-down phase.

Backend coverage for the attribution-ladder audit + the two new
drill-down endpoints.

Scope — matches the brief for this phase:
  1. Attribution ladder — ``technician_id`` → ``technician_name``
     (users.name rescue) → ``crew_id`` → ``Unassigned``.
  2. Reconciliation diagnostic (passive — never raises).
  3. Explicit ``Unassigned`` row surfaces when attribution fails.
  4. ``/reports/pool-service/jobs`` bucket + tech_id drill-down.
  5. ``/reports/pool-service/email-history/{id}/contents`` drill.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from tests._shared_mongo import shared_db as _shared_db


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_db = _shared_db()
_CACHE: dict = {}


def _login(email: str) -> str:
    key = f"tok:{email}"
    if _CACHE.get(key):
        return _CACHE[key]
    for _ in range(3):
        try:
            r = requests.post(
                f"{API}/auth/login",
                json={"email": email, "password": "password123"},
                timeout=30,
            )
            if r.status_code == 200:
                _CACHE[key] = r.json()["access_token"]
                return _CACHE[key]
        except requests.exceptions.RequestException:
            continue
    raise RuntimeError(f"login failed for {email}")


def _seed_tenant() -> str:
    tid = f"TEST-poolsvc-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({
        "id": tid, "slug": tid.lower(),
        "name": "TEST_poolsvc_drilldown",
        "active": True,
        # Pool industry so ``derive_industry_for_job`` keeps the
        # seeded jobs in the Pool Service Report.
        "industries": ["pool"], "industry": "pool",
    })
    return tid


def _seed_admin(tid: str):
    from utils import hash_password
    uid = f"TEST-poolsvc-u-{uuid.uuid4().hex[:6]}"
    email = f"poolsvc-{uuid.uuid4().hex[:6]}@example.com"
    _db.users.insert_one({
        "id": uid, "tenant_id": tid, "email": email,
        "name": "TEST_poolsvc_admin", "role": "admin",
        "password_hash": hash_password("password123"),
    })
    return uid, email, _login(email)


def _seed_tech(tid: str, name: str) -> tuple[str, str]:
    """Seed a tech user AND stash a canonical ``technician_id`` on
    the row so the aggregator uses the same bucket key as
    production data."""
    from utils import hash_password
    uid = f"TEST-tech-{uuid.uuid4().hex[:6]}"
    _db.users.insert_one({
        "id": uid, "tenant_id": tid,
        "email": f"{uid}@example.com", "name": name,
        "role": "technician", "technician_id": uid,
        "active": True,
        "password_hash": hash_password("password123"),
    })
    return uid, name


def _seed_crew(tid: str, lead_uid: str) -> str:
    cid = f"TEST-crew-{uuid.uuid4().hex[:6]}"
    _db.crews.insert_one({
        "id": cid, "tenant_id": tid, "name": "TEST_crew",
        "tech_ids": [lead_uid], "active": True,
    })
    return cid


def _seed_job(tid, *, sched, status="completed", work_class=None,
              technician_id=None, technician_name=None,
              crew_id=None, customer_name="TEST_customer"):
    jid = f"TEST-job-{uuid.uuid4().hex[:6]}"
    doc = {
        "id": jid, "tenant_id": tid, "status": status,
        "scheduled_date": sched,
        # service_type carries a pool keyword so
        # ``derive_industry_for_job(strict_mode=True)`` returns
        # "pool" without the tenant having to carry an explicit
        # industry override.
        "service_type": "weekly pool service",
        "title": "Weekly service",
        "customer_id": f"TEST-cust-{uuid.uuid4().hex[:6]}",
        "customer_name": customer_name,
    }
    if work_class:      doc["work_class"] = work_class
    if technician_id:   doc["technician_id"] = technician_id
    if technician_name: doc["technician_name"] = technician_name
    if crew_id:         doc["crew_id"] = crew_id
    _db.jobs.insert_one(doc)
    return jid


def _cleanup(tid, uid, email):
    _db.jobs.delete_many({"tenant_id": tid})
    _db.crews.delete_many({"tenant_id": tid})
    _db.users.delete_many({"tenant_id": tid})
    _db.tenants.delete_one({"id": tid})
    _db.email_delivery_log.delete_many({"tenant_id": tid})
    _CACHE.pop(f"tok:{email}", None)


def _mon_sun():
    d = date.today()
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat(), (monday + timedelta(days=6)).isoformat()


# ───────── Attribution ladder — Problem 1 ─────────

def test_pool_service_report_attribution_ladder_covers_every_rung():
    """Seed a mix of jobs per the schema ladder and assert
    attribution matches the documented priority order."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, ethan_name = _seed_tech(tid, "Ethan Smith")
        carlos_uid, carlos_name = _seed_tech(tid, "Carlos Rivera")
        mia_uid, mia_name = _seed_tech(tid, "Mia Johnson")
        crew_id = _seed_crew(tid, mia_uid)

        mon, sun = _mon_sun()

        # Rung #1 — technician_id direct (Ethan × 2 service).
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=ethan_uid, technician_name=ethan_name)
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=ethan_uid, technician_name=ethan_name)
        # Rung #2 — name-only, resolves via users.name (Carlos × 1).
        _seed_job(tid, sched=mon, work_class="service",
                   technician_name=carlos_name)
        # Rung #3 — crew_id only, resolves to Mia (× 1).
        _seed_job(tid, sched=mon, work_class="repair", crew_id=crew_id)
        # Rung #4 — no attribution anywhere → Unassigned (× 1).
        _seed_job(tid, sched=mon, work_class="service")

        r = requests.get(
            f"{API}/reports/pool-service?date_from={mon}&date_to={sun}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        by_tech = {t["technician_id"]: t for t in body["by_technician"]}
        # Rung #1
        assert by_tech[ethan_uid]["pools_serviced"] == 2
        # Rung #2
        assert by_tech[carlos_uid]["pools_serviced"] == 1
        # Rung #3 — crew_id → mia
        assert by_tech[mia_uid]["repairs_completed"] == 1
        # Rung #4 — Unassigned present AND holds the orphan job
        unassigned = by_tech.get(None)
        assert unassigned is not None
        assert unassigned["pools_serviced"] == 1
        # Published attribution_priority metadata.
        assert body["attribution_priority"] == [
            "technician_id", "technician_name",
            "crew_id→crews.tech_ids[0]", "Unassigned",
        ]
    finally:
        _cleanup(tid, uid, email)


def test_pool_service_report_unassigned_not_silently_bucketed_into_other():
    """A job with no attribution AND no ``work_class`` MUST land
    in the Unassigned row's ``other`` counter — NOT silently
    absorbed by a tech or dropped from the response."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        mon, sun = _mon_sun()
        _seed_job(tid, sched=mon)  # no work_class, no tech, no crew
        r = requests.get(
            f"{API}/reports/pool-service?date_from={mon}&date_to={sun}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=20,
        )
        assert r.status_code == 200
        body = r.json()
        by_tech = {t["technician_id"]: t for t in body["by_technician"]}
        unassigned = by_tech.get(None)
        assert unassigned is not None, (
            "Unassigned row must be present when attribution fails"
        )
        assert unassigned["other"] == 1
        # Bucket surfaces in the top-level ``other`` array too.
        other_rows = body.get("other") or []
        assert any(r_["technician_id"] is None and r_["other"] >= 1
                    for r_ in other_rows)
    finally:
        _cleanup(tid, uid, email)


def test_pool_service_report_reconciliation_present_and_matches():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, ethan_name = _seed_tech(tid, "Ethan Smith")
        mon, sun = _mon_sun()
        # 3 completed service + 1 completed repair + 1 skipped.
        for _ in range(3):
            _seed_job(tid, sched=mon, work_class="service",
                       technician_id=ethan_uid, technician_name=ethan_name)
        _seed_job(tid, sched=mon, work_class="repair",
                   technician_id=ethan_uid, technician_name=ethan_name)
        _seed_job(tid, sched=mon, status="skipped",
                   technician_id=ethan_uid, technician_name=ethan_name)
        r = requests.get(
            f"{API}/reports/pool-service?date_from={mon}&date_to={sun}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        rec = body.get("reconciliation")
        assert rec and rec["matches"] is True
        assert rec["delta"] == 0
        # counted_total == 3 service + 1 repair + 0 other + 1 skipped
        assert rec["counted_total"] == 5
        assert rec["actual_total"] == 5
        assert rec["dropped_count"] == 0
    finally:
        _cleanup(tid, uid, email)


def test_pool_service_report_sum_of_buckets_equals_total():
    """Invariant: sum(per-tech maintenance) + sum(per-tech repairs)
    + sum(per-tech other) + unassigned === total_completed_all for
    the window."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, ethan_name = _seed_tech(tid, "Ethan Smith")
        mon, sun = _mon_sun()
        for _ in range(4):
            _seed_job(tid, sched=mon, work_class="service",
                       technician_id=ethan_uid, technician_name=ethan_name)
        for _ in range(2):
            _seed_job(tid, sched=mon, work_class="repair",
                       technician_id=ethan_uid, technician_name=ethan_name)
        # 3 "other" (no work_class) completed jobs — the historic
        # silent-21 scenario, now surfaced explicitly.
        for _ in range(3):
            _seed_job(tid, sched=mon,
                       technician_id=ethan_uid, technician_name=ethan_name)
        r = requests.get(
            f"{API}/reports/pool-service?date_from={mon}&date_to={sun}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=20,
        )
        body = r.json()
        rows = body["by_technician"]
        counted = sum(
            (row["pools_serviced"] + row["repairs_completed"]
             + row["other"]) for row in rows
        )
        assert counted == body["total_completed_all"]
        assert counted == 4 + 2 + 3  # 9
    finally:
        _cleanup(tid, uid, email)


# ───────── Drill-down endpoint — Problem 2 TC-A / TC-B ─────────

def test_drilldown_bucket_maintenance_returns_only_service_rows():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, ethan_name = _seed_tech(tid, "Ethan Smith")
        mon, sun = _mon_sun()
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=ethan_uid, technician_name=ethan_name,
                   customer_name="Alpha")
        _seed_job(tid, sched=mon, work_class="repair",
                   technician_id=ethan_uid, technician_name=ethan_name,
                   customer_name="Bravo")
        _seed_job(tid, sched=mon,
                   technician_id=ethan_uid, technician_name=ethan_name,
                   customer_name="Charlie")
        r = requests.get(
            f"{API}/reports/pool-service/jobs"
            f"?date_from={mon}&date_to={sun}&bucket=maintenance",
            headers={"Authorization": f"Bearer {tok}"}, timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 1
        names = [r_["customer_name"] for r_ in body["items"]]
        assert names == ["Alpha"]
    finally:
        _cleanup(tid, uid, email)


def test_drilldown_bucket_unassigned_returns_only_orphan_jobs():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, _ = _seed_tech(tid, "Ethan Smith")
        mon, sun = _mon_sun()
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=ethan_uid, customer_name="Attributed")
        _seed_job(tid, sched=mon, work_class="service",
                   customer_name="Orphan")  # no tech, no crew
        r = requests.get(
            f"{API}/reports/pool-service/jobs"
            f"?date_from={mon}&date_to={sun}&bucket=unassigned",
            headers={"Authorization": f"Bearer {tok}"}, timeout=20,
        )
        body = r.json()
        assert body["count"] == 1
        assert body["items"][0]["customer_name"] == "Orphan"
    finally:
        _cleanup(tid, uid, email)


def test_drilldown_tech_id_returns_only_that_techs_jobs():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, ethan_name = _seed_tech(tid, "Ethan Smith")
        carlos_uid, carlos_name = _seed_tech(tid, "Carlos Rivera")
        mon, sun = _mon_sun()
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=ethan_uid, technician_name=ethan_name,
                   customer_name="EthanJob")
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=carlos_uid, technician_name=carlos_name,
                   customer_name="CarlosJob")
        r = requests.get(
            f"{API}/reports/pool-service/jobs"
            f"?date_from={mon}&date_to={sun}&tech_id={ethan_uid}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=20,
        )
        body = r.json()
        assert body["count"] == 1
        assert body["items"][0]["customer_name"] == "EthanJob"
    finally:
        _cleanup(tid, uid, email)


def test_drilldown_rejects_both_bucket_and_tech_id():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        mon, sun = _mon_sun()
        r = requests.get(
            f"{API}/reports/pool-service/jobs"
            f"?date_from={mon}&date_to={sun}"
            f"&bucket=maintenance&tech_id=foo",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        assert r.status_code == 422
        r2 = requests.get(
            f"{API}/reports/pool-service/jobs"
            f"?date_from={mon}&date_to={sun}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        assert r2.status_code == 422
    finally:
        _cleanup(tid, uid, email)


def test_drilldown_totals_equal_summary_bucket_counts():
    """Invariant: for every bucket, the drill-down's ``count``
    matches the corresponding summary chip count on the same week."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, ethan_name = _seed_tech(tid, "Ethan Smith")
        mon, sun = _mon_sun()
        for _ in range(3):
            _seed_job(tid, sched=mon, work_class="service",
                       technician_id=ethan_uid)
        for _ in range(2):
            _seed_job(tid, sched=mon, work_class="repair",
                       technician_id=ethan_uid)
        summary = requests.get(
            f"{API}/reports/pool-service?date_from={mon}&date_to={sun}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        for bucket, expected in (
            ("maintenance", summary["summary"]["maintenance_visits"]),
            ("repairs",     summary["summary"]["repair_visits"]),
        ):
            drill = requests.get(
                f"{API}/reports/pool-service/jobs"
                f"?date_from={mon}&date_to={sun}&bucket={bucket}",
                headers={"Authorization": f"Bearer {tok}"}, timeout=15,
            ).json()
            assert drill["count"] == expected, (
                f"bucket={bucket} drill count {drill['count']} != "
                f"summary chip {expected}"
            )
    finally:
        _cleanup(tid, uid, email)


# ───────── Email delivery contents — TC-C ─────────

def test_email_delivery_contents_returns_delivery_plus_customers():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, ethan_name = _seed_tech(tid, "Ethan Smith")
        mon, sun = _mon_sun()
        # Two completed service jobs for two different customers +
        # one skipped (should NOT appear in delivery contents).
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=ethan_uid, technician_name=ethan_name,
                   customer_name="Alpha")
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=ethan_uid, technician_name=ethan_name,
                   customer_name="Bravo")
        _seed_job(tid, sched=mon, status="skipped",
                   technician_id=ethan_uid, technician_name=ethan_name,
                   customer_name="SkippedCo")
        delivery_id = f"TEST-dlv-{uuid.uuid4().hex[:6]}"
        _db.email_delivery_log.insert_one({
            "id": delivery_id, "tenant_id": tid,
            "kind": "pool_service_report",
            "week_start": mon, "week_end": sun,
            "recipients": ["admin@example.com"], "sent": True,
            "mocked": False,
            "sent_at": "2026-02-14T17:00:00+00:00",
        })
        r = requests.get(
            f"{API}/reports/pool-service/email-history/"
            f"{delivery_id}/contents",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["delivery"]["id"] == delivery_id
        # 2 completed jobs, 2 distinct customers; the SkippedCo
        # row is intentionally excluded.
        assert body["job_count"] == 2
        assert body["customer_count"] == 2
        names = sorted(c["customer_name"] for c in body["customers"])
        assert names == ["Alpha", "Bravo"]
    finally:
        _cleanup(tid, uid, email)


def test_email_delivery_contents_404_on_missing_or_wrong_tenant():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        r = requests.get(
            f"{API}/reports/pool-service/email-history/"
            f"does-not-exist/contents",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        assert r.status_code == 404
    finally:
        _cleanup(tid, uid, email)


# ───────── Fix 1 · drill-down status filter (Feb-2026 follow-up) ─────────

def test_drilldown_tech_id_default_completed_matches_chip_count():
    """Fix 1 — the default ``status=completed`` filter restores
    chip↔modal parity (prior behavior returned completed +
    skipped so the modal exceeded the chip)."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        mike_uid, mike_name = _seed_tech(tid, "Mike Rivera")
        mon, sun = _mon_sun()
        # 5 completed service + 2 missed (status=skipped) — pre-fix
        # the drill-down returned all 7.
        for _ in range(5):
            _seed_job(tid, sched=mon, work_class="service",
                       technician_id=mike_uid, technician_name=mike_name)
        for _ in range(2):
            _seed_job(tid, sched=mon, status="skipped",
                       technician_id=mike_uid, technician_name=mike_name)
        drill = requests.get(
            f"{API}/reports/pool-service/jobs"
            f"?date_from={mon}&date_to={sun}&tech_id={mike_uid}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        # Default status=completed → only the 5 completed rows.
        assert drill["count"] == 5
        # Summary chip count for the tech row matches.
        summary = requests.get(
            f"{API}/reports/pool-service?date_from={mon}&date_to={sun}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        by_tech = {t["technician_id"]: t for t in summary["by_technician"]}
        row_completed = (by_tech[mike_uid]["pools_serviced"]
                          + by_tech[mike_uid]["repairs_completed"]
                          + by_tech[mike_uid]["other"])
        assert drill["count"] == row_completed
    finally:
        _cleanup(tid, uid, email)


def test_drilldown_unassigned_default_completed_matches_chip_count():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        mon, sun = _mon_sun()
        # 14 completed service unassigned + 42 missed unassigned.
        for _ in range(14):
            _seed_job(tid, sched=mon, work_class="service",
                       customer_name="Completed")
        for _ in range(42):
            _seed_job(tid, sched=mon, status="skipped",
                       customer_name="MissedCo")
        drill = requests.get(
            f"{API}/reports/pool-service/jobs"
            f"?date_from={mon}&date_to={sun}&bucket=unassigned",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        # Default status=completed → only the 14 completed rows.
        assert drill["count"] == 14
    finally:
        _cleanup(tid, uid, email)


def test_drilldown_status_missed_returns_only_skipped():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        mike_uid, mike_name = _seed_tech(tid, "Mike Rivera")
        mon, sun = _mon_sun()
        for _ in range(5):
            _seed_job(tid, sched=mon, work_class="service",
                       technician_id=mike_uid, technician_name=mike_name)
        for _ in range(2):
            _seed_job(tid, sched=mon, status="skipped",
                       technician_id=mike_uid, technician_name=mike_name)
        drill = requests.get(
            f"{API}/reports/pool-service/jobs"
            f"?date_from={mon}&date_to={sun}"
            f"&tech_id={mike_uid}&status=missed",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        assert drill["count"] == 2
        assert drill["filter"]["status"] == "missed"
    finally:
        _cleanup(tid, uid, email)


def test_drilldown_status_all_returns_union_excluding_dropped():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        mike_uid, mike_name = _seed_tech(tid, "Mike Rivera")
        mon, sun = _mon_sun()
        for _ in range(3):
            _seed_job(tid, sched=mon, work_class="service",
                       technician_id=mike_uid, technician_name=mike_name)
        for _ in range(1):
            _seed_job(tid, sched=mon, status="skipped",
                       technician_id=mike_uid, technician_name=mike_name)
        # A non-terminal (dropped) job — must NOT appear in status=all.
        _seed_job(tid, sched=mon, status="scheduled",
                   technician_id=mike_uid, technician_name=mike_name)
        drill = requests.get(
            f"{API}/reports/pool-service/jobs"
            f"?date_from={mon}&date_to={sun}"
            f"&tech_id={mike_uid}&status=all",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        # 3 completed + 1 missed = 4, scheduled job excluded.
        assert drill["count"] == 4
    finally:
        _cleanup(tid, uid, email)


def test_drilldown_rejects_unknown_status():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        mon, sun = _mon_sun()
        r = requests.get(
            f"{API}/reports/pool-service/jobs"
            f"?date_from={mon}&date_to={sun}"
            f"&bucket=maintenance&status=garbage",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        assert r.status_code == 422
    finally:
        _cleanup(tid, uid, email)


# ───────── Fix 2 · reconciliation now requires dropped==0 ─────────

def test_reconciliation_matches_false_when_dropped_nonzero():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, ethan_name = _seed_tech(tid, "Ethan Smith")
        mon, sun = _mon_sun()
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=ethan_uid, technician_name=ethan_name)
        # Two "dropped" jobs — non-terminal status, no completed
        # timestamp. Pre-fix the reconciliation returned matches=
        # true even though 2 jobs were silently dropped.
        dropped_a = _seed_job(tid, sched=mon, status="scheduled",
                                customer_name="DropA")
        dropped_b = _seed_job(tid, sched=mon, status="in_progress",
                                customer_name="DropB")
        body = requests.get(
            f"{API}/reports/pool-service?date_from={mon}&date_to={sun}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        rec = body["reconciliation"]
        assert rec["matches"] is False
        assert rec["delta"] == 2
        assert rec["dropped_count"] == 2
        sample_ids = {s["job_id"] for s in rec["dropped_sample"]}
        assert dropped_a in sample_ids and dropped_b in sample_ids
        # Each sample row carries a human-readable reason.
        for s in rec["dropped_sample"]:
            assert "reason" in s and s["reason"]
    finally:
        _cleanup(tid, uid, email)


def test_reconciliation_dropped_sample_capped_at_ten():
    """Sanity on the cap — seed 15 dropped jobs, assert only 10
    land in the sample so the payload stays lean."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        mon, sun = _mon_sun()
        for i in range(15):
            _seed_job(tid, sched=mon, status="scheduled",
                       customer_name=f"Drop{i:02d}")
        body = requests.get(
            f"{API}/reports/pool-service?date_from={mon}&date_to={sun}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        rec = body["reconciliation"]
        assert rec["dropped_count"] == 15
        assert len(rec["dropped_sample"]) == 10
    finally:
        _cleanup(tid, uid, email)


# ───────── Fix 3 · delivery contents snapshot vs legacy ─────────

def test_email_contents_reads_snapshot_when_present_and_ignores_later_jobs():
    """Fix 3 — a delivery emitted WITH a ``payload_snapshot`` must
    return the snapshotted job list, NOT the current aggregator
    result (which would include jobs completed after the email)."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, ethan_name = _seed_tech(tid, "Ethan Smith")
        mon, sun = _mon_sun()
        # Seed 2 completed jobs that were in the email body.
        jid_a = _seed_job(tid, sched=mon, work_class="service",
                           technician_id=ethan_uid, technician_name=ethan_name,
                           customer_name="InEmail-A")
        jid_b = _seed_job(tid, sched=mon, work_class="service",
                           technician_id=ethan_uid, technician_name=ethan_name,
                           customer_name="InEmail-B")
        # Create a delivery with the frozen snapshot.
        delivery_id = f"TEST-dlv-{uuid.uuid4().hex[:6]}"
        _db.email_delivery_log.insert_one({
            "id": delivery_id, "tenant_id": tid,
            "kind": "pool_service_report",
            "week_start": mon, "week_end": sun,
            "recipients": ["admin@example.com"], "sent": True,
            "mocked": False, "total_completed": 2,
            "sent_at": "2026-02-14T17:00:00+00:00",
            "payload_snapshot": {
                "job_ids": [jid_a, jid_b],
                "customer_ids": ["cust-a", "cust-b"],
                "jobs": [
                    {"job_id": jid_a, "title": "Weekly service A",
                      "customer_id": "cust-a",
                      "customer_name": "InEmail-A",
                      "scheduled_date": mon,
                      "work_class": "service", "status": "completed"},
                    {"job_id": jid_b, "title": "Weekly service B",
                      "customer_id": "cust-b",
                      "customer_name": "InEmail-B",
                      "scheduled_date": mon,
                      "work_class": "service", "status": "completed"},
                ],
            },
        })
        # Add a new completed job AFTER the delivery was logged.
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=ethan_uid, technician_name=ethan_name,
                   customer_name="PostEmail")
        r = requests.get(
            f"{API}/reports/pool-service/email-history/"
            f"{delivery_id}/contents",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        assert r["source"] == "snapshot"
        assert r["job_count"] == 2  # not 3
        names = sorted(c["customer_name"] for c in r["customers"])
        assert names == ["InEmail-A", "InEmail-B"]
    finally:
        _cleanup(tid, uid, email)


def test_email_contents_legacy_delivery_falls_back_to_recompute_tagged():
    """Fix 3 — a delivery WITHOUT a snapshot (pre-change) still
    returns something, tagged ``source: 'legacy_recompute'`` so
    admins know the drift risk."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, ethan_name = _seed_tech(tid, "Ethan Smith")
        mon, sun = _mon_sun()
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=ethan_uid, technician_name=ethan_name,
                   customer_name="LegacyCo")
        delivery_id = f"TEST-dlv-{uuid.uuid4().hex[:6]}"
        _db.email_delivery_log.insert_one({
            "id": delivery_id, "tenant_id": tid,
            "kind": "pool_service_report",
            "week_start": mon, "week_end": sun,
            "recipients": ["admin@example.com"], "sent": True,
            "mocked": False, "total_completed": 1,
            "sent_at": "2026-02-14T17:00:00+00:00",
            # No ``payload_snapshot`` — simulates a pre-fix row.
        })
        r = requests.get(
            f"{API}/reports/pool-service/email-history/"
            f"{delivery_id}/contents",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        assert r["source"] == "legacy_recompute"
        assert r["job_count"] == 1
    finally:
        _cleanup(tid, uid, email)


# ───────── Mini-fix A · tech-name fallback (never leak UUIDs) ─────────

def test_summary_renders_unknown_tech_label_when_user_missing():
    """A technician_id that cannot be resolved to a user name
    MUST render as ``Unknown tech (xxxxxxxx)``, never the raw
    UUID. ``xxxxxxxx`` is the first 8 chars of the id."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        mon, sun = _mon_sun()
        # Deliberately NOT seeding a users row for this tech id.
        orphan_tid = "b8a68119-1234-abcd-5678-9876543210aa"
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=orphan_tid)
        body = requests.get(
            f"{API}/reports/pool-service?date_from={mon}&date_to={sun}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        row = next((r for r in body["by_technician"]
                     if r["technician_id"] == orphan_tid), None)
        assert row is not None
        assert row["technician_name"] == "Unknown tech (b8a68119)"
        # Full UUID is NOT in the human-readable label.
        assert orphan_tid not in row["technician_name"]
    finally:
        _cleanup(tid, uid, email)


def test_summary_marks_deactivated_user_with_suffix():
    """Deactivated techs still resolve by name BUT the label
    carries ``(deactivated)`` so admins can tell."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        # Seed a tech user WITH active=False.
        from utils import hash_password
        tech_uid = f"TEST-deact-{uuid.uuid4().hex[:6]}"
        _db.users.insert_one({
            "id": tech_uid, "tenant_id": tid,
            "email": f"{tech_uid}@example.com", "name": "Pat Retired",
            "role": "technician", "technician_id": tech_uid,
            "active": False,
            "password_hash": hash_password("password123"),
        })
        mon, sun = _mon_sun()
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=tech_uid)
        body = requests.get(
            f"{API}/reports/pool-service?date_from={mon}&date_to={sun}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        row = next((r for r in body["by_technician"]
                     if r["technician_id"] == tech_uid), None)
        assert row is not None
        assert row["technician_name"] == "Pat Retired (deactivated)"
        assert row["technician_active"] is False
    finally:
        _cleanup(tid, uid, email)


# ───────── Mini-fix B · admin-triggered Friday email ─────────

def test_run_now_requires_admin_role_403_for_tech():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        # Seed a technician user and get its token.
        from utils import hash_password
        tech_uid = f"TEST-rn-tech-{uuid.uuid4().hex[:6]}"
        tech_email = f"rn-tech-{uuid.uuid4().hex[:6]}@example.com"
        _db.users.insert_one({
            "id": tech_uid, "tenant_id": tid, "email": tech_email,
            "name": "RN Tech", "role": "technician",
            "password_hash": hash_password("password123"),
        })
        tech_tok = _login(tech_email)
        r = requests.post(
            f"{API}/reports/pool-service/email-history/run-now",
            headers={"Authorization": f"Bearer {tech_tok}"},
            json={}, timeout=15,
        )
        assert r.status_code == 403
    finally:
        _db.users.delete_one({"id": tech_uid})
        _cleanup(tid, uid, email)


def test_run_now_creates_delivery_with_snapshot_and_returns_stub():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, ethan_name = _seed_tech(tid, "Ethan Smith")
        mon, sun = _mon_sun()
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=ethan_uid, technician_name=ethan_name,
                   customer_name="RunNowCo")
        r = requests.post(
            f"{API}/reports/pool-service/email-history/run-now",
            headers={"Authorization": f"Bearer {tok}"},
            json={"week_ref": mon}, timeout=20,
        )
        assert r.status_code == 200, r.text
        stub = r.json()
        assert "delivery_id" in stub
        assert stub["week_start"] == mon
        assert stub["week_end"]   == sun
        # Delivery row persisted with ``payload_snapshot``.
        delivery = _db.email_delivery_log.find_one(
            {"id": stub["delivery_id"]}, {"_id": 0},
        )
        assert delivery is not None
        snap = delivery.get("payload_snapshot") or {}
        assert isinstance(snap, dict)
        assert snap.get("jobs"), "snapshot jobs must be populated"
        # Fix 3 · Feb-2026 — preview env coerces dry_run so the
        # trigger reflects that posture. The admin-manual
        # (non-dry) branch is only reachable in production.
        assert delivery.get("trigger") in (
            "admin_manual", "admin_dry_run",
        )
        # Audit-log entry present.
        audit = _db.audit_log.find_one(
            {"action": "pool_service_report.email.run_now",
              "target_id": stub["delivery_id"]},
            {"_id": 0},
        )
        assert audit is not None
        assert audit.get("actor_user_id") == uid
    finally:
        _cleanup(tid, uid, email)
        _db.audit_log.delete_many(
            {"action": "pool_service_report.email.run_now",
              "actor_user_id": uid},
        )


def test_run_now_allows_repeat_calls_each_creates_new_delivery():
    """Admin may re-send after a correction — brief rule: allow
    repeats; each run creates its own delivery record."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, ethan_name = _seed_tech(tid, "Ethan Smith")
        mon, sun = _mon_sun()
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=ethan_uid, technician_name=ethan_name)
        stubs = []
        for _ in range(2):
            r = requests.post(
                f"{API}/reports/pool-service/email-history/run-now",
                headers={"Authorization": f"Bearer {tok}"},
                json={"week_ref": mon}, timeout=20,
            )
            assert r.status_code == 200
            stubs.append(r.json())
        # Distinct delivery ids — no dedupe collision.
        assert stubs[0]["delivery_id"] != stubs[1]["delivery_id"]
    finally:
        _cleanup(tid, uid, email)
        _db.audit_log.delete_many(
            {"action": "pool_service_report.email.run_now",
              "actor_user_id": uid},
        )


# ───────── Fix 1 · snapshot key-existence check (Feb-2026 follow-up) ─────────

def test_empty_payload_snapshot_returned_as_snapshot_source_not_legacy():
    """Fix 1 — an empty-but-present ``payload_snapshot`` (admin
    dry-ran on a week with zero completed jobs) must return
    ``source: 'snapshot'`` and job_count=0 — NOT be mis-tagged
    as ``legacy_recompute``."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        mon, sun = _mon_sun()
        delivery_id = f"TEST-empty-{uuid.uuid4().hex[:6]}"
        _db.email_delivery_log.insert_one({
            "id": delivery_id, "tenant_id": tid,
            "kind": "pool_service_report",
            "week_start": mon, "week_end": sun,
            "recipients": [], "sent": True, "mocked": False,
            "total_completed": 0,
            "sent_at": "2026-02-14T17:00:00+00:00",
            # Explicit empty snapshot — ``jobs`` falsy but KEY
            # present. Prior behavior slid into legacy_recompute.
            "payload_snapshot": {"job_ids": [], "customer_ids": [],
                                  "jobs": []},
        })
        r = requests.get(
            f"{API}/reports/pool-service/email-history/"
            f"{delivery_id}/contents",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        assert r["source"] == "snapshot"
        assert r["job_count"] == 0
        assert r["customer_count"] == 0
    finally:
        _cleanup(tid, uid, email)


def test_truly_missing_snapshot_still_falls_back_to_legacy_recompute():
    """Fix 1 negative — only a delivery WITHOUT the
    ``payload_snapshot`` key gets the legacy_recompute tag."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        mon, sun = _mon_sun()
        delivery_id = f"TEST-nosnap-{uuid.uuid4().hex[:6]}"
        _db.email_delivery_log.insert_one({
            "id": delivery_id, "tenant_id": tid,
            "kind": "pool_service_report",
            "week_start": mon, "week_end": sun,
            "recipients": [], "sent": True, "mocked": False,
            "total_completed": 0,
            "sent_at": "2026-02-14T17:00:00+00:00",
            # No ``payload_snapshot`` at all.
        })
        r = requests.get(
            f"{API}/reports/pool-service/email-history/"
            f"{delivery_id}/contents",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        assert r["source"] == "legacy_recompute"
    finally:
        _cleanup(tid, uid, email)


# ───────── Fix 2 · tech-name consistency across weeks ─────────

def test_same_technician_id_renders_same_label_across_weeks():
    """Fix 2 — a given ``technician_id`` must render the SAME
    label on every week in the summary response, regardless of
    whether the ``technician_name`` denorm happened to be
    populated on jobs in that week."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        # Seed a tech user whose canonical label is "Mike Rivera".
        mike_uid, mike_name = _seed_tech(tid, "Mike Rivera")

        from datetime import date, timedelta
        today = date.today()
        weeks = []
        for i in (0, 1, 2):
            mon = today - timedelta(days=today.weekday() + 7 * i)
            sun = mon + timedelta(days=6)
            weeks.append((mon.isoformat(), sun.isoformat()))

        # Week 0 — job carries technician_name denorm.
        _seed_job(tid, sched=weeks[0][0], work_class="service",
                   technician_id=mike_uid,
                   technician_name=mike_name)
        # Week 1 — job carries ONLY technician_id (no denorm).
        _seed_job(tid, sched=weeks[1][0], work_class="service",
                   technician_id=mike_uid)
        # Week 2 — same (no denorm) — different week.
        _seed_job(tid, sched=weeks[2][0], work_class="service",
                   technician_id=mike_uid)

        labels = []
        for mon, sun in weeks:
            r = requests.get(
                f"{API}/reports/pool-service"
                f"?date_from={mon}&date_to={sun}",
                headers={"Authorization": f"Bearer {tok}"}, timeout=15,
            ).json()
            row = next((rr for rr in r["by_technician"]
                         if rr["technician_id"] == mike_uid), None)
            assert row is not None, f"no row for Mike on week {mon}"
            labels.append(row["technician_name"])
        # All three weeks must render the SAME label.
        assert len(set(labels)) == 1, (
            f"inconsistent labels across weeks: {labels}"
        )
        # And the label MUST be the canonical name, not a UUID.
        assert labels[0] == "Mike Rivera"
    finally:
        _cleanup(tid, uid, email)


# ───────── Fix 3 · dry_run safety + preview-env guard ─────────

def test_run_now_dry_run_true_skips_mailer_but_persists_snapshot(monkeypatch):
    """Fix 3 — dry_run=true writes the delivery row with
    ``payload_snapshot`` populated AND tagged
    ``trigger: 'admin_dry_run'`` BUT MUST NOT call the mailer."""
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, ethan_name = _seed_tech(tid, "Ethan Smith")
        mon, sun = _mon_sun()
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=ethan_uid, technician_name=ethan_name,
                   customer_name="DryRunCo")
        # Spy on the mailer via mock patch at the module level —
        # if the dry-run branch is wired correctly, this fn is
        # never awaited.
        import services.pool_service_email as _psm
        called = {"n": 0}
        orig = _psm._send_via_resend

        async def _spy(*a, **kw):
            called["n"] += 1
            return await orig(*a, **kw)
        _psm._send_via_resend = _spy
        try:
            r = requests.post(
                f"{API}/reports/pool-service/email-history/run-now",
                headers={"Authorization": f"Bearer {tok}"},
                json={"week_ref": mon, "dry_run": True}, timeout=20,
            )
        finally:
            _psm._send_via_resend = orig
        assert r.status_code == 200, r.text
        stub = r.json()
        assert stub["dry_run"] is True
        assert stub["sent"] is False
        assert stub["mocked"] is True
        assert called["n"] == 0, "mailer must not be called in dry_run"
        row = _db.email_delivery_log.find_one(
            {"id": stub["delivery_id"]}, {"_id": 0},
        )
        assert row["trigger"] == "admin_dry_run"
        assert row["sent"] is False
        assert (row.get("payload_snapshot") or {}).get("jobs"), (
            "snapshot must still be populated on dry run"
        )
    finally:
        _cleanup(tid, uid, email)
        _db.audit_log.delete_many(
            {"action": "pool_service_report.email.run_now",
              "actor_user_id": uid},
        )


def test_run_now_dry_run_false_in_preview_env_forces_dry_run():
    """Fix 3 — a non-production environment (``APP_ENV !=
    production``) coerces dry_run to True regardless of the
    admin's request, and the response flags this on
    ``dry_run_forced_by_env``.
    """
    # Confirm we're on a non-production APP_ENV. We don't mutate
    # the env in-test; the preview harness runs with
    # ``APP_ENV=development`` per /app/backend/.env.
    from boot_flags import is_production
    assert not is_production(), (
        "test harness must run outside production — set APP_ENV"
    )
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        ethan_uid, _ = _seed_tech(tid, "Ethan Smith")
        mon, _sun = _mon_sun()
        _seed_job(tid, sched=mon, work_class="service",
                   technician_id=ethan_uid)
        # Spy on the mailer AGAIN to prove it's not called even
        # when the admin requests a real send.
        import services.pool_service_email as _psm
        called = {"n": 0}
        orig = _psm._send_via_resend

        async def _spy(*a, **kw):
            called["n"] += 1
            return await orig(*a, **kw)
        _psm._send_via_resend = _spy
        try:
            r = requests.post(
                f"{API}/reports/pool-service/email-history/run-now",
                headers={"Authorization": f"Bearer {tok}"},
                json={"week_ref": mon, "dry_run": False}, timeout=20,
            )
        finally:
            _psm._send_via_resend = orig
        stub = r.json()
        assert stub["dry_run"] is True
        assert stub["dry_run_forced_by_env"] is True
        assert stub["sent"] is False
        assert called["n"] == 0
    finally:
        _cleanup(tid, uid, email)
        _db.audit_log.delete_many(
            {"action": "pool_service_report.email.run_now",
              "actor_user_id": uid},
        )
