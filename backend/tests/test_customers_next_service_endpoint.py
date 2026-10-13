"""CUSTOMER-DETAIL-NEXT-SERVICE · Feb-2026 — admin
``GET /customers/{cid}/next-service`` endpoint tests.

Mirrors the pytest pattern used by
``test_phase27_customer_kpi_summary.py``: direct in-process invocation
via ``tests._f7_loop_fixture.run_test``.  Covers:

  1. Returns the earliest upcoming job scoped to the caller's tenant.
  2. Returns ``{"next_service": None}`` when no upcoming jobs exist.
  3. Phase P47 rung-2 fallthrough — a row with no ``scheduled_start``
     but ``scheduled_date == today`` is still surfaced.  Regression
     lock on the pre-P47 null-sort-first trap.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

from tests._f7_loop_fixture import run_test


load_dotenv("/app/backend/.env")


def _tenant_id() -> str:
    return f"test-next-service-{uuid.uuid4()}"


# ─── Case 1 · Earliest upcoming job scoped to tenant ──────────────
def test_next_service_returns_earliest_upcoming_scoped_to_tenant():
    tid = _tenant_id()
    cid = str(uuid.uuid4())
    other_tid = _tenant_id()
    other_cid = str(uuid.uuid4())

    async def _run(db):
        try:
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid, "name": "Next-Service Cust",
            })
            # Cross-tenant decoy — same customer id does NOT exist in
            # the other tenant, but we add a job there to confirm the
            # tenant filter is applied.
            await db.customers.insert_one({
                "id": other_cid, "tenant_id": other_tid,
                "name": "Other-Tenant Cust",
            })

            now = datetime.now(timezone.utc)
            earliest = now + timedelta(days=1)
            later = now + timedelta(days=5)
            cross = now + timedelta(hours=12)

            jid_earliest = str(uuid.uuid4())
            jid_later = str(uuid.uuid4())
            jid_cross = str(uuid.uuid4())

            await db.jobs.insert_many([
                {
                    "id": jid_later,
                    "tenant_id": tid, "customer_id": cid,
                    "status": "scheduled",
                    "service_type": "Weekly maintenance",
                    "title": "Weekly maintenance",
                    "scheduled_start": later.isoformat(),
                    "scheduled_date": later.date().isoformat(),
                },
                {
                    "id": jid_earliest,
                    "tenant_id": tid, "customer_id": cid,
                    "status": "scheduled",
                    "service_type": "Pool cleaning",
                    "title": "Pool cleaning",
                    "scheduled_start": earliest.isoformat(),
                    "scheduled_date": earliest.date().isoformat(),
                },
                # Cross-tenant row scheduled before "earliest" — must
                # NOT be returned when calling as tenant ``tid``.
                {
                    "id": jid_cross,
                    "tenant_id": other_tid, "customer_id": other_cid,
                    "status": "scheduled",
                    "service_type": "Should-not-leak",
                    "title": "Should-not-leak",
                    "scheduled_start": cross.isoformat(),
                    "scheduled_date": cross.date().isoformat(),
                },
            ])

            from routers.customers import get_customer_next_service
            res = await get_customer_next_service(
                cid=cid,
                user={"role": "admin", "id": "u-admin"},
                tenant={"id": tid},
            )
            assert "next_service" in res, res
            job = res["next_service"]
            assert job is not None, "expected an upcoming job, got None"
            assert job["id"] == jid_earliest, (
                f"earliest wrong: got {job['id']!r} vs {jid_earliest!r}")
            assert job["tenant_id"] == tid
            assert job["customer_id"] == cid
            # Full canonical object — service_type + status present.
            assert job["service_type"] == "Pool cleaning"
            assert job["status"] == "scheduled"
        finally:
            await db.customers.delete_many(
                {"tenant_id": {"$in": [tid, other_tid]}})
            await db.jobs.delete_many(
                {"tenant_id": {"$in": [tid, other_tid]}})

    run_test(_run)


# ─── Case 2 · Returns None when no upcoming jobs ──────────────────
def test_next_service_returns_none_when_no_upcoming():
    tid = _tenant_id()
    cid = str(uuid.uuid4())

    async def _run(db):
        try:
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid, "name": "Empty-Future Cust",
            })

            now = datetime.now(timezone.utc)
            # Past job — status still "scheduled" but date was
            # yesterday.  Must be excluded by the P47 date guard.
            await db.jobs.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tid, "customer_id": cid,
                "status": "scheduled",
                "service_type": "Yesterday visit",
                "title": "Yesterday visit",
                "scheduled_start": (now - timedelta(days=1)).isoformat(),
                "scheduled_date": (now - timedelta(days=1)).date().isoformat(),
            })
            # Future-dated but completed — status excluded.
            await db.jobs.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tid, "customer_id": cid,
                "status": "completed",
                "service_type": "Future-done",
                "title": "Future-done",
                "scheduled_start": (now + timedelta(days=1)).isoformat(),
                "scheduled_date": (now + timedelta(days=1)).date().isoformat(),
            })

            from routers.customers import get_customer_next_service
            res = await get_customer_next_service(
                cid=cid,
                user={"role": "admin", "id": "u-admin"},
                tenant={"id": tid},
            )
            assert res == {"next_service": None}, res
        finally:
            await db.customers.delete_many({"tenant_id": tid})
            await db.jobs.delete_many({"tenant_id": tid})

    run_test(_run)


# ─── Case 3 · P47 rung-2 — bare scheduled_date, no scheduled_start ─
def test_next_service_rung2_bare_date_today_surfaces():
    tid = _tenant_id()
    cid = str(uuid.uuid4())

    async def _run(db):
        try:
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid, "name": "Rung-2 Cust",
            })
            today_ymd = datetime.now(timezone.utc).date().isoformat()

            # Rung-2 row — only ``scheduled_date`` populated, today.
            # Pre-P47 the BSON null-sort-first trap would surface a
            # stale past row instead of this; P47 pushed the date
            # guard into the DB query, so this must be returned.
            jid_rung2 = str(uuid.uuid4())
            await db.jobs.insert_one({
                "id": jid_rung2,
                "tenant_id": tid, "customer_id": cid,
                "status": "scheduled",
                "service_type": "Rung-2 today",
                "title": "Rung-2 today",
                "scheduled_start": None,
                "scheduled_date": today_ymd,
            })
            # Decoy — stale row with past ``scheduled_date`` and no
            # start.  Must be filtered out by rung-2's date guard.
            await db.jobs.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tid, "customer_id": cid,
                "status": "scheduled",
                "service_type": "Stale rung-2",
                "title": "Stale rung-2",
                "scheduled_start": None,
                "scheduled_date": "2020-01-01",
            })

            from routers.customers import get_customer_next_service
            res = await get_customer_next_service(
                cid=cid,
                user={"role": "admin", "id": "u-admin"},
                tenant={"id": tid},
            )
            assert res["next_service"] is not None, res
            assert res["next_service"]["id"] == jid_rung2, res
        finally:
            await db.customers.delete_many({"tenant_id": tid})
            await db.jobs.delete_many({"tenant_id": tid})

    run_test(_run)
