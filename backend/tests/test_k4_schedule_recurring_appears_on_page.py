"""Phase K4 · Feb-2026 — Bug fix: Schedule-created recurring jobs
now appear on the Recurring Jobs page.

Contract lock:
  1. Creating a template through the same wire the Schedule flow now
     hits (POST /recurring-jobs with an initial
     ``last_generated_through`` cursor) succeeds AND the row shows up
     on GET /recurring-jobs.
  2. The cursor is honoured — the daily generator's ``_next_
     occurrences`` walker starts at ``last_generated_through + 1`` so
     pre-materialized occurrences don't double-book.
  3. Weekly / biweekly / same-day-monthly cadences all land on the
     RJ listing.
  4. Nth-weekday branch (pre-K4) still works — regression guard.
"""
from __future__ import annotations

from datetime import date, timedelta

import httpx

from tests._f7_loop_fixture import run_test


BASE = "/api/recurring-jobs"


def _get_app():
    from server import app
    return app


async def _ensure_tenant(db, tenant_id="aquaterra"):
    from utils import now_iso
    existing = await db.tenants.find_one({"id": tenant_id})
    if existing:
        if not existing.get("active"):
            await db.tenants.update_one(
                {"id": tenant_id}, {"$set": {"active": True}},
            )
        return existing
    row = {"id": tenant_id, "slug": tenant_id, "name": tenant_id,
              "active": True, "created_at": now_iso()}
    await db.tenants.insert_one(dict(row))
    return row


