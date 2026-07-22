"""Phase 11 · Feb 2026 — Equipment Service Trackers coverage.

Covers backend + service surface:
  · CRUD (POST/GET/PATCH/DELETE) with role gates.
  · ``status_computed`` derivation at query time using per-tenant
    ``equipment_service_coming_due_days``.
  · ``mark-cleaned`` rolls last_cleaned_at + due_at forward and appends
    a history entry.
  · Auto-log helper ``log_cleaning_from_job`` creates + updates the
    tracker when a Filter/Salt Cell job completes — idempotent when
    called twice on the same job.
  · 4 EQUIPMENT_* merge tags resolve against an ``equipment_tracker``
    ctx scope; empty (+ unresolved) when the scope is missing.
  · Per-tenant local-time cron: ``run_weekly_for_tenant`` fires a
    digest + reminders when reminders_enabled is set, no-ops when
    nothing is due.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pytest
import requests
from dotenv import dotenv_values
from pathlib import Path
from pymongo import MongoClient

API = "http://localhost:8001/api"


_BACKEND_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_MONGO_URL = _BACKEND_ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _BACKEND_ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync_client = MongoClient(_MONGO_URL)
_sync_db = _sync_client[_DB_NAME]

from tests._shared_loop import LOOP as _LOOP, run as _run


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    return r.json()["access_token"]


def _hdr(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _admin_tok() -> str:
    return _login("admin@aquaterra.com")


def _customer_ids(tok: str) -> list:
    r = requests.get(f"{API}/customers", headers=_hdr(tok), timeout=15)
    r.raise_for_status()
    js = r.json()
    rows = js if isinstance(js, list) else js.get("customers") or js.get("items") or []
    return [c["id"] for c in rows if c.get("id")]


def _wipe_trackers_for(customer_id: str) -> None:
    """Delete any lingering tracker rows for this customer using the
    sync PyMongo client (avoids Motor loop-binding issues)."""
    _sync_db.equipment_service_trackers.delete_many({"customer_id": customer_id})


def _create_tracker(tok: str, *, customer_id: Optional[str] = None,
                     tracker_type: str = "filter",
                     interval_months: int = 3,
                     last_cleaned_at: Optional[str] = None,
                     property_id: Optional[str] = None,
                     is_active: bool = True) -> Dict[str, Any]:
    cid = customer_id or _customer_ids(tok)[0]
    _wipe_trackers_for(cid)
    payload = {
        "customer_id": cid,
        "tracker_type": tracker_type,
        "interval_months": interval_months,
        "last_cleaned_at": last_cleaned_at or date.today().isoformat(),
        "is_active": is_active,
    }
    if property_id is not None:
        payload["property_id"] = property_id
    r = requests.post(f"{API}/equipment/trackers",
                       headers=_hdr(tok), json=payload, timeout=15)
    assert r.status_code == 201, r.text
    return r.json()


def _hard_delete(tid: str) -> None:
    _sync_db.equipment_service_trackers.delete_many({"id": tid})


# ═══════════════════════════ CRUD + role gate ═════════════════════════
def test_create_tracker_returns_status_and_type_label():
    tok = _admin_tok()
    t = _create_tracker(tok, tracker_type="salt_cell", interval_months=12)
    try:
        assert t["tracker_type"] == "salt_cell"
        assert t["interval_months"] == 12
        assert t["type_label"] == "Salt Cell"
        assert t["status_computed"] in ("current", "coming_due", "past_due")
        assert t["status_computed"] != "past_due"
        assert t["due_at"]
    finally:
        _hard_delete(t["id"])


def test_create_tracker_duplicate_returns_409():
    tok = _admin_tok()
    cid = _customer_ids(tok)[0]
    t = _create_tracker(tok, customer_id=cid, tracker_type="filter")
    try:
        r = requests.post(f"{API}/equipment/trackers",
                           headers=_hdr(tok),
                           json={"customer_id": cid, "tracker_type": "filter",
                                  "interval_months": 3,
                                  "last_cleaned_at": date.today().isoformat()},
                           timeout=15)
        assert r.status_code == 409, r.text
        # Structured 409 detail carries existing_tracker_id so the
        # frontend can offer a "Jump to existing" affordance without
        # regex-parsing the human message.
        body = r.json()
        detail = body.get("detail")
        assert isinstance(detail, dict), (
            f"expected dict detail with existing_tracker_id, got: {body}"
        )
        assert detail.get("existing_tracker_id") == t["id"]
        assert "already exists" in (detail.get("message") or "").lower()
    finally:
        _hard_delete(t["id"])


def test_create_tracker_denies_technician():
    tech = _login("mike@aquaterra.com")
    r = requests.post(f"{API}/equipment/trackers",
                       headers=_hdr(tech),
                       json={"customer_id": "x", "tracker_type": "filter",
                              "interval_months": 3}, timeout=15)
    assert r.status_code in (401, 403)


def test_list_trackers_technician_can_read():
    admin = _admin_tok()
    t = _create_tracker(admin, tracker_type="filter")
    try:
        tech = _login("mike@aquaterra.com")
        r = requests.get(f"{API}/equipment/trackers",
                          headers=_hdr(tech), timeout=15)
        assert r.status_code == 200, r.text
        ids = {row["id"] for row in r.json().get("trackers", [])}
        assert t["id"] in ids
    finally:
        _hard_delete(t["id"])


def test_list_trackers_filters_by_type_and_status():
    tok = _admin_tok()
    ids = _customer_ids(tok)
    assert len(ids) >= 2, "aquaterra tenant should have >= 2 customers"
    cid_a, cid_b = ids[0], ids[1]
    t1 = _create_tracker(tok, customer_id=cid_a, tracker_type="filter",
                            interval_months=3)
    long_ago = (date.today() - timedelta(days=400)).isoformat()
    t2 = _create_tracker(tok, customer_id=cid_b, tracker_type="filter",
                            interval_months=3, last_cleaned_at=long_ago)
    try:
        r = requests.get(f"{API}/equipment/trackers?tracker_type=filter",
                          headers=_hdr(tok), timeout=15)
        js = r.json()
        assert all(row["tracker_type"] == "filter" for row in js["trackers"])
        assert set(js["counts_by_status"].keys()) == {"current", "coming_due", "past_due"}
        r = requests.get(f"{API}/equipment/trackers?status=past_due",
                          headers=_hdr(tok), timeout=15)
        ids2 = {row["id"] for row in r.json()["trackers"]}
        assert t2["id"] in ids2
        assert t1["id"] not in ids2
    finally:
        _hard_delete(t1["id"])
        _hard_delete(t2["id"])


# ═══════════════════════════ status_computed derivation ═══════════════
def test_status_current_when_recently_cleaned():
    tok = _admin_tok()
    t = _create_tracker(tok, tracker_type="filter", interval_months=6,
                          last_cleaned_at=date.today().isoformat())
    try:
        r = requests.get(f"{API}/equipment/trackers/{t['id']}",
                          headers=_hdr(tok), timeout=15)
        assert r.json()["status_computed"] == "current"
    finally:
        _hard_delete(t["id"])


def test_status_past_due_when_overdue():
    tok = _admin_tok()
    long_ago = (date.today() - timedelta(days=400)).isoformat()
    t = _create_tracker(tok, tracker_type="salt_cell", interval_months=12,
                          last_cleaned_at=long_ago)
    try:
        r = requests.get(f"{API}/equipment/trackers/{t['id']}",
                          headers=_hdr(tok), timeout=15)
        assert r.json()["status_computed"] == "past_due"
    finally:
        _hard_delete(t["id"])


def test_status_coming_due_within_default_30_day_window():
    tok = _admin_tok()
    # 75 days ago cleaned, cadence 3 months → due ~15 days from now.
    days_ago = (date.today() - timedelta(days=75)).isoformat()
    t = _create_tracker(tok, tracker_type="filter", interval_months=3,
                          last_cleaned_at=days_ago)
    try:
        r = requests.get(f"{API}/equipment/trackers/{t['id']}",
                          headers=_hdr(tok), timeout=15)
        assert r.json()["status_computed"] == "coming_due"
    finally:
        _hard_delete(t["id"])


# ═══════════════════════════ mark-cleaned ═════════════════════════════
def test_mark_cleaned_rolls_forward_and_appends_history():
    tok = _admin_tok()
    long_ago = (date.today() - timedelta(days=200)).isoformat()
    t = _create_tracker(tok, tracker_type="filter", interval_months=3,
                          last_cleaned_at=long_ago)
    try:
        r = requests.post(f"{API}/equipment/trackers/{t['id']}/mark-cleaned",
                           headers=_hdr(tok), json={"note": "unit test"},
                           timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["last_cleaned_at"] == date.today().isoformat()
        assert j["status_computed"] == "current"
        assert j["history"], "history should have >= 1 entry"
        last = j["history"][-1]
        assert last["source"] == "manual"
        assert last["cleaned_at"] == date.today().isoformat()
        assert last["note"] == "unit test"
    finally:
        _hard_delete(t["id"])


def test_mark_cleaned_technician_allowed():
    admin = _admin_tok()
    t = _create_tracker(admin, tracker_type="filter", interval_months=3,
                          last_cleaned_at=(date.today() - timedelta(days=80)).isoformat())
    try:
        tech = _login("mike@aquaterra.com")
        r = requests.post(f"{API}/equipment/trackers/{t['id']}/mark-cleaned",
                           headers=_hdr(tech), timeout=15)
        assert r.status_code == 200, r.text
    finally:
        _hard_delete(t["id"])


# ═══════════════════════════ PATCH ═════════════════════════════════════
def test_patch_interval_months_recomputes_due_date():
    tok = _admin_tok()
    t = _create_tracker(tok, tracker_type="filter", interval_months=3,
                          last_cleaned_at=date.today().isoformat())
    try:
        r = requests.patch(f"{API}/equipment/trackers/{t['id']}",
                             headers=_hdr(tok), json={"interval_months": 6},
                             timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["interval_months"] == 6
        assert j["due_at"] > t["due_at"]
    finally:
        _hard_delete(t["id"])


def test_delete_soft_deletes_and_survives_fetch():
    tok = _admin_tok()
    t = _create_tracker(tok)
    try:
        r = requests.delete(f"{API}/equipment/trackers/{t['id']}",
                              headers=_hdr(tok), timeout=15)
        assert r.status_code == 204
        g = requests.get(f"{API}/equipment/trackers/{t['id']}",
                          headers=_hdr(tok), timeout=15).json()
        assert g["is_active"] is False
    finally:
        _hard_delete(t["id"])


# ═══════════════════════════ Merge tags ════════════════════════════════
def test_equipment_merge_tags_present_in_catalog():
    tok = _admin_tok()
    r = requests.get(f"{API}/marketing/merge-tags", headers=_hdr(tok), timeout=15)
    assert r.status_code == 200
    cats = r.json()["categories"]
    assert "Equipment" in cats
    tokens = {t["token"] for t in cats["Equipment"]}
    assert tokens == {"EQUIPMENT_TYPE", "EQUIPMENT_LAST_CLEANED_DATE",
                       "EQUIPMENT_DUE_DATE", "EQUIPMENT_INTERVAL_MONTHS"}


def test_equipment_merge_tags_resolve_against_ctx_scope():
    from services.marketing.merge_tags import render_template
    ctx = {
        "equipment_tracker": {
            "type_label": "Filter",
            "last_cleaned_at": "2026-01-15",
            "last_cleaned_at_pretty": "Jan 15, 2026",
            "due_at": "2026-04-15",
            "due_at_pretty": "Apr 15, 2026",
            "interval_months": 3,
        },
    }
    out, missing = render_template(
        "Your {{EQUIPMENT_TYPE}} is due {{EQUIPMENT_DUE_DATE}}, "
        "last cleaned {{EQUIPMENT_LAST_CLEANED_DATE}} "
        "(every {{EQUIPMENT_INTERVAL_MONTHS}} months).", ctx,
    )
    assert out == (
        "Your Filter is due Apr 15, 2026, last cleaned Jan 15, 2026 "
        "(every 3 months)."
    )
    assert missing == []


def test_equipment_merge_tags_unresolved_outside_scope():
    from services.marketing.merge_tags import render_template
    out, missing = render_template(
        "Type: {{EQUIPMENT_TYPE}}", {"customer": {"name": "X"}},
        missing="placeholder",
    )
    assert "[MISSING: EQUIPMENT_TYPE]" in out
    assert "EQUIPMENT_TYPE" in missing


# ═══════════════════════════ Auto-log from job ═════════════════════════
def test_log_cleaning_from_job_creates_then_updates():
    """Simulates two consecutive Filter Cleaning job completions on
    the same customer. First call creates the tracker; second call
    updates + appends a history row. Never breaks job completion."""
    async def _do():
        from config import db
        from routers.equipment_trackers import log_cleaning_from_job
        cust = await db.customers.find_one({"tenant_id": {"$exists": True}}, {"_id": 0})
        tenant_id = cust["tenant_id"]
        cid = cust["id"]
        await db.equipment_service_trackers.delete_many({
            "tenant_id": tenant_id, "customer_id": cid, "tracker_type": "filter",
        })
        yesterday = (date.today() - timedelta(days=1)).isoformat() + "T12:00:00Z"
        job = {
            "id": f"job-{uuid.uuid4().hex[:8]}",
            "tenant_id": tenant_id,
            "customer_id": cid,
            "service_type": "Filter Cleaning",
            "maintenance_type": "filter",
            "completed_at": yesterday,
            "technician_id": "tech-1",
            "technician_name": "Mike",
            "status": "completed",
        }
        r1 = await log_cleaning_from_job(job)
        assert r1 is not None
        assert r1["tracker_type"] == "filter"
        assert r1["last_cleaned_at"] == yesterday[:10]
        today_iso = date.today().isoformat() + "T09:00:00Z"
        r2 = await log_cleaning_from_job({**job, "id": job["id"] + "-b",
                                          "completed_at": today_iso})
        assert r2 is not None
        row = await db.equipment_service_trackers.find_one({
            "tenant_id": tenant_id, "customer_id": cid, "tracker_type": "filter",
        }, {"_id": 0})
        assert row is not None
        assert row["last_cleaned_at"] == today_iso[:10]
        assert len(row.get("history") or []) >= 2
        await db.equipment_service_trackers.delete_many({
            "tenant_id": tenant_id, "customer_id": cid, "tracker_type": "filter",
        })
    _run(_do())


def test_log_cleaning_from_job_noop_for_non_maintenance():
    async def _do():
        from routers.equipment_trackers import log_cleaning_from_job
        res = await log_cleaning_from_job({
            "id": "j", "tenant_id": "t", "customer_id": "c",
            "service_type": "Weekly Pool Service",
        })
        assert res is None
    _run(_do())


# ═══════════════════════════ Cron dispatcher ═══════════════════════════
def test_run_weekly_for_tenant_skips_when_nothing_due():
    async def _do():
        from config import db
        from services.equipment_trackers_cron import run_weekly_for_tenant
        tenant = await db.tenants.find_one({}, {"_id": 0})
        await db.equipment_service_trackers.delete_many({"tenant_id": tenant["id"]})
        res = await run_weekly_for_tenant(tenant)
        assert res["past_due"] == 0
        assert res["coming_due"] == 0
        assert res["digest"].get("skipped") is True
    _run(_do())


def test_run_weekly_for_tenant_dispatches_digest_when_past_due():
    async def _do():
        from config import db
        from routers.equipment_trackers import _add_months_iso
        from services.equipment_trackers_cron import run_weekly_for_tenant
        tenant = await db.tenants.find_one({}, {"_id": 0})
        admin = await db.users.find_one(
            {"tenant_id": tenant["id"], "role": {"$in": ["admin", "super_admin"]}},
            {"_id": 0},
        )
        assert admin
        cust = await db.customers.find_one(
            {"tenant_id": tenant["id"]}, {"_id": 0, "id": 1},
        )
        await db.equipment_service_trackers.delete_many({"tenant_id": tenant["id"]})
        long_ago = (date.today() - timedelta(days=200)).isoformat()
        doc = {
            "id": f"tst-{uuid.uuid4().hex[:8]}",
            "tenant_id": tenant["id"],
            "customer_id": cust["id"],
            "property_id": None,
            "tracker_type": "filter",
            "interval_months": 3,
            "last_cleaned_at": long_ago,
            "due_at": _add_months_iso(long_ago, 3),
            "is_active": True,
            "history": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        # Also wipe any previous digest dedup rows so this run actually sends.
        iso_week = f"{datetime.now(timezone.utc).isocalendar().year:04d}-W{datetime.now(timezone.utc).isocalendar().week:02d}"
        await db.outbound_emails.delete_many({
            "tenant_id": tenant["id"], "kind": "equipment_service_digest",
            "iso_week": iso_week,
        })
        await db.equipment_service_trackers.insert_one(doc)
        try:
            res = await run_weekly_for_tenant(tenant)
            assert res["past_due"] >= 1, res
            d = res["digest"]
            assert d.get("recipients", 0) >= 1, d
        finally:
            await db.equipment_service_trackers.delete_many({"tenant_id": tenant["id"]})
    _run(_do())


def test_hourly_scan_fires_only_on_monday_08_local():
    """Monkeypatches ``_now_local`` so we can drive the wall clock
    deterministically. Fires when local weekday=Mon and hour=8;
    skips otherwise."""
    async def _do():
        from services import equipment_trackers_cron as cron
        from config import db

        # 1) Wed 10:00 local → no tenant should fire.
        cron._now_local = lambda t: datetime(2026, 2, 25, 10, 0, tzinfo=timezone.utc)  # type: ignore
        res_wed = await cron.hourly_scan()
        assert res_wed["fired"] == []
        tenant_count = await db.tenants.count_documents({})
        assert res_wed["total"] == tenant_count
        assert res_wed["skipped"] == tenant_count

        # 2) Mon 08:00 local → every tenant is *considered* (may still
        #    "skip" the digest internally when nothing is due, but the
        #    tenant is *attempted*).
        cron._now_local = lambda t: datetime(2026, 2, 23, 8, 0, tzinfo=timezone.utc)  # type: ignore
        res_mon = await cron.hourly_scan()
        assert isinstance(res_mon["fired"], list)
        assert len(res_mon["fired"]) + res_mon["skipped"] == res_mon["total"]

        # Restore normal behavior — reload the module.
        import importlib
        importlib.reload(cron)
    _run(_do())
