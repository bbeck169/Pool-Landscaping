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


# ──────────────────────────────────────────────────────────────────
# TD-portal-next-service-missing-tile · Feb-2026 — projection fallback
# ──────────────────────────────────────────────────────────────────
def _mk_tpl(ctx: Dict[str, str], *, industry: str,
             start_days_out: int,
             service_type: str = "Routine visit",
             title: str = None,
             last_generated_through: str = None,
             end_date: str = None) -> str:
    tpl_id = str(uuid.uuid4())
    start = (datetime.now(timezone.utc).date()
             + timedelta(days=start_days_out))
    doc = {
        "id": tpl_id,
        "tenant_id": ctx["tenant_id"],
        "customer_id": ctx["customer_id"],
        "service_type": service_type,
        "title": title or f"{industry.title()} monthly",
        "industry": "pool" if industry == "pool" else "landscaping",
        "frequency": "monthly",
        "day_of_month": start.day,
        "start_date": start.isoformat(),
        "end_date": end_date,
        "last_generated_through": last_generated_through,
        "is_active": True,
        "active": True,
        "recurrence_never_ends": True,
    }
    _db.recurring_job_templates.insert_one(doc)
    return tpl_id


@pytest.fixture
def ctx_tpl(ctx):
    """Reuse ``ctx`` and clean recurring_job_templates on teardown."""
    yield ctx
    _db.recurring_job_templates.delete_many({
        "customer_id": ctx["customer_id"],
        "tenant_id": ctx["tenant_id"],
    })


def test_projection_fills_pool_when_no_materialized_job(ctx_tpl):
    """Template start_date 30 days out (beyond 14-day cron horizon)
    with no materialized job → portal projects the next date."""
    tpl_id = _mk_tpl(ctx_tpl, industry="pool", start_days_out=30,
                      title="Monthly Pool Service")
    s = _get_summary(ctx_tpl["tok"])
    assert s.get("next_pool_service"), (
        "expected projection to fill pool side when start_date is "
        "beyond the 14-day cron horizon"
    )
    assert s["next_pool_service"].get("projected") is True
    assert s["next_pool_service"]["job_id"] is None
    assert s["next_pool_service"]["title"] == "Monthly Pool Service"
    assert s.get("next_landscape_service") is None
    # Legacy mirror picks the projection too.
    assert s.get("next_service")
    assert s["next_service"].get("projected") is True


def test_materialized_wins_over_projection(ctx_tpl):
    """Materialized job (today+1) and template (start 30 days out) →
    the materialized row wins; no ``projected`` key on the response."""
    pool_jid = _mk_job(ctx_tpl, industry="pool", days_from_now=1)
    _mk_tpl(ctx_tpl, industry="pool", start_days_out=30)
    s = _get_summary(ctx_tpl["tok"])
    assert s.get("next_pool_service")
    assert s["next_pool_service"]["job_id"] == pool_jid
    assert s["next_pool_service"].get("projected") is not True


def test_projection_skipped_when_end_date_in_past(ctx_tpl):
    """Template with start_date far out but end_date already passed →
    projection must respect end_date and NOT emit a date."""
    yesterday = (datetime.now(timezone.utc).date()
                  - timedelta(days=1)).isoformat()
    _mk_tpl(ctx_tpl, industry="landscaping", start_days_out=30,
             end_date=yesterday)
    s = _get_summary(ctx_tpl["tok"])
    assert s.get("next_landscape_service") is None
    assert s.get("next_pool_service") is None


def test_projection_fills_both_sides_independently(ctx_tpl):
    """Separate pool + landscape templates — both tiles projected."""
    _mk_tpl(ctx_tpl, industry="pool", start_days_out=30,
             title="Monthly Pool")
    _mk_tpl(ctx_tpl, industry="landscaping", start_days_out=45,
             title="Monthly Landscape")
    s = _get_summary(ctx_tpl["tok"])
    assert s.get("next_pool_service")
    assert s["next_pool_service"].get("projected") is True
    assert s.get("next_landscape_service")
    assert s["next_landscape_service"].get("projected") is True


def test_projection_skipped_when_template_stopped(ctx_tpl):
    """Template with ``stopped_at`` set → projection must skip it."""
    tpl_id = _mk_tpl(ctx_tpl, industry="pool", start_days_out=30)
    _db.recurring_job_templates.update_one(
        {"id": tpl_id},
        {"$set": {"stopped_at": datetime.now(timezone.utc).isoformat()}},
    )
    s = _get_summary(ctx_tpl["tok"])
    assert s.get("next_pool_service") is None
    assert s.get("next_landscape_service") is None


def test_projection_honours_last_generated_through(ctx_tpl):
    """Template whose ``last_generated_through`` is already past today
    (cron advanced, mat'd jobs completed) must project the NEXT
    occurrence AFTER that cursor, not re-emit the stale date."""
    today = datetime.now(timezone.utc).date()
    # Monthly template rooted at day 1; last_generated_through = today.
    tpl_id = _mk_tpl(
        ctx_tpl, industry="pool",
        start_days_out=-60,  # start_date in the past
        last_generated_through=today.isoformat(),
    )
    # Force the day_of_month to today's day so there IS a date today —
    # and the next natural occurrence is next month.
    _db.recurring_job_templates.update_one(
        {"id": tpl_id},
        {"$set": {"day_of_month": today.day}},
    )
    s = _get_summary(ctx_tpl["tok"])
    assert s.get("next_pool_service")
    assert s["next_pool_service"].get("projected") is True
    # Projected date must be strictly AFTER last_generated_through.
    assert s["next_pool_service"]["date"] > today.isoformat()
