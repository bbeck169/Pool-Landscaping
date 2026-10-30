"""Feb-2026 · CYA Over-Threshold report — operator v2 fix.

Pins the 12 pytest cases locked in the operator dispatch for the BE
rewrite:

  * Per-reading granularity (one row per reading over threshold)
  * All historical readings (``submitted_at`` gate dropped)
  * Three canonical aliases (``cyanuric``, ``cyanuric_acid``, ``cya``)
  * Job date resolved via ``$lookup`` on ``jobs`` with ``$ifNull``
    chain to SR fields
  * Shape: ``{customer_id, customer_name, job_id, job_date, value}``
"""
from __future__ import annotations

import csv
import io
import os
import uuid
from typing import Optional

import pytest

from tests._phase34_http_shim import http
from tests._phase34_asyncio import batch_safe_run as _run


BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, password: str = "password123") -> str:
    r = http.post(
        f"{API}/auth/login",
        json={"email": email, "password": password}, timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def db():
    from config import db as _db  # noqa: PLC0415
    return _db


@pytest.fixture(scope="module")
def aq_tenant_id(db) -> str:
    async def _go():
        t = await db.tenants.find_one(
            {"slug": "aquaterra"}, {"_id": 0, "id": 1},
        )
        return t["id"]
    return _run(_go())


@pytest.fixture(scope="module")
def foreign_tenant_id(db, aq_tenant_id) -> Optional[str]:
    async def _go():
        other = await db.tenants.find_one(
            {"id": {"$ne": aq_tenant_id}}, {"_id": 0, "id": 1},
        )
        return other["id"] if other else None
    return _run(_go())


@pytest.fixture(scope="module")
def admin_h() -> dict:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_h() -> dict:
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


# ─── seeding helpers ──────────────────────────────────────────
def _plant_customer(db, tenant_id, cid, name) -> None:
    async def _go():
        await db.customers.insert_one({
            "id": cid, "tenant_id": tenant_id, "name": name,
            "address": "1 CYA Ln", "is_active": True,
            "created_at": "2026-01-01T00:00:00Z",
        })
    _run(_go())


def _plant_job(db, tenant_id, jid, customer_id,
                scheduled_date="2026-07-04") -> None:
    async def _go():
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tenant_id,
            "customer_id": customer_id,
            "scheduled_date": scheduled_date,
            "scheduled_start": f"{scheduled_date}T09:00:00-07:00",
            "status": "completed",
            "created_at": "2026-01-01T00:00:00Z",
        })
    _run(_go())


def _plant_report(
    db, tenant_id, *,
    customer_id, job_id, cya_key, cya_value,
    submitted_at="2026-07-04T15:00:00+00:00",
) -> str:
    rid = f"cya2-r-{uuid.uuid4().hex[:12]}"

    async def _go():
        await db.service_reports.insert_one({
            "id": rid, "tenant_id": tenant_id,
            "job_id": job_id, "customer_id": customer_id,
            "tech_id": "test-tech",
            "submitted_at": submitted_at,
            "created_at": "2026-07-04T14:00:00+00:00",
            "chemical_readings": [{
                "key": cya_key, "name": "Cyanuric Acid",
                "unit": "ppm", "value": cya_value,
            }],
        })
    _run(_go())
    return rid


def _cleanup(db, coll: str, ids: list[str]) -> None:
    if not ids:
        return

    async def _go():
        await getattr(db, coll).delete_many({"id": {"$in": ids}})
    _run(_go())


# ─── tests ────────────────────────────────────────────────────
def test_cya_01_admin_200_well_shaped(db, admin_h, aq_tenant_id):
    """1. Admin GET → 200 with per-reading row shape."""
    m = uuid.uuid4().hex[:8]
    cid, jid = f"cya2-c-01-{m}", f"cya2-j-01-{m}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA2-01-{m}")
    _plant_job(db, aq_tenant_id, jid, cid)
    rid = _plant_report(
        db, aq_tenant_id, customer_id=cid, job_id=jid,
        cya_key="cyanuric_acid", cya_value=150,
    )
    try:
        r = http.get(f"{API}/reports/cya-high", headers=admin_h,
                     timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body.keys()) >= {"threshold", "count", "items"}
        row = next((x for x in body["items"] if x["job_id"] == jid), None)
        assert row is not None
        assert set(row.keys()) == {
            "customer_id", "customer_name",
            "job_id", "job_date", "value",
        }
        assert row["customer_id"] == cid
        assert row["value"] == 150.0
        assert row["job_date"] == "2026-07-04"
    finally:
        _cleanup(db, "service_reports", [rid])
        _cleanup(db, "jobs", [jid])
        _cleanup(db, "customers", [cid])


