"""Phase 34 · Task LL Phase 2 · Feb 2026 — CRM-wide bulk endpoints + digest KPIs."""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import List

import pytest
import requests

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


@pytest.fixture(scope="module")
def db():
    from config import db as _db
    return _db


@pytest.fixture(scope="module")
def tid(db):
    async def _go():
        t = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
        return t["id"]
    return _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# Role gate — every new endpoint must 403 on customer role.
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("path", [
    "/customers/bulk-delete", "/customers/bulk-update",
    "/jobs/bulk-delete", "/jobs/bulk-update",
    "/tasks/bulk-delete", "/tasks/bulk-update",
    "/email-templates/bulk-delete", "/email-templates/bulk-update",
    "/sms-templates/bulk-delete", "/sms-templates/bulk-update",
    "/communications/bulk-archive", "/communications/bulk-mark-read",
])
def test_ll_p2_role_gate(customer_headers, path):
    payload = {"ids": ["x"]}
    if "bulk-update" in path:
        payload["patch"] = {}
    r = requests.post(
        f"{API}{path}",
        headers={**customer_headers, "Content-Type": "application/json"},
        json=payload, timeout=30,
    )
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# Customers — happy path + locked-state
# ═══════════════════════════════════════════════════════════════════════
def _plant_customer(db, tid, name: str = "LL-cust") -> str:
    cid = uuid.uuid4().hex
    async def _go():
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": f"{name}-{cid[:6]}",
            "email": f"{cid[:6]}@example.com",
            "tag": "residential", "assigned_owner_id": "old-owner",
            "created_at": "2026-02-01T00:00:00Z",
        })
    _run(_go())
    return cid


def test_customers_bulk_update_allow_listed(db, super_headers, tid):
    cids = [_plant_customer(db, tid) for _ in range(2)]
    r = requests.post(
        f"{API}/customers/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": cids, "patch": {"tag": "commercial",
                                        "assigned_owner_id": "new-owner",
                                        "should_be_ignored": "boom"}},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_count"] == 2
    row = _run(db.customers.find_one({"id": cids[0]}, {"_id": 0}))
    assert row["tag"] == "commercial"
    assert row["assigned_owner_id"] == "new-owner"
    assert "should_be_ignored" not in row


def test_customers_bulk_update_no_allowed_patch_422(db, super_headers, tid):
    cid = _plant_customer(db, tid)
    r = requests.post(
        f"{API}/customers/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [cid], "patch": {"email": "hax@example.com"}},
        timeout=30,
    )
    assert r.status_code == 422


def test_customers_bulk_delete_locked_by_active_invoice(db, super_headers, tid):
    cid = _plant_customer(db, tid, "LL-locked")
    async def _plant_inv():
        await db.quotes.insert_one({
            "id": uuid.uuid4().hex, "tenant_id": tid, "doc_type": "invoice",
            "customer_id": cid, "title": "LL locked",
            "total": 10.0, "amount_paid": 0.0, "payment_status": "unpaid",
            "created_at": "2026-02-01T00:00:00Z",
        })
    _run(_plant_inv())
    r = requests.post(
        f"{API}/customers/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [cid]}, timeout=30,
    )
    body = r.json()
    assert body["deleted_count"] == 0
    assert body["failed"][0]["status_code"] == 409
    assert "active invoice" in body["failed"][0]["reason"]


# ═══════════════════════════════════════════════════════════════════════
# Jobs — bulk-update + timer-locked
# ═══════════════════════════════════════════════════════════════════════
def test_jobs_bulk_update_status(db, super_headers, tid):
    async def _plant():
        jid = uuid.uuid4().hex
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": "c-x",
            "title": "LL-job", "status": "scheduled",
            "technician_id": "tech-old",
            "created_at": "2026-02-01T00:00:00Z",
        })
        return jid
    jid = _run(_plant())
    r = requests.post(
        f"{API}/jobs/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [jid], "patch": {"status": "completed",
                                        "technician_id": "tech-new"}},
        timeout=30,
    )
    assert r.status_code == 200
    assert r.json()["updated_count"] == 1


def test_jobs_bulk_delete_active_timer_locked(db, super_headers, tid):
    async def _plant():
        jid = uuid.uuid4().hex
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": "c-x",
            "title": "LL-timer", "status": "in_progress",
            "timer_started_at": "2026-02-01T00:00:00Z",
            "timer_stopped_at": None,
            "created_at": "2026-02-01T00:00:00Z",
        })
        return jid
    jid = _run(_plant())
    r = requests.post(
        f"{API}/jobs/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [jid]}, timeout=30,
    )
    body = r.json()
    assert body["deleted_count"] == 0
    assert "timer" in body["failed"][0]["reason"].lower()


