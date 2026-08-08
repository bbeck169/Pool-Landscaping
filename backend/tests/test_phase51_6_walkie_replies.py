"""Phase 51.6 · Feb-2026 — Walkie-Talkie reply-with-clip tests.

Locks the six invariants:

1. Reply with a valid parent → 200; ``reply_preview`` populated on GET.
2. Reply to a message in a different channel → 400.
3. Reply to a non-existent message → 404.
4. Reply to all-hands from tech → 403 (broadcast gate still fires).
5. Reply after parent TTL-expires → ``reply_preview.deleted: True``, reply itself still surfaces.
6. Cross-tenant reply → 404.

Plus one interaction: pinned parent + replies — pin stays at the top, replies at natural position.
"""
from __future__ import annotations

import uuid

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


API = "http://127.0.0.1:8001/api"
TIMEOUT = 30
PW = "password123"
USERS = {
    "admin":     "admin@aquaterra.com",
    "manager":   "manager@aquaterra.com",
    "super":     "super@aquaterra.com",
    "tech_pool": "mike@aquaterra.com",
}


@pytest.fixture(scope="module")
def sync_db():
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        yield mc[be["DB_NAME"]]
    finally:
        mc.close()


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": PW}, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _hdr(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


def _channels(email: str) -> list[dict]:
    return requests.get(f"{API}/walkie/channels", headers=_hdr(email), timeout=TIMEOUT).json()["channels"]


def _all_hands(email: str) -> str:
    return next(c["id"] for c in _channels(email) if c["kind"] == "all_hands")


def _pool_dept(email: str) -> str:
    return next(
        c["id"] for c in _channels(email)
        if c["kind"] == "department" and c["department"] == "pool"
    )


def _land_dept(email: str) -> str:
    return next(
        c["id"] for c in _channels(email)
        if c["kind"] == "department" and c["department"] == "landscape"
    )


def _post_clip(email: str, channel_id: str, reply_to: str | None = None):
    data = {"channel_id": channel_id, "duration_ms": "2000"}
    if reply_to:
        data["reply_to_message_id"] = reply_to
    return requests.post(
        f"{API}/walkie/messages",
        headers=_hdr(email),
        data=data,
        files={"audio_file": ("clip.webm",
                              b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 200,
                              "audio/webm")},
        timeout=TIMEOUT,
    )


# ═══════════════════════════════════════════════════════════════════
def test_reply_happy_path_populates_reply_preview_on_get():
    ch = _all_hands(USERS["admin"])
    parent = _post_clip(USERS["admin"], ch).json()["message"]
    r = _post_clip(USERS["admin"], ch, reply_to=parent["id"])
    assert r.status_code == 200, r.text
    reply_id = r.json()["message"]["id"]
    # GET returns the reply with a populated reply_preview.
    r2 = requests.get(f"{API}/walkie/messages?channel_id={ch}",
                      headers=_hdr(USERS["admin"]), timeout=TIMEOUT)
    assert r2.status_code == 200
    row = next(m for m in r2.json()["messages"] if m["id"] == reply_id)
    assert row.get("reply_to_message_id") == parent["id"]
    prev = row.get("reply_preview")
    assert prev is not None
    assert prev["id"] == parent["id"]
    assert prev["deleted"] is False
    assert prev["duration_ms"] == parent["duration_ms"]
    assert prev["sender_display_name"]  # non-empty


def test_reply_to_wrong_channel_is_400(sync_db):
    """Parent lives in landscape dept, reply attempted in pool dept — 400."""
    admin = USERS["admin"]
    parent = _post_clip(admin, _land_dept(admin)).json()["message"]
    r = _post_clip(admin, _pool_dept(admin), reply_to=parent["id"])
    assert r.status_code == 400
    assert "wrong_channel" in r.json()["detail"]


