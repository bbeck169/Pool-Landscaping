"""Phase 51a · Feb 2026 — Walkie-Talkie backend regression suite.

Async voice-clip MVP. Tests cover channel listing per role, direct
channel idempotency, message upload validation, tenant + recipient
isolation on listing, listened marking, TTL index presence, and
auto-provisioning of standard channels on first GET.

Uses ``requests`` against the running uvicorn server (mirrors the
pattern in ``test_phase56_20_auto_email.py``, ``test_widget_gh0.py``,
etc.) so we don't fight Starlette ``TestClient``'s per-request
anyio-portal loop against Motor's client binding.
"""
from __future__ import annotations

import os

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
TIMEOUT = 30

TID = "3814833a-dd0d-4bd9-90ea-351c24924649"  # aquaterra
USERS = {
    "super":       "super@aquaterra.com",
    "admin":       "admin@aquaterra.com",
    "manager":     "manager@aquaterra.com",
    "tech_pool":   "mike@aquaterra.com",
    "tech_land":   "landscaper@aquaterra.com",
    "customer":    "customer@aquaterra.com",
}
PW = "password123"


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def sync_db():
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        yield mc[be["DB_NAME"]]
    finally:
        mc.close()


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": PW}, timeout=TIMEOUT)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


def _hdr(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


def _resolve_uid(sync_db, email: str) -> str:
    u = sync_db.users.find_one({"email": email}, {"_id": 0, "id": 1})
    assert u and u.get("id"), f"no user row for {email}"
    return u["id"]


def _wav_bytes() -> bytes:
    return b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 200


def _get_all_hands(email: str) -> str:
    r = requests.get(f"{API}/walkie/channels", headers=_hdr(email), timeout=TIMEOUT)
    for c in r.json()["channels"]:
        if c["kind"] == "all_hands":
            return c["id"]
    raise AssertionError("no all_hands channel visible")


# ═══════════════════════════════════════════════════════════════════
# Channel listing per role
# ═══════════════════════════════════════════════════════════════════
def test_channels_super_admin_sees_standards():
    r = requests.get(f"{API}/walkie/channels", headers=_hdr(USERS["super"]), timeout=TIMEOUT)
    assert r.status_code == 200
    kinds = sorted({c["kind"] for c in r.json()["channels"]})
    assert "all_hands" in kinds
    assert "department" in kinds
    deps = sorted({c.get("department") for c in r.json()["channels"] if c["kind"] == "department"})
    assert "pool" in deps and "landscape" in deps


def test_channels_technician_pool_sees_only_pool_department():
    r = requests.get(f"{API}/walkie/channels", headers=_hdr(USERS["tech_pool"]), timeout=TIMEOUT)
    assert r.status_code == 200
    deps = [c.get("department") for c in r.json()["channels"] if c["kind"] == "department"]
    assert deps == ["pool"]


def test_channels_technician_landscape_sees_only_landscape_department():
    r = requests.get(f"{API}/walkie/channels", headers=_hdr(USERS["tech_land"]), timeout=TIMEOUT)
    assert r.status_code == 200
    deps = [c.get("department") for c in r.json()["channels"] if c["kind"] == "department"]
    assert deps == ["landscape"]


def test_channels_customer_is_403():
    r = requests.get(f"{API}/walkie/channels", headers=_hdr(USERS["customer"]), timeout=TIMEOUT)
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# Direct channel creation idempotency
# ═══════════════════════════════════════════════════════════════════
def test_direct_channel_is_idempotent(sync_db):
    admin_hdr = _hdr(USERS["admin"])
    tech_uid = _resolve_uid(sync_db, USERS["tech_pool"])
    r1 = requests.post(f"{API}/walkie/channels/direct",
                       headers=admin_hdr, json={"user_id": tech_uid}, timeout=TIMEOUT)
    assert r1.status_code == 200, r1.text
    ch1 = r1.json()["channel"]
    r2 = requests.post(f"{API}/walkie/channels/direct",
                       headers=admin_hdr, json={"user_id": tech_uid}, timeout=TIMEOUT)
    assert r2.status_code == 200
    assert r2.json()["channel"]["id"] == ch1["id"]


def test_direct_channel_rejects_customer_target(sync_db):
    cust_uid = _resolve_uid(sync_db, USERS["customer"])
    r = requests.post(f"{API}/walkie/channels/direct",
                      headers=_hdr(USERS["admin"]),
                      json={"user_id": cust_uid}, timeout=TIMEOUT)
    assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# Message upload validation
# ═══════════════════════════════════════════════════════════════════
def test_message_upload_happy_path():
    ch_id = _get_all_hands(USERS["admin"])
    r = requests.post(
        f"{API}/walkie/messages",
        headers=_hdr(USERS["admin"]),
        data={"channel_id": ch_id, "duration_ms": "3000"},
        files={"audio_file": ("clip.webm", _wav_bytes(), "audio/webm")},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, r.text
    msg = r.json()["message"]
    assert msg["duration_ms"] == 3000
    assert msg["recipient_count"] >= 1


def test_message_upload_rejects_oversized_audio():
    ch_id = _get_all_hands(USERS["admin"])
    huge = b"\x00" * (3 * 1024 * 1024)  # 3 MB
    r = requests.post(
        f"{API}/walkie/messages",
        headers=_hdr(USERS["admin"]),
        data={"channel_id": ch_id, "duration_ms": "3000"},
        files={"audio_file": ("clip.webm", huge, "audio/webm")},
        timeout=TIMEOUT,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "AUDIO_TOO_LARGE"


def test_message_upload_rejects_wrong_content_type():
    ch_id = _get_all_hands(USERS["admin"])
    r = requests.post(
        f"{API}/walkie/messages",
        headers=_hdr(USERS["admin"]),
        data={"channel_id": ch_id, "duration_ms": "3000"},
        files={"audio_file": ("clip.txt", b"hello", "text/plain")},
        timeout=TIMEOUT,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "UNSUPPORTED_AUDIO_MIME"


def test_message_upload_rejects_over_30s_duration():
    ch_id = _get_all_hands(USERS["admin"])
    r = requests.post(
        f"{API}/walkie/messages",
        headers=_hdr(USERS["admin"]),
        data={"channel_id": ch_id, "duration_ms": "45000"},
        files={"audio_file": ("clip.webm", _wav_bytes(), "audio/webm")},
        timeout=TIMEOUT,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "DURATION_OUT_OF_RANGE"


def test_message_upload_rejects_non_member_channel():
    """A pool technician cannot send to the landscape department channel."""
    r = requests.get(f"{API}/walkie/channels", headers=_hdr(USERS["admin"]), timeout=TIMEOUT)
    land_ch_id = next(
        c["id"] for c in r.json()["channels"]
        if c["kind"] == "department" and c["department"] == "landscape"
    )
    r = requests.post(
        f"{API}/walkie/messages",
        headers=_hdr(USERS["tech_pool"]),
        data={"channel_id": land_ch_id, "duration_ms": "3000"},
        files={"audio_file": ("clip.webm", _wav_bytes(), "audio/webm")},
        timeout=TIMEOUT,
    )
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# Message listing + listened marking
# ═══════════════════════════════════════════════════════════════════
def test_list_messages_and_mark_listened():
    ch_id = _get_all_hands(USERS["admin"])
    # Send a fresh clip from admin.
    r = requests.post(
        f"{API}/walkie/messages",
        headers=_hdr(USERS["admin"]),
        data={"channel_id": ch_id, "duration_ms": "2000"},
        files={"audio_file": ("clip.webm", _wav_bytes(), "audio/webm")},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200
    msg_id = r.json()["message"]["id"]
    # Pool technician (recipient) lists messages — should see this one.
    r2 = requests.get(
        f"{API}/walkie/messages?channel_id={ch_id}",
        headers=_hdr(USERS["tech_pool"]),
        timeout=TIMEOUT,
    )
    assert r2.status_code == 200
    ids = [m["id"] for m in r2.json()["messages"]]
    assert msg_id in ids
    # Mark listened.
    r3 = requests.post(
        f"{API}/walkie/messages/{msg_id}/listened",
        headers=_hdr(USERS["tech_pool"]),
        timeout=TIMEOUT,
    )
    assert r3.status_code == 200
    # Idempotent second call.
    r4 = requests.post(
        f"{API}/walkie/messages/{msg_id}/listened",
        headers=_hdr(USERS["tech_pool"]),
        timeout=TIMEOUT,
    )
    assert r4.status_code == 200


def test_mark_listened_404_when_not_a_recipient():
    """The sender has no receipt row so they can't mark their own
    message as listened."""
    ch_id = _get_all_hands(USERS["admin"])
    r = requests.post(
        f"{API}/walkie/messages",
        headers=_hdr(USERS["admin"]),
        data={"channel_id": ch_id, "duration_ms": "2000"},
        files={"audio_file": ("clip.webm", _wav_bytes(), "audio/webm")},
        timeout=TIMEOUT,
    )
    msg_id = r.json()["message"]["id"]
    r2 = requests.post(
        f"{API}/walkie/messages/{msg_id}/listened",
        headers=_hdr(USERS["admin"]),
        timeout=TIMEOUT,
    )
    assert r2.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# TTL index presence + auto-provisioning
# ═══════════════════════════════════════════════════════════════════
def test_ttl_index_exists_on_walkie_messages(sync_db):
    # Trigger a hit so bootstrap has definitely run.
    r = requests.get(f"{API}/walkie/channels", headers=_hdr(USERS["admin"]), timeout=TIMEOUT)
    assert r.status_code == 200
    info = sync_db.walkie_messages.index_information()
    matched = [
        (name, spec) for name, spec in info.items()
        if any(k[0] == "expires_at" for k in spec.get("key", []))
        and spec.get("expireAfterSeconds") == 0
    ]
    assert matched, (
        f"No TTL index found on walkie_messages.expires_at. "
        f"index_information() = {info}"
    )


def test_auto_provision_of_standard_channels_on_first_get(sync_db):
    """Even if the aquaterra bootstrap somehow missed a channel, the
    first GET must self-heal by creating it. Delete both department
    rows, hit the endpoint, and confirm they come back."""
    sync_db.walkie_channels.delete_many({"tenant_id": TID, "kind": "department"})
    r = requests.get(f"{API}/walkie/channels", headers=_hdr(USERS["admin"]), timeout=TIMEOUT)
    assert r.status_code == 200
    deps = sorted({
        c["department"] for c in r.json()["channels"] if c["kind"] == "department"
    })
    assert deps == ["landscape", "pool"]