async def _make_token(db, role, email, tenant_id="aquaterra"):
    from utils import create_token, new_id
    from datetime import datetime, timezone
    user = await db.users.find_one({"email": email})
    if user:
        if user.get("role") != role:
            await db.users.update_one({"email": email},
                                             {"$set": {"role": role}})
            user["role"] = role
        return create_token(user)
    doc = {
        "id": new_id(), "email": email, "role": role,
        "tenant_id": tenant_id, "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(dict(doc))
    return create_token(doc)


async def _seed_customer(db, cid="cust_k4",
                              tenant_id="aquaterra", name="K4 Test Cust"):
    from utils import now_iso
    row = await db.customers.find_one({"id": cid, "tenant_id": tenant_id})
    if row:
        return row
    doc = {"id": cid, "tenant_id": tenant_id, "name": name,
              "first_name": "K4", "last_name": "Tester",
              "created_at": now_iso()}
    await db.customers.insert_one(dict(doc))
    return doc


# ═══════════════════════════════════════════════════════════════════
# 1. Weekly template created via the Schedule wire lands on the RJ
#    listing WITH the pre-materialized cursor.
# ═══════════════════════════════════════════════════════════════════
def test_k4_weekly_template_appears_on_recurring_jobs_page():
    async def _go(db):
        await _ensure_tenant(db)
        await _seed_customer(db, cid="cust_k4_weekly")
        token = await _make_token(db, "admin", "k4admin@aquaterra.com")
        headers = {"Authorization": f"Bearer {token}"}
        start = date.today().isoformat()
        # Same shape the Schedule flow POSTs after the pre-mat loop.
        payload = {
            "customer_id": "cust_k4_weekly",
            "service_type": "Pool Cleaning",
            "frequency": "weekly",
            "start_date": start,
            "price_cents": 12000,
            "notes": "K4 · seeded from Schedule",
            "active": True,
            "work_class": "service",
            "day_of_week": 2,  # Wed
            "recurrence_never_ends": True,
            "end_date": None,
            # The pre-materialized cursor — 3 weeks out.
            "last_generated_through": (date.today()
                                            + timedelta(days=21)).isoformat(),
        }
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(transport=transport,
                                             base_url="http://test") as ac:
            r_create = await ac.post(BASE, json=payload, headers=headers)
            assert r_create.status_code == 200, r_create.text
            tpl = r_create.json()
            assert tpl["frequency"] == "weekly"
            # Cursor was honoured (not silently overwritten to None).
            assert tpl["last_generated_through"] \
                == payload["last_generated_through"]

            # GET /recurring-jobs shows the template.
            r_list = await ac.get(BASE, headers=headers)
            assert r_list.status_code == 200, r_list.text
            body = r_list.json()
            assert body["count"] >= 1
            found = [t for t in body["items"] if t["id"] == tpl["id"]]
            assert found, "K4 · created weekly template MUST be listed"
            assert found[0]["frequency"] == "weekly"

        await db.recurring_job_templates.delete_many(
            {"customer_id": "cust_k4_weekly"})
        await db.customers.delete_many({"id": "cust_k4_weekly"})

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 2. The `last_generated_through` cursor is honoured by the daily
#    generator wire — `POST /recurring-jobs/{id}/generate` skips
#    every date ≤ cursor (this is the same _generate_from_template
#    path the H10 nightly generator uses).
# ═══════════════════════════════════════════════════════════════════
def test_k4_cursor_prevents_double_booking_via_generator():
    async def _go(db):
        await _ensure_tenant(db)
        await _seed_customer(db, cid="cust_k4_cursor")
        token = await _make_token(db, "admin", "k4admin@aquaterra.com")
        headers = {"Authorization": f"Bearer {token}"}
        start = (date.today() - timedelta(days=1)).isoformat()
        cursor = (date.today() + timedelta(days=21)).isoformat()
        through = (date.today() + timedelta(days=90)).isoformat()
        payload = {
            "customer_id": "cust_k4_cursor",
            "service_type": "Pool Cleaning",
            "frequency": "weekly",
            "start_date": start,
            "day_of_week": date.today().weekday(),
            "price_cents": 0,
            "active": True,
            "last_generated_through": cursor,
        }
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(transport=transport,
                                             base_url="http://test") as ac:
            r_create = await ac.post(BASE, json=payload, headers=headers)
            assert r_create.status_code == 200, r_create.text
            tid = r_create.json()["id"]
            # Fire the same generator wire the H10 nightly cron uses.
            r_gen = await ac.post(
                f"{BASE}/{tid}/generate?through={through}", headers=headers)
            assert r_gen.status_code == 200, r_gen.text
            # Every job created MUST have a scheduled_date strictly
            # AFTER the cursor — the pre-materialized dates ≤ cursor
            # are deliberately skipped.
            created_jobs = await db.jobs.find(
                {"recurring_template_id": tid, "tenant_id": "aquaterra"},
                {"_id": 0, "scheduled_date": 1},
            ).to_list(200)
            for j in created_jobs:
                sd = j.get("scheduled_date")
                assert sd and sd > cursor, (
                    f"generator created job for {sd} which is ≤ cursor "
                    f"{cursor} — that would double-book a pre-mat "
                    "occurrence from the Schedule flow.")

        # Cleanup — remove generated jobs + template + seed customer.
        await db.jobs.delete_many({"recurring_template_id": tid})
        await db.recurring_job_templates.delete_many(
            {"customer_id": "cust_k4_cursor"})
        await db.customers.delete_many({"id": "cust_k4_cursor"})

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 3. Biweekly cadence path lands on the RJ listing.
# ═══════════════════════════════════════════════════════════════════
def test_k4_biweekly_template_appears_on_recurring_jobs_page():
    async def _go(db):
        await _ensure_tenant(db)
        await _seed_customer(db, cid="cust_k4_biw")
        token = await _make_token(db, "admin", "k4admin@aquaterra.com")
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "customer_id": "cust_k4_biw",
            "service_type": "Pool Cleaning",
            "frequency": "biweekly",
            "start_date": date.today().isoformat(),
            "day_of_week": 4,  # Fri
            "price_cents": 8000,
            "active": True,
        }
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(transport=transport,
                                             base_url="http://test") as ac:
            r = await ac.post(BASE, json=payload, headers=headers)
            assert r.status_code == 200, r.text
            tid = r.json()["id"]
            r_list = await ac.get(BASE, headers=headers)
            assert any(t["id"] == tid and t["frequency"] == "biweekly"
                            for t in r_list.json()["items"])

        await db.recurring_job_templates.delete_many(
            {"customer_id": "cust_k4_biw"})
        await db.customers.delete_many({"id": "cust_k4_biw"})

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 4. Same-day-of-month monthly cadence lands.
# ═══════════════════════════════════════════════════════════════════
def test_k4_monthly_same_day_template_appears():
    async def _go(db):
        await _ensure_tenant(db)
        await _seed_customer(db, cid="cust_k4_month")
        token = await _make_token(db, "admin", "k4admin@aquaterra.com")
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "customer_id": "cust_k4_month",
            "service_type": "Pool Cleaning",
            "frequency": "monthly",
            "start_date": date.today().isoformat(),
            "day_of_month": 15,
            "monthly_pattern": "day_of_month",
            "price_cents": 25000,
            "active": True,
        }
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(transport=transport,
                                             base_url="http://test") as ac:
            r = await ac.post(BASE, json=payload, headers=headers)
            assert r.status_code == 200, r.text
            tid = r.json()["id"]
            r_list = await ac.get(BASE, headers=headers)
            assert any(t["id"] == tid
                          and t["frequency"] == "monthly"
                          and t["monthly_pattern"] == "day_of_month"
                          for t in r_list.json()["items"])

        await db.recurring_job_templates.delete_many(
            {"customer_id": "cust_k4_month"})
        await db.customers.delete_many({"id": "cust_k4_month"})

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 5. Regression — the Nth-weekday branch (pre-K4, JobNew.jsx:246)
#    still lands on the listing.
# ═══════════════════════════════════════════════════════════════════
def test_k4_nth_weekday_regression_still_lists():
    async def _go(db):
        await _ensure_tenant(db)
        await _seed_customer(db, cid="cust_k4_nth")
        token = await _make_token(db, "admin", "k4admin@aquaterra.com")
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "customer_id": "cust_k4_nth",
            "service_type": "Pool Cleaning",
            "frequency": "monthly",
            "start_date": date.today().isoformat(),
            "monthly_pattern": "nth_weekday",
            "monthly_nth_week": "third",
            "monthly_weekday": 4,   # Fri
            "price_cents": 20000,
            "active": True,
        }
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(transport=transport,
                                             base_url="http://test") as ac:
            r = await ac.post(BASE, json=payload, headers=headers)
            assert r.status_code == 200, r.text
            tid = r.json()["id"]
            r_list = await ac.get(BASE, headers=headers)
            assert any(t["id"] == tid
                          and t["monthly_pattern"] == "nth_weekday"
                          for t in r_list.json()["items"])

        await db.recurring_job_templates.delete_many(
            {"customer_id": "cust_k4_nth"})
        await db.customers.delete_many({"id": "cust_k4_nth"})

    run_test(_go)