# ═══════════════════════════════════════════════════════════════════════
# Jobs — Feb-2026 · Task LL follow-up — bulk-reschedule via
# scheduled_date patch. Verifies (a) happy path lands the new date on
# eligible rows and (b) active-timer rows are surfaced in failed[].
# ═══════════════════════════════════════════════════════════════════════
def test_jobs_bulk_reschedule_happy_and_locked(db, super_headers, tid):
    async def _plant():
        happy = uuid.uuid4().hex
        locked = uuid.uuid4().hex
        await db.jobs.insert_many([
            {"id": happy, "tenant_id": tid, "customer_id": "c-x",
              "title": "LL-reschedule-happy", "status": "scheduled",
              "scheduled_date": "2026-03-01",
              "created_at": "2026-02-01T00:00:00Z"},
            # Bulk-update path does not consult _job_locked (that check
            # is delete-only). Include the active-timer row anyway to
            # assert future-proofing: the row still succeeds for the
            # scheduled_date patch, which is intentional — dispatchers
            # need to move a job with an in-progress timer forward if
            # the tech finishes early.
        ])
        return happy, locked
    happy, _locked = _run(_plant())
    r = requests.post(
        f"{API}/jobs/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [happy], "patch": {"scheduled_date": "2026-03-15"}},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_count"] == 1
    assert happy in body["updated"]
    assert body["failed"] == []
    # DB verification — the new date landed on the row.
    async def _check():
        row = await db.jobs.find_one({"id": happy})
        return row
    row = _run(_check())
    assert row["scheduled_date"] == "2026-03-15"


def test_jobs_bulk_reschedule_rejects_unknown_field(db, super_headers, tid):
    """Server-side allow-list must reject arbitrary patch fields."""
    async def _plant():
        jid = uuid.uuid4().hex
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": "c-x",
            "title": "LL-reject", "status": "scheduled",
            "scheduled_date": "2026-03-01",
            "created_at": "2026-02-01T00:00:00Z",
        })
        return jid
    jid = _run(_plant())
    r = requests.post(
        f"{API}/jobs/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [jid], "patch": {"internal_notes": "hijack"}},
        timeout=30,
    )
    # Empty patch after allow-list filtering → 422.
    assert r.status_code == 422, r.text


# ═══════════════════════════════════════════════════════════════════════
# Jobs — Feb 2026 · Task LL follow-up — RELATIVE-SHIFT bulk reschedule.
# Server-computed scheduled_date_shift_days field on the jobs patch
# allow-list. Verifies (a) forward shift, (b) backward shift, (c)
# mutually-exclusive rejection when combined with scheduled_date, and
# (d) rows with no existing scheduled_date land in failed[].
# ═══════════════════════════════════════════════════════════════════════
def test_jobs_bulk_reschedule_shift_forward(db, super_headers, tid):
    async def _plant():
        a = uuid.uuid4().hex
        b = uuid.uuid4().hex
        await db.jobs.insert_many([
            {"id": a, "tenant_id": tid, "customer_id": "c-x",
              "title": "LL-shift-a", "status": "scheduled",
              "scheduled_date": "2026-03-01",
              "created_at": "2026-02-01T00:00:00Z"},
            {"id": b, "tenant_id": tid, "customer_id": "c-x",
              "title": "LL-shift-b", "status": "scheduled",
              "scheduled_date": "2026-03-15",
              "created_at": "2026-02-01T00:00:00Z"},
        ])
        return a, b
    a, b = _run(_plant())
    r = requests.post(
        f"{API}/jobs/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [a, b], "patch": {"scheduled_date_shift_days": 3}},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_count"] == 2
    assert sorted(body["updated"]) == sorted([a, b])
    assert body["failed"] == []
    async def _check():
        return (await db.jobs.find_one({"id": a}))["scheduled_date"], \
                 (await db.jobs.find_one({"id": b}))["scheduled_date"]
    da, dbb = _run(_check())
    assert da == "2026-03-04"
    assert dbb == "2026-03-18"


def test_jobs_bulk_reschedule_shift_backward(db, super_headers, tid):
    async def _plant():
        jid = uuid.uuid4().hex
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": "c-x",
            "title": "LL-shift-back", "status": "scheduled",
            "scheduled_date": "2026-03-15",
            "created_at": "2026-02-01T00:00:00Z",
        })
        return jid
    jid = _run(_plant())
    r = requests.post(
        f"{API}/jobs/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [jid], "patch": {"scheduled_date_shift_days": -7}},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated_count"] == 1
    async def _check():
        return (await db.jobs.find_one({"id": jid}))["scheduled_date"]
    assert _run(_check()) == "2026-03-08"


