"""Phase 3 · pytest — Dispatch route optimizer.

Covers acceptance criteria:
  1. Deterministic 4-point nearest-neighbor correctness.
  2. Apply persists route_index 0..N-1 and is idempotent.
  3. Skipped list populated when a job has no coords.
  4. Role gate: tech + customer → 403 on BOTH endpoints (inherits from
     the include_router() wrap of ``require_gps_read``).
"""
from __future__ import annotations

import os
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


def _seed_layout() -> dict:
    """4 known points around Phoenix. Origin is at (33.5, -112.0).
    A(33.55,-112.0) B(33.6,-112.0) C(33.7,-112.0) D(33.5,-112.2).
    Nearest from origin: A (5.5km lat), then B, then C, then D.
    Any other order costs more."""
    tenant_id = _tenant_of("manager@aquaterra.com")
    tech = _tech_id()
    date = "2026-11-11"
    marker = f"TEST_p3_{uuid.uuid4().hex[:6]}"

    # Give the tech a home_base so origin is deterministic.
    _sync.users.update_one({"id": tech},
                            {"$set": {"home_base_lat": 33.5,
                                       "home_base_lon": -112.0}})

    pts = [("A", 33.55, -112.0), ("B", 33.60, -112.0),
            ("C", 33.70, -112.0), ("D", 33.50, -112.2)]
    ids = []
    for i, (lbl, lat, lon) in enumerate(pts):
        jid = f"{marker}_{lbl}"
        _sync.jobs.insert_one({
            "id": jid,
            "tenant_id": tenant_id,
            "customer_id": None,
            "tech_user_id": tech,
            "assigned_to": tech,
            "scheduled_date": date,
            "route_index": i,  # hand-order = A,B,C,D → optimal already
            "lat": lat, "lon": lon,
            "address": f"seed-{lbl}",
        })
        ids.append(jid)
    return {"marker": marker, "date": date, "tech": tech,
             "tenant": tenant_id, "job_ids": ids}


def _cleanup(marker: str) -> None:
    _sync.jobs.delete_many({"id": {"$regex": f"^{marker}"}})


# ── 1. Nearest-neighbor correctness ───────────────────────────────
def test_nearest_neighbor_correct_on_deterministic_seed():
    seed = _seed_layout()
    try:
        tok = _login("manager@aquaterra.com")
        r = requests.post(f"{API}/dispatch/route/optimize",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={"tech_user_id": seed["tech"],
                                  "route_date": seed["date"]}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["origin"]["source"] == "home_base"
        assert d["origin"]["lat"] == 33.5 and d["origin"]["lon"] == -112.0
        # Order must be A, B, C, D (nearest-then-next).
        order = [x["job_id"] for x in d["ordered_jobs"]]
        assert order == [f"{seed['marker']}_{k}" for k in ["A","B","C","D"]], order
        assert d["total_distance_km"] > 0
        # Optimal happens to equal hand-order here, savings ≈ 0.
        assert abs(d["savings_km"]) < 0.01
    finally:
        _cleanup(seed["marker"])


# ── 2. Skipped list populated when no coords resolvable ───────────
def test_skipped_list_for_jobs_without_coords():
    seed = _seed_layout()
    # Add a fifth job with NO lat/lon and NO customer_id.
    _sync.jobs.insert_one({
        "id": f"{seed['marker']}_E_nocoords",
        "tenant_id": seed["tenant"],
        "tech_user_id": seed["tech"], "assigned_to": seed["tech"],
        "scheduled_date": seed["date"], "route_index": 4,
        "address": "no coords",
    })
    try:
        tok = _login("manager@aquaterra.com")
        r = requests.post(f"{API}/dispatch/route/optimize",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={"tech_user_id": seed["tech"],
                                  "route_date": seed["date"]}, timeout=10)
        assert r.status_code == 200
        d = r.json()
        skipped_ids = [s["job_id"] for s in d["skipped"]]
        assert f"{seed['marker']}_E_nocoords" in skipped_ids
        # Only 4 in the tour, not 5.
        assert len(d["ordered_jobs"]) == 4
    finally:
        _cleanup(seed["marker"])


# ── 3. Apply persists route_index 0..N-1; second call idempotent ──
def test_apply_persists_and_is_idempotent():
    seed = _seed_layout()
    try:
        tok = _login("manager@aquaterra.com")
        # Reverse the order to prove indices are re-written.
        new_order = list(reversed(seed["job_ids"]))
        r = requests.post(f"{API}/dispatch/route/apply",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={"tech_user_id": seed["tech"],
                                  "route_date": seed["date"],
                                  "ordered_job_ids": new_order}, timeout=10)
        assert r.status_code == 200 and r.json()["updated"] == 4

        # Verify persistence: index 0 == last of original.
        docs = list(_sync.jobs.find(
            {"id": {"$in": seed["job_ids"]}},
            {"_id": 0, "id": 1, "route_index": 1}).sort("route_index", 1))
        got = [d["id"] for d in docs]
        assert got == new_order, got

        # Second identical call → still updated=4 (matched_count), no dupes.
        r = requests.post(f"{API}/dispatch/route/apply",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={"tech_user_id": seed["tech"],
                                  "route_date": seed["date"],
                                  "ordered_job_ids": new_order}, timeout=10)
        assert r.status_code == 200 and r.json()["updated"] == 4
        n = _sync.jobs.count_documents(
            {"id": {"$in": seed["job_ids"]}})
        assert n == 4  # no new docs written
    finally:
        _cleanup(seed["marker"])


# ── 4. Role gate ─────────────────────────────────────────────────
def test_tech_and_customer_forbidden():
    body = {"tech_user_id": "x", "route_date": "2026-11-11"}
    for email in ("landscaper@aquaterra.com", "customer@aquaterra.com"):
        tok = _login(email)
        r = requests.post(f"{API}/dispatch/route/optimize",
                           headers={"Authorization": f"Bearer {tok}"},
                           json=body, timeout=10)
        assert r.status_code == 403, f"{email} optimize → {r.status_code}"
        r = requests.post(f"{API}/dispatch/route/apply",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={**body, "ordered_job_ids": []}, timeout=10)
        assert r.status_code == 403, f"{email} apply → {r.status_code}"