def test_cya_02_non_admin_403(customer_h):
    """2. Non-admin → 403."""
    r = http.get(f"{API}/reports/cya-high", headers=customer_h,
                 timeout=30)
    assert r.status_code == 403


def test_cya_03_cross_tenant_isolation(db, admin_h, aq_tenant_id,
                                       foreign_tenant_id):
    """3. Cross-tenant filter."""
    if not foreign_tenant_id:
        pytest.skip("no second tenant available")
    m = uuid.uuid4().hex[:8]
    a_cid, a_jid = f"cya2-c-A-{m}", f"cya2-j-A-{m}"
    b_cid, b_jid = f"cya2-c-B-{m}", f"cya2-j-B-{m}"
    _plant_customer(db, aq_tenant_id, a_cid, f"CYA2-A-{m}")
    _plant_customer(db, foreign_tenant_id, b_cid, f"CYA2-B-{m}")
    _plant_job(db, aq_tenant_id, a_jid, a_cid)
    _plant_job(db, foreign_tenant_id, b_jid, b_cid)
    a_rid = _plant_report(
        db, aq_tenant_id, customer_id=a_cid, job_id=a_jid,
        cya_key="cyanuric_acid", cya_value=140,
    )
    b_rid = _plant_report(
        db, foreign_tenant_id, customer_id=b_cid, job_id=b_jid,
        cya_key="cyanuric_acid", cya_value=180,
    )
    try:
        r = http.get(f"{API}/reports/cya-high", headers=admin_h,
                     timeout=30)
        job_ids = {x["job_id"] for x in r.json()["items"]}
        assert a_jid in job_ids
        assert b_jid not in job_ids
    finally:
        _cleanup(db, "service_reports", [a_rid, b_rid])
        _cleanup(db, "jobs", [a_jid, b_jid])
        _cleanup(db, "customers", [a_cid, b_cid])


def test_cya_04_all_three_aliases_surface(db, admin_h, aq_tenant_id):
    """4. All 3 aliases participate: cyanuric, cyanuric_acid, cya."""
    m = uuid.uuid4().hex[:8]
    cid = f"cya2-c-04-{m}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA2-04-{m}")
    pieces: list[tuple[str, str, int]] = []
    for i, alias in enumerate(["cyanuric", "cyanuric_acid", "cya"]):
        jid = f"cya2-j-04{i}-{m}"
        _plant_job(db, aq_tenant_id, jid, cid,
                     scheduled_date=f"2026-07-{10 + i:02d}")
        rid = _plant_report(
            db, aq_tenant_id, customer_id=cid, job_id=jid,
            cya_key=alias, cya_value=130 + i,
        )
        pieces.append((alias, rid, jid))
    try:
        r = http.get(f"{API}/reports/cya-high", headers=admin_h,
                     timeout=30)
        job_ids = {x["job_id"] for x in r.json()["items"]}
        for alias, _rid, jid in pieces:
            assert jid in job_ids, f"alias {alias!r} missing"
    finally:
        _cleanup(db, "service_reports", [p[1] for p in pieces])
        _cleanup(db, "jobs", [p[2] for p in pieces])
        _cleanup(db, "customers", [cid])


def test_cya_05_draft_readings_surface(db, admin_h, aq_tenant_id):
    """5. ``submitted_at=null`` draft readings SURFACE (gate drop)."""
    m = uuid.uuid4().hex[:8]
    cid, jid = f"cya2-c-05-{m}", f"cya2-j-05-{m}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA2-05-{m}")
    _plant_job(db, aq_tenant_id, jid, cid)
    rid = _plant_report(
        db, aq_tenant_id, customer_id=cid, job_id=jid,
        cya_key="cyanuric_acid", cya_value=200,
        submitted_at=None,
    )
    try:
        r = http.get(f"{API}/reports/cya-high", headers=admin_h,
                     timeout=30)
        job_ids = {x["job_id"] for x in r.json()["items"]}
        assert jid in job_ids, "draft reading was wrongly excluded"
    finally:
        _cleanup(db, "service_reports", [rid])
        _cleanup(db, "jobs", [jid])
        _cleanup(db, "customers", [cid])


