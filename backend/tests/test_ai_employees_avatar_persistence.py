"""Feb-2026 · P24 — regression pins for AI employee avatar persistence.

Four assertions covering the reported production bug:

  1. ``PATCH /api/ai-employees/{eid}`` without ``avatar_url`` in the
     payload leaves the existing avatar_url unchanged.
  2. Sending ``avatar_url: <new-url>`` updates it.
  3. Sending ``avatar_url: null`` WITHOUT ``clear_avatar=true`` is
     silently dropped — the existing portrait is preserved. This is
     the reported bug fix.
  4. Sending ``clear_avatar=true`` explicitly wipes the field.

Plus one integration pin on the dedupe merge:

  5. When two rows for the same ``(tenant_id, key)`` are collapsed
     and only the loser has ``avatar_url``, the survivor inherits
     it before deletion.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


from migrations.task_jj_dedupe_ai_employees import (
    _dedupe_within_tenant_groups,
)

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": "password123"},
                        timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"})["tenant_id"]


def _seed_employee(tid: str, *, key: str, avatar_url: str | None) -> str:
    eid = f"TEST_p24_{uuid.uuid4().hex[:8]}"
    _sync.ai_employees.insert_one({
        "id": eid, "tenant_id": tid, "key": key,
        "name": f"TEST P24 {key}", "role": "test", "audience": "admin",
        "avatar_emoji": "🧪", "avatar_url": avatar_url,
        "system_prompt": "test", "read_access_scope": "customer_scoped",
        "active": True,
        "created_at": "2026-06-01T09:00:00+00:00",
        "updated_at": "2026-06-01T09:00:00+00:00",
    })
    return eid


def _cleanup(prefix: str = "TEST_p24_") -> None:
    _sync.ai_employees.delete_many({"id": {"$regex": f"^{prefix}"}})


# ─── 1. PATCH without avatar_url leaves existing value ───────────────

def test_patch_without_avatar_url_leaves_it_unchanged(admin_h, aquaterra_tid):
    eid = _seed_employee(aquaterra_tid, key=f"kA_{uuid.uuid4().hex[:6]}",
                            avatar_url="/avatars/personas/original.jpg")
    try:
        r = requests.patch(f"{API}/ai-employees/{eid}",
                              json={"name": "Renamed"},
                              headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Renamed"
        doc = _sync.ai_employees.find_one({"id": eid})
        assert doc["avatar_url"] == "/avatars/personas/original.jpg"
    finally:
        _cleanup()


# ─── 2. PATCH with a new avatar_url updates the field ────────────────

def test_patch_with_new_avatar_url_updates(admin_h, aquaterra_tid):
    eid = _seed_employee(aquaterra_tid, key=f"kB_{uuid.uuid4().hex[:6]}",
                            avatar_url="/avatars/personas/original.jpg")
    try:
        r = requests.patch(
            f"{API}/ai-employees/{eid}",
            json={"avatar_url": "/avatars/personas/new.jpg"},
            headers=admin_h, timeout=15,
        )
        assert r.status_code == 200, r.text
        doc = _sync.ai_employees.find_one({"id": eid})
        assert doc["avatar_url"] == "/avatars/personas/new.jpg"
    finally:
        _cleanup()


# ─── 3. PATCH avatar_url=null WITHOUT clear_avatar is DROPPED ───────

def test_patch_avatar_url_null_without_clear_flag_is_dropped(
    admin_h, aquaterra_tid,
):
    """This is the reported prod bug: partial forms shipping
    ``{avatar_url: null}`` used to silently wipe portraits.
    """
    eid = _seed_employee(aquaterra_tid, key=f"kC_{uuid.uuid4().hex[:6]}",
                            avatar_url="/avatars/personas/preserved.jpg")
    try:
        r = requests.patch(
            f"{API}/ai-employees/{eid}",
            json={"avatar_url": None},
            headers=admin_h, timeout=15,
        )
        assert r.status_code == 200, r.text
        doc = _sync.ai_employees.find_one({"id": eid})
        assert doc["avatar_url"] == "/avatars/personas/preserved.jpg", \
            "P24 fix: avatar_url=null without clear_avatar must be dropped"

        # Same guard on empty string.
        r2 = requests.patch(
            f"{API}/ai-employees/{eid}",
            json={"avatar_url": "   "},
            headers=admin_h, timeout=15,
        )
        assert r2.status_code == 200, r2.text
        doc2 = _sync.ai_employees.find_one({"id": eid})
        assert doc2["avatar_url"] == "/avatars/personas/preserved.jpg"
    finally:
        _cleanup()


# ─── 4. clear_avatar=true explicitly wipes the field ─────────────────

def test_patch_with_clear_avatar_true_wipes_field(admin_h, aquaterra_tid):
    eid = _seed_employee(aquaterra_tid, key=f"kD_{uuid.uuid4().hex[:6]}",
                            avatar_url="/avatars/personas/wipeme.jpg")
    try:
        r = requests.patch(
            f"{API}/ai-employees/{eid}",
            json={"clear_avatar": True},
            headers=admin_h, timeout=15,
        )
        assert r.status_code == 200, r.text
        doc = _sync.ai_employees.find_one({"id": eid})
        assert doc.get("avatar_url") in (None, ""), \
            "clear_avatar=true must nullify the field explicitly"
    finally:
        _cleanup()


# ─── 5. Dedupe migration promotes loser's avatar_url ─────────────────

def test_dedupe_merge_promotes_loser_avatar_url_to_survivor():
    """Seed two rows for the same ``(tenant_id, key)`` where only the
    loser carries ``avatar_url``. After the P24-enhanced dedupe runs,
    the survivor must inherit the loser's avatar before the loser is
    deleted. Fills-in-blanks only — the survivor's other populated
    fields must not be overwritten.
    """
    tid = f"TEST_p24_dedupe_{uuid.uuid4().hex[:8]}"
    key = "dupe-key"
    survivor_id = f"TEST_p24_survivor_{uuid.uuid4().hex[:6]}"
    loser_id = f"TEST_p24_loser_{uuid.uuid4().hex[:6]}"

    # Temporarily drop the (tenant_id, key) unique index so we can
    # actually seed a duplicate pair — the whole point of task_jj
    # is to collapse historical dupes that existed before the index
    # was installed. We restore the index in the finally block.
    _idx_name = "phase34_task_jj_tenant_key_uniq"
    _sync.ai_employees.drop_index(_idx_name)
    try:
        # The "would-be-winner" has MORE populated fields overall but
        # no avatar. The "would-be-loser" has fewer populated fields
        # but carries the avatar we need to rescue. This is the exact
        # shape that caused prod portraits to vanish.
        _sync.ai_employees.insert_many([
        {"id": survivor_id, "tenant_id": tid, "key": key,
          "name": "Survivor",
          "role": "detailed role",
          "audience": "admin",
          "avatar_url": None,       # <-- empty on the survivor
          "avatar_emoji": "🏆",
          "system_prompt": "survivor prompt",
          "read_access_scope": "customer_scoped",
          "brand_voice_snippet": "brand voice",
          "active": True,
          "created_at": "2026-06-01T10:00:00+00:00",
          "updated_at": "2026-06-01T11:00:00+00:00"},
        {"id": loser_id, "tenant_id": tid, "key": key,
          "name": "Loser",
          "role": None,
          "audience": None,
          "avatar_url": "/avatars/personas/rescued.jpg",  # <-- to rescue
          "avatar_emoji": None,
          "system_prompt": None,
          "read_access_scope": None,
          "active": True,
          "created_at": "2026-06-01T09:00:00+00:00",
          "updated_at": "2026-06-01T10:00:00+00:00"},
    ])
        asyncio.get_event_loop().run_until_complete(
            _dedupe_within_tenant_groups(),
        )
        survivor = _sync.ai_employees.find_one({"id": survivor_id})
        assert survivor is not None, "survivor should NOT have been deleted"
        assert survivor["avatar_url"] == "/avatars/personas/rescued.jpg", \
            "P24 merge: survivor must inherit loser's avatar_url"
        # Survivor's own populated fields are NOT overwritten.
        assert survivor["system_prompt"] == "survivor prompt"
        assert survivor["name"] == "Survivor"
        # Loser is deleted.
        assert _sync.ai_employees.find_one({"id": loser_id}) is None
    finally:
        _sync.ai_employees.delete_many({"tenant_id": tid})
        # Restore the unique index we dropped for this test.
        try:
            _sync.ai_employees.create_index(
                [("tenant_id", 1), ("key", 1)],
                name=_idx_name, unique=True,
            )
        except Exception:
            pass
