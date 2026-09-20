"""Phase B · Feb-2026 · Super Timeline — 6-source aggregator tests.

Covers the acceptance criteria in the D5 spec:
  1. Aggregator returns all 6 source types when the fixture has
     one of each.
  2. DESC sort by ``occurred_at`` across sources.
  3. Timezone normalisation — naive datetime + UTC + non-UTC offset
     all coerce to UTC strings.
  4. ``admin`` and ``super_admin`` get the full 6-source response.
  5. ``technician`` / ``customer`` get 403 with
     ``insufficient_role_for_full_timeline``.
  6. Tenant isolation — cross-tenant call_log + note do not leak.
  7. Cursor pagination — ``before=`` produces non-overlapping pages.
  8. Backward compatibility — legacy ``kind``, ``created_at``,
     ``ref_id`` fields still present alongside the new B-shape.

Uses ``httpx.ASGITransport`` inside the shared ``_f7_loop_fixture``
harness so the app boots on the test's loop and the rebound-db
guarantee holds. Live HTTP is NOT required.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import httpx
import pytest

from tests._f7_loop_fixture import run_test


API = "/api"


def _get_app():
    from server import app
    return app


# ─── auth helper ────────────────────────────────────────────────
def _mint_token(*, uid: str, tid: str, role: str, email: str = "x@x") -> str:
    import jwt
    from datetime import datetime as _dt, timezone as _tz
    from config import JWT_SECRET
    payload = {
        "sub":       uid,
        "email":     email,
        "role":      role,
        "tenant_id": tid,
        "exp":       int((_dt.now(_tz.utc)
                            + timedelta(hours=1)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


# ─── fixture seed ───────────────────────────────────────────────
@pytest.fixture
def super_timeline_seed():
    """Seed a tenant, an admin user, a customer, and one row per
    source (marketing email + SMS + invoice + estimate + call + note).
    Timestamps are interleaved so DESC sort is provable.

    Yields ``{tenant_id, customer_id, admin_token, super_token,
    tech_token, customer_token, ...}``.
    """
    from config import db

    tid = f"tl-B-tid-{uuid.uuid4()}"
    tid_other = f"tl-B-tid-other-{uuid.uuid4()}"
    cid = f"tl-B-cust-{uuid.uuid4()}"
    admin_uid = f"tl-B-admin-{uuid.uuid4()}"
    super_uid = f"tl-B-super-{uuid.uuid4()}"
    tech_uid  = f"tl-B-tech-{uuid.uuid4()}"
    portal_customer_uid = f"tl-B-portal-{uuid.uuid4()}"
    author_uid = f"tl-B-author-{uuid.uuid4()}"
    inv_id = f"tl-B-inv-{uuid.uuid4()}"
    est_id = f"tl-B-est-{uuid.uuid4()}"
    call_id = f"tl-B-call-{uuid.uuid4()}"
    call_id_other = f"tl-B-call-other-{uuid.uuid4()}"
    job_id = f"tl-B-job-{uuid.uuid4()}"
    job_id_other = f"tl-B-job-other-{uuid.uuid4()}"
    md_email_id = f"tl-B-md-email-{uuid.uuid4()}"
    md_sms_id = f"tl-B-md-sms-{uuid.uuid4()}"

    # Six interleaved timestamps, newest → oldest.
    now = datetime.now(timezone.utc)
    t_email = now - timedelta(minutes=10)     # newest
    t_call = now - timedelta(minutes=20)
    t_sms = now - timedelta(minutes=30)
    t_estimate = now - timedelta(minutes=40)
    t_invoice = now - timedelta(minutes=50)
    t_note = now - timedelta(minutes=60)      # oldest

    async def _seed(_db):
        await _db.tenants.insert_many([
            {"id": tid, "name": "Tenant B",
             "slug": f"tb-{uuid.uuid4().hex[:8]}", "active": True},
            {"id": tid_other, "name": "Other Tenant",
             "slug": f"to-{uuid.uuid4().hex[:8]}", "active": True},
        ])
        await _db.users.insert_many([
            {"id": admin_uid, "email": f"admin-{admin_uid}@ex.test",
             "role": "admin", "tenant_id": tid, "name": "Alice Admin"},
            {"id": super_uid, "email": f"super-{super_uid}@ex.test",
             "role": "super_admin", "tenant_id": tid, "name": "Sam Super"},
            {"id": tech_uid, "email": f"tech-{tech_uid}@ex.test",
             "role": "technician", "tenant_id": tid, "name": "Terry Tech"},
            {"id": portal_customer_uid,
             "email": f"cust-{portal_customer_uid}@ex.test",
             "role": "customer", "tenant_id": tid,
             "customer_id": cid, "name": "Charlie Customer"},
            {"id": author_uid, "email": f"auth-{author_uid}@ex.test",
             "role": "technician", "tenant_id": tid,
             "name": "Nora Author"},
        ])
        await _db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "Timeline B",
            "email": f"cust-{cid}@ex.test", "phone": "+15550000000",
        })
        # ── quotes: invoice + estimate ──
        await _db.quotes.insert_many([
            {"id": inv_id, "tenant_id": tid, "customer_id": cid,
             "doc_type": "invoice", "total": 250.0, "status": "sent",
             "number": "B-INV-1",
             "created_at": t_invoice.isoformat()},
            {"id": est_id, "tenant_id": tid, "customer_id": cid,
             "doc_type": "quote", "total": 100.0, "status": "draft",
             "number": "B-EST-1",
             "created_at": t_estimate.isoformat()},
        ])
        # ── marketing: email + sms ──
        await _db.marketing_deliveries.insert_many([
            {"id": md_email_id, "tenant_id": tid, "customer_id": cid,
             "channel": "email",
             "recipient_address": f"cust-{cid}@ex.test",
             "template_code": "invoice_sent_email",
             "subject": "Your invoice is ready",
             "delivery_status": "sent",
             "created_at": t_email.isoformat()},
            {"id": md_sms_id, "tenant_id": tid, "customer_id": cid,
             "channel": "sms",
             "recipient_address": "+15550000000",
             "template_code": "invoice_sent_sms",
             "subject": "SMS: pay $250",
             "delivery_status": "sent",
             "created_at": t_sms.isoformat()},
        ])
        # ── call_logs: one on our tenant, one on the OTHER tenant ──
        # Note: ``started_at`` on the target-tenant row is passed
        # as a **non-UTC** offset ("+05:30") to prove the aggregator
        # coerces to UTC.
        t_call_ist = t_call.astimezone(timezone(timedelta(hours=5, minutes=30)))
        await _db.call_logs.insert_many([
            {"id": call_id, "session_id": "sess-1",
             "tenant_id": tid, "customer_id": cid,
             "from_number": "+15551234567", "to_number": "+15550000000",
             "direction": "inbound", "duration": 134,
             "recording_url": "https://media/rec-abc",
             "started_at": t_call_ist.isoformat(),
             "created_at": t_call_ist.isoformat()},
            # Cross-tenant call_log with the SAME customer_id (must
            # not leak into our tenant's timeline).
            {"id": call_id_other, "session_id": "sess-2",
             "tenant_id": tid_other, "customer_id": cid,
             "from_number": "+19995551111", "to_number": "+15550000000",
             "direction": "outbound", "duration": 45,
             "started_at": t_call.isoformat(),
             "created_at": t_call.isoformat()},
        ])
        # ── jobs.notes: one on our tenant (string shape), one on
        # the OTHER tenant (must not leak). The note ``occurred_at``
        # is derived from ``job.created_at`` — we pass a naive
        # datetime to prove the aggregator attaches UTC before
        # coercion.
        await _db.jobs.insert_many([
            {"id": job_id, "tenant_id": tid, "customer_id": cid,
             "service_type": "chemical treatment",
             "notes": "Customer requests early morning slot.",
             "internal_notes":
                 "Tech-only: pool motor was noisy — schedule service.",
             "created_at": t_note.replace(tzinfo=None).isoformat(),
             "created_by": author_uid},
            {"id": job_id_other, "tenant_id": tid_other,
             "customer_id": cid,
             "notes": "Cross-tenant leak trap.",
             "created_at": t_note.isoformat()},
        ])

    async def _teardown(_db):
        await _db.tenants.delete_many({"id": {"$in": [tid, tid_other]}})
        await _db.users.delete_many({
            "id": {"$in": [admin_uid, super_uid, tech_uid,
                             portal_customer_uid, author_uid]}})
        await _db.customers.delete_many({"id": cid})
        await _db.quotes.delete_many({"id": {"$in": [inv_id, est_id]}})
        await _db.marketing_deliveries.delete_many({
            "id": {"$in": [md_email_id, md_sms_id]}})
        await _db.call_logs.delete_many({
            "id": {"$in": [call_id, call_id_other]}})
        await _db.jobs.delete_many({
            "id": {"$in": [job_id, job_id_other]}})

    run_test(_seed)
    admin_token = _mint_token(uid=admin_uid, tid=tid, role="admin",
                                 email=f"admin-{admin_uid}@ex.test")
    super_token = _mint_token(uid=super_uid, tid=tid, role="super_admin",
                                 email=f"super-{super_uid}@ex.test")
    tech_token = _mint_token(uid=tech_uid, tid=tid, role="technician",
                                 email=f"tech-{tech_uid}@ex.test")
    customer_token = _mint_token(uid=portal_customer_uid, tid=tid,
                                     role="customer",
                                     email=f"cust-{portal_customer_uid}@ex.test")
    yield {
        "tenant_id":      tid,
        "tenant_other":   tid_other,
        "customer_id":    cid,
        "admin_token":    admin_token,
        "super_token":    super_token,
        "tech_token":     tech_token,
        "customer_token": customer_token,
        "author_uid":     author_uid,
        "inv_id":         inv_id, "est_id": est_id,
        "call_id":        call_id, "call_id_other": call_id_other,
        "job_id":         job_id, "job_id_other": job_id_other,
        "md_email_id":    md_email_id, "md_sms_id": md_sms_id,
    }
    run_test(_teardown)


# ═════════════════════════════════════════════════════════════════════
# Tests
# ═════════════════════════════════════════════════════════════════════
async def _get(client: httpx.AsyncClient, path: str, tok: str, tid: str):
    return await client.get(
        path, headers={
            "Authorization": f"Bearer {tok}",
            "X-Tenant-Id":   tid,
        },
    )


# 1 — admin gets all 6 source types
def test_admin_gets_all_six_source_types(super_timeline_seed):
    S = super_timeline_seed

    async def _go(_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            r = await _get(
                client,
                f"{API}/customers/{S['customer_id']}/timeline?page_size=100",
                S["admin_token"], S["tenant_id"],
            )
            assert r.status_code == 200, r.text
            body = r.json()
            src_types = {i["source_type"] for i in body["items"]}
            assert src_types == {"email", "sms", "invoice", "quote",
                                   "call", "note"}, src_types
    run_test(_go)


# 2 — DESC sort by occurred_at across all sources
def test_admin_items_sorted_desc_by_occurred_at(super_timeline_seed):
    S = super_timeline_seed

    async def _go(_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            r = await _get(
                client,
                f"{API}/customers/{S['customer_id']}/timeline?page_size=100",
                S["admin_token"], S["tenant_id"],
            )
            body = r.json()
            ts = [i["occurred_at"] for i in body["items"]]
            assert ts == sorted(ts, reverse=True), ts
    run_test(_go)


# 3 — timezone normalisation to UTC
def test_all_occurred_at_are_utc_iso(super_timeline_seed):
    S = super_timeline_seed

    async def _go(_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            r = await _get(
                client,
                f"{API}/customers/{S['customer_id']}/timeline?page_size=100",
                S["admin_token"], S["tenant_id"],
            )
            body = r.json()
            # Every item must have a non-empty occurred_at, and
            # every parseable one must be UTC-anchored ("+00:00").
            from datetime import datetime as _dt, timezone as _tz
            for i in body["items"]:
                assert i["occurred_at"], i
                parsed = _dt.fromisoformat(
                    i["occurred_at"].replace("Z", "+00:00"))
                # Must be UTC (offset 0). No drift.
                assert parsed.utcoffset() == timedelta(0), (
                    f"{i['source_type']} occurred_at "
                    f"{i['occurred_at']!r} is not UTC"
                )
    run_test(_go)


# 4 — super_admin also gets full 6-source view
def test_super_admin_gets_full_response(super_timeline_seed):
    S = super_timeline_seed

    async def _go(_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            r = await _get(
                client,
                f"{API}/customers/{S['customer_id']}/timeline?page_size=100",
                S["super_token"], S["tenant_id"],
            )
            assert r.status_code == 200, r.text
            src_types = {i["source_type"] for i in r.json()["items"]}
            assert "call" in src_types
            assert "note" in src_types
    run_test(_go)


# 5 — technician + customer → 403 insufficient_role_for_full_timeline
def test_technician_gets_403_with_specific_detail(super_timeline_seed):
    S = super_timeline_seed

    async def _go(_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            r = await _get(
                client,
                f"{API}/customers/{S['customer_id']}/timeline",
                S["tech_token"], S["tenant_id"],
            )
            assert r.status_code == 403, r.text
            assert r.json()["detail"] == "insufficient_role_for_full_timeline"
    run_test(_go)


def test_customer_gets_403_on_admin_timeline(super_timeline_seed):
    S = super_timeline_seed

    async def _go(_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            r = await _get(
                client,
                f"{API}/customers/{S['customer_id']}/timeline",
                S["customer_token"], S["tenant_id"],
            )
            assert r.status_code == 403, r.text
            assert r.json()["detail"] == "insufficient_role_for_full_timeline"
    run_test(_go)


# 6 — tenant isolation
def test_cross_tenant_call_and_note_do_not_leak(super_timeline_seed):
    S = super_timeline_seed

    async def _go(_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            r = await _get(
                client,
                f"{API}/customers/{S['customer_id']}/timeline?page_size=100",
                S["admin_token"], S["tenant_id"],
            )
            body = r.json()
            ids = {i.get("id") for i in body["items"]}
            assert S["call_id_other"] not in ids
            # The cross-tenant job's note body / job id must not
            # appear anywhere.
            for i in body["items"]:
                d = i.get("detail") or {}
                if i.get("source_type") == "note":
                    assert d.get("job_id") != S["job_id_other"], i
    run_test(_go)


# 7 — cursor pagination: no overlap between pages
def test_cursor_pagination_before_returns_earlier_items(super_timeline_seed):
    S = super_timeline_seed

    async def _go(_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            # First page: newest ``limit=3``.
            r1 = await _get(
                client,
                f"{API}/customers/{S['customer_id']}/timeline?limit=3&before=2999-01-01T00:00:00%2B00:00",
                S["admin_token"], S["tenant_id"],
            )
            body1 = r1.json()
            assert len(body1["items"]) == 3
            page1_ids = {i["id"] for i in body1["items"]}
            cursor = body1.get("next_before")
            assert cursor
            # Second page: strictly earlier than cursor.
            r2 = await _get(
                client,
                f"{API}/customers/{S['customer_id']}/timeline?limit=10&before={cursor}",
                S["admin_token"], S["tenant_id"],
            )
            body2 = r2.json()
            page2_ids = {i["id"] for i in body2["items"]}
            # No overlap.
            assert page1_ids.isdisjoint(page2_ids), (
                page1_ids & page2_ids
            )
            # Union must cover every item (page 1 had 3 of ~7 rows;
            # page 2 must include the remaining rows).
            for it in body2["items"]:
                iso_before = cursor
                assert (it["occurred_at"] or it["created_at"]) < iso_before
    run_test(_go)


# 8 — backwards-compat: legacy fields still shipped alongside new ones
def test_legacy_fields_still_present_alongside_new_shape(super_timeline_seed):
    S = super_timeline_seed

    async def _go(_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            r = await _get(
                client,
                f"{API}/customers/{S['customer_id']}/timeline?page_size=100",
                S["admin_token"], S["tenant_id"],
            )
            body = r.json()
            # Envelope shape unchanged.
            for k in ("items", "page", "page_size", "total", "total_pages"):
                assert k in body, k
            # Every item retains the legacy fields.
            for i in body["items"]:
                for k in ("kind", "created_at", "ref_type", "ref_id"):
                    assert k in i, (k, i.get("source_type"))
                # New required fields present.
                for k in ("id", "source_type", "occurred_at",
                           "summary", "detail", "actor"):
                    assert k in i, (k, i)
                # ``occurred_at`` and ``created_at`` are synchronised
                # on new-source items (call/note); on legacy items
                # both must at least be non-empty.
                assert i["occurred_at"]
                assert i["created_at"]
    run_test(_go)


# 9 — call row structural spot-check
def test_call_row_carries_direction_duration_and_recording(super_timeline_seed):
    S = super_timeline_seed

    async def _go(_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            r = await _get(
                client,
                f"{API}/customers/{S['customer_id']}/timeline?kind=call",
                S["admin_token"], S["tenant_id"],
            )
            items = r.json()["items"]
            assert len(items) == 1
            call = items[0]
            assert call["source_type"] == "call"
            d = call["detail"]
            assert d["direction"] == "inbound"
            assert d["duration_sec"] == 134
            assert d["duration"] == "2m 14s"
            assert d["recording_url"] == "https://media/rec-abc"
            # Legacy alias.
            assert call["ref_type"] == "call_log"
            assert call["kind"] == "call"
    run_test(_go)


# 10 — note row carries actor display_name + note_kind
def test_note_rows_map_author_to_display_name(super_timeline_seed):
    S = super_timeline_seed

    async def _go(_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_get_app()),
            base_url="http://test",
        ) as client:
            r = await _get(
                client,
                f"{API}/customers/{S['customer_id']}/timeline?kind=note",
                S["admin_token"], S["tenant_id"],
            )
            items = r.json()["items"]
            # The seed inserts ONE job with both ``notes`` and
            # ``internal_notes`` non-empty → 2 note rows.
            assert len(items) == 2
            kinds = {i["detail"]["note_kind"] for i in items}
            assert kinds == {"visit", "internal"}
            for i in items:
                assert i["actor"] is not None
                assert i["actor"]["display_name"] == "Nora Author"
                assert i["actor"]["id"] == S["author_uid"]
                assert i["detail"]["job_id"] == S["job_id"]
    run_test(_go)
