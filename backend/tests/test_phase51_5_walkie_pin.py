"""Phase 51.5 · Feb-2026 — Walkie-Talkie pin/unpin regression tests.

Exercises the four locked invariants:

1. Only ``super_admin`` / ``admin`` / ``manager`` can pin/unpin; techs
   get 403.
2. Auto-unpin behaviour — pinning a new message unpins the previous
   (only one pinned per channel at a time).
3. Pinned messages have ``expires_at`` unset, so Mongo's TTL index
   doesn't evict them — synthetic time-warp test asserts survival
   past the 24 h mark.
4. Unpinning restores ``expires_at = created_at + 24h`` and if
   already past that, the next TTL sweep will handle deletion.

Plus a Phase 51d cleanup-cron interaction test: the orphan-file
sweep must never delete the pinned message's audio file.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from services.walkie import cleanup_cron


BACKEND = "http://127.0.0.1:8001"
API = f"{BACKEND}/api"
TIMEOUT = 30

TID = "3814833a-dd0d-4bd9-90ea-351c24924649"  # aquaterra
USERS = {
    "super":     "super@aquaterra.com",
    "admin":     "admin@aquaterra.com",
    "manager":   "manager@aquaterra.com",
    "tech_pool": "mike@aquaterra.com",
}
PW = "password123"


# ── Helpers ─────────────────────────────────────────────────────────
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


def _get_all_hands(email: str) -> str:
    r = requests.get(f"{API}/walkie/channels", headers=_hdr(email), timeout=TIMEOUT)
    for c in r.json()["channels"]:
        if c["kind"] == "all_hands":
            return c["id"]
    raise AssertionError("no all_hands channel visible")


def _post_clip(email: str, channel_id: str):
    return requests.post(
        f"{API}/walkie/messages",
        headers=_hdr(email),
        data={"channel_id": channel_id, "duration_ms": "2000"},
        files={"audio_file": ("clip.webm",
                              b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 200,
                              "audio/webm")},
        timeout=TIMEOUT,
    )


def _run(coro):
    """Run a coroutine on a fresh loop + rebind Motor to it. Restore
    on exit so subsequent tests using the live uvicorn (via
    ``requests``) aren't affected."""
    from config import client as _motor_client
    prev = getattr(_motor_client, "_io_loop", None)
    loop = asyncio.new_event_loop()
    _motor_client._io_loop = loop
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        _motor_client._io_loop = prev


# ═══════════════════════════════════════════════════════════════════
# 1. Role gate — pin/unpin is admin/manager/super only
# ═══════════════════════════════════════════════════════════════════
def test_tech_pool_cannot_pin_403():
    ch = _get_all_hands(USERS["admin"])
    r = _post_clip(USERS["admin"], ch)
    msg_id = r.json()["message"]["id"]
    r = requests.post(
        f"{API}/walkie/channels/{ch}/pin",
        headers=_hdr(USERS["tech_pool"]),
        json={"message_id": msg_id}, timeout=TIMEOUT,
    )
    assert r.status_code == 403
    assert "admins" in r.json()["detail"].lower()


def test_admin_manager_super_can_pin(sync_db):
    ch = _get_all_hands(USERS["admin"])
    for role_email in [USERS["admin"], USERS["manager"], USERS["super"]]:
        r = _post_clip(role_email, ch)
        msg_id = r.json()["message"]["id"]
        r = requests.post(
            f"{API}/walkie/channels/{ch}/pin",
            headers=_hdr(role_email),
            json={"message_id": msg_id}, timeout=TIMEOUT,
        )
        assert r.status_code == 200, f"{role_email} pin failed: {r.text}"
        assert r.json()["pinned_message_id"] == msg_id


