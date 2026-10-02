"""Feb-2026 · Phase 3d-portal · Next-service split."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict

import pytest
import requests
from dotenv import load_dotenv
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()


def _admin_login() -> Dict[str, str]:
    for _ in range(3):
        try:
            r = requests.post(
                f"{API}/auth/login",
                json={"email": "super@aquaterra.com", "password": "password123"},
                timeout=15,
            )
            if r.status_code == 200:
                tok = r.json()["access_token"]
                me = requests.get(
                    f"{API}/auth/me",
                    headers={"Authorization": f"Bearer {tok}"}, timeout=10,
                ).json()
                return {"tok": tok, "tenant_id": me["tenant_id"]}
        except requests.exceptions.RequestException:
            pass
    pytest.skip("admin login unavailable")


def _register_customer(tenant_id: str) -> Dict[str, str]:
    marker = uuid.uuid4().hex[:10]
    email = f"pp_{marker}@t.co"
    password = "TestPass1!"
    tenant_row = _db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "slug": 1},
    )
    if not tenant_row or not tenant_row.get("slug"):
        pytest.skip(f"tenant {tenant_id!r} missing slug")
    r = requests.post(
        f"{API}/auth/signup",
        json={
            "email": email, "password": password,
            "name": f"Pp Split{marker}",
            "phone": "5555550100",
            "address": "1234 Old St, Springfield IL 62701",
        },
        headers={"X-Tenant-Slug": tenant_row["slug"]},
        timeout=15,
    )
    if r.status_code != 200:
        pytest.skip(f"signup unavailable: {r.status_code} {r.text}")
    tok = r.json().get("access_token")
    me = requests.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"},
        timeout=10,
    ).json()
    cid = me.get("customer_id")
    if not cid:
        pytest.skip("signup did not produce a customer_id")
    return {
        "tok": tok, "email": email,
        "customer_id": cid, "user_id": me["id"],
    }


@pytest.fixture
def ctx():
    admin = _admin_login()
    cust = _register_customer(admin["tenant_id"])
    cust["tenant_id"] = admin["tenant_id"]
    yield cust
    _db.jobs.delete_many({
        "customer_id": cust["customer_id"],
        "tenant_id": admin["tenant_id"],
    })


def _mk_job(ctx: Dict[str, str], *, industry: str, days_from_now: int,
            service_type: str = "Routine visit") -> str:
    jid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    sched = now + timedelta(days=days_from_now)
    _db.jobs.insert_one({
        "id": jid,
        "tenant_id": ctx["tenant_id"],
        "customer_id": ctx["customer_id"],
        "status": "scheduled",
        "industry": industry,
        "service_type": service_type,
        "title": f"{industry.title()} visit",
        "scheduled_start": sched.isoformat(),
        "scheduled_date": sched.date().isoformat(),
    })
    return jid


def _get_summary(tok: str) -> dict:
    r = requests.get(
        f"{API}/customer-portal/summary",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_both_pool_and_landscape_populate_split(ctx):
    pool_id = _mk_job(ctx, industry="pool", days_from_now=1)
    land_id = _mk_job(ctx, industry="landscaping", days_from_now=3)
    s = _get_summary(ctx["tok"])
    assert s.get("next_pool_service"), s
    assert s.get("next_landscape_service"), s
    assert s["next_pool_service"]["job_id"] == pool_id
    assert s["next_landscape_service"]["job_id"] == land_id
    assert s.get("next_service"), s
    assert s["next_service"]["job_id"] == pool_id


def test_only_pool_future_job(ctx):
    pool_id = _mk_job(ctx, industry="pool", days_from_now=2)
    s = _get_summary(ctx["tok"])
    assert s.get("next_pool_service")
    assert s["next_pool_service"]["job_id"] == pool_id
    assert s.get("next_landscape_service") is None
    assert s.get("next_service")
    assert s["next_service"]["job_id"] == pool_id


def test_only_landscape_future_job(ctx):
    land_id = _mk_job(ctx, industry="landscaping", days_from_now=2)
    s = _get_summary(ctx["tok"])
    assert s.get("next_pool_service") is None
    assert s.get("next_landscape_service")
    assert s["next_landscape_service"]["job_id"] == land_id
    assert s.get("next_service")
    assert s["next_service"]["job_id"] == land_id


def test_no_future_jobs_all_null(ctx):
    s = _get_summary(ctx["tok"])
    assert s.get("next_pool_service") is None
    assert s.get("next_landscape_service") is None
    assert s.get("next_service") is None


def test_multiple_pool_jobs_earliest_wins(ctx):
    _mk_job(ctx, industry="pool", days_from_now=5)
    early_pool = _mk_job(ctx, industry="pool", days_from_now=1)
    s = _get_summary(ctx["tok"])
    assert s.get("next_pool_service")
    assert s["next_pool_service"]["job_id"] == early_pool
