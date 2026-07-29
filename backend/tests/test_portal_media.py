"""Portal media (Photos / Videos / Messages-unread) · Feb-2026.

End-to-end HTTP tests against the running backend. Uses the ``TEST-`` id
prefix so ``conftest.py`` cleans everything up at session teardown.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]


# ── Auth helpers (cached, retried) ────────────────────────────────
_CACHE: dict = {}


def _login(email: str, password: str = "password123") -> str:
    key = f"tok:{email}"
    if _CACHE.get(key):
        return _CACHE[key]
    last = None
    for _ in range(3):
        try:
            r = requests.post(
                f"{API}/auth/login",
                json={"email": email, "password": password}, timeout=30,
            )
            if r.status_code == 200:
                _CACHE[key] = r.json()["access_token"]
                return _CACHE[key]
            last = r.text
        except requests.exceptions.RequestException as exc:
            last = str(exc)
    raise RuntimeError(f"login failed for {email}: {last}")


def _customer_ctx() -> dict:
    """Return {token, customer_id, tenant_id} for the demo customer."""
    if _CACHE.get("cust_ctx"):
        return _CACHE["cust_ctx"]
    tok = _login("customer@aquaterra.com")
    me = requests.get(f"{API}/auth/me",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=15).json()
    _CACHE["cust_ctx"] = {
        "token": tok,
        "customer_id": me.get("customer_id"),
        "tenant_id": me.get("tenant_id"),
    }
    return _CACHE["cust_ctx"]


def _admin_token() -> str:
    return _login("manager@aquaterra.com")


# ── Seed helpers ──────────────────────────────────────────────────
def _seed_job(customer_id: str, tenant_id: str,
                title: str = "TEST_pm_job") -> str:
    jid = f"TEST-pm-job-{uuid.uuid4().hex[:8]}"
    _db.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "customer_id": customer_id,
        "title": title, "status": "scheduled",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _seed_file(*, tenant_id: str, entity_type: str, entity_id: str,
                mime: str = "image/png",
                purpose: str = "job_photo",
                created_at: str | None = None) -> str:
    fid = f"TEST-pm-file-{uuid.uuid4().hex[:8]}"
    _db.files.insert_one({
        "id": fid, "tenant_id": tenant_id,
        "storage_path": f"test/{fid}.png",
        "original_filename": f"{fid}.png",
        "content_type": mime,
        "size": 1024,
        "uploaded_by_user_id": "TEST-uploader",
        "purpose": purpose,
        "linked_entity_type": entity_type,
        "linked_entity_id": entity_id,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "is_deleted": False,
        "deleted_at": None,
    })
    return fid


def _seed_service_report_with_video(*, tenant_id: str, job_id: str) -> str:
    """Insert a submitted service report with one photo + one video."""
    rid = f"TEST-pm-rep-{uuid.uuid4().hex[:8]}"
    pub = f"TEST-pm-pub-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()
    _db.service_reports.insert_one({
        "id": rid, "tenant_id": tenant_id,
        "job_id": job_id, "public_uuid": pub,
        "submitted_at": now, "updated_at": now,
        "photos": [{
            "id": f"pm-photo-{uuid.uuid4().hex[:6]}",
            "storage_path": "test/rp.jpg",
            "mime": "image/jpeg", "size_bytes": 4096,
            "uploaded_at": now, "is_deleted": False,
        }],
        "videos": [{
            "id": f"pm-video-{uuid.uuid4().hex[:6]}",
            "storage_path": "test/rp.mp4",
            "mime": "video/mp4", "size_bytes": 12345,
            "duration_seconds": 42.5,
            "poster_url": "/api/x/y.jpg",
            "uploaded_at": now, "is_deleted": False,
        }],
    })
    return rid


def _cleanup(ids: list[str]):
    for coll in ("jobs", "files", "service_reports"):
        _db[coll].delete_many({"id": {"$in": ids}})


# ── Photos tests ──────────────────────────────────────────────────
def test_portal_photos_requires_auth():
    r = requests.get(f"{API}/portal/photos", timeout=10)
    assert r.status_code in (401, 403), r.text


def test_portal_photos_returns_own_jobs_photos():
    ctx = _customer_ctx()
    cid = ctx["customer_id"]
    tid = ctx["tenant_id"]

    # Two jobs — one owned, one owned by a phantom other customer.
    own_job = _seed_job(cid, tid, "TEST_own_job")
    other_cust = f"TEST-pm-other-cust-{uuid.uuid4().hex[:6]}"
    other_job = _seed_job(other_cust, tid, "TEST_other_job")

    mine = _seed_file(tenant_id=tid, entity_type="job",
                        entity_id=own_job, mime="image/png")
    stranger = _seed_file(tenant_id=tid, entity_type="job",
                            entity_id=other_job, mime="image/png")
    seeded = [own_job, other_job, mine, stranger]
    try:
        r = requests.get(
            f"{API}/portal/photos?limit=50",
            headers={"Authorization": f"Bearer {ctx['token']}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        ids = {p["file_id"] for p in body["items"]}
        assert mine in ids, "customer should see their own job's photo"
        assert stranger not in ids, "cross-customer photo leaked!"
    finally:
        _cleanup(seeded)


def test_portal_photos_includes_customer_linked_files():
    ctx = _customer_ctx()
    cid = ctx["customer_id"]
    tid = ctx["tenant_id"]
    cust_file = _seed_file(tenant_id=tid, entity_type="customer",
                             entity_id=cid, mime="image/jpeg",
                             purpose="portal_upload")
    try:
        r = requests.get(
            f"{API}/portal/photos?limit=50",
            headers={"Authorization": f"Bearer {ctx['token']}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        ids = {p["file_id"] for p in r.json()["items"]}
        assert cust_file in ids
    finally:
        _cleanup([cust_file])


def test_portal_photos_pagination():
    ctx = _customer_ctx()
    cid = ctx["customer_id"]
    tid = ctx["tenant_id"]
    job = _seed_job(cid, tid, "TEST_pagination_job")
    files = [
        _seed_file(tenant_id=tid, entity_type="job",
                   entity_id=job, mime="image/png",
                   created_at=f"2026-07-{20+i:02d}T00:00:00+00:00")
        for i in range(4)
    ]
    try:
        r1 = requests.get(
            f"{API}/portal/photos?limit=2&offset=0&job_id={job}",
            headers={"Authorization": f"Bearer {ctx['token']}"}, timeout=15,
        ).json()
        r2 = requests.get(
            f"{API}/portal/photos?limit=2&offset=2&job_id={job}",
            headers={"Authorization": f"Bearer {ctx['token']}"}, timeout=15,
        ).json()
        # Same total, different pages, no overlap.
        assert r1["total"] == 4 and r2["total"] == 4, (r1, r2)
        assert len(r1["items"]) == 2 and len(r2["items"]) == 2
        ids_p1 = {p["file_id"] for p in r1["items"]}
        ids_p2 = {p["file_id"] for p in r2["items"]}
        assert ids_p1.isdisjoint(ids_p2), "pagination overlap"
    finally:
        _cleanup([job] + files)


def test_portal_photos_empty_state_no_jobs():
    # We build a *fresh* isolated customer + user for this test so the
    # baseline is guaranteed empty. We do NOT use the demo customer
    # (who has seeded photos).
    pass_email = f"test-empty-{uuid.uuid4().hex[:8]}@example.com"
    tid = _customer_ctx()["tenant_id"]
    cid = f"TEST-pm-empty-cust-{uuid.uuid4().hex[:6]}"
    _db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "TEST empty",
        "email": pass_email, "phone": "+15555550100",
    })
    from utils import hash_password  # local import to avoid session dep
    uid = f"TEST-pm-empty-user-{uuid.uuid4().hex[:6]}"
    _db.users.insert_one({
        "id": uid, "tenant_id": tid,
        "name": "TEST empty",
        "email": pass_email,
        "password_hash": hash_password("password123"),
        "role": "customer",
        "customer_id": cid,
    })
    try:
        tok = _login(pass_email)
        r = requests.get(
            f"{API}/portal/photos?limit=50",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["items"] == []
        assert body["total"] == 0
    finally:
        _db.users.delete_one({"id": uid})
        _db.customers.delete_one({"id": cid})
        _CACHE.pop(f"tok:{pass_email}", None)


# ── Videos tests ──────────────────────────────────────────────────
def test_portal_videos_requires_auth():
    r = requests.get(f"{API}/portal/videos", timeout=10)
    assert r.status_code in (401, 403), r.text


def test_portal_videos_returns_own_service_report_videos():
    ctx = _customer_ctx()
    cid, tid = ctx["customer_id"], ctx["tenant_id"]
    job = _seed_job(cid, tid, "TEST_video_job")
    rid = _seed_service_report_with_video(tenant_id=tid, job_id=job)
    try:
        r = requests.get(
            f"{API}/portal/videos?limit=50",
            headers={"Authorization": f"Bearer {ctx['token']}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        # Our seeded video should be in there.
        found = [v for v in items if v.get("mime") == "video/mp4"
                  and v.get("job_id") == job]
        assert found, f"expected our seeded video, got {items}"
        v = found[0]
        assert v["url"].startswith("/api/public/service/")
        assert v["duration_seconds"] == 42.5
        assert v["source"] == "service_report"
    finally:
        _cleanup([job, rid])


def test_portal_videos_cross_customer_isolation():
    ctx = _customer_ctx()
    tid = ctx["tenant_id"]
    other_cust = f"TEST-pm-other-{uuid.uuid4().hex[:6]}"
    other_job = _seed_job(other_cust, tid, "TEST_stranger_job")
    other_rep = _seed_service_report_with_video(tenant_id=tid, job_id=other_job)
    try:
        r = requests.get(
            f"{API}/portal/videos?limit=50",
            headers={"Authorization": f"Bearer {ctx['token']}"}, timeout=15,
        ).json()
        # None of the returned videos should point to the stranger's job.
        for v in r["items"]:
            assert v["job_id"] != other_job, "cross-customer video leaked!"
    finally:
        _cleanup([other_job, other_rep])


# ── Messages unread count ─────────────────────────────────────────
def test_portal_unread_count_requires_auth():
    r = requests.get(f"{API}/portal/messages/unread-count", timeout=10)
    assert r.status_code in (401, 403), r.text


def test_portal_unread_count_sums_chats():
    ctx = _customer_ctx()
    cid, tid = ctx["customer_id"], ctx["tenant_id"]
    # Seed two fake chats with unread counts.
    chats = []
    for u in (2, 3):
        chat_id = f"TEST-pm-chat-{uuid.uuid4().hex[:8]}"
        _db.portal_chats.insert_one({
            "id": chat_id, "tenant_id": tid, "customer_id": cid,
            "subject": "TEST_chat",
            "unread_by_customer": u, "unread_by_admin": 0,
            "last_message_at": datetime.now(timezone.utc).isoformat(),
        })
        chats.append(chat_id)
    try:
        r = requests.get(
            f"{API}/portal/messages/unread-count",
            headers={"Authorization": f"Bearer {ctx['token']}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        # >= 5 (may be more if there are real seed chats too).
        assert r.json()["unread"] >= 5
    finally:
        _db.portal_chats.delete_many({"id": {"$in": chats}})