def test_reply_to_nonexistent_message_is_404():
    ch = _all_hands(USERS["admin"])
    r = _post_clip(USERS["admin"], ch, reply_to="does_not_exist_" + uuid.uuid4().hex)
    assert r.status_code == 404


def test_reply_to_all_hands_from_tech_is_403():
    """Broadcast gate still fires for replies — a tech-pool user
    cannot post to all-hands even when quoting an existing clip."""
    admin_ch = _all_hands(USERS["admin"])
    parent = _post_clip(USERS["admin"], admin_ch).json()["message"]
    r = _post_clip(USERS["tech_pool"], admin_ch, reply_to=parent["id"])
    assert r.status_code == 403
    assert "admins" in r.json()["detail"].lower()


def test_reply_survives_when_parent_ttl_expires(sync_db):
    """Simulate TTL-eviction by deleting the parent message row after
    the reply is posted, then GET the channel — the reply row still
    surfaces with ``reply_preview.deleted: True`` and the pointer
    fields nulled out."""
    admin = USERS["admin"]
    ch = _all_hands(admin)
    parent = _post_clip(admin, ch).json()["message"]
    reply = _post_clip(admin, ch, reply_to=parent["id"]).json()["message"]
    # Simulate the TTL sweep.
    sync_db.walkie_messages.delete_one({"id": parent["id"]})
    r = requests.get(f"{API}/walkie/messages?channel_id={ch}",
                     headers=_hdr(admin), timeout=TIMEOUT)
    assert r.status_code == 200
    row = next(m for m in r.json()["messages"] if m["id"] == reply["id"])
    prev = row["reply_preview"]
    assert prev["deleted"] is True
    assert prev["id"] is None
    assert prev["sender_display_name"] is None
    assert prev["duration_ms"] is None


def test_cross_tenant_reply_is_404(sync_db):
    """Insert a synthetic parent under a foreign tenant_id and confirm
    the aquaterra admin can't reply to it (surfaces as 404, not 400).
    Locks the tenant-isolation guard."""
    admin = USERS["admin"]
    ch = _all_hands(admin)
    foreign_id = f"foreign_parent_{uuid.uuid4().hex}"
    sync_db.walkie_messages.insert_one({
        "id": foreign_id,
        "tenant_id": "some_other_tenant",
        "channel_id": ch,
        "sender_user_id": "foreign_user",
        "audio_file_id": "f",
        "duration_ms": 2000,
        "waveform_peaks": [],
        "created_at": "2026-02-07T00:00:00Z",
    })
    try:
        r = _post_clip(admin, ch, reply_to=foreign_id)
        assert r.status_code == 404
    finally:
        sync_db.walkie_messages.delete_one({"id": foreign_id})


def test_pinned_parent_with_replies_keeps_pin_on_top(sync_db):
    """Pinning a parent that has replies must NOT hoist the replies
    to the top — pin at index 0, replies still ordered by
    ``created_at desc`` beneath it."""
    admin = USERS["admin"]
    ch = _all_hands(admin)
    parent = _post_clip(admin, ch).json()["message"]
    _reply1 = _post_clip(admin, ch, reply_to=parent["id"]).json()["message"]
    _reply2 = _post_clip(admin, ch, reply_to=parent["id"]).json()["message"]
    # Pin the parent.
    r = requests.post(f"{API}/walkie/channels/{ch}/pin",
                      headers=_hdr(admin), json={"message_id": parent["id"]}, timeout=TIMEOUT)
    assert r.status_code == 200
    r2 = requests.get(f"{API}/walkie/messages?channel_id={ch}",
                      headers=_hdr(admin), timeout=TIMEOUT)
    msgs = r2.json()["messages"]
    assert msgs[0]["id"] == parent["id"]
    assert msgs[0]["is_pinned"] is True
    # Replies appear somewhere below the pin — NOT hoisted.
    reply_ids = {_reply1["id"], _reply2["id"]}
    below_ids = {m["id"] for m in msgs[1:]}
    assert reply_ids.issubset(below_ids)