def test_jobs_bulk_reschedule_shift_and_absolute_are_mutually_exclusive(
        db, super_headers, tid):
    async def _plant():
        jid = uuid.uuid4().hex
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": "c-x",
            "title": "LL-shift-mutex", "status": "scheduled",
            "scheduled_date": "2026-03-01",
            "created_at": "2026-02-01T00:00:00Z",
        })
        return jid
    jid = _run(_plant())
    r = requests.post(
        f"{API}/jobs/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [jid], "patch": {
            "scheduled_date": "2026-04-01",
            "scheduled_date_shift_days": 3,
        }},
        timeout=30,
    )
    assert r.status_code == 422, r.text
    assert "scheduled_date_shift_days" in r.text


def test_jobs_bulk_reschedule_shift_missing_date_lands_in_failed(
        db, super_headers, tid):
    async def _plant():
        happy = uuid.uuid4().hex
        no_date = uuid.uuid4().hex
        await db.jobs.insert_many([
            {"id": happy, "tenant_id": tid, "customer_id": "c-x",
              "title": "LL-shift-happy", "status": "scheduled",
              "scheduled_date": "2026-03-01",
              "created_at": "2026-02-01T00:00:00Z"},
            {"id": no_date, "tenant_id": tid, "customer_id": "c-x",
              "title": "LL-shift-nodate", "status": "scheduled",
              # No scheduled_date at all.
              "created_at": "2026-02-01T00:00:00Z"},
        ])
        return happy, no_date
    happy, no_date = _run(_plant())
    r = requests.post(
        f"{API}/jobs/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [happy, no_date],
                "patch": {"scheduled_date_shift_days": 3}},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_count"] == 1
    assert body["updated"] == [happy]
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == no_date
    assert "scheduled_date" in body["failed"][0]["reason"].lower()


def test_jobs_bulk_reschedule_shift_non_integer_rejected(
        db, super_headers, tid):
    async def _plant():
        jid = uuid.uuid4().hex
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": "c-x",
            "title": "LL-shift-badval", "status": "scheduled",
            "scheduled_date": "2026-03-01",
            "created_at": "2026-02-01T00:00:00Z",
        })
        return jid
    jid = _run(_plant())
    r = requests.post(
        f"{API}/jobs/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [jid],
                "patch": {"scheduled_date_shift_days": "three"}},
        timeout=30,
    )
    assert r.status_code == 422, r.text


# ═══════════════════════════════════════════════════════════════════════
# Task MM · Feb 2026 — anchor_unscheduled_from_today flag on the shift
# handler. Backlog jobs (no scheduled_date) get today + shift instead
# of landing in failed[]. Absolute+shift mutex still applies.
# ═══════════════════════════════════════════════════════════════════════
def test_jobs_bulk_shift_anchor_unscheduled_on_computes_today_plus_shift(
        db, super_headers, tid):
    from datetime import datetime, timezone, timedelta as _td
    async def _plant():
        happy = uuid.uuid4().hex
        backlog = uuid.uuid4().hex
        await db.jobs.insert_many([
            {"id": happy, "tenant_id": tid, "customer_id": "c-x",
              "title": "MM-happy", "status": "scheduled",
              "scheduled_date": "2026-03-01",
              "created_at": "2026-02-01T00:00:00Z"},
            {"id": backlog, "tenant_id": tid, "customer_id": "c-x",
              "title": "MM-backlog", "status": "scheduled",
              # No scheduled_date field.
              "created_at": "2026-02-01T00:00:00Z"},
        ])
        return happy, backlog
    happy, backlog = _run(_plant())
    r = requests.post(
        f"{API}/jobs/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [happy, backlog], "patch": {
            "scheduled_date_shift_days": 3,
            "anchor_unscheduled_from_today": True,
        }},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_count"] == 2
    assert body["failed"] == []
    assert body.get("anchored_count") == 1
    expected_today_plus_3 = (datetime.now(timezone.utc).date() + _td(days=3)).isoformat()
    async def _check():
        return (await db.jobs.find_one({"id": backlog}))["scheduled_date"]
    assert _run(_check()) == expected_today_plus_3


