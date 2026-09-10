"""Feb-2026 P0 · Recurring-jobs orphan backfill regression tests.

Bug: 80+ customers set up as recurring jobs from the Schedule page
never appeared on the Recurring Visits admin page because they had
no matching row in ``db.recurring_job_templates``.

Sync test pattern (pymongo + requests) matching the rest of the
suite.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _login_super() -> str:
    """Return a JWT for ``super@aquaterra.com`` (demo super-admin)."""
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "super@aquaterra.com", "password": "password123"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _tenant_id_of(token: str) -> str:
    r = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    return r.json()["tenant_id"]


def _seed_customer(tid: str) -> str:
    cid = f"p0rec-c-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": f"TEST_p0rec_{cid[-6:]}",
    })
    return cid


def _seed_recurring_cluster(*, tid, cid, service_type, frequency,
                                 n=4, gap_days=7,
                                 tag_recurring=True,
                                 template_id=None,
                                 start=date(2026, 1, 1)):
    for i in range(n):
        d = (start + timedelta(days=gap_days * i)).isoformat()
        doc = {
            "id": f"p0rec-j-{uuid.uuid4().hex[:8]}",
            "tenant_id": tid, "customer_id": cid,
            "customer_name": f"TEST_p0rec_{cid[-6:]}",
            "title": f"TEST_p0rec {service_type} {i}",
            "service_type": service_type,
            "scheduled_date": d, "price": 120.0,
            "frequency": frequency,
            "status": "scheduled",
        }
        if tag_recurring:
            doc["is_recurring"] = True
        if template_id:
            doc["recurring_template_id"] = template_id
        _sync.jobs.insert_one(doc)


def _cleanup(tid: str, cid: str):
    _sync.jobs.delete_many({"tenant_id": tid, "customer_id": cid})
    _sync.recurring_job_templates.delete_many(
        {"tenant_id": tid, "customer_id": cid},
    )
    _sync.customers.delete_many({"id": cid})


# ── Tests ──────────────────────────────────────────────────────────

def test_orphan_scan_detects_cluster():
    tok = _login_super()
    tid = _tenant_id_of(tok)
    cid = _seed_customer(tid)
    try:
        _seed_recurring_cluster(tid=tid, cid=cid,
                                  service_type="TEST_p0rec_Weekly",
                                  frequency="weekly", n=4)
        r = requests.get(
            f"{API}/recurring-jobs/orphans",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Filter to our cluster only (tenant may have other jobs).
        ours = [x for x in body["orphans"]
                if x.get("customer_id") == cid]
        assert len(ours) == 1
        assert ours[0]["frequency"] == "weekly"
        assert ours[0]["occurrence_count"] == 4
        assert ours[0]["day_of_week"] is not None
    finally:
        _cleanup(tid, cid)


def test_orphan_scan_ignores_jobs_linked_to_existing_template():
    tok = _login_super()
    tid = _tenant_id_of(tok)
    cid = _seed_customer(tid)
    try:
        tpl_id = f"p0rec-tpl-{uuid.uuid4().hex[:8]}"
        _sync.recurring_job_templates.insert_one({
            "id": tpl_id, "tenant_id": tid, "customer_id": cid,
            "customer_name": f"TEST_p0rec_{cid[-6:]}",
            "service_type": "TEST_p0rec_Linked",
            "frequency": "weekly", "active": True,
            "start_date": "2026-01-01", "price_cents": 12000,
        })
        _seed_recurring_cluster(tid=tid, cid=cid,
                                  service_type="TEST_p0rec_Linked",
                                  frequency="weekly", n=3,
                                  template_id=tpl_id)
        r = requests.get(
            f"{API}/recurring-jobs/orphans",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        assert r.status_code == 200
        ours = [x for x in r.json()["orphans"]
                if x.get("customer_id") == cid]
        assert len(ours) == 0
    finally:
        _cleanup(tid, cid)


def test_backfill_creates_template_and_is_idempotent():
    tok = _login_super()
    tid = _tenant_id_of(tok)
    cid = _seed_customer(tid)
    try:
        _seed_recurring_cluster(tid=tid, cid=cid,
                                  service_type="TEST_p0rec_Backfill",
                                  frequency="weekly", n=4)

        # First run — creates a template for our cluster.
        r = requests.post(
            f"{API}/recurring-jobs/backfill-orphans",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json()["created"] >= 1

        # Confirm the template surfaces on the standard list.
        rl = requests.get(
            f"{API}/recurring-jobs",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        assert rl.status_code == 200
        matches = [x for x in rl.json()["items"]
                   if x.get("customer_id") == cid
                   and x.get("service_type") == "TEST_p0rec_Backfill"]
        assert len(matches) == 1
        assert matches[0]["frequency"] == "weekly"

        # Second run — idempotent, does not double-create our cluster.
        r2 = requests.post(
            f"{API}/recurring-jobs/backfill-orphans",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r2.status_code == 200
        rl2 = requests.get(
            f"{API}/recurring-jobs",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        matches2 = [x for x in rl2.json()["items"]
                    if x.get("customer_id") == cid
                    and x.get("service_type") == "TEST_p0rec_Backfill"]
        assert len(matches2) == 1
    finally:
        _cleanup(tid, cid)


def test_backfill_picks_day_of_week_from_first_occurrence():
    """Weekly cluster whose first job is a Wednesday → ``day_of_week=2``."""
    tok = _login_super()
    tid = _tenant_id_of(tok)
    cid = _seed_customer(tid)
    try:
        # 2026-01-07 is a Wednesday → ISO weekday 2.
        _seed_recurring_cluster(tid=tid, cid=cid,
                                  service_type="TEST_p0rec_DoW",
                                  frequency="weekly", n=3,
                                  start=date(2026, 1, 7))
        r = requests.get(
            f"{API}/recurring-jobs/orphans",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        ours = [x for x in r.json()["orphans"]
                if x.get("customer_id") == cid]
        assert len(ours) == 1
        assert ours[0]["day_of_week"] == 2

        requests.post(
            f"{API}/recurring-jobs/backfill-orphans",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        rl = requests.get(
            f"{API}/recurring-jobs",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        tpl = next(
            (x for x in rl.json()["items"]
             if x.get("customer_id") == cid
             and x.get("service_type") == "TEST_p0rec_DoW"),
            None,
        )
        assert tpl is not None
        assert tpl.get("day_of_week") == 2
    finally:
        _cleanup(tid, cid)
