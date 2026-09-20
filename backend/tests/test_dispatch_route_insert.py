"""Phase 4 · pytest — Drag-drop / auto-insert unscheduled job.

Covers acceptance criteria 1-6:
  1. Cheapest-position math on a deterministic 3-existing-job layout.
  2. Empty-route insert lands at index 0 with added_km == d(origin, new).
  3. Missing-coords job → 422, DB unchanged.
  4. Already-scheduled job → 409, no duplicate write.
  5. Role gate: tech + customer → 403.
  6. Cross-tenant job_id → 404.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _tenant_of(email: str) -> str:
    return _sync.users.find_one({"email": email})["tenant_id"]


def _tech_id() -> str:
    return _sync.users.find_one({"email": "landscaper@aquaterra.com"})["id"]


# ─────────────────────────────────────────────────────────────────
# 1. Cheapest-position math (deterministic 3-job seed).
#
# Route + origin (home_base = 33.5, -112.0) with 3 existing stops:
#   E0 = (33.55, -112.0)   ← very close to origin
#   E1 = (33.60, -112.0)   ← 5km further N
#   E2 = (33.70, -112.0)   ← 11km further N
#
# NEW = (33.575, -112.0) — geographically between E0 and E1.
# Best slot = insert at index 1 (between E0 and E1), added ≈ 0.
# ─────────────────────────────────────────────────────────────────
def _seed_insert() -> dict:
    tenant_id = _tenant_of("manager@aquaterra.com")
    tech = _tech_id()
    date = "2026-12-01"
    marker = f"TEST_p4_{uuid.uuid4().hex[:6]}"

    _sync.users.update_one({"id": tech},
                            {"$set": {"home_base_lat": 33.5,
                                       "home_base_lon": -112.0}})
    existing = [("E0", 33.55, -112.0), ("E1", 33.60, -112.0),
                 ("E2", 33.70, -112.0)]
    for i, (lbl, lat, lon) in enumerate(existing):
        _sync.jobs.insert_one({
            "id": f"{marker}_{lbl}",
            "tenant_id": tenant_id,
            "customer_id": None,
            "tech_user_id": tech,
            "assigned_to": tech,
            "scheduled_date": date,
            "route_index": i,
            "lat": lat, "lon": lon,
            "address": f"seed-{lbl}",
        })
    # NEW = unscheduled between E0 and E1.
    new_id = f"{marker}_NEW"
    _sync.jobs.insert_one({
        "id": new_id,
        "tenant_id": tenant_id,
        "customer_id": None,
        "scheduled_date": None,
        "tech_user_id": None,
        "assigned_to": None,
        "technician_id": None,
        "lat": 33.575, "lon": -112.0,
        "address": "new-drop",
        "title": "Auto-insert probe",
    })
    return {"marker": marker, "date": date, "tech": tech,
             "tenant": tenant_id, "new_id": new_id,
             "existing_ids": [f"{marker}_{lbl}" for lbl, _, _ in existing]}


def _cleanup(marker: str) -> None:
    _sync.jobs.delete_many({"id": {"$regex": f"^{marker}"}})


# ── 1. Cheapest slot math ─────────────────────────────────────────
def test_cheapest_slot_between_existing_stops():
    seed = _seed_insert()
    try:
        tok = _login("manager@aquaterra.com")
        r = requests.post(f"{API}/dispatch/route/insert",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={"tech_user_id": seed["tech"],
                                  "route_date": seed["date"],
                                  "job_id": seed["new_id"]}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["inserted_at"] == 1, d
        assert d["total_stops"] == 4
        # Added distance for slot 1 between E0 and E1 is essentially 0
        # (new is exactly between them on the same meridian).
        assert d["added_distance_km"] < 0.01, d["added_distance_km"]

        # Persistence: new job has route_index 1, E1/E2 shifted to 2/3.
        docs = list(_sync.jobs.find(
            {"id": {"$in": [seed["new_id"]] + seed["existing_ids"]}},
            {"_id": 0, "id": 1, "route_index": 1, "scheduled_date": 1,
              "tech_user_id": 1, "technician_id": 1},
        ).sort("route_index", 1))
        got = [(x["id"], x["route_index"]) for x in docs]
        assert got == [
            (f"{seed['marker']}_E0", 0),
            (seed["new_id"], 1),
            (f"{seed['marker']}_E1", 2),
            (f"{seed['marker']}_E2", 3),
        ], got
        # The dropped job now has tech + date set.
        new_doc = _sync.jobs.find_one({"id": seed["new_id"]})
        assert new_doc["tech_user_id"] == seed["tech"]
        assert new_doc["scheduled_date"] == seed["date"]
    finally:
        _cleanup(seed["marker"])


# ── 2. Empty route → index 0, added_km == d(origin, new) ──────────
def test_empty_route_insert_lands_at_zero():
    tenant_id = _tenant_of("manager@aquaterra.com")
    tech = _tech_id()
    date = "2026-12-02"
    marker = f"TEST_p4e_{uuid.uuid4().hex[:6]}"
    _sync.users.update_one({"id": tech},
                            {"$set": {"home_base_lat": 33.5,
                                       "home_base_lon": -112.0}})
    new_id = f"{marker}_NEW"
    _sync.jobs.insert_one({
        "id": new_id, "tenant_id": tenant_id,
        "scheduled_date": None,
        "tech_user_id": None, "assigned_to": None, "technician_id": None,
        "lat": 33.6, "lon": -112.0, "address": "empty-route-drop",
    })
    try:
        tok = _login("manager@aquaterra.com")
        r = requests.post(f"{API}/dispatch/route/insert",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={"tech_user_id": tech,
                                  "route_date": date,
                                  "job_id": new_id}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["inserted_at"] == 0
        assert d["total_stops"] == 1
        # Origin=(33.5,-112.0), new=(33.6,-112.0) → ~11.12 km.
        assert 10.5 < d["added_distance_km"] < 11.5, d["added_distance_km"]
    finally:
        _cleanup(marker)


# ── 3. Missing-coords → 422; DB unchanged ─────────────────────────
def test_missing_coords_returns_422_and_no_write():
    tenant_id = _tenant_of("manager@aquaterra.com")
    tech = _tech_id()
    marker = f"TEST_p4m_{uuid.uuid4().hex[:6]}"
    new_id = f"{marker}_NEW"
    _sync.jobs.insert_one({
        "id": new_id, "tenant_id": tenant_id,
        "scheduled_date": None,
        "tech_user_id": None, "assigned_to": None, "technician_id": None,
        "address": "no coords here",
        # No lat/lon; no customer_id.
    })
    try:
        tok = _login("manager@aquaterra.com")
        r = requests.post(f"{API}/dispatch/route/insert",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={"tech_user_id": tech,
                                  "route_date": "2026-12-03",
                                  "job_id": new_id}, timeout=10)
        assert r.status_code == 422, r.text
        assert r.json()["detail"] == "job_missing_coords"
        # DB must be untouched.
        doc = _sync.jobs.find_one({"id": new_id})
        assert doc.get("tech_user_id") is None
        assert doc.get("scheduled_date") in (None, "", False)
        assert doc.get("route_index") is None
    finally:
        _cleanup(marker)


# ── 4. Already-scheduled → 409; no duplicate write ────────────────
def test_already_scheduled_returns_409():
    tenant_id = _tenant_of("manager@aquaterra.com")
    tech = _tech_id()
    marker = f"TEST_p4s_{uuid.uuid4().hex[:6]}"
    new_id = f"{marker}_NEW"
    _sync.jobs.insert_one({
        "id": new_id, "tenant_id": tenant_id,
        "scheduled_date": "2026-12-04",
        "tech_user_id": tech, "route_index": 0,
        "lat": 33.5, "lon": -112.0, "address": "already scheduled",
    })
    try:
        tok = _login("manager@aquaterra.com")
        r = requests.post(f"{API}/dispatch/route/insert",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={"tech_user_id": tech,
                                  "route_date": "2026-12-04",
                                  "job_id": new_id}, timeout=10)
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == "job_already_scheduled"
        n = _sync.jobs.count_documents({"id": new_id})
        assert n == 1
    finally:
        _cleanup(marker)


# ── 5. Role gate ──────────────────────────────────────────────────
def test_role_gate_tech_and_customer_forbidden():
    body = {"tech_user_id": "x", "route_date": "2026-12-05", "job_id": "y"}
    for email in ("landscaper@aquaterra.com", "customer@aquaterra.com"):
        tok = _login(email)
        r = requests.post(f"{API}/dispatch/route/insert",
                           headers={"Authorization": f"Bearer {tok}"},
                           json=body, timeout=10)
        assert r.status_code == 403, f"{email} insert → {r.status_code}"


# ── 6. Cross-tenant job → 404 ─────────────────────────────────────
def test_cross_tenant_job_returns_404():
    # Seed a job in NO tenant (fake tenant_id) — manager must not see it.
    fake_tenant = f"tenant_p4_{uuid.uuid4().hex[:6]}"
    new_id = f"TEST_p4x_{uuid.uuid4().hex[:6]}_NEW"
    _sync.jobs.insert_one({
        "id": new_id, "tenant_id": fake_tenant,
        "scheduled_date": None,
        "tech_user_id": None, "lat": 33.5, "lon": -112.0,
        "address": "other-tenant",
    })
    try:
        tok = _login("manager@aquaterra.com")
        r = requests.post(f"{API}/dispatch/route/insert",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={"tech_user_id": "any",
                                  "route_date": "2026-12-05",
                                  "job_id": new_id}, timeout=10)
        assert r.status_code == 404, r.text
    finally:
        _sync.jobs.delete_one({"id": new_id})



# ── 7. Unscheduled Jobs panel filter (Phase 4 fold-in) ────────────
#
# User clarification (Feb 2026): the Dispatch → Unscheduled Jobs
# panel must ONLY show jobs with NO tech and NO crew and NO
# scheduled_date. Both one-time and recurring jobs qualify — the
# filter is on assignment, not job type.
def _seed_unscheduled_variants() -> dict:
    tenant_id = _tenant_of("manager@aquaterra.com")
    tech = _tech_id()
    marker = f"TEST_p4u_{uuid.uuid4().hex[:6]}"

    # a. Fully unscheduled one-time → SHOULD appear.
    a_id = f"{marker}_A_oneoff"
    _sync.jobs.insert_one({
        "id": a_id, "tenant_id": tenant_id,
        "scheduled_date": None, "tech_user_id": None, "assigned_to": None,
        "technician_id": None, "crew_id": None,
        "lat": 33.5, "lon": -112.0, "address": "unassigned one-off",
        "title": "One-off unassigned",
    })
    # b. Fully unscheduled recurring instance → SHOULD appear.
    b_id = f"{marker}_B_recurring"
    _sync.jobs.insert_one({
        "id": b_id, "tenant_id": tenant_id,
        "scheduled_date": None, "tech_user_id": None, "assigned_to": None,
        "technician_id": None, "crew_id": None,
        "recurring_template_id": "tmpl_x", "lat": 33.5, "lon": -112.0,
        "address": "unassigned recurring", "title": "Recurring unassigned",
    })
    # c. Has technician_id → MUST be filtered out.
    c_id = f"{marker}_C_hasTech"
    _sync.jobs.insert_one({
        "id": c_id, "tenant_id": tenant_id,
        "scheduled_date": None, "technician_id": tech,
        "crew_id": None,
        "lat": 33.5, "lon": -112.0, "address": "has-tech-no-date",
        "title": "Tech-assigned no date",
    })
    # d. Has crew_id → MUST be filtered out (new Phase 4 rule).
    d_id = f"{marker}_D_hasCrew"
    _sync.jobs.insert_one({
        "id": d_id, "tenant_id": tenant_id,
        "scheduled_date": None, "tech_user_id": None, "technician_id": None,
        "assigned_to": None, "crew_id": "crew-abc",
        "lat": 33.5, "lon": -112.0, "address": "has-crew-no-date",
        "title": "Crew-assigned no date",
    })
    # e. Has scheduled_date → MUST be filtered out.
    e_id = f"{marker}_E_hasDate"
    _sync.jobs.insert_one({
        "id": e_id, "tenant_id": tenant_id,
        "scheduled_date": "2026-12-10",
        "tech_user_id": None, "technician_id": None, "crew_id": None,
        "lat": 33.5, "lon": -112.0, "address": "has-date-no-assign",
        "title": "Dated but unassigned",
    })
    return {"marker": marker,
             "a_id": a_id, "b_id": b_id, "c_id": c_id,
             "d_id": d_id, "e_id": e_id}


def test_unscheduled_panel_lists_only_unassigned_undated_jobs():
    seed = _seed_unscheduled_variants()
    try:
        tok = _login("manager@aquaterra.com")
        r = requests.get(f"{API}/dispatch/route/unscheduled-jobs",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=10)
        assert r.status_code == 200, r.text
        ids = {it["id"] for it in r.json()["items"]}
        # a + b (recurring) must appear.
        assert seed["a_id"] in ids, (
            f"one-off unassigned missing: {ids}")
        assert seed["b_id"] in ids, (
            f"recurring unassigned missing: {ids}")
        # c (tech), d (crew), e (dated) must NOT appear.
        assert seed["c_id"] not in ids, (
            f"tech-assigned leaked into unscheduled: {seed['c_id']}")
        assert seed["d_id"] not in ids, (
            f"crew-assigned leaked into unscheduled: {seed['d_id']}")
        assert seed["e_id"] not in ids, (
            f"dated leaked into unscheduled: {seed['e_id']}")
    finally:
        _cleanup(seed["marker"])