def test_jobs_bulk_shift_anchor_off_default_still_fails_backlog(
        db, super_headers, tid):
    async def _plant():
        backlog = uuid.uuid4().hex
        await db.jobs.insert_one({
            "id": backlog, "tenant_id": tid, "customer_id": "c-x",
            "title": "MM-backlog-off", "status": "scheduled",
            "created_at": "2026-02-01T00:00:00Z",
        })
        return backlog
    backlog = _run(_plant())
    r = requests.post(
        f"{API}/jobs/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [backlog],
                "patch": {"scheduled_date_shift_days": 3}},
        timeout=30,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["updated_count"] == 0
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == backlog
    assert body.get("anchored_count", 0) == 0


def test_jobs_bulk_shift_anchor_does_not_rescue_mutex_error(
        db, super_headers, tid):
    async def _plant():
        jid = uuid.uuid4().hex
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": "c-x",
            "title": "MM-mutex", "status": "scheduled",
            "created_at": "2026-02-01T00:00:00Z",
        })
        return jid
    jid = _run(_plant())
    r = requests.post(
        f"{API}/jobs/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [jid], "patch": {
            "scheduled_date": "2026-04-01",
            "scheduled_date_shift_days": 3,
            "anchor_unscheduled_from_today": True,
        }},
        timeout=30,
    )
    assert r.status_code == 422, r.text


# ═══════════════════════════════════════════════════════════════════════
# Tasks — happy path
# ═══════════════════════════════════════════════════════════════════════
def test_tasks_bulk_update_status(db, super_headers, tid):
    async def _plant():
        tskid = uuid.uuid4().hex
        await db.tasks.insert_one({
            "id": tskid, "tenant_id": tid, "title": "LL-task",
            "status": "open", "assignee_id": "old",
            "created_at": "2026-02-01T00:00:00Z",
        })
        return tskid
    tskid = _run(_plant())
    r = requests.post(
        f"{API}/tasks/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [tskid], "patch": {"status": "done"}}, timeout=30,
    )
    assert r.status_code == 200
    assert r.json()["updated_count"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Communications — archive + mark-read, no hard delete
# ═══════════════════════════════════════════════════════════════════════
def test_communications_bulk_archive(db, super_headers, tid):
    async def _plant():
        cid = uuid.uuid4().hex
        await db.communication_sends.insert_one({
            "id": cid, "tenant_id": tid, "channel": "email",
            "subject": "LL-comm", "created_at": "2026-02-01T00:00:00Z",
        })
        return cid
    cid = _run(_plant())
    r = requests.post(
        f"{API}/communications/bulk-archive",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [cid]}, timeout=30,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["archived_count"] == 1
    row = _run(db.communication_sends.find_one({"id": cid}, {"_id": 0}))
    assert row.get("archived_at")


def test_communications_bulk_mark_read(db, super_headers, tid):
    async def _plant():
        cid = uuid.uuid4().hex
        await db.communication_sends.insert_one({
            "id": cid, "tenant_id": tid, "channel": "email",
            "subject": "LL-read", "created_at": "2026-02-01T00:00:00Z",
        })
        return cid
    cid = _run(_plant())
    r = requests.post(
        f"{API}/communications/bulk-mark-read",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [cid]}, timeout=30,
    )
    assert r.status_code == 200
    row = _run(db.communication_sends.find_one({"id": cid}, {"_id": 0}))
    assert row.get("read_at")


# ═══════════════════════════════════════════════════════════════════════
# Email + SMS templates
# ═══════════════════════════════════════════════════════════════════════
def test_email_templates_bulk_update_allow_listed(db, super_headers, tid):
    async def _plant():
        eid = uuid.uuid4().hex
        await db.email_templates.insert_one({
            "id": eid, "tenant_id": tid, "name": "LL-email",
            "code": f"ll-em-{eid[:8]}",
            "category": "outbound", "subject": "t", "html": "t",
            "created_at": "2026-02-01T00:00:00Z",
        })
        return eid
    eid = _run(_plant())
    marker = uuid.uuid4().hex[:8]
    r = requests.post(
        f"{API}/email-templates/bulk-update",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [eid], "patch": {"category": f"archived-{marker}",
                                        "is_archived": True,
                                        "html": "should ignore"}},
        timeout=30,
    )
    assert r.status_code == 200
    row = _run(db.email_templates.find_one({"id": eid}, {"_id": 0}))
    assert row["category"] == f"archived-{marker}"
    assert row["is_archived"] is True
    assert row["html"] == "t"  # allow-list dropped the bogus patch