def test_cya_06_string_values_coerced(db, admin_h, aq_tenant_id):
    """6. Stringy legacy values ("120") coerce correctly."""
    m = uuid.uuid4().hex[:8]
    cid = f"cya2-c-06-{m}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA2-06-{m}")
    hi_jid = f"cya2-j-06H-{m}"; lo_jid = f"cya2-j-06L-{m}"
    _plant_job(db, aq_tenant_id, hi_jid, cid)
    _plant_job(db, aq_tenant_id, lo_jid, cid)
    hi_rid = _plant_report(db, aq_tenant_id, customer_id=cid,
                             job_id=hi_jid, cya_key="cyanuric_acid",
                             cya_value="120")
    lo_rid = _plant_report(db, aq_tenant_id, customer_id=cid,
                             job_id=lo_jid, cya_key="cyanuric_acid",
                             cya_value="50")
    try:
        r = http.get(f"{API}/reports/cya-high", headers=admin_h,
                     timeout=30)
        job_ids = {x["job_id"] for x in r.json()["items"]}
        assert hi_jid in job_ids
        assert lo_jid not in job_ids
    finally:
        _cleanup(db, "service_reports", [hi_rid, lo_rid])
        _cleanup(db, "jobs", [hi_jid, lo_jid])
        _cleanup(db, "customers", [cid])


def test_cya_07_threshold_override(db, admin_h, aq_tenant_id):
    """7. ``?threshold=50`` widens the result set."""
    m = uuid.uuid4().hex[:8]
    cid, jid = f"cya2-c-07-{m}", f"cya2-j-07-{m}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA2-07-{m}")
    _plant_job(db, aq_tenant_id, jid, cid)
    rid = _plant_report(db, aq_tenant_id, customer_id=cid,
                         job_id=jid, cya_key="cyanuric_acid",
                         cya_value=75)
    try:
        r = http.get(f"{API}/reports/cya-high", headers=admin_h,
                     timeout=30)
        assert jid not in {x["job_id"] for x in r.json()["items"]}
        r2 = http.get(f"{API}/reports/cya-high?threshold=50",
                      headers=admin_h, timeout=30)
        body = r2.json()
        assert body["threshold"] == 50.0
        assert jid in {x["job_id"] for x in body["items"]}
    finally:
        _cleanup(db, "service_reports", [rid])
        _cleanup(db, "jobs", [jid])
        _cleanup(db, "customers", [cid])


def test_cya_08_date_range_filter_on_job_date(db, admin_h,
                                              aq_tenant_id):
    """8. ``?from=/?to=`` clips to ``job_date`` window."""
    m = uuid.uuid4().hex[:8]
    cid = f"cya2-c-08-{m}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA2-08-{m}")
    old_jid = f"cya2-j-08O-{m}"; new_jid = f"cya2-j-08N-{m}"
    _plant_job(db, aq_tenant_id, old_jid, cid,
                 scheduled_date="2025-06-01")
    _plant_job(db, aq_tenant_id, new_jid, cid,
                 scheduled_date="2026-07-04")
    old_rid = _plant_report(db, aq_tenant_id, customer_id=cid,
                              job_id=old_jid, cya_key="cyanuric_acid",
                              cya_value=160)
    new_rid = _plant_report(db, aq_tenant_id, customer_id=cid,
                              job_id=new_jid, cya_key="cyanuric_acid",
                              cya_value=130)
    try:
        r = http.get(
            f"{API}/reports/cya-high?from=2026-01-01&to=2026-12-31",
            headers=admin_h, timeout=30,
        )
        job_ids = {x["job_id"] for x in r.json()["items"]}
        assert new_jid in job_ids
        assert old_jid not in job_ids
    finally:
        _cleanup(db, "service_reports", [old_rid, new_rid])
        _cleanup(db, "jobs", [old_jid, new_jid])
        _cleanup(db, "customers", [cid])


