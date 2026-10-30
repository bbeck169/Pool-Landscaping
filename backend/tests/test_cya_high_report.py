"""Feb-2026 · CYA Over-Threshold Report tests.

Covers ``GET /api/reports/cya-high`` and ``/export.csv`` with the
10 pytest cases locked in the operator dispatch for this ticket.
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


# ─── auth / fixtures ──────────────────────────────────────────────
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
    """Non-admin role for the 403 case."""
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


# ─── seeding helpers ──────────────────────────────────────────────
def _plant_customer(db, tenant_id: str, cid: str, name: str) -> None:
    async def _go():
        await db.customers.insert_one({
            "id": cid, "tenant_id": tenant_id, "name": name,
            "address": "1 CYA Ln", "is_active": True,
            "created_at": "2026-01-01T00:00:00Z",
        })
    _run(_go())


def _plant_report(
    db, tenant_id: str, *,
    customer_id: str, cya_key: str, cya_value,
    submitted_at: Optional[str],
) -> str:
    rid = f"cya-r-{uuid.uuid4().hex[:12]}"

    async def _go():
        await db.service_reports.insert_one({
            "id": rid,
            "tenant_id": tenant_id,
            "job_id": f"cya-j-{rid}",
            "customer_id": customer_id,
            "tech_id": "test-tech",
            "submitted_at": submitted_at,
            "chemical_readings": [
                {"key": cya_key, "name": "Cyanuric Acid",
                 "unit": "ppm", "value": cya_value},
            ],
        })
    _run(_go())
    return rid


def _cleanup(db, coll: str, ids: list[str]) -> None:
    if not ids:
        return

    async def _go():
        await getattr(db, coll).delete_many({"id": {"$in": ids}})
    _run(_go())


# ─── tests ────────────────────────────────────────────────────────
def test_cya_01_admin_200_well_shaped(db, admin_h, aq_tenant_id):
    """1. Admin can call → 200, well-shaped response."""
    marker = uuid.uuid4().hex[:8]
    cid = f"cya-c-01-{marker}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA-01-{marker}")
    rid = _plant_report(
        db, aq_tenant_id,
        customer_id=cid, cya_key="cyanuric_acid", cya_value=150,
        submitted_at="2026-02-15T10:00:00Z",
    )
    try:
        r = http.get(f"{API}/reports/cya-high", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body.keys()) >= {"threshold", "count", "items"}
        assert body["threshold"] == 100.0
        assert isinstance(body["items"], list)
        assert body["count"] == len(body["items"])
        row = next((x for x in body["items"] if x["customer_id"] == cid), None)
        assert row is not None, "seeded customer missing from items"
        assert set(row.keys()) >= {
            "customer_id", "customer_name",
            "last_value", "last_date",
            "max_value", "max_date",
            "reading_count_over_threshold",
        }
        assert row["max_value"] == 150.0
        assert row["reading_count_over_threshold"] == 1
    finally:
        _cleanup(db, "service_reports", [rid])
        _cleanup(db, "customers", [cid])


def test_cya_02_non_admin_403(customer_h):
    """2. Non-admin → 403."""
    r = http.get(f"{API}/reports/cya-high", headers=customer_h, timeout=30)
    assert r.status_code == 403, r.text


def test_cya_03_cross_tenant_isolation(db, admin_h, aq_tenant_id,
                                       foreign_tenant_id):
    """3. Tenant A admin never sees tenant B readings."""
    if not foreign_tenant_id:
        pytest.skip("no second tenant available in preview")
    marker = uuid.uuid4().hex[:8]
    a_cid = f"cya-c-A-{marker}"
    b_cid = f"cya-c-B-{marker}"
    _plant_customer(db, aq_tenant_id, a_cid, f"CYA-A-{marker}")
    _plant_customer(db, foreign_tenant_id, b_cid, f"CYA-B-{marker}")
    a_rid = _plant_report(
        db, aq_tenant_id, customer_id=a_cid,
        cya_key="cyanuric_acid", cya_value=140,
        submitted_at="2026-02-15T10:00:00Z",
    )
    b_rid = _plant_report(
        db, foreign_tenant_id, customer_id=b_cid,
        cya_key="cyanuric_acid", cya_value=180,
        submitted_at="2026-02-15T10:00:00Z",
    )
    try:
        r = http.get(f"{API}/reports/cya-high", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        ids = {x["customer_id"] for x in items}
        assert a_cid in ids
        assert b_cid not in ids
    finally:
        _cleanup(db, "service_reports", [a_rid, b_rid])
        _cleanup(db, "customers", [a_cid, b_cid])


def test_cya_04_draft_readings_excluded(db, admin_h, aq_tenant_id):
    """4. Reports with no submitted_at (drafts) are excluded (Q2=a)."""
    marker = uuid.uuid4().hex[:8]
    cid = f"cya-c-04-{marker}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA-04-{marker}")
    draft_rid = _plant_report(
        db, aq_tenant_id, customer_id=cid,
        cya_key="cyanuric_acid", cya_value=200,
        submitted_at=None,
    )
    try:
        r = http.get(f"{API}/reports/cya-high", headers=admin_h, timeout=30)
        assert r.status_code == 200
        ids = {x["customer_id"] for x in r.json()["items"]}
        assert cid not in ids, "draft reading leaked into report"
    finally:
        _cleanup(db, "service_reports", [draft_rid])
        _cleanup(db, "customers", [cid])


def test_cya_05_both_key_conventions_included(db, admin_h, aq_tenant_id):
    """5. Both `cyanuric` and `cyanuric_acid` key spellings participate."""
    marker = uuid.uuid4().hex[:8]
    legacy_cid = f"cya-c-05L-{marker}"
    canon_cid = f"cya-c-05C-{marker}"
    _plant_customer(db, aq_tenant_id, legacy_cid, f"CYA-05L-{marker}")
    _plant_customer(db, aq_tenant_id, canon_cid, f"CYA-05C-{marker}")
    legacy_rid = _plant_report(
        db, aq_tenant_id, customer_id=legacy_cid,
        cya_key="cyanuric", cya_value=130,
        submitted_at="2026-02-15T10:00:00Z",
    )
    canon_rid = _plant_report(
        db, aq_tenant_id, customer_id=canon_cid,
        cya_key="cyanuric_acid", cya_value=145,
        submitted_at="2026-02-15T10:00:00Z",
    )
    try:
        r = http.get(f"{API}/reports/cya-high", headers=admin_h, timeout=30)
        assert r.status_code == 200
        ids = {x["customer_id"] for x in r.json()["items"]}
        assert legacy_cid in ids, "legacy `cyanuric` key missed"
        assert canon_cid in ids, "canonical `cyanuric_acid` key missed"
    finally:
        _cleanup(db, "service_reports", [legacy_rid, canon_rid])
        _cleanup(db, "customers", [legacy_cid, canon_cid])


def test_cya_06_string_values_coerced(db, admin_h, aq_tenant_id):
    """6. Stringy legacy values ("120") coerce via $convert."""
    marker = uuid.uuid4().hex[:8]
    hi_cid = f"cya-c-06H-{marker}"
    lo_cid = f"cya-c-06L-{marker}"
    _plant_customer(db, aq_tenant_id, hi_cid, f"CYA-06H-{marker}")
    _plant_customer(db, aq_tenant_id, lo_cid, f"CYA-06L-{marker}")
    hi_rid = _plant_report(
        db, aq_tenant_id, customer_id=hi_cid,
        cya_key="cyanuric_acid", cya_value="120",
        submitted_at="2026-02-15T10:00:00Z",
    )
    lo_rid = _plant_report(
        db, aq_tenant_id, customer_id=lo_cid,
        cya_key="cyanuric_acid", cya_value="50",
        submitted_at="2026-02-15T10:00:00Z",
    )
    try:
        r = http.get(f"{API}/reports/cya-high", headers=admin_h, timeout=30)
        assert r.status_code == 200
        ids = {x["customer_id"] for x in r.json()["items"]}
        assert hi_cid in ids, 'string "120" not coerced above threshold'
        assert lo_cid not in ids, 'string "50" wrongly surfaced above 100'
    finally:
        _cleanup(db, "service_reports", [hi_rid, lo_rid])
        _cleanup(db, "customers", [hi_cid, lo_cid])


def test_cya_07_threshold_override(db, admin_h, aq_tenant_id):
    """7. ?threshold=50 widens the result set."""
    marker = uuid.uuid4().hex[:8]
    cid = f"cya-c-07-{marker}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA-07-{marker}")
    rid = _plant_report(
        db, aq_tenant_id, customer_id=cid,
        cya_key="cyanuric_acid", cya_value=75,
        submitted_at="2026-02-15T10:00:00Z",
    )
    try:
        # default (100) → excluded
        r = http.get(f"{API}/reports/cya-high", headers=admin_h, timeout=30)
        assert cid not in {x["customer_id"] for x in r.json()["items"]}
        # override 50 → included
        r2 = http.get(
            f"{API}/reports/cya-high?threshold=50",
            headers=admin_h, timeout=30,
        )
        assert r2.status_code == 200
        body = r2.json()
        assert body["threshold"] == 50.0
        assert cid in {x["customer_id"] for x in body["items"]}
    finally:
        _cleanup(db, "service_reports", [rid])
        _cleanup(db, "customers", [cid])


def test_cya_08_date_range_filter(db, admin_h, aq_tenant_id):
    """8. ?from/?to clips to the submitted_at window."""
    marker = uuid.uuid4().hex[:8]
    cid = f"cya-c-08-{marker}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA-08-{marker}")
    old_rid = _plant_report(
        db, aq_tenant_id, customer_id=cid,
        cya_key="cyanuric_acid", cya_value=160,
        submitted_at="2025-06-01T10:00:00Z",
    )
    new_rid = _plant_report(
        db, aq_tenant_id, customer_id=cid,
        cya_key="cyanuric_acid", cya_value=130,
        submitted_at="2026-02-15T10:00:00Z",
    )
    try:
        # window excludes the old (160) reading → only 130 counts
        r = http.get(
            f"{API}/reports/cya-high?from=2026-01-01&to=2026-12-31",
            headers=admin_h, timeout=30,
        )
        assert r.status_code == 200
        row = next((x for x in r.json()["items"]
                   if x["customer_id"] == cid), None)
        assert row is not None
        assert row["max_value"] == 130.0, (
            "date filter failed to exclude older 160-ppm reading"
        )
        assert row["reading_count_over_threshold"] == 1
    finally:
        _cleanup(db, "service_reports", [old_rid, new_rid])
        _cleanup(db, "customers", [cid])


def test_cya_09_csv_matches_json(db, admin_h, aq_tenant_id):
    """9. CSV export mirrors JSON items row-for-row."""
    marker = uuid.uuid4().hex[:8]
    cid = f"cya-c-09-{marker}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA-09-{marker}")
    rid = _plant_report(
        db, aq_tenant_id, customer_id=cid,
        cya_key="cyanuric_acid", cya_value=175,
        submitted_at="2026-02-15T10:00:00Z",
    )
    try:
        jr = http.get(f"{API}/reports/cya-high", headers=admin_h, timeout=30)
        cr = http.get(
            f"{API}/reports/cya-high/export.csv",
            headers=admin_h, timeout=30,
        )
        assert jr.status_code == 200 and cr.status_code == 200
        assert cr.headers.get("content-type", "").startswith("text/csv")
        reader = csv.reader(io.StringIO(cr.text))
        rows = list(reader)
        assert rows[0] == [
            "customer_id", "customer_name",
            "last_value", "last_date",
            "max_value", "max_date",
            "reading_count_over_threshold",
        ]
        body_rows = {r[0]: r for r in rows[1:]}
        for item in jr.json()["items"]:
            row = body_rows.get(item["customer_id"])
            assert row is not None, (
                f"customer {item['customer_id']} missing from CSV"
            )
            assert row[1] == item["customer_name"]
            assert float(row[2]) == float(item["last_value"])
            assert row[3] == item["last_date"]
            assert float(row[4]) == float(item["max_value"])
            assert row[5] == item["max_date"]
            assert int(row[6]) == int(item["reading_count_over_threshold"])
    finally:
        _cleanup(db, "service_reports", [rid])
        _cleanup(db, "customers", [cid])


def test_cya_10_exactly_at_threshold_excluded(db, admin_h, aq_tenant_id):
    """10. Reading exactly AT threshold (= 100) is EXCLUDED — strict `>`."""
    marker = uuid.uuid4().hex[:8]
    cid = f"cya-c-10-{marker}"
    _plant_customer(db, aq_tenant_id, cid, f"CYA-10-{marker}")
    rid = _plant_report(
        db, aq_tenant_id, customer_id=cid,
        cya_key="cyanuric_acid", cya_value=100,
        submitted_at="2026-02-15T10:00:00Z",
    )
    try:
        r = http.get(f"{API}/reports/cya-high", headers=admin_h, timeout=30)
        assert r.status_code == 200
        ids = {x["customer_id"] for x in r.json()["items"]}
        assert cid not in ids, (
            "exactly-100 reading surfaced — contract is strict `> threshold`"
        )
    finally:
        _cleanup(db, "service_reports", [rid])
        _cleanup(db, "customers", [cid])
