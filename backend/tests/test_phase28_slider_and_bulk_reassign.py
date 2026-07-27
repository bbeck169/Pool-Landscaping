"""Phase 28 · Feb 2026 — SERVICE_RECORD_IMAGES slider-preview + bulk
reassign endpoint.

Feature 1 · Merge tag slider:
    * 0 media → empty string
    * 1 photo → single 300x300 tile
    * 3 photos → 3 tiles at 200x200, no counter
    * 5 photos → 3 tiles + "View 2 more" counter
    * 12 photos + 2 videos → 3 tiles + "View 11 more"
    * Video tile has the ``&#9654;`` (▶) play-icon glyph
    * Every tile links to the public portal URL

Feature 2 · Bulk reassign endpoint:
    * Admin can POST /api/jobs/bulk-reassign
    * Tech role cannot (403)
    * Invalid ``new_tech_id`` → 400
    * Missing job → per-job ``failed`` entry, endpoint still 200
    * Audit log row + in-app notifications for both old + new tech
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]


def _mk(prefix: str) -> str:
    return f"TEST_{prefix}_{uuid.uuid4().hex[:12]}"


# ═══════════ Feature 1 — Merge tag slider preview ══════════════════════
@pytest.fixture(autouse=True)
def _env():
    os.environ["APP_PUBLIC_URL"] = "https://example.test"
    yield


def _sr(public_uuid: str, photo_count: int = 0, video_count: int = 0) -> dict:
    photos = [{"url": f"https://cdn.test/p{i}.jpg",
                "thumbnail_url": f"https://cdn.test/p{i}-t.jpg"}
               for i in range(photo_count)]
    videos = [{"url": f"https://cdn.test/v{i}.mp4",
                "poster_url": f"https://cdn.test/v{i}-p.jpg"}
               for i in range(video_count)]
    return {"id": "sr", "public_uuid": public_uuid,
            "photos": photos, "videos": videos}


def _render(sr: dict) -> str:
    from services.marketing.merge_tags import render_template, render_context
    ctx = render_context(job={"id": "j1"}, service_report=sr)
    out, _ = render_template("{{SERVICE_RECORD_IMAGES}}", ctx)
    return out


def test_slider_empty_when_no_media():
    out = _render(_sr("abc123", 0, 0))
    assert out == ""


def test_slider_single_photo_renders_300px_tile():
    out = _render(_sr("abc123", 1, 0))
    assert out.count("<img") == 1
    assert 'width="300" height="300"' in out
    assert "portal/service/abc123" in out
    assert "View" not in out  # no counter for 1 tile


def test_slider_three_photos_no_counter():
    out = _render(_sr("abc123", 3, 0))
    assert out.count("<img") == 3
    assert 'width="200" height="200"' in out
    assert "View" not in out
    assert "portal/service/abc123" in out


def test_slider_five_photos_shows_counter_with_two_more():
    out = _render(_sr("abc123", 5, 0))
    # Three visible <img> tiles.
    assert out.count("<img") == 3
    # Counter tile.
    assert "View 2 more" in out
    assert "+2" in out
    # All 4 anchor tiles (3 img tiles + 1 counter) point at the portal.
    assert out.count("portal/service/abc123") == 4


def test_slider_twelve_photos_plus_two_videos_counter_shows_eleven():
    out = _render(_sr("abc123", 12, 2))
    # Combined pool = 14; visible = 3; counter shows 11 hidden.
    assert out.count("<img") == 3
    assert "View 11 more" in out
    assert "+11" in out


def test_slider_video_first_position_shows_play_icon():
    out = _render(_sr("abc123", 0, 1))
    assert "&#9654;" in out            # play glyph
    assert 'alt="Service video"' in out
    assert "portal/service/abc123" in out


def test_slider_video_mixed_pool_only_first_three_visible():
    out = _render(_sr("abc123", 2, 3))   # 5 items total
    assert out.count("<img") == 3
    assert "View 2 more" in out


def test_slider_all_tiles_link_to_portal():
    out = _render(_sr("abc123", 5, 0))
    # Each `<a href` must point at the portal URL.
    for chunk in out.split('<a href="')[1:]:
        assert chunk.startswith("https://example.test/portal/service/abc123")


# ═══════════ Feature 2 — Bulk reassign endpoint ════════════════════════
@pytest.fixture(scope="module")
def api_base():
    frontend_env = Path(__file__).resolve().parents[2] / "frontend" / ".env"
    react = dotenv_values(frontend_env) if frontend_env.is_file() else {}
    public = (react.get("REACT_APP_BACKEND_URL")
              or os.environ.get("REACT_APP_BACKEND_URL"))
    return ((public.rstrip("/") + "/api") if public else
            "http://localhost:8001/api")


@pytest.fixture()
def seeded(request):
    """Seed a tenant + admin + 2 techs + 2 jobs assigned to old_tech."""
    tid = _mk("tenant")
    _sync.tenants.insert_one({"id": tid, "name": "TEST_ Tenant",
                                 "active": True,
                                 "slug": f"testtenant{uuid.uuid4().hex[:6]}"})

    def _hash(pw: str) -> str:
        import bcrypt
        return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode()

    admin_id = _mk("admin")
    admin_email = f"admin_{uuid.uuid4().hex[:6]}@example.com"
    _sync.users.insert_one({
        "id": admin_id, "tenant_id": tid, "email": admin_email,
        "password_hash": _hash("Testpass1!"),
        "role": "admin", "name": "TEST_ Admin",
        "primary_tenant_id": tid, "tenant_ids": [tid],
    })
    tech_ids = []
    tech_users = []
    for i, (role, name) in enumerate([("pool_tech", "TEST_ OldTech"),
                                       ("landscape_tech", "TEST_ NewTech"),
                                       ("technician", "TEST_ ThirdTech")]):
        tech_id = _mk(f"techid{i}")
        uid = _mk(f"techu{i}")
        _sync.users.insert_one({
            "id": uid, "tenant_id": tid,
            "email": f"tech{i}_{uuid.uuid4().hex[:6]}@example.com",
            "password_hash": _hash("Testpass1!"),
            "role": role, "name": name,
            "technician_id": tech_id,
            "primary_tenant_id": tid, "tenant_ids": [tid],
        })
        tech_ids.append(tech_id)
        tech_users.append(uid)
    old_tech, new_tech, third_tech = tech_ids
    old_uid, new_uid, third_uid = tech_users

    job_ids = []
    for i in range(2):
        jid = _mk(f"job{i}")
        _sync.jobs.insert_one({
            "id": jid, "tenant_id": tid,
            "title": f"TEST_ Pool #{i}", "service_type": "Pool Service",
            "technician_id": old_tech, "assigned_tech_id": old_tech,
            "status": "scheduled",
        })
        job_ids.append(jid)

    ctx = {"tenant_id": tid, "admin_email": admin_email,
           "old_tech": old_tech, "new_tech": new_tech, "third_tech": third_tech,
           "old_uid": old_uid, "new_uid": new_uid,
           "job_ids": job_ids}

    yield ctx

    # Teardown
    _sync.jobs.delete_many({"tenant_id": tid})
    _sync.users.delete_many({"tenant_id": tid})
    _sync.tenants.delete_one({"id": tid})
    _sync.audit_log.delete_many({"tenant_id": tid})
    _sync.notifications.delete_many({"tenant_id": tid})


def _login(api_base: str, email: str, password: str) -> str:
    r = requests.post(f"{api_base}/auth/login",
                       json={"email": email, "password": password},
                       timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _tenant_headers(api_base: str, token: str, tid: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Tenant-Id": tid}


def test_admin_can_bulk_reassign(seeded, api_base):
    tok = _login(api_base, seeded["admin_email"], "Testpass1!")
    h = _tenant_headers(api_base, tok, seeded["tenant_id"])
    r = requests.post(f"{api_base}/jobs/bulk-reassign",
                       json={"job_ids": seeded["job_ids"],
                              "new_tech_id": seeded["new_tech"]},
                       headers=h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["count"] == 2
    assert set(body["reassigned"]) == set(seeded["job_ids"])
    assert body["failed"] == []
    # Mongo state matches.
    for jid in seeded["job_ids"]:
        j = _sync.jobs.find_one({"id": jid}, {"_id": 0, "technician_id": 1,
                                                 "assigned_tech_id": 1})
        assert j["technician_id"] == seeded["new_tech"]
        assert j["assigned_tech_id"] == seeded["new_tech"]


def test_bulk_reassign_writes_audit_and_notifications(seeded, api_base):
    tok = _login(api_base, seeded["admin_email"], "Testpass1!")
    h = _tenant_headers(api_base, tok, seeded["tenant_id"])
    r = requests.post(f"{api_base}/jobs/bulk-reassign",
                       json={"job_ids": seeded["job_ids"],
                              "new_tech_id": seeded["new_tech"]},
                       headers=h, timeout=15)
    assert r.status_code == 200, r.text
    # Audit rows.
    audits = list(_sync.audit_log.find(
        {"tenant_id": seeded["tenant_id"], "action": "job.reassign"}))
    assert len(audits) == 2
    for a in audits:
        assert a["new_tech_id"] == seeded["new_tech"]
        assert a["old_tech_id"] == seeded["old_tech"]
    # Notifications — new tech gets one aggregate, old tech gets one aggregate.
    new_notifs = list(_sync.notifications.find(
        {"tenant_id": seeded["tenant_id"], "user_id": seeded["new_uid"]}))
    old_notifs = list(_sync.notifications.find(
        {"tenant_id": seeded["tenant_id"], "user_id": seeded["old_uid"]}))
    assert any("assigned" in (n.get("title") or "").lower() for n in new_notifs)
    assert any("reassigned away" in (n.get("title") or "").lower()
                for n in old_notifs)


def test_bulk_reassign_rejects_invalid_new_tech_id(seeded, api_base):
    tok = _login(api_base, seeded["admin_email"], "Testpass1!")
    h = _tenant_headers(api_base, tok, seeded["tenant_id"])
    r = requests.post(f"{api_base}/jobs/bulk-reassign",
                       json={"job_ids": seeded["job_ids"],
                              "new_tech_id": "not-a-real-tech"},
                       headers=h, timeout=15)
    assert r.status_code == 400


def test_bulk_reassign_records_missing_job_in_failed(seeded, api_base):
    tok = _login(api_base, seeded["admin_email"], "Testpass1!")
    h = _tenant_headers(api_base, tok, seeded["tenant_id"])
    body_ids = seeded["job_ids"] + ["TEST_missing_job_id"]
    r = requests.post(f"{api_base}/jobs/bulk-reassign",
                       json={"job_ids": body_ids,
                              "new_tech_id": seeded["new_tech"]},
                       headers=h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2
    assert len(body["failed"]) == 1
    assert body["failed"][0]["job_id"] == "TEST_missing_job_id"
    assert body["failed"][0]["status_code"] == 404


def test_bulk_reassign_forbidden_for_technician_role(seeded, api_base):
    """Log in as one of the seeded tech users (role=pool_tech) — the
    ``require_admin`` guard on the endpoint must refuse."""
    tech_user = _sync.users.find_one(
        {"tenant_id": seeded["tenant_id"], "role": "pool_tech"},
        {"_id": 0, "email": 1})
    tok = _login(api_base, tech_user["email"], "Testpass1!")
    h = _tenant_headers(api_base, tok, seeded["tenant_id"])
    r = requests.post(f"{api_base}/jobs/bulk-reassign",
                       json={"job_ids": seeded["job_ids"],
                              "new_tech_id": seeded["new_tech"]},
                       headers=h, timeout=15)
    assert r.status_code == 403


def test_bulk_reassign_rejects_non_tech_role_target(seeded, api_base):
    """Passing an ADMIN's technician_id (or a non-tech user id) must
    be refused — reassign target must be a tech-family role."""
    # Create a NON-tech user with a technician_id to try to trick the check.
    trap_id = _mk("trap")
    trap_uid = _mk("trapu")
    _sync.users.insert_one({
        "id": trap_uid, "tenant_id": seeded["tenant_id"],
        "email": f"trap_{uuid.uuid4().hex[:6]}@example.com",
        "role": "dispatcher",   # not in tech-family set
        "technician_id": trap_id,
    })
    tok = _login(api_base, seeded["admin_email"], "Testpass1!")
    h = _tenant_headers(api_base, tok, seeded["tenant_id"])
    r = requests.post(f"{api_base}/jobs/bulk-reassign",
                       json={"job_ids": seeded["job_ids"],
                              "new_tech_id": trap_id},
                       headers=h, timeout=15)
    assert r.status_code == 400