def test_cya_09_csv_mirrors_json(db, admin_h, aq_tenant_id):
    """9. CSV export mirrors JSON items row-for-row."""
    m = uuid.uuid4().hex[:8]
    cid, jid = f"cya2-c-09-{m}", f"cya2-j-09-{m}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA2-09-{m}")
    _plant_job(db, aq_tenant_id, jid, cid)
    rid = _plant_report(db, aq_tenant_id, customer_id=cid,
                         job_id=jid, cya_key="cyanuric_acid",
                         cya_value=175)
    try:
        jr = http.get(f"{API}/reports/cya-high",
                      headers=admin_h, timeout=30)
        cr = http.get(f"{API}/reports/cya-high/export.csv",
                      headers=admin_h, timeout=30)
        assert cr.headers.get("content-type", "").startswith(
            "text/csv")
        rows = list(csv.reader(io.StringIO(cr.text)))
        assert rows[0] == [
            "customer_id", "customer_name",
            "job_id", "job_date", "value",
        ]
        body_rows = {r[2]: r for r in rows[1:]}  # keyed by job_id
        for item in jr.json()["items"]:
            row = body_rows.get(item["job_id"])
            assert row is not None, (
                f"job_id {item['job_id']} missing from CSV"
            )
            assert row[0] == item["customer_id"]
            assert row[1] == item["customer_name"]
            assert row[3] == item["job_date"]
            assert float(row[4]) == float(item["value"])
    finally:
        _cleanup(db, "service_reports", [rid])
        _cleanup(db, "jobs", [jid])
        _cleanup(db, "customers", [cid])


def test_cya_10_exactly_at_threshold_excluded(db, admin_h,
                                              aq_tenant_id):
    """10. Reading at exactly 100 EXCLUDED (strict ``>``)."""
    m = uuid.uuid4().hex[:8]
    cid, jid = f"cya2-c-10-{m}", f"cya2-j-10-{m}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA2-10-{m}")
    _plant_job(db, aq_tenant_id, jid, cid)
    rid = _plant_report(db, aq_tenant_id, customer_id=cid,
                         job_id=jid, cya_key="cyanuric_acid",
                         cya_value=100)
    try:
        r = http.get(f"{API}/reports/cya-high",
                     headers=admin_h, timeout=30)
        assert jid not in {x["job_id"] for x in r.json()["items"]}
    finally:
        _cleanup(db, "service_reports", [rid])
        _cleanup(db, "jobs", [jid])
        _cleanup(db, "customers", [cid])


def test_cya_11_multiple_readings_same_customer_different_jobs(
        db, admin_h, aq_tenant_id):
    """11. Per-reading granularity: one customer, N jobs → N rows."""
    m = uuid.uuid4().hex[:8]
    cid = f"cya2-c-11-{m}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA2-11-{m}")
    pieces: list[tuple[str, str]] = []
    for i, value in enumerate([115, 125, 135]):
        jid = f"cya2-j-11{i}-{m}"
        _plant_job(db, aq_tenant_id, jid, cid,
                     scheduled_date=f"2026-08-{10 + i:02d}")
        rid = _plant_report(
            db, aq_tenant_id, customer_id=cid, job_id=jid,
            cya_key="cyanuric_acid", cya_value=value,
        )
        pieces.append((rid, jid))
    try:
        r = http.get(f"{API}/reports/cya-high",
                     headers=admin_h, timeout=30)
        rows = [x for x in r.json()["items"] if x["customer_id"] == cid]
        assert len(rows) == 3
        values = sorted(x["value"] for x in rows)
        assert values == [115.0, 125.0, 135.0]
        # Each row has a distinct job_id.
        assert len({x["job_id"] for x in rows}) == 3
    finally:
        _cleanup(db, "service_reports", [p[0] for p in pieces])
        _cleanup(db, "jobs", [p[1] for p in pieces])
        _cleanup(db, "customers", [cid])


def test_cya_12_cya_alias_specifically_surfaces(db, admin_h,
                                                aq_tenant_id):
    """12. Regression lock: the ``cya`` alias (3rd spelling,
    added by this fix) must surface."""
    m = uuid.uuid4().hex[:8]
    cid, jid = f"cya2-c-12-{m}", f"cya2-j-12-{m}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA2-12-{m}")
    _plant_job(db, aq_tenant_id, jid, cid)
    rid = _plant_report(
        db, aq_tenant_id, customer_id=cid, job_id=jid,
        cya_key="cya", cya_value=145,
    )
    try:
        r = http.get(f"{API}/reports/cya-high",
                     headers=admin_h, timeout=30)
        row = next(
            (x for x in r.json()["items"] if x["job_id"] == jid),
            None,
        )
        assert row is not None, (
            "the 'cya' alias was wrongly excluded"
        )
        assert row["value"] == 145.0
    finally:
        _cleanup(db, "service_reports", [rid])
        _cleanup(db, "jobs", [jid])
        _cleanup(db, "customers", [cid])
