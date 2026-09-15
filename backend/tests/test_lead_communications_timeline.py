"""Phase L3 · Feb-2026 · Lead communication timeline.

Backend acceptance tests for ``GET /api/leads/{lead_id}/communications``:

* DESC ordering — most recent first, merged across
  ``lead_communications`` (outbound) + ``sms_inbound`` (inbound
  RC-matched) + ``leads.timeline[]`` (status_change).
* Pagination — ``limit=2`` returns 2 items + a cursor; the cursor
  drives a page-2 fetch that returns the remaining item(s).
* Tenant isolation — a lead in ANOTHER tenant returns 404 even
  when the ``lead_id`` matches.
"""
from __future__ import annotations

import asyncio
from typing import Dict

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.test_lead_communications_send_sms import _DB, _build_app


def _run(coro): return asyncio.run(coro)


def _seed_lead(db, *, tenant_id="t1", lid="lead-1", timeline=None):
    row = {
        "id": lid, "tenant_id": tenant_id,
        "name": "Test Lead", "email": "lead@example.com",
        "phone": "+15555550100",
        "status": "new", "created_at": "2026-02-01T10:00:00Z",
        "timeline": list(timeline or []),
    }
    db.leads.rows.append(row)
    return row


def _seed_comm(db, *, tenant_id, lid, cid, channel, created_at,
                direction="outbound", status="sent", body="hi",
                subject=None):
    db.lead_communications.rows.append({
        "id": cid, "tenant_id": tenant_id, "lead_id": lid,
        "direction": direction, "channel": channel,
        "from_identity": "+15555550001", "to_identity": "+15555550100",
        "subject": subject, "body": body, "status": status,
        "provider_message_id": f"pm-{cid}", "error": None,
        "created_at": created_at, "updated_at": created_at,
        "sent_by_user_id": "u-admin",
    })


def _seed_inbound(db, *, tenant_id, lid, mid, received_at, text="reply"):
    db.sms_inbound.rows.append({
        "id": f"in-{mid}", "tenant_id": tenant_id,
        "matched_lead_id": lid, "message_id": mid,
        "from_number": "+15555550100", "to_number": "+15555550001",
        "text": text, "received_at": received_at,
    })


# ─── DESC ordering + merge ───────────────────────────────────────────
def test_timeline_desc_ordering_merges_all_sources():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub, timeline=[
            {"ts": "2026-02-01T12:00:00Z",
             "kind": "status_change",
             "actor_user_id": "u-admin",
             "payload": {"from": "new", "to": "contacted"}},
        ])
        _seed_comm(db_stub, tenant_id="t1", lid="lead-1",
                    cid="c1", channel="sms",
                    created_at="2026-02-01T13:00:00Z")
        _seed_comm(db_stub, tenant_id="t1", lid="lead-1",
                    cid="c2", channel="email",
                    subject="Following up",
                    created_at="2026-02-01T14:00:00Z")
        _seed_inbound(db_stub, tenant_id="t1", lid="lead-1", mid="m1",
                       received_at="2026-02-01T15:00:00Z",
                       text="Thanks!")

        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
        ) as ac:
            r = await ac.get("/api/leads/lead-1/communications")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 4, items
        # Newest first — inbound SMS @15:00 → email @14:00 → sms @13:00 → status @12:00.
        assert items[0]["direction"] == "inbound"
        assert items[0]["body"] == "Thanks!"
        assert items[1]["type"] == "email"
        assert items[1]["subject"] == "Following up"
        assert items[2]["type"] == "sms"
        assert items[2]["direction"] == "outbound"
        assert items[3]["type"] == "status_change"

    _run(run())


# ─── Pagination via cursor ───────────────────────────────────────────
def test_timeline_pagination_with_cursor():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub)
        # 4 outbound SMS rows across distinct timestamps.
        for i in range(4):
            _seed_comm(db_stub, tenant_id="t1", lid="lead-1",
                        cid=f"c{i}", channel="sms",
                        created_at=f"2026-02-01T10:0{i}:00Z")
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
        ) as ac:
            r1 = await ac.get(
                "/api/leads/lead-1/communications?limit=2",
            )
            assert r1.status_code == 200, r1.text
            page1 = r1.json()
            assert page1["has_more"] is True
            assert len(page1["items"]) == 2
            assert page1["next_cursor"]
            # Page 2 with the cursor.
            r2 = await ac.get(
                f"/api/leads/lead-1/communications?limit=2"
                f"&cursor={page1['next_cursor']}",
            )
            assert r2.status_code == 200, r2.text
            page2 = r2.json()
            assert page2["has_more"] is False
            assert len(page2["items"]) == 2
            # No overlap between pages.
            ids_1 = {i["id"] for i in page1["items"]}
            ids_2 = {i["id"] for i in page2["items"]}
            assert not ids_1 & ids_2, "pages must not overlap"

    _run(run())


# ─── Tenant isolation ────────────────────────────────────────────────
def test_timeline_tenant_isolation_404():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub, tenant_id="t-other")
        _seed_comm(db_stub, tenant_id="t-other", lid="lead-1",
                    cid="c-secret", channel="sms",
                    created_at="2026-02-01T13:00:00Z")
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}  # caller is on tenant t1, NOT t-other
        app = _build_app(user, tenant, db_stub)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
        ) as ac:
            r = await ac.get("/api/leads/lead-1/communications")
        assert r.status_code == 404, r.text

    _run(run())