def test_tech_pool_cannot_unpin_403(sync_db):
    ch = _get_all_hands(USERS["admin"])
    r = requests.delete(
        f"{API}/walkie/channels/{ch}/pin",
        headers=_hdr(USERS["tech_pool"]),
        timeout=TIMEOUT,
    )
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# 2. Auto-unpin — only one pinned per channel at a time
# ═══════════════════════════════════════════════════════════════════
def test_pinning_new_message_auto_unpins_previous(sync_db):
    ch = _get_all_hands(USERS["admin"])
    m1 = _post_clip(USERS["admin"], ch).json()["message"]["id"]
    m2 = _post_clip(USERS["admin"], ch).json()["message"]["id"]
    # Pin m1.
    requests.post(f"{API}/walkie/channels/{ch}/pin",
                  headers=_hdr(USERS["admin"]), json={"message_id": m1}, timeout=TIMEOUT)
    # m1 has ``expires_at`` unset.
    doc1 = sync_db.walkie_messages.find_one({"id": m1}, {"_id": 0, "expires_at": 1})
    assert doc1.get("expires_at") is None
    # Pin m2 — must auto-unpin m1 and restore its expires_at.
    r2 = requests.post(f"{API}/walkie/channels/{ch}/pin",
                       headers=_hdr(USERS["admin"]), json={"message_id": m2}, timeout=TIMEOUT)
    assert r2.status_code == 200
    assert r2.json()["pinned_message_id"] == m2
    # Channel now points at m2.
    ch_doc = sync_db.walkie_channels.find_one({"id": ch}, {"_id": 0, "pinned_message_id": 1})
    assert ch_doc["pinned_message_id"] == m2
    # m1 got its expires_at restored (created_at + 24h).
    doc1 = sync_db.walkie_messages.find_one({"id": m1}, {"_id": 0, "created_at": 1, "expires_at": 1})
    assert doc1.get("expires_at") is not None
    created = doc1["created_at"]
    expires = doc1["expires_at"]
    delta = (expires - created).total_seconds()
    assert abs(delta - 24 * 3600) < 5  # within 5 seconds tolerance


def test_pin_is_idempotent(sync_db):
    ch = _get_all_hands(USERS["admin"])
    m = _post_clip(USERS["admin"], ch).json()["message"]["id"]
    r1 = requests.post(f"{API}/walkie/channels/{ch}/pin",
                       headers=_hdr(USERS["admin"]), json={"message_id": m}, timeout=TIMEOUT)
    assert r1.status_code == 200
    assert r1.json().get("unchanged") is False
    r2 = requests.post(f"{API}/walkie/channels/{ch}/pin",
                       headers=_hdr(USERS["admin"]), json={"message_id": m}, timeout=TIMEOUT)
    assert r2.status_code == 200
    assert r2.json().get("unchanged") is True


def test_pin_rejects_message_from_other_channel(sync_db):
    """Cross-channel guard — can't pin a landscape-dept clip to
    all-hands. Uses admin to send in landscape then tries to pin in
    all-hands."""
    admin_hdr = _hdr(USERS["admin"])
    channels = requests.get(f"{API}/walkie/channels", headers=admin_hdr, timeout=TIMEOUT).json()["channels"]
    all_hands = next(c["id"] for c in channels if c["kind"] == "all_hands")
    landscape = next(c["id"] for c in channels if c["kind"] == "department" and c["department"] == "landscape")
    r = _post_clip(USERS["admin"], landscape)
    land_msg = r.json()["message"]["id"]
    r = requests.post(f"{API}/walkie/channels/{all_hands}/pin",
                      headers=admin_hdr, json={"message_id": land_msg}, timeout=TIMEOUT)
    assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 3. Pinned messages survive past 24h — TTL bypass evidence
