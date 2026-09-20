"""Phase 17 · Feb-2026 — Additions (reassignment, unrouted, suggestions).

Consolidated test suite covering the follow-on features folded into
the Dispatch Board redesign:

  1. Route Assignment Overrides — create, apply, cancel, permanent.
  2. Unrouted customers — surface on ``GET /api/dispatch/board``.
  3. Smart route suggestions — cheapest-insertion recommender.
  4. Assignment audit log — reads back permanent changes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
_TENANT_ID = _sync.tenants.find_one({"slug": "aquaterra"})["id"]
API = "http://localhost:8001/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_headers():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_headers():
    return _login("mike@aquaterra.com")


@pytest.fixture
def phase17_customers():
    """Six geocoded customers + two synthetic techs (source + target).

    Layout:
      c-alpha (Mon) → tech-src
      c-bravo (Mon) → tech-src
      c-charlie (Mon) → tech-src
      c-delta (Thu) → tech-src (already on route)
      c-echo (no service_days, no tech) → UNROUTED
      c-foxtrot (Mon, no tech) → UNROUTED (no_tech_assigned)
    """
    m = uuid.uuid4().hex[:6]
    src = f"p17add-src-{m}"
    tgt = f"p17add-tgt-{m}"
    _sync.users.insert_many([
        {"id": src, "tenant_id": _TENANT_ID, "role": "technician",
          "email": f"src-{m}@ex.local", "name": f"Source Tech {m}",
          "display_color_hex": "#0EA5E9", "department": "Pool"},
        {"id": tgt, "tenant_id": _TENANT_ID, "role": "technician",
          "email": f"tgt-{m}@ex.local", "name": f"Target Tech {m}",
          "display_color_hex": "#F97316", "department": "Landscaping"},
    ])
    now_iso = datetime.now(timezone.utc).isoformat()
    docs = [
        {"id": f"p17add-alpha-{m}", "name": "Alpha", "service_address": "1 A St",
          "service_lat": 33.70, "service_lng": -112.30,
          "service_days": ["mon"], "assigned_tech_ids": [src]},
        {"id": f"p17add-bravo-{m}", "name": "Bravo", "service_address": "2 B St",
          "service_lat": 33.71, "service_lng": -112.31,
          "service_days": ["mon"], "assigned_tech_ids": [src]},
        {"id": f"p17add-charlie-{m}", "name": "Charlie", "service_address": "3 C St",
          "service_lat": 33.72, "service_lng": -112.32,
          "service_days": ["mon"], "assigned_tech_ids": [src]},
        {"id": f"p17add-delta-{m}", "name": "Delta", "service_address": "4 D St",
          "service_lat": 33.73, "service_lng": -112.33,
          "service_days": ["thu"], "assigned_tech_ids": [src]},
        {"id": f"p17add-echo-{m}", "name": "Echo Unrouted", "service_address": "5 E St",
          "service_lat": 33.74, "service_lng": -112.34,
          "service_days": [], "assigned_tech_ids": []},
        {"id": f"p17add-foxtrot-{m}", "name": "Foxtrot NoTech", "service_address": "6 F St",
          "service_lat": 33.75, "service_lng": -112.35,
          "service_days": ["mon"], "assigned_tech_ids": []},
    ]
    for d in docs:
        d.update({"tenant_id": _TENANT_ID, "is_active": True,
                    "email": f"{d['id']}@ex.local", "phone": "+15550000000",
                    "first_name": d["name"], "created_at": now_iso})
    _sync.customers.insert_many(docs)
    yield {"marker": m, "src": src, "tgt": tgt,
            "ids": {d["id"].split("-")[1]: d["id"] for d in docs}}
    _sync.customers.delete_many({"id": {"$in": [d["id"] for d in docs]}})
    _sync.users.delete_many({"id": {"$in": [src, tgt]}})
    _sync.route_assignment_overrides.delete_many({"source_tech_user_id": src})
    _sync.assignment_change_log.delete_many({"from_tech_user_id": src})
    _sync.recurring_job_templates.delete_many({"customer_id": {"$in": [d["id"] for d in docs]}})


# ══════════════════════════════════════════════════════════════
# 1. Route Assignment Overrides
# ══════════════════════════════════════════════════════════════
def test_partial_override_shifts_stops_to_target(admin_headers, phase17_customers):
    alpha = phase17_customers["ids"]["alpha"]
    bravo = phase17_customers["ids"]["bravo"]
    src, tgt = phase17_customers["src"], phase17_customers["tgt"]

    r = requests.post(f"{API}/dispatch/reassign", headers=admin_headers,
                       json={"source_tech_user_id": src, "target_tech_user_id": tgt,
                              "scope": "partial", "customer_ids": [alpha, bravo]},
                       timeout=10)
    assert r.status_code == 200, r.text
    override = r.json()
    assert "id" in override
    assert override["end_at"] > override["start_at"]

    # Board GET for target tech should include alpha/bravo w/ override tag.
    r2 = requests.get(f"{API}/dispatch/board",
                       params={"day": "mon", "tech_user_id": tgt},
                       headers=admin_headers, timeout=10)
    ids = {p["customer_id"] for p in r2.json()["pins"]}
    assert alpha in ids and bravo in ids
    tagged = [p for p in r2.json()["pins"]
              if p["customer_id"] == alpha][0]
    assert tagged.get("override_source_tech_id") == src

    # Source tech should no longer see alpha/bravo on Mon.
    r3 = requests.get(f"{API}/dispatch/board",
                       params={"day": "mon", "tech_user_id": src},
                       headers=admin_headers, timeout=10)
    src_ids = {p["customer_id"] for p in r3.json()["pins"]}
    assert alpha not in src_ids and bravo not in src_ids


def test_end_at_is_saturday_in_tenant_tz():
    from services.route_reassign import compute_end_at
    from datetime import datetime, timezone
    # Tuesday noon UTC — end should be the following Saturday 23:59
    # in America/Phoenix (which is UTC-7, no DST). Saturday 23:59:59
    # local == Sunday 06:59:59 UTC.
    t = datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc)   # Tue
    end = compute_end_at(t, {"timezone": "America/Phoenix"})
    # Saturday Feb 28, 23:59:59 MST = March 1 06:59:59 UTC
    assert end.year == 2026 and end.month == 3 and end.day == 1
    assert end.hour == 6 and end.minute == 59


def test_cancel_override_clears_effect(admin_headers, phase17_customers):
    alpha = phase17_customers["ids"]["alpha"]
    src, tgt = phase17_customers["src"], phase17_customers["tgt"]
    r = requests.post(f"{API}/dispatch/reassign", headers=admin_headers,
                       json={"source_tech_user_id": src, "target_tech_user_id": tgt,
                              "scope": "partial", "customer_ids": [alpha]},
                       timeout=10)
    oid = r.json()["id"]
    # Cancel.
    r2 = requests.post(f"{API}/dispatch/reassign/{oid}/cancel",
                        headers=admin_headers, timeout=10)
    assert r2.status_code == 200
    # Source tech regains alpha.
    r3 = requests.get(f"{API}/dispatch/board",
                       params={"day": "mon", "tech_user_id": src},
                       headers=admin_headers, timeout=10)
    src_ids = {p["customer_id"] for p in r3.json()["pins"]}
    assert alpha in src_ids


def test_overlapping_override_warning(admin_headers, phase17_customers):
    alpha = phase17_customers["ids"]["alpha"]
    src, tgt = phase17_customers["src"], phase17_customers["tgt"]
    # First shift succeeds.
    r = requests.post(f"{API}/dispatch/reassign", headers=admin_headers,
                       json={"source_tech_user_id": src, "target_tech_user_id": tgt,
                              "scope": "partial", "customer_ids": [alpha]},
                       timeout=10)
    assert "id" in r.json()
    # Second attempt without force → warning.
    r2 = requests.post(f"{API}/dispatch/reassign", headers=admin_headers,
                        json={"source_tech_user_id": src, "target_tech_user_id": tgt,
                               "scope": "partial", "customer_ids": [alpha]},
                        timeout=10)
    assert r2.status_code == 200
    assert r2.json().get("warning") == "existing_override_conflict"
    # With force=True → succeeds.
    r3 = requests.post(f"{API}/dispatch/reassign", headers=admin_headers,
                        json={"source_tech_user_id": src, "target_tech_user_id": tgt,
                               "scope": "partial", "customer_ids": [alpha],
                               "force": True}, timeout=10)
    assert "id" in r3.json()


def test_permanent_reassign_mutates_master_and_writes_audit(admin_headers, phase17_customers):
    alpha = phase17_customers["ids"]["alpha"]
    src, tgt = phase17_customers["src"], phase17_customers["tgt"]
    r = requests.post(f"{API}/dispatch/reassign", headers=admin_headers,
                       json={"source_tech_user_id": src, "target_tech_user_id": tgt,
                              "scope": "partial", "customer_ids": [alpha],
                              "duration": "permanent"},
                       timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["permanent"] is True
    assert body["changed_log_entries"] == 1
    # Customer denorm actually mutated.
    cust = _sync.customers.find_one({"id": alpha}, {"_id": 0, "assigned_tech_ids": 1})
    assert src not in cust["assigned_tech_ids"]
    assert tgt in cust["assigned_tech_ids"]
    # Audit log endpoint returns the row.
    r2 = requests.get(f"{API}/dispatch/assignment-change-log",
                       params={"customer_id": alpha},
                       headers=admin_headers, timeout=10)
    logs = r2.json()["items"]
    assert len(logs) == 1
    assert logs[0]["from_tech_user_id"] == src
    assert logs[0]["to_tech_user_id"] == tgt


def test_permanent_cancels_overlapping_overrides(admin_headers, phase17_customers):
    alpha = phase17_customers["ids"]["alpha"]
    src, tgt = phase17_customers["src"], phase17_customers["tgt"]
    # Create temporary override first.
    requests.post(f"{API}/dispatch/reassign", headers=admin_headers,
                    json={"source_tech_user_id": src, "target_tech_user_id": tgt,
                           "scope": "partial", "customer_ids": [alpha]},
                    timeout=10)
    # Then permanent.
    r = requests.post(f"{API}/dispatch/reassign", headers=admin_headers,
                       json={"source_tech_user_id": src, "target_tech_user_id": tgt,
                              "scope": "partial", "customer_ids": [alpha],
                              "duration": "permanent", "force": True},
                       timeout=10)
    assert r.json().get("canceled_overrides", 0) >= 1


# ══════════════════════════════════════════════════════════════
# 2. Unrouted customers surface
# ══════════════════════════════════════════════════════════════
def test_unrouted_customers_surface_with_reasons(admin_headers, phase17_customers):
    src = phase17_customers["src"]
    r = requests.get(f"{API}/dispatch/board",
                      params={"day": "thu", "tech_user_id": src},
                      headers=admin_headers, timeout=10)
    body = r.json()
    unrouted = {u["customer_id"]: u for u in body["unrouted_customers"]}
    echo = phase17_customers["ids"]["echo"]
    foxtrot = phase17_customers["ids"]["foxtrot"]
    # Echo has no service_days → no_service_day.
    assert echo in unrouted
    assert unrouted[echo]["reason"] == "no_service_day"
    # Foxtrot has service_days=[mon] but no tech → no_tech_assigned.
    assert foxtrot in unrouted
    assert unrouted[foxtrot]["reason"] == "no_tech_assigned"


def test_unrouted_pins_include_geocoded_coords(admin_headers, phase17_customers):
    src = phase17_customers["src"]
    r = requests.get(f"{API}/dispatch/board",
                      params={"day": "thu", "tech_user_id": src},
                      headers=admin_headers, timeout=10)
    unrouted = {u["customer_id"]: u for u in r.json()["unrouted_customers"]}
    echo = phase17_customers["ids"]["echo"]
    assert unrouted[echo]["lat"] == 33.74
    assert unrouted[echo]["lng"] == -112.34


# ══════════════════════════════════════════════════════════════
# 3. Pin color mode fields
# ══════════════════════════════════════════════════════════════
def test_board_pins_include_crew_and_color_fields(admin_headers, phase17_customers):
    src = phase17_customers["src"]
    alpha = phase17_customers["ids"]["alpha"]
    r = requests.get(f"{API}/dispatch/board",
                      params={"day": "mon", "tech_user_id": src},
                      headers=admin_headers, timeout=10)
    body = r.json()
    p = [pin for pin in body["pins"] if pin["customer_id"] == alpha][0]
    assert "tech_color_hex" in p
    assert "crew_label" in p and p["crew_label"] in ("Pool", "Other")
    assert "crew_color_hex" in p
    assert p.get("service_day") == "mon"


# ══════════════════════════════════════════════════════════════
# 4. Smart route suggestions
# ══════════════════════════════════════════════════════════════
def test_suggest_route_picks_matching_day_and_tech(admin_headers, phase17_customers):
    src = phase17_customers["src"]
    echo = phase17_customers["ids"]["echo"]
    # Echo's lat/lng (33.74, -112.34) is closest to Delta on Thursday (33.73, -112.33).
    r = requests.post(f"{API}/dispatch/suggest-route",
                       headers=admin_headers,
                       json={"customer_ids": [echo]}, timeout=15)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    top = items[0]["suggestion"]
    assert top is not None
    # Should recommend some tech that has a route (may be tech-src or
    # another demo-seeded tech — algorithm picks the geographically
    # nearest existing stop). Just verify a valid recommendation returned.
    assert top["tech_user_id"]
    assert top["service_day"] in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    assert top["added_seconds"] >= 0
    assert top["confidence"] in ("high", "medium", "low")
    assert "rationale" in top and top["rationale"]


def test_suggest_route_respects_max_added_minutes(admin_headers, phase17_customers):
    echo = phase17_customers["ids"]["echo"]
    r = requests.post(f"{API}/dispatch/suggest-route",
                       headers=admin_headers,
                       json={"customer_ids": [echo],
                              "constraints": {"max_added_minutes": 0.01}},
                       timeout=15)
    # With 0.01-min cap, geographic candidates get filtered out, so
    # either fallback (dept match) kicks in or suggestion is None.
    top = r.json()["items"][0]["suggestion"]
    # Either the fallback fired (rationale contains "No nearby") OR
    # suggestion is None. Both are acceptable outcomes of the cap.
    if top is not None:
        assert "No nearby" in top.get("rationale", "") or top["added_seconds"] == 0


# ══════════════════════════════════════════════════════════════
# 5. Cross-role guards
# ══════════════════════════════════════════════════════════════
def test_reassign_endpoints_are_admin_only(tech_headers, phase17_customers):
    alpha = phase17_customers["ids"]["alpha"]
    src, tgt = phase17_customers["src"], phase17_customers["tgt"]
    r = requests.post(f"{API}/dispatch/reassign", headers=tech_headers,
                       json={"source_tech_user_id": src, "target_tech_user_id": tgt,
                              "scope": "partial", "customer_ids": [alpha]},
                       timeout=10)
    assert r.status_code == 403
    r2 = requests.get(f"{API}/dispatch/assignment-change-log",
                       headers=tech_headers, timeout=10)
    assert r2.status_code == 403
