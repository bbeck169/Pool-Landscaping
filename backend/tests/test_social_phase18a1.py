"""Phase 18A.1 — Social Suite (approvals, bulk, UTM, short-links, library upgrades)."""
import io
import os
from pathlib import Path

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
def sunbelt_admin_h():
    return {"Authorization": f"Bearer {_login('admin@sunbelt.com')}"}


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


def _new_post(headers, caption="TEST_ 18a1", **kw):
    body = {"networks": ["facebook"], "caption": caption, **kw}
    r = requests.post(f"{API}/social/posts", headers=headers, json=body, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


def _cleanup_post(headers, pid):
    try:
        requests.delete(f"{API}/social/posts/{pid}", headers=headers, timeout=15)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 1 — Approvals
# ═══════════════════════════════════════════════════════════════════════════
def test_approval_submit_then_approve_moves_to_scheduled(admin_h):
    from datetime import datetime, timedelta, timezone
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    post = _new_post(admin_h, caption="TEST_ 18a1 approve-scheduled", scheduled_at=future)
    pid = post["id"]
    try:
        r = requests.post(f"{API}/social/posts/{pid}/submit-for-approval",
                          headers=admin_h, timeout=15)
        assert r.status_code == 200 and r.json()["status"] == "pending_approval"

        # queue shows the post
        q = requests.get(f"{API}/social/approvals?status=pending", headers=admin_h, timeout=15)
        assert q.status_code == 200 and any(a["post_id"] == pid for a in q.json())

        r = requests.post(f"{API}/social/posts/{pid}/approve", headers=admin_h,
                          json={"comment": "LGTM"}, timeout=15)
        assert r.status_code == 200 and r.json()["post_status"] == "scheduled"

        # post now has status=scheduled
        gp = requests.get(f"{API}/social/posts/{pid}", headers=admin_h, timeout=15).json()
        assert gp["status"] == "scheduled"
    finally:
        _cleanup_post(admin_h, pid)


def test_approval_reject_requires_comment(admin_h):
    post = _new_post(admin_h, caption="TEST_ 18a1 reject-no-comment")
    pid = post["id"]
    try:
        assert requests.post(f"{API}/social/posts/{pid}/submit-for-approval",
                             headers=admin_h, timeout=15).status_code == 200
        # Empty comment → 400
        r = requests.post(f"{API}/social/posts/{pid}/reject", headers=admin_h,
                          json={"comment": ""}, timeout=15)
        assert r.status_code == 400
        # With comment → OK, post drops back to draft
        r = requests.post(f"{API}/social/posts/{pid}/reject", headers=admin_h,
                          json={"comment": "off-brand tone"}, timeout=15)
        assert r.status_code == 200 and r.json()["post_status"] == "draft"
    finally:
        _cleanup_post(admin_h, pid)


def test_approval_tech_forbidden(tech_h):
    r = requests.get(f"{API}/social/approvals", headers=tech_h, timeout=15)
    assert r.status_code == 403
    r = requests.post(f"{API}/social/posts/nope/submit-for-approval",
                      headers=tech_h, timeout=15)
    assert r.status_code == 403


def test_approval_tenant_isolation(admin_h, sunbelt_admin_h):
    post = _new_post(admin_h, caption="TEST_ 18a1 aquaterra approval isolation")
    pid = post["id"]
    try:
        assert requests.post(f"{API}/social/posts/{pid}/submit-for-approval",
                             headers=admin_h, timeout=15).status_code == 200
        # Sunbelt admin queue MUST NOT contain the aquaterra post
        q = requests.get(f"{API}/social/approvals?status=pending",
                         headers=sunbelt_admin_h, timeout=15).json()
        assert not any(a["post_id"] == pid for a in q)
    finally:
        _cleanup_post(admin_h, pid)


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 2 — Bulk CSV
# ═══════════════════════════════════════════════════════════════════════════
def test_bulk_csv_creates_valid_rows_and_reports_errors(admin_h):
    csv_body = (
        "caption,networks,scheduled_at,media_urls,hashtags,first_comment\n"
        "TEST_ 18a1 bulk row A,facebook;instagram,,,#a;#b,\n"
        "TEST_ 18a1 bulk row B,linkedin,,,,\n"
        ",instagram,,,,\n"                       # error: empty caption
        "TEST_ 18a1 bulk row C,mars-network,,,,\n"  # error: bad network
    )
    files = {"file": ("bulk.csv", csv_body, "text/csv")}
    r = requests.post(f"{API}/social/posts/bulk", headers=admin_h,
                      files=files, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["created"] == 2
    assert len(data["errors"]) == 2
    assert {e["row"] for e in data["errors"]} == {3, 4}
    # cleanup
    for pid in data.get("preview_ids", []):
        _cleanup_post(admin_h, pid)


def test_bulk_500_cap(admin_h):
    rows = ["caption,networks,scheduled_at,media_urls,hashtags,first_comment"]
    for i in range(501):
        rows.append(f"cap {i},facebook,,,,")
    csv_body = "\n".join(rows)
    files = {"file": ("bulk.csv", csv_body, "text/csv")}
    r = requests.post(f"{API}/social/posts/bulk", headers=admin_h,
                      files=files, timeout=30)
    assert r.status_code == 400
    assert "500" in r.text


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 3 — UTM builder + presets
# ═══════════════════════════════════════════════════════════════════════════
def test_utm_build_appends_params(admin_h):
    r = requests.post(f"{API}/social/utm/build", headers=admin_h, json={
        "url": "https://aquaterra.com/services",
        "source": "instagram", "medium": "social", "campaign": "july-launch",
    }, timeout=15)
    assert r.status_code == 200
    u = r.json()["tagged_url"]
    assert "utm_source=instagram" in u
    assert "utm_medium=social" in u
    assert "utm_campaign=july-launch" in u


def test_utm_presets_tenant_isolation(admin_h, sunbelt_admin_h):
    r = requests.post(f"{API}/social/utm/presets", headers=admin_h, json={
        "name": "TEST_ 18a1 default IG", "source": "instagram",
        "campaign": "spring-clean",
    }, timeout=15)
    assert r.status_code == 200
    pid = r.json()["id"]
    try:
        # aquaterra sees the preset
        aq = requests.get(f"{API}/social/utm/presets", headers=admin_h,
                          timeout=15).json()
        assert any(p["id"] == pid for p in aq)
        # sunbelt cannot see it
        sb = requests.get(f"{API}/social/utm/presets", headers=sunbelt_admin_h,
                          timeout=15).json()
        assert not any(p["id"] == pid for p in sb)
    finally:
        requests.delete(f"{API}/social/utm/presets/{pid}", headers=admin_h, timeout=15)


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 4 — Short links (create + follow via /r/{alias} increments count)
# ═══════════════════════════════════════════════════════════════════════════
def test_short_link_create_and_follow_increments_count(admin_h, dbc):
    r = requests.post(f"{API}/social/short-links", headers=admin_h, json={
        "target_url": "https://aquaterra.com/testing-18a1",
    }, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    sid = data["id"]; alias = data["alias"]
    # Short URL is under `/api/r/` so it works through Kubernetes ingress.
    assert data["short_url"].endswith(f"/api/r/{alias}")
    try:
        # Follow via /api/r/{alias} — public (no auth), expect 302.
        rr = requests.get(f"{API}/r/{alias}", allow_redirects=False, timeout=15)
        assert rr.status_code == 302
        assert rr.headers.get("location", "").startswith("https://aquaterra.com/testing-18a1")
        # Backend also serves `/r/{alias}` when hit directly (bypasses ingress).
        rr2 = requests.get(f"{BASE}/r/{alias}", allow_redirects=False, timeout=15)
        assert rr2.status_code in (200, 302)  # Ingress may 200 to frontend index externally.
        # Stats reflect at least one click from the /api/r hop.
        stats = requests.get(f"{API}/social/short-links/{sid}/stats",
                             headers=admin_h, timeout=15).json()
        assert stats["clicks"] >= 1
    finally:
        requests.delete(f"{API}/social/short-links/{sid}", headers=admin_h, timeout=15)


def test_short_link_alias_globally_unique(admin_h, sunbelt_admin_h):
    r1 = requests.post(f"{API}/social/short-links", headers=admin_h, json={
        "target_url": "https://aquaterra.com/x", "alias": "test-18a1-clash",
    }, timeout=15)
    assert r1.status_code == 200
    sid = r1.json()["id"]
    try:
        r2 = requests.post(f"{API}/social/short-links", headers=sunbelt_admin_h, json={
            "target_url": "https://sunbelt.com/x", "alias": "test-18a1-clash",
        }, timeout=15)
        assert r2.status_code == 409
    finally:
        requests.delete(f"{API}/social/short-links/{sid}", headers=admin_h, timeout=15)


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 5 — Library: folders, brand kit, alt-text
# ═══════════════════════════════════════════════════════════════════════════
def test_folder_create_list_and_cascade_delete(admin_h, dbc):
    r = requests.post(f"{API}/social/media/folders", headers=admin_h,
                      json={"name": "TEST_ 18a1 folder"}, timeout=15)
    assert r.status_code == 200
    fid = r.json()["id"]
    # Place an asset in that folder
    m = requests.post(f"{API}/social/media", headers=admin_h, json={
        "url": "data:image/png;base64,iVBORw0KGgo=",
        "mime": "image/png", "folder_id": fid,
    }, timeout=15).json()
    mid = m["id"]
    try:
        # Folder appears in list
        lst = requests.get(f"{API}/social/media/folders", headers=admin_h, timeout=15).json()
        assert any(f["id"] == fid for f in lst)
        # Delete folder → asset moves to root
        assert requests.delete(f"{API}/social/media/folders/{fid}",
                               headers=admin_h, timeout=15).status_code == 200
        got = requests.get(f"{API}/social/media", headers=admin_h, timeout=15).json()
        rec = next((a for a in got if a["id"] == mid), None)
        assert rec is not None
        assert rec.get("folder_id") in (None, "")
    finally:
        requests.delete(f"{API}/social/media/{mid}", headers=admin_h, timeout=15)


def test_brand_kit_get_and_put(admin_h):
    kit = requests.get(f"{API}/social/brand-kit", headers=admin_h, timeout=15).json()
    assert "primary_color" in kit
    r = requests.put(f"{API}/social/brand-kit", headers=admin_h, json={
        "primary_color": "#123456", "tagline": "TEST_ 18a1 tagline",
    }, timeout=15)
    assert r.status_code == 200
    assert r.json()["primary_color"] == "#123456"
    assert r.json()["tagline"] == "TEST_ 18a1 tagline"


def test_alt_text_ai_and_manual_set(admin_h):
    m = requests.post(f"{API}/social/media", headers=admin_h, json={
        "url": "https://images.unsplash.com/photo-1519823551278-64ac92734fb1?w=600",
        "mime": "image/jpeg",
    }, timeout=15).json()
    mid = m["id"]
    try:
        # Manual PATCH
        r = requests.patch(f"{API}/social/media/{mid}", headers=admin_h,
                           json={"alt_text": "Manual alt"}, timeout=15)
        assert r.status_code == 200 and r.json()["alt_text"] == "Manual alt"
        # AI generation happy path (returns mocked:True or False; alt_text present)
        r = requests.post(f"{API}/social/ai/alt-text", headers=admin_h,
                          json={"media_id": mid}, timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert "alt_text" in d and d["alt_text"]
        # If EMERGENT_LLM_KEY is set, no silent mocking.
        if os.environ.get("EMERGENT_LLM_KEY"):
            assert d["mocked"] is False
    finally:
        requests.delete(f"{API}/social/media/{mid}", headers=admin_h, timeout=15)
