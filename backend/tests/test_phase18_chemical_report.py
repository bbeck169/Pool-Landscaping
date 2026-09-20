"""Phase 18 · Chemical Cost Report + Per-Tech Inventory + Low-Stock Notifications.

Test pattern matches the repo's convention (see test_qbo_phase17.py,
test_public_lead_intake_bugfix.py):
    - Sync ``requests`` for HTTP against the live backend on :8001.
    - Sync ``pymongo`` for DB fixtures.
    - Async internals invoked via ``asyncio.run()`` where needed.

Coverage:
    A) Seed idempotency: ``seed_chemicals_for_tenant`` inserts 8 rows
       on first run, 0 on the second run.
    B) Seed preserves existing tuned ``reorder_point``.
    C) ``should_alert`` returns False for null thresholds (user
       decision 4 — do NOT alert on null).
    D) Real-time fan-out fires exactly once per 24h dedup window;
       Slack + bell rows land; second call in the window is deduped.
    E) Quiet hours defer real-time; cron path still notifies.
    F) Cost report RBAC: admin/manager+ → 200, technician → 403.
    G) Aggregation math + per-tech / per-department buckets.
    H) Mobile my-inventory NEVER exposes cost fields.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

# Pin one asyncio loop for the entire module and rebind Motor to it,
# same pattern as test_qbo_phase17.py — Motor stashes references to the
# loop and blows up with "Event loop is closed" across ``asyncio.run``
# calls otherwise.
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_FRESH = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _FRESH[_ENV["DB_NAME"]]

from services import inventory_alerts as _inv_alerts  # noqa: E402
_inv_alerts.db = _DB


def _run(coro):
    try:
        asyncio.set_event_loop(_LOOP)
    except Exception:  # noqa: BLE001
        pass
    return _LOOP.run_until_complete(coro)

# Match utils.create_token — HS256 with JWT_SECRET.
JWT_SECRET = _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET") \
    or "dev-secret-change-me"
JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _issue_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id, "email": email, "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


@pytest.fixture()
def tenant_id():
    tid = f"p18-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one(
        {"id": tid, "name": f"P18 {tid}", "slug": f"p18-{tid}",
         "active": True, "widget_allowed_domains": []},
    )
    yield tid
    for col in ("tenants", "inventory_items", "chemical_usage_events",
                "stock_movements", "inventory_alert_events",
                "inventory_alert_settings", "notifications",
                "notification_preferences", "users"):
        _sync[col].delete_many({"tenant_id": tid})


@pytest.fixture()
def admin_user(tenant_id):
    uid = f"admin-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@p18test.com"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "admin",
        "name": "P18 Admin", "email": email,
    })
    return {"id": uid, "email": email, "role": "admin",
            "token": _issue_token(uid, email, "admin"),
            "tenant_id": tenant_id}


@pytest.fixture()
def tech_user(tenant_id):
    uid = f"tech-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@p18test.com"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "technician",
        "name": "P18 Tech", "email": email,
    })
    return {"id": uid, "email": email, "role": "technician",
            "token": _issue_token(uid, email, "technician"),
            "tenant_id": tenant_id}


# ── A) seed idempotency ─────────────────────────────────────────

def test_A_seed_is_idempotent(tenant_id):
    from services.inventory_alerts import seed_chemicals_for_tenant
    r1 = _run(seed_chemicals_for_tenant(tenant_id))
    assert r1["inserted"] == 8, r1
    r2 = _run(seed_chemicals_for_tenant(tenant_id))
    assert r2["inserted"] == 0
    assert r2["patched"] == 0
    seeded = _sync.inventory_items.count_documents(
        {"tenant_id": tenant_id, "is_seeded_chemical": True})
    assert seeded == 8


# ── B) seed preserves tuned reorder_point ───────────────────────

def test_B_seed_preserves_existing_reorder_point(tenant_id):
    from services.inventory_alerts import seed_chemicals_for_tenant
    pre_id = _new_id()
    _sync.inventory_items.insert_one({
        "id": pre_id, "tenant_id": tenant_id,
        "name": "Liquid Chlorine", "category": "chemical", "unit": "gal",
        "sku": "", "current_qty": 30.0, "reorder_point": 42.0,
        "reorder_qty": 42.0, "unit_cost": 0.0,
        "created_at": _now_iso(), "updated_at": _now_iso(),
    })
    r = _run(seed_chemicals_for_tenant(tenant_id))
    assert r["patched"] >= 1
    row = _sync.inventory_items.find_one({"id": pre_id})
    assert row["reorder_point"] == 42.0, "tuned threshold must be preserved"
    assert row["sku"] == "P18-liquid_chlorine"
    assert row["is_seeded_chemical"] is True
    assert row["department"] == "pool"


# ── C) null threshold never alerts ──────────────────────────────

def test_C_null_threshold_never_alerts():
    from services.inventory_alerts import should_alert
    assert should_alert({"current_qty": 0, "reorder_point": None}) is False
    assert should_alert({"current_qty": 0, "reorder_point": 0}) is True
    assert should_alert({"current_qty": 11, "reorder_point": 10}) is False
    assert should_alert({"current_qty": 10, "reorder_point": 10}) is True


# ── D) real-time fan-out + 24h dedup ────────────────────────────

def test_D_realtime_fanout_and_dedup(tenant_id, admin_user):
    from services.inventory_alerts import (
        check_and_notify_low_stock, seed_chemicals_for_tenant,
    )
    _run(seed_chemicals_for_tenant(tenant_id))
    _sync.inventory_items.update_one(
        {"tenant_id": tenant_id, "sku": "P18-liquid_chlorine"},
        {"$set": {"current_qty": 2.0, "low_stock_notified_at": None}},
    )
    item = _sync.inventory_items.find_one(
        {"tenant_id": tenant_id, "sku": "P18-liquid_chlorine"})

    _sync.inventory_alert_settings.update_one(
        {"tenant_id": tenant_id},
        {"$set": {"tenant_id": tenant_id,
                   "slack_webhook_url": "https://hooks.example/xxx"}},
        upsert=True,
    )
    slack_calls = []

    async def fake_slack(url, payload):
        slack_calls.append({"url": url, "payload": payload})
        return {"ok": True, "status": 200}

    r1 = _run(check_and_notify_low_stock(
        tenant_id, item_ids=[item["id"]],
        source="real_time", slack_post=fake_slack,
    ))
    assert r1["notified"] == 1, r1
    assert r1["slack"]["sent"] is True
    assert len(slack_calls) == 1
    bell = _sync.notifications.count_documents(
        {"tenant_id": tenant_id, "kind": "inventory_low_stock"})
    assert bell >= 1

    r2 = _run(check_and_notify_low_stock(
        tenant_id, item_ids=[item["id"]],
        source="real_time", slack_post=fake_slack,
    ))
    assert r2["notified"] == 0, r2
    assert r2.get("deduped") == 1
    assert len(slack_calls) == 1


# ── E) quiet hours ──────────────────────────────────────────────

def test_E_quiet_hours_defers_realtime(tenant_id, admin_user):
    from services.inventory_alerts import (
        check_and_notify_low_stock, seed_chemicals_for_tenant,
    )
    _run(seed_chemicals_for_tenant(tenant_id))
    _sync.inventory_items.update_one(
        {"tenant_id": tenant_id, "sku": "P18-shock"},
        {"$set": {"current_qty": 0.0, "low_stock_notified_at": None}},
    )
    item = _sync.inventory_items.find_one(
        {"tenant_id": tenant_id, "sku": "P18-shock"})

    hour = datetime.now(timezone.utc).hour
    _sync.inventory_alert_settings.update_one(
        {"tenant_id": tenant_id},
        {"$set": {"tenant_id": tenant_id,
                   "quiet_hours_utc": {"start_hour": hour,
                                        "end_hour": (hour + 2) % 24}}},
        upsert=True,
    )
    slack_calls = []

    async def fake_slack(url, payload):
        slack_calls.append(payload)
        return {"ok": True, "status": 200}

    r_rt = _run(check_and_notify_low_stock(
        tenant_id, item_ids=[item["id"]],
        source="real_time", slack_post=fake_slack,
    ))
    assert r_rt["deferred_quiet_hours"] is True
    assert r_rt["notified"] == 0

    r_cron = _run(check_and_notify_low_stock(
        tenant_id, item_ids=[item["id"]],
        source="cron", slack_post=fake_slack,
    ))
    assert r_cron["notified"] == 1


# ── F) cost report RBAC ─────────────────────────────────────────

def test_F_cost_report_rbac(tenant_id, admin_user, tech_user):
    r_admin = requests.get(
        f"{API}/reports/chemical-costs",
        headers={"Authorization": f"Bearer {admin_user['token']}",
                 "X-Tenant-Id": tenant_id},
    )
    assert r_admin.status_code == 200, r_admin.text
    body = r_admin.json()
    assert "totals" in body
    assert "per_tech" in body
    assert "per_department" in body

    r_tech = requests.get(
        f"{API}/reports/chemical-costs",
        headers={"Authorization": f"Bearer {tech_user['token']}",
                 "X-Tenant-Id": tenant_id},
    )
    assert r_tech.status_code == 403, r_tech.text


# ── G) cost report aggregation ──────────────────────────────────

def test_G_cost_report_aggregation(tenant_id, admin_user, tech_user):
    from services.inventory_alerts import seed_chemicals_for_tenant
    _run(seed_chemicals_for_tenant(tenant_id))
    when = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    for ev in [
        {"product_slug": "liquid_chlorine", "name": "Liquid Chlorine",
         "quantity_used": 5.0, "unit": "gal",
         "unit_cost_at_time_cents": 450, "total_cost_cents": 2250},
        {"product_slug": "liquid_chlorine", "name": "Liquid Chlorine",
         "quantity_used": 3.0, "unit": "gal",
         "unit_cost_at_time_cents": 450, "total_cost_cents": 1350},
        {"product_slug": "shock", "name": "Cal-Hypo Shock",
         "quantity_used": 2.0, "unit": "lbs",
         "unit_cost_at_time_cents": 350, "total_cost_cents": 700},
    ]:
        _sync.chemical_usage_events.insert_one({
            "id": _new_id(),
            "tenant_id": tenant_id,
            "job_id": "j1", "service_report_id": "sr1",
            "customer_id": "c1",
            "occurred_at": when, "created_at": when,
            "created_by": tech_user["id"],
            **ev,
        })
    r = requests.get(
        f"{API}/reports/chemical-costs",
        headers={"Authorization": f"Bearer {admin_user['token']}",
                 "X-Tenant-Id": tenant_id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totals"]["total_cost_cents"] == 2250 + 1350 + 700
    assert body["totals"]["event_count"] == 3
    tech_row = next(t for t in body["per_tech"]
                    if t["user_id"] == tech_user["id"])
    assert tech_row["total_cost_cents"] == 4300
    lc = next(p for p in body["per_product"]
              if p["product_slug"] == "liquid_chlorine")
    assert lc["quantity_used"] == 8.0
    assert lc["total_cost_cents"] == 3600
    pool = next(d for d in body["per_department"]
                if d["department"] == "pool")
    assert pool["event_count"] == 3


# ── H) mobile my-inventory hides costs ──────────────────────────

def test_H_my_inventory_never_exposes_costs(tenant_id, tech_user):
    from services.inventory_alerts import seed_chemicals_for_tenant
    _run(seed_chemicals_for_tenant(tenant_id))
    _sync.inventory_items.update_one(
        {"tenant_id": tenant_id, "sku": "P18-liquid_chlorine"},
        {"$set": {"unit_cost": 4.50, "current_qty": 5.0}},
    )
    r = requests.get(
        f"{API}/inventory/my-inventory",
        headers={"Authorization": f"Bearer {tech_user['token']}",
                 "X-Tenant-Id": tenant_id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    for it in body["items"]:
        assert "unit_cost" not in it, (
            f"item leaked unit_cost: {it}")
        assert "cost_per_unit_cents" not in it
    lc = next(i for i in body["items"] if i["sku"] == "P18-liquid_chlorine")
    assert lc["low_stock"] is True
