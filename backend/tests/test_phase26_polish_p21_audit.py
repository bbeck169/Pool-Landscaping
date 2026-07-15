"""Phase 26 skill-matching enhancement + Phase 21 estimator SDK audit."""
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


def _login(e, pw="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": e, "password": pw},
                       timeout=15)
    r.raise_for_status(); return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(_BE["MONGO_URL"])[_BE["DB_NAME"]]

@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}


# ═══════════ Phase 26 · Skill-matching scenarios ═══════════════════════

def _make_scenario(dbc, techs_config, new_job_service_type,
                     job_coords=(33.60, -112.10)):
    """techs_config: list of dicts {name, coords_of_stop_today_or_None,
       preferred_service_types}."""
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    tenant_id = t["id"]
    today = time.strftime("%Y-%m-%d")
    tag = f"skill-{int(time.time() * 1000) % 100000000}"
    tech_ids = []
    for i, c in enumerate(techs_config):
        tid = f"{tag}-tech-{i}"
        uid = f"{tag}-user-{i}"
        dbc.technicians.insert_one({
            "id": tid, "user_id": uid, "tenant_id": tenant_id,
            "name": c["name"], "email": f"{tid}@test.local",
            "is_active": True,
            "preferred_service_types": c.get("preferred_service_types", []),
        })
        if c.get("stop_coords"):
            dbc.jobs.insert_one({
                "id": f"{tag}-existing-{i}", "tenant_id": tenant_id,
                "technician_id": tid, "scheduled_date": today,
                "site_lat": c["stop_coords"][0],
                "site_lng": c["stop_coords"][1], "status": "scheduled",
                "customer_id": None, "customer_name": f"exist-{i}",
            })
        tech_ids.append(tid)
    new_job = {"id": f"{tag}-newjob", "tenant_id": tenant_id,
                "customer_id": None, "customer_name": "new",
                "scheduled_date": today, "status": "scheduled",
                "site_lat": job_coords[0], "site_lng": job_coords[1],
                "service_type": new_job_service_type}
    dbc.jobs.insert_one(new_job)
    return {"tenant_id": tenant_id, "tag": tag,
             "new_job_id": new_job["id"], "tech_ids": tech_ids}


def _cleanup(dbc, scenario):
    tag = scenario["tag"]
    dbc.technicians.delete_many({"id": {"$regex": f"^{tag}-tech"}})
    dbc.jobs.delete_many({"id": {"$regex": f"^{tag}-"}})


def test_dispatcher_prefers_skilled_tech(admin_h, dbc):
    """Two techs equidistant; the one with 'pool' in preferences wins."""
    s = _make_scenario(dbc, [
        {"name": "Pool Specialist",
          "stop_coords": (33.55, -112.10),
          "preferred_service_types": ["pool", "chemistry"]},
        {"name": "Landscape Specialist",
          "stop_coords": (33.55, -112.10),
          "preferred_service_types": ["landscape", "hardscape"]},
    ], new_job_service_type="pool")
    try:
        r = requests.post(f"{API}/dispatch/auto-assign", headers=admin_h,
                            json={"job_id": s["new_job_id"]}, timeout=15).json()
        ours = [x for x in r["reasoning"] if x["tech_id"] in s["tech_ids"]]
        ours.sort(key=lambda x: x["cost"])
        assert ours[0]["skill_match"] == "exact"
        assert ours[0]["tech_name"] == "Pool Specialist", ours
        assert ours[-1]["skill_match"] == "off_specialty"
    finally: _cleanup(dbc, s)


def test_dispatcher_penalizes_off_specialty(admin_h, dbc):
    """Skilled tech at 5km beats off-specialty tech at 3km via skill-mult.

    Pool-skilled tech at ~5km  → raw≈5000m × 1.0 = 5000
    Off-specialty at ~3km      → raw≈3000m × 2.5 = 7500  → skilled wins
    """
    s = _make_scenario(dbc, [
        {"name": "Pool Skilled (5km)",
          "stop_coords": (33.55, -112.10),
          "preferred_service_types": ["pool"]},
        {"name": "Off Specialty (3km)",
          "stop_coords": (33.573, -112.10),
          "preferred_service_types": ["landscape"]},
    ], new_job_service_type="pool", job_coords=(33.60, -112.10))
    try:
        r = requests.post(f"{API}/dispatch/auto-assign", headers=admin_h,
                            json={"job_id": s["new_job_id"]}, timeout=15).json()
        ours = [x for x in r["reasoning"] if x["tech_id"] in s["tech_ids"]]
        ours.sort(key=lambda x: x["cost"])
        assert ours[0]["tech_name"] == "Pool Skilled (5km)", (
            f"skilled should win despite being 2km farther:\n{ours}")
        assert ours[0]["skill_match"] == "exact"
        assert ours[-1]["skill_match"] == "off_specialty"
        # Sanity: off_specialty's cost > pool_skilled's cost due to multiplier
        skilled = next(x for x in ours if x["skill_match"] == "exact")
        off = next(x for x in ours if x["skill_match"] == "off_specialty")
        assert off["cost"] > skilled["cost"]
        assert off["raw_cost"] < skilled["raw_cost"], (
            "expected off-specialty raw distance to be smaller, but got "
            f"off={off['raw_cost']} skilled={skilled['raw_cost']}")
    finally: _cleanup(dbc, s)