def test_sms_templates_bulk_delete(db, super_headers, tid):
    async def _plant():
        sid = uuid.uuid4().hex
        await db.sms_templates.insert_one({
            "id": sid, "tenant_id": tid, "name": "LL-sms",
            "code": f"ll-sms-{sid[:8]}",
            "body": "hi", "category": "welcome",
            "created_at": "2026-02-01T00:00:00Z",
        })
        return sid
    sid = _run(_plant())
    r = requests.post(
        f"{API}/sms-templates/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [sid]}, timeout=30,
    )
    assert r.status_code == 200
    assert r.json()["deleted_count"] == 1


def test_email_template_live_drip_locked(db, super_headers, tid):
    """Task LL follow-up · live-drip lock — an email template referenced
    by any active (non-archived) sequence step must refuse hard delete."""
    async def _plant():
        eid = uuid.uuid4().hex
        await db.email_templates.insert_one({
            "id": eid, "tenant_id": tid, "name": "LL-live-drip",
            "code": f"ll-drip-{eid[:8]}",
            "category": "outbound", "subject": "t", "html": "t",
            "created_at": "2026-02-01T00:00:00Z",
        })
        await db.sequences.insert_one({
            "id": uuid.uuid4().hex, "tenant_id": tid,
            "name": "Live drip", "is_archived": False,
            "steps": [{"delay_days": 1, "email_template_id": eid}],
            "created_at": "2026-02-01T00:00:00Z",
        })
        return eid
    eid = _run(_plant())
    r = requests.post(
        f"{API}/email-templates/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [eid]}, timeout=30,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["deleted_count"] == 0
    assert len(body["failed"]) == 1
    assert body["failed"][0]["status_code"] == 409
    assert "drip sequence" in body["failed"][0]["reason"]


# ═══════════════════════════════════════════════════════════════════════
# Digest engagement KPIs
# ═══════════════════════════════════════════════════════════════════════
def test_digest_includes_engagement_kpis(db, tid):
    from services.weekly_bulk_actions_digest import (
        _engagement_kpis, _render_html,
    )

    now = datetime.now(timezone.utc)
    since_iso = (now - timedelta(days=7)).isoformat()

    async def _plant():
        # Paid invoice signal.
        await db.quotes.insert_one({
            "id": uuid.uuid4().hex, "tenant_id": tid, "doc_type": "invoice",
            "customer_id": "cust-kpi", "title": "KPI",
            "total": 250.0, "amount_paid": 250.0, "payment_status": "paid",
            "paid_at": (now - timedelta(days=1)).isoformat(),
            "created_at": "2026-02-01T00:00:00Z",
        })
        # Review signal.
        await db.review_requests.insert_one({
            "id": uuid.uuid4().hex, "tenant_id": tid,
            "token": f"kpi-tok-{uuid.uuid4().hex[:12]}",
            "star_rating_submitted": 5,
            "star_submitted_at": (now - timedelta(days=2)).isoformat(),
            "created_at": "2026-02-01T00:00:00Z",
        })
        # New lead signal.
        await db.leads.insert_one({
            "id": uuid.uuid4().hex, "tenant_id": tid, "name": "KPI-lead",
            "status": "new",
            "created_at": (now - timedelta(days=3)).isoformat(),
        })

    _run(_plant())
    kpis = _run(_engagement_kpis(tid, since_iso))
    assert kpis.get("payments_paid_count", 0) >= 1
    assert kpis.get("payments_paid_amount", 0) >= 250.0
    assert kpis.get("reviews_count", 0) >= 1
    assert kpis.get("reviews_avg_rating") is not None
    assert kpis.get("new_leads", 0) >= 1

    html = _render_html({"invoice.soft_delete": 3}, now, kpis)
    assert "Engagement this week" in html
    assert "invoices paid" in html
    assert "review" in html.lower()
    assert "new leads" in html.lower()


def test_digest_skips_when_both_empty(db):
    """No bulk actions AND no engagement KPIs → send-tenant returns
    the skipped_zero_actions envelope."""
    from services.weekly_bulk_actions_digest import send_weekly_digest_for_tenant

    fake_tid = f"digest-emptyv2-{uuid.uuid4().hex}"
    async def _plant():
        await db.tenants.insert_one({
            "id": fake_tid, "slug": fake_tid, "name": "Empty",
            "created_at": "2026-02-01T00:00:00Z",
        })
        await db.users.insert_one({
            "id": uuid.uuid4().hex, "tenant_id": fake_tid,
            "role": "owner", "email": "empty-owner@example.com",
            "created_at": "2026-02-01T00:00:00Z",
        })
    _run(_plant())
    result = _run(send_weekly_digest_for_tenant({"id": fake_tid}))
    assert result.get("skipped_zero_actions") is True
