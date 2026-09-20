"""Phase 10 · sub-item E — Batch preview-insert."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"


def _login(email):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=10)
    return r.json()["access_token"]


def _tid():
    return _sync.users.find_one({"email": "manager@aquaterra.com"})["tenant_id"]


def _seed_route(tid, tech_id, date_str, coords_list):
    """coords_list = [(lat, lon), ...] in route order. Returns [job_id]."""
    ids = []
    for i, (lat, lon) in enumerate(coords_list):
        jid = f"jseed_{uuid.uuid4().hex[:10]}"
        _sync.jobs.insert_one({
            "id": jid, "tenant_id": tid, "title": f"Seed job {i}",
            "address": f"seed {i}", "tech_user_id": tech_id,
            "technician_id": tech_id, "scheduled_date": date_str,
            "route_index": i, "lat": lat, "lon": lon})
        ids.append(jid)
    return ids


def _seed_candidate(tid, coords):
    jid = f"jcand_{uuid.uuid4().hex[:10]}"
    doc = {"id": jid, "tenant_id": tid, "title": "cand",
            "address": "cand"}
    if coords:
        doc["lat"] = coords[0]; doc["lon"] = coords[1]
    _sync.jobs.insert_one(doc)
    return jid


# ── 1. Batch preview returns per-job added_km on a deterministic seed ─
def test_batch_preview_returns_added_km():
    tid = _tid()
    tok = _login("manager@aquaterra.com")
    tech = "tech_p10e_a"
    date_str = "2026-07-30"
    _sync.jobs.delete_many({"tenant_id": tid,
                              "id": {"$regex": "^jseed_|^jcand_"}})
    _sync.users.update_one(
        {"id": tech, "tenant_id": tid},
        {"$set": {"id": tech, "tenant_id": tid,
                    "role": "tech", "email": f"{tech}@aquaterra.com",
                    "home_base_lat": 33.7, "home_base_lon": -112.2}},
        upsert=True)
    route_ids = _seed_route(tid, tech, date_str,
                                [(33.71, -112.20), (33.72, -112.19),
                                  (33.73, -112.18)])
    near = _seed_candidate(tid, (33.735, -112.175))  # close to end
    far = _seed_candidate(tid, (33.80, -111.50))     # far
    r = requests.post(f"{API}/dispatch/route/preview-insert-batch",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"tech_user_id": tech, "route_date": date_str,
                              "job_ids": [near, far]}, timeout=10)
    assert r.status_code == 200, r.text
    prevs = {p["job_id"]: p for p in r.json()["previews"]}
    assert prevs[near]["currently_missing_coords"] is False
    assert prevs[far]["currently_missing_coords"] is False
    assert prevs[near]["added_distance_km"] < prevs[far]["added_distance_km"]
    assert prevs[near]["added_distance_km"] >= 0
    # Cleanup.
    _sync.jobs.delete_many({"id": {"$in": route_ids + [near, far]}})


# ── 2. Missing-coords → null + flag ───────────────────────────────
def test_missing_coords_returns_null_and_flag():
    tid = _tid()
    tok = _login("manager@aquaterra.com")
    tech = "tech_p10e_b"
    date_str = "2026-07-30"
    _sync.jobs.delete_many({"tenant_id": tid,
                              "id": {"$regex": "^jseed_|^jcand_"}})
    _sync.users.update_one(
        {"id": tech, "tenant_id": tid},
        {"$set": {"id": tech, "tenant_id": tid, "role": "tech",
                    "email": f"{tech}@aquaterra.com",
                    "home_base_lat": 33.7, "home_base_lon": -112.2}},
        upsert=True)
    route_ids = _seed_route(tid, tech, date_str, [(33.71, -112.20)])
    no_coords = _seed_candidate(tid, None)
    r = requests.post(f"{API}/dispatch/route/preview-insert-batch",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"tech_user_id": tech, "route_date": date_str,
                              "job_ids": [no_coords]}, timeout=10)
    assert r.status_code == 200
    p = r.json()["previews"][0]
    assert p["job_id"] == no_coords
    assert p["added_distance_km"] is None
    assert p["currently_missing_coords"] is True
    _sync.jobs.delete_many({"id": {"$in": route_ids + [no_coords]}})


# ── 3. Role guard: tech + customer → 403 ──────────────────────────
def test_preview_batch_role_guard():
    for email in ("landscaper@aquaterra.com", "customer@aquaterra.com"):
        tok = _login(email)
        h = {"Authorization": f"Bearer {tok}"}
        r = requests.post(f"{API}/dispatch/route/preview-insert-batch",
                           headers=h,
                           json={"tech_user_id": "any", "route_date": "2026-07-30",
                                  "job_ids": []}, timeout=10)
        assert r.status_code == 403, f"{email}: {r.status_code} {r.text}"


# ── 4. Unknown job_id → treated as missing_coords ─────────────────
def test_unknown_job_id_treated_as_missing():
    tid = _tid()
    tok = _login("manager@aquaterra.com")
    r = requests.post(f"{API}/dispatch/route/preview-insert-batch",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"tech_user_id": "tech_none",
                              "route_date": "2026-07-30",
                              "job_ids": [f"missing_{uuid.uuid4().hex[:10]}"]},
                       timeout=10)
    assert r.status_code == 200
    p = r.json()["previews"][0]
    assert p["added_distance_km"] is None
    assert p["currently_missing_coords"] is True