def test_dispatcher_neutral_when_no_preferences(admin_h, dbc):
    """Tech with no preferences gets neutral (1.5x), not penalized."""
    s = _make_scenario(dbc, [
        {"name": "Neutral Tech",
          "stop_coords": (33.55, -112.10),
          "preferred_service_types": []},
        {"name": "Off Specialty",
          "stop_coords": (33.55, -112.10),
          "preferred_service_types": ["landscape"]},
    ], new_job_service_type="pool")
    try:
        r = requests.post(f"{API}/dispatch/auto-assign", headers=admin_h,
                            json={"job_id": s["new_job_id"]}, timeout=15).json()
        ours = [x for x in r["reasoning"] if x["tech_id"] in s["tech_ids"]]
        neutral = next(x for x in ours if x["tech_name"] == "Neutral Tech")
        off = next(x for x in ours if x["tech_name"] == "Off Specialty")
        assert neutral["skill_match"] == "neutral"
        assert neutral["skill_multiplier"] == 1.5
        assert off["skill_multiplier"] == 2.5
        assert neutral["cost"] < off["cost"]
    finally: _cleanup(dbc, s)


def test_patch_skill_profile_and_list(admin_h, dbc):
    """PATCH updates preferences; GET technician-skills reflects them."""
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    tid = f"skillep-{int(time.time())}"
    uid = f"skillep-user-{int(time.time())}"
    dbc.users.insert_one({
        "id": uid, "tenant_id": t["id"], "role": "technician",
        "name": "Skill Endpoint Test",
        "email": f"{uid}@test.local",
    })
    dbc.technicians.insert_one({
        "id": tid, "user_id": uid, "tenant_id": t["id"],
        "name": "Skill Endpoint Test", "is_active": True,
    })
    try:
        r = requests.patch(f"{API}/users/{uid}/skill-profile", headers=admin_h,
                             json={"preferred_service_types":
                                     ["Pool", "REPAIR", "Chemistry"]},
                             timeout=15).json()
        assert r["preferred_service_types"] == ["pool", "repair", "chemistry"]
        # Both users and technicians rows should have the updated prefs.
        u = dbc.users.find_one({"id": uid})
        te = dbc.technicians.find_one({"id": tid})
        assert u["preferred_service_types"] == ["pool", "repair", "chemistry"]
        assert te["preferred_service_types"] == ["pool", "repair", "chemistry"]
        # List endpoint returns him with the prefs.
        lst = requests.get(f"{API}/dispatch/technician-skills",
                              headers=admin_h, timeout=15).json()
        entry = next((x for x in lst["items"] if x["id"] == tid), None)
        assert entry is not None
        assert entry["preferred_service_types"] == \
            ["pool", "repair", "chemistry"]
    finally:
        dbc.users.delete_one({"id": uid})
        dbc.technicians.delete_one({"id": tid})


# ═══════════ Phase 21 · Estimator ImageContent SDK audit ═══════════════

@pytest.fixture
def estimator_with_broken_photos(dbc, admin_h):
    """Create an estimate with a mix of valid + broken photo URLs so
    generate can be smoke-tested."""
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    est_id = f"est-audit-{int(time.time())}"
    dbc.estimator_estimates.insert_one({
        "id": est_id, "tenant_id": t["id"],
        "title": "Broken photo audit",
        "description": "Small pool tile repair",
        "service_type": "pool",
        "photos": [
            {"url": "https://example.invalid/does-not-exist.jpg"},
            {"url": "https://httpstat.us/404"},
            {"url": "https://images.unsplash.com/photo-1519046904884-53103b34b206?auto=format&fit=crop&w=800"},
        ],
        "status": "draft",
        "created_by": "test", "created_at": "2026-02-15T00:00:00Z",
    })
    yield {"tenant_id": t["id"], "estimate_id": est_id}
    dbc.estimator_estimates.delete_one({"id": est_id})


def test_estimator_generate_survives_broken_photos(admin_h,
                                                       estimator_with_broken_photos):
    """Broken photo URLs must NOT crash generate — endpoint returns 200."""
    r = requests.post(
        f"{API}/estimator/estimates/{estimator_with_broken_photos['estimate_id']}/generate",
        headers=admin_h, timeout=90)
    assert r.status_code == 200, r.text
    body = r.json()
    # Should not be mocked purely because of a broken image (as long as
    # EMERGENT_LLM_KEY is set and at least one photo fetched).
    if body.get("mocked"):
        # If it IS mocked, reason must NOT be about SDK misuse — must be
        # explicit LLM/key related.
        reason = (body.get("reason") or "").lower()
        assert "image_url" not in reason, (
            "estimator still using old ImageContent signature")
    # skipped_photos array should mention the two broken URLs (if the
    # response surfaces it — otherwise at least no crash).
    if "skipped_photos" in body:
        skipped_urls = [s["url"] for s in body["skipped_photos"]]
        assert any("invalid" in u or "404" in u
                     for u in skipped_urls), skipped_urls
