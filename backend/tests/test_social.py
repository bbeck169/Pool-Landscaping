"""Phase 18A · Social Suite backend tests."""
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def sunbelt_admin_h():
    return {"Authorization": f"Bearer {_login('admin@sunbelt.com')}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


def test_create_draft_and_list(admin_h, db):
    r = requests.post(f"{API}/social/posts", headers=admin_h, json={
        "networks": ["facebook", "instagram"],
        "caption": "TEST_ draft caption from Phase 18A",
        "hashtags": ["#pool", "#service"],
    }, timeout=20)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert r.json()["status"] == "draft"

    r = requests.get(f"{API}/social/posts?status=draft", headers=admin_h, timeout=20)
    assert r.status_code == 200
    assert any(p["id"] == pid for p in r.json())
    # cleanup
    requests.delete(f"{API}/social/posts/{pid}", headers=admin_h, timeout=20)


def test_scheduled_status_when_future(admin_h):
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    r = requests.post(f"{API}/social/posts", headers=admin_h, json={
        "networks": ["linkedin"],
        "caption": "TEST_ scheduled post",
        "scheduled_at": future,
    }, timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "scheduled"
    requests.delete(f"{API}/social/posts/{body['id']}", headers=admin_h, timeout=20)


def test_tenant_isolation(admin_h, sunbelt_admin_h):
    r = requests.post(f"{API}/social/posts", headers=admin_h, json={
        "networks": ["facebook"], "caption": "TEST_ isolation aquaterra"
    }, timeout=20)
    pid = r.json()["id"]
    try:
        r2 = requests.get(f"{API}/social/posts", headers=sunbelt_admin_h, timeout=20)
        ids = [p["id"] for p in r2.json()]
        assert pid not in ids
        # Direct fetch cross-tenant → 404
        assert requests.get(f"{API}/social/posts/{pid}",
                            headers=sunbelt_admin_h, timeout=20).status_code == 404
    finally:
        requests.delete(f"{API}/social/posts/{pid}", headers=admin_h, timeout=20)


def test_technician_forbidden(tech_h):
    r = requests.get(f"{API}/social/posts", headers=tech_h, timeout=20)
    assert r.status_code == 403
    r = requests.post(f"{API}/social/posts", headers=tech_h,
                      json={"networks": ["facebook"], "caption": "x"}, timeout=20)
    assert r.status_code == 403


def test_ai_caption_live_or_flagged_mock(admin_h):
    r = requests.post(f"{API}/social/ai/caption", headers=admin_h, json={
        "topic": "Weekly pool service tips for AZ summer",
        "networks": ["instagram", "facebook"],
    }, timeout=45)
    assert r.status_code == 200
    d = r.json()
    assert "mocked" in d
    # If key is present the response MUST not be silently mocked.
    if os.environ.get("EMERGENT_LLM_KEY"):
        assert d["mocked"] is False
    assert isinstance(d.get("captions") or [], list)


def test_reschedule_and_duplicate(admin_h):
    r = requests.post(f"{API}/social/posts", headers=admin_h, json={
        "networks": ["facebook"], "caption": "TEST_ reschedule-src"
    }, timeout=20)
    pid = r.json()["id"]
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    r = requests.post(f"{API}/social/posts/{pid}/reschedule", headers=admin_h,
                      json={"scheduled_at": future}, timeout=20)
    assert r.status_code == 200 and r.json()["status"] == "scheduled"
    r = requests.post(f"{API}/social/posts/{pid}/duplicate", headers=admin_h, timeout=20)
    assert r.status_code == 200
    dup_id = r.json()["id"]
    assert dup_id != pid
    assert r.json()["status"] == "draft"
    requests.delete(f"{API}/social/posts/{pid}", headers=admin_h, timeout=20)
    requests.delete(f"{API}/social/posts/{dup_id}", headers=admin_h, timeout=20)


def test_media_upload_and_list(admin_h):
    r = requests.post(f"{API}/social/media", headers=admin_h, json={
        "url": "data:image/png;base64,iVBORw0KGgo=",
        "mime": "image/png", "width": 1, "height": 1, "tags": ["test"],
    }, timeout=20)
    assert r.status_code == 200
    mid = r.json()["id"]
    r = requests.get(f"{API}/social/media?type=image", headers=admin_h, timeout=20)
    assert r.status_code == 200
    assert any(m["id"] == mid for m in r.json())
    requests.delete(f"{API}/social/media/{mid}", headers=admin_h, timeout=20)