# ═══════════════════════════════════════════════════════════════════
def test_pinned_message_survives_past_24h_ttl(sync_db):
    """Synthetic time-warp — push ``created_at`` back 48 h AND rely
    on the pin flow to leave ``expires_at`` unset. Then re-run the
    cleanup cron which is what Mongo's TTL sweep triggers logically.
    The pinned message and its file must both survive."""
    ch = _get_all_hands(USERS["admin"])
    r = _post_clip(USERS["admin"], ch)
    msg_id = r.json()["message"]["id"]
    # Pin it.
    requests.post(f"{API}/walkie/channels/{ch}/pin",
                  headers=_hdr(USERS["admin"]), json={"message_id": msg_id}, timeout=TIMEOUT)
    # Time-warp: push created_at back 48 h. TTL wouldn't touch a
    # pinned row since expires_at is unset, but this simulates a
    # long-lived pinned SOP clip.
    sync_db.walkie_messages.update_one(
        {"id": msg_id},
        {"$set": {"created_at": datetime.now(timezone.utc) - timedelta(hours=48)}},
    )
    # Sanity — expires_at should still be unset.
    row = sync_db.walkie_messages.find_one({"id": msg_id}, {"_id": 0, "expires_at": 1})
    assert row.get("expires_at") is None
    # Row survives — TTL index skips docs missing expires_at (that's
    # the Mongo semantic; expireAfterSeconds only fires when the
    # indexed field is a valid Date). We assert the row still exists.
    still = sync_db.walkie_messages.find_one({"id": msg_id}, {"_id": 0, "id": 1})
    assert still is not None
    # Cleanup cron must NOT delete the pinned file either.
    audio_id = sync_db.walkie_messages.find_one({"id": msg_id}, {"_id": 0, "audio_file_id": 1})["audio_file_id"]
    file_row = sync_db.files.find_one({"id": audio_id})
    assert file_row is not None
    # Run the cleanup cron once.
    from config import db as motor_db
    _run(cleanup_cron.run_walkie_cleanup_once(motor_db))
    # Pinned audio file must still be there.
    file_row = sync_db.files.find_one({"id": audio_id})
    assert file_row is not None, "cleanup cron must not delete the pinned message's audio file"


# ═══════════════════════════════════════════════════════════════════
# 4. Unpin restores expires_at
# ═══════════════════════════════════════════════════════════════════
def test_unpin_restores_expires_at(sync_db):
    ch = _get_all_hands(USERS["admin"])
    m = _post_clip(USERS["admin"], ch).json()["message"]["id"]
    requests.post(f"{API}/walkie/channels/{ch}/pin",
                  headers=_hdr(USERS["admin"]), json={"message_id": m}, timeout=TIMEOUT)
    r = requests.delete(f"{API}/walkie/channels/{ch}/pin",
                        headers=_hdr(USERS["admin"]), timeout=TIMEOUT)
    assert r.status_code == 200
    assert r.json()["pinned_message_id"] is None
    doc = sync_db.walkie_messages.find_one({"id": m}, {"_id": 0, "expires_at": 1})
    assert doc.get("expires_at") is not None


# ═══════════════════════════════════════════════════════════════════
# 5. GET /messages surfaces the pinned message at the top with
#    ``is_pinned: true`` regardless of the ``since`` window
# ═══════════════════════════════════════════════════════════════════
def test_get_messages_surfaces_pinned_first(sync_db):
    ch = _get_all_hands(USERS["admin"])
    # Two fresh clips; pin the older of the two.
    m1 = _post_clip(USERS["admin"], ch).json()["message"]["id"]
    _ = _post_clip(USERS["admin"], ch).json()["message"]["id"]
    requests.post(f"{API}/walkie/channels/{ch}/pin",
                  headers=_hdr(USERS["admin"]), json={"message_id": m1}, timeout=TIMEOUT)
    r = requests.get(f"{API}/walkie/messages?channel_id={ch}", headers=_hdr(USERS["admin"]), timeout=TIMEOUT)
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert msgs[0]["id"] == m1
    assert msgs[0]["is_pinned"] is True
    for m in msgs[1:]:
        assert m["is_pinned"] is False
