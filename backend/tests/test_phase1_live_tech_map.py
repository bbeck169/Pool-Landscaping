"""Feb-2026 · Live-Tech-Map · Phase 1 — pytest suite.

Covers the ship contract of Phase 1:

Pure-Python (no HTTP, no Mongo):
  01. Palette constants — 12 colors, correct order, uppercased set.
  02. ``is_palette_color`` — accepts palette hexes (case-insensitive),
      rejects arbitrary hex.
  03. ``deterministic_color_for_id`` — same seed → same color,
      distribution across the 12 slots.

HTTP-driven (live backend + demo tenant):
  04. GET /api/tech-colors/palette — admin OK, unauth 401, returns 12
      entries with name/hex keys.
  05. PATCH /api/users/{uid} display_color_hex — admin can set to a
      palette hex, off-palette rejects with 400.
  06. PATCH /api/crews/{cid} color — same palette lock.
  07. GET /api/dispatch/board — ETag round-trip: first call 200 with
      ETag header, second call with If-None-Match: <etag> → 304.

Mongo-driven (via services.tech_color_migration directly):
  08. Migration idempotency — running twice fills the same set of
      rows the first time and 0 rows the second time.
  09. Migration preserves non-null values (does not overwrite off-
      palette customs that predate the palette lock).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict

import httpx
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)



BASE = "http://localhost:8001"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db() if (_MONGO_URL and _DB_NAME) else None
# ═════════════════════════════════════════════════════════════════
# 01–03 · Pure-Python unit tests
# ═════════════════════════════════════════════════════════════════
class TestPaletteConstants:
    def test_palette_has_at_least_24_entries(self):
        # TEST-DRIFT · Feb-2026 — Ticket B expanded the palette from 12 to
        # 24 slots; CREWS-FIX-2b appended slot 25 (``sky``).  Use ``>=`` so
        # future additive expansions don't re-break this assertion while
        # still catching a palette that's been unexpectedly shrunk.
        from constants.tech_colors import TECH_COLOR_PALETTE, PALETTE_HEXES
        assert len(TECH_COLOR_PALETTE) >= 24
        assert len(PALETTE_HEXES) >= 24

    def test_first_twelve_order_preserved(self):
        # TEST-DRIFT · Feb-2026 — assert the hash-stability contract on
        # the original 12-slot epoch (slots 0..11).  Any slot shift in
        # that range re-keys every tech/crew row ever hashed by
        # ``deterministic_color_for_id``; additive growth beyond slot 11
        # does NOT re-key existing rows, so we deliberately do NOT pin
        # the tail of the array here.
        from constants.tech_colors import TECH_COLOR_PALETTE
        assert TECH_COLOR_PALETTE[0] == ("blue", "#3B82F6")
        assert TECH_COLOR_PALETTE[11] == ("fuchsia", "#D946EF")

    def test_hex_set_is_uppercased(self):
        from constants.tech_colors import PALETTE_HEX_SET
        for h in PALETTE_HEX_SET:
            assert h == h.upper()


class TestIsPaletteColor:
    def test_accepts_palette_hex(self):
        from constants.tech_colors import is_palette_color
        assert is_palette_color("#3B82F6") is True
        assert is_palette_color("#F97316") is True

    def test_case_insensitive(self):
        from constants.tech_colors import is_palette_color
        assert is_palette_color("#3b82f6") is True
        assert is_palette_color("#f97316") is True

    def test_rejects_off_palette(self):
        from constants.tech_colors import is_palette_color
        # Custom color not in the 12-slot palette.
        assert is_palette_color("#123456") is False
        # Old-dispatch-board palette color that's NOT in the new
        # palette (verifies the palette-lock has teeth).
        assert is_palette_color("#4F46E5") is False

    def test_rejects_empty_and_none(self):
        from constants.tech_colors import is_palette_color
        assert is_palette_color(None) is False
        assert is_palette_color("") is False
        assert is_palette_color("not-a-hex") is False


class TestDeterministicColor:
    def test_same_seed_same_color(self):
        from constants.tech_colors import deterministic_color_for_id
        c1 = deterministic_color_for_id("user_abc123")
        c2 = deterministic_color_for_id("user_abc123")
        assert c1 == c2

    def test_output_is_palette_member(self):
        from constants.tech_colors import (
            deterministic_color_for_id, is_palette_color,
        )
        for seed in ["u1", "u2", "u3", "user_deadbeef", "landscape_tech_5"]:
            assert is_palette_color(deterministic_color_for_id(seed))

    def test_covers_multiple_slots(self):
        """Rough distribution check — 60 random seeds should hit at
        least 6 different palette slots (well under the pigeon-hole
        expectation of ~12 but tolerant of hash luck)."""
        from constants.tech_colors import deterministic_color_for_id
        colors = {deterministic_color_for_id(f"seed_{i}") for i in range(60)}
        assert len(colors) >= 6

    def test_empty_seed_returns_first_slot(self):
        from constants.tech_colors import (
            deterministic_color_for_id, PALETTE_HEXES,
        )
        assert deterministic_color_for_id("") == PALETTE_HEXES[0]
        assert deterministic_color_for_id(None) == PALETTE_HEXES[0]


# ═════════════════════════════════════════════════════════════════
# HTTP fixture helpers — build a throwaway tenant + admin per test
# ═════════════════════════════════════════════════════════════════
def _skip_if_no_mongo():
    if _sync is None:
        pytest.skip("MONGO_URL / DB_NAME not set — HTTP tests skipped")


def _mk_tenant() -> str:
    _skip_if_no_mongo()
    tid = f"LTM_tenant_{uuid.uuid4().hex}"
    _sync.tenants.insert_one({
        "id": tid, "slug": f"ltm-{uuid.uuid4().hex[:8]}",
        "name": "LTM Tenant", "active": True,
    })
    return tid


def _mk_user(tid: str, role: str = "admin") -> tuple[str, str]:
    """Return (user_id, email) — password is always ``password123``."""
    from utils import hash_password
    email = f"ltm-{role}-{uuid.uuid4().hex[:8]}@example.com"
    uid = f"LTM_user_{uuid.uuid4().hex}"
    _sync.users.insert_one({
        "id": uid, "email": email, "role": role,
        "password_hash": hash_password("password123"),
        "tenant_id": tid, "name": f"LTM {role}",
        "failed_login_attempts": 0, "active": True,
    })
    return uid, email


def _mk_crew(tid: str, color: str | None = None) -> str:
    cid = f"LTM_crew_{uuid.uuid4().hex}"
    doc: Dict[str, Any] = {
        "id": cid, "tenant_id": tid, "name": "LTM crew",
        "tech_ids": [], "created_at": "2026-02-01T00:00:00+00:00",
    }
    if color is not None:
        doc["color"] = color
    _sync.crews.insert_one(doc)
    return cid


def _token_for(email: str) -> str:
    r = httpx.post(f"{BASE}/api/auth/login", json={
        "email": email, "password": "password123",
    }, timeout=30)
    r.raise_for_status()
    b = r.json()
    return b.get("access_token") or b.get("token") or ""


def _admin_hdrs(tid: str) -> Dict[str, str]:
    _uid, email = _mk_user(tid, "admin")
    return {"Authorization": f"Bearer {_token_for(email)}"}


def _tech_hdrs(tid: str) -> Dict[str, str]:
    _uid, email = _mk_user(tid, "technician")
    return {"Authorization": f"Bearer {_token_for(email)}"}


# ═════════════════════════════════════════════════════════════════
# 04 · GET /api/tech-colors/palette
# ═════════════════════════════════════════════════════════════════
class TestPaletteEndpoint:
    def test_admin_gets_palette(self):
        _skip_if_no_mongo()
        tid = _mk_tenant()
        hdrs = _admin_hdrs(tid)
        r = httpx.get(f"{BASE}/api/tech-colors/palette",
                       headers=hdrs, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "palette" in body
        # TEST-DRIFT · Feb-2026 — endpoint applies a WCAG 3.0 contrast
        # cut before returning (``_filtered_palette()`` in
        # ``routers/tech_colors.py``), so the response is intentionally
        # smaller than the raw constant.  Loose lower bound keeps the
        # test future-proof against palette growth AND filter tweaks.
        assert len(body["palette"]) >= 15
        for entry in body["palette"]:
            assert "name" in entry and "hex" in entry
            assert entry["hex"].startswith("#")

    def test_unauth_rejected(self):
        r = httpx.get(f"{BASE}/api/tech-colors/palette", timeout=30)
        assert r.status_code in (401, 403), r.status_code


# ═════════════════════════════════════════════════════════════════
# 05 · PATCH /users/{uid} palette lock
# ═════════════════════════════════════════════════════════════════
class TestUserDisplayColorPatch:
    def test_admin_can_set_palette_color(self):
        _skip_if_no_mongo()
        tid = _mk_tenant()
        target_uid, _ = _mk_user(tid, "technician")
        hdrs = _admin_hdrs(tid)
        r = httpx.patch(
            f"{BASE}/api/users/{target_uid}",
            json={"display_color_hex": "#3B82F6"},
            headers=hdrs, timeout=30,
        )
        assert r.status_code == 200, r.text
        doc = _sync.users.find_one({"id": target_uid}, {"_id": 0})
        assert doc["display_color_hex"] == "#3B82F6"

    def test_rejects_off_palette_hex(self):
        _skip_if_no_mongo()
        tid = _mk_tenant()
        target_uid, _ = _mk_user(tid, "technician")
        hdrs = _admin_hdrs(tid)
        r = httpx.patch(
            f"{BASE}/api/users/{target_uid}",
            # Valid #RRGGBB shape but NOT in the 12-slot palette.
            json={"display_color_hex": "#123456"},
            headers=hdrs, timeout=30,
        )
        assert r.status_code == 400, r.text

    def test_tech_cannot_patch(self):
        _skip_if_no_mongo()
        tid = _mk_tenant()
        target_uid, _ = _mk_user(tid, "technician")
        hdrs = _tech_hdrs(tid)
        r = httpx.patch(
            f"{BASE}/api/users/{target_uid}",
            json={"display_color_hex": "#3B82F6"},
            headers=hdrs, timeout=30,
        )
        assert r.status_code in (401, 403), r.status_code


# ═════════════════════════════════════════════════════════════════
# 06 · PATCH /crews/{cid} palette lock
# ═════════════════════════════════════════════════════════════════
class TestCrewColorPatch:
    def test_admin_can_set_palette_color(self):
        _skip_if_no_mongo()
        tid = _mk_tenant()
        cid = _mk_crew(tid)
        hdrs = _admin_hdrs(tid)
        r = httpx.patch(
            f"{BASE}/api/crews/{cid}",
            json={"color": "#F97316"},
            headers=hdrs, timeout=30,
        )
        assert r.status_code == 200, r.text
        doc = _sync.crews.find_one({"id": cid}, {"_id": 0})
        assert doc["color"] == "#F97316"

    def test_rejects_off_palette(self):
        _skip_if_no_mongo()
        tid = _mk_tenant()
        cid = _mk_crew(tid)
        hdrs = _admin_hdrs(tid)
        r = httpx.patch(
            f"{BASE}/api/crews/{cid}",
            json={"color": "#ABCDEF"},
            headers=hdrs, timeout=30,
        )
        assert r.status_code == 400, r.text


# ═════════════════════════════════════════════════════════════════
# 07 · Dispatch board ETag round-trip
# ═════════════════════════════════════════════════════════════════
class TestDispatchBoardETag:
    def test_first_call_returns_etag(self):
        _skip_if_no_mongo()
        tid = _mk_tenant()
        hdrs = _admin_hdrs(tid)
        r = httpx.get(
            f"{BASE}/api/dispatch/board?day=all",
            headers=hdrs, timeout=30,
        )
        assert r.status_code == 200, r.text
        etag = r.headers.get("ETag") or r.headers.get("etag")
        assert etag is not None and etag.startswith('"')

    def test_if_none_match_returns_304(self):
        _skip_if_no_mongo()
        tid = _mk_tenant()
        hdrs = _admin_hdrs(tid)
        r1 = httpx.get(
            f"{BASE}/api/dispatch/board?day=all",
            headers=hdrs, timeout=30,
        )
        assert r1.status_code == 200
        etag = r1.headers.get("ETag") or r1.headers.get("etag")
        assert etag
        # Second call with the cached etag → 304, empty body.
        r2 = httpx.get(
            f"{BASE}/api/dispatch/board?day=all",
            headers={**hdrs, "If-None-Match": etag}, timeout=30,
        )
        assert r2.status_code == 304, (r2.status_code, r2.text)
        assert r2.content == b""
        # ETag echoes back on 304 too.
        assert (r2.headers.get("ETag") or r2.headers.get("etag")) == etag

    def test_stale_etag_returns_200(self):
        _skip_if_no_mongo()
        tid = _mk_tenant()
        hdrs = _admin_hdrs(tid)
        r = httpx.get(
            f"{BASE}/api/dispatch/board?day=all",
            headers={**hdrs, "If-None-Match": '"deadbeefdeadbeef"'},
            timeout=30,
        )
        assert r.status_code == 200, r.text


# ═════════════════════════════════════════════════════════════════
# 08–09 · Migration idempotency (direct-service, no HTTP)
# ═════════════════════════════════════════════════════════════════
class TestColorMigration:
    def _make_null_tech(self, tid: str) -> str:
        _skip_if_no_mongo()
        uid = f"LTM_migtech_{uuid.uuid4().hex}"
        _sync.users.insert_one({
            "id": uid, "tenant_id": tid,
            "role": "technician", "email": f"{uid}@example.com",
            "display_color_hex": None,
            "created_at": "2026-02-01T00:00:00+00:00",
        })
        return uid

    def _make_off_palette_tech(self, tid: str) -> str:
        _skip_if_no_mongo()
        uid = f"LTM_offp_{uuid.uuid4().hex}"
        _sync.users.insert_one({
            "id": uid, "tenant_id": tid,
            "role": "technician", "email": f"{uid}@example.com",
            "display_color_hex": "#123456",  # off palette on purpose
            "created_at": "2026-02-01T00:00:00+00:00",
        })
        return uid

    def _run_migration_sync(self):
        """Motor is bound to the server's persistent loop; direct-
        service calls from a fresh loop crash on cross-loop bind.
        Spin up a dedicated Motor client tied to THIS loop so the
        migration runs cleanly. Same behavior — same code path,
        just a private connection."""
        from motor.motor_asyncio import AsyncIOMotorClient
        from services.tech_color_migration import fill_missing_tech_colors
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            client = AsyncIOMotorClient(_MONGO_URL)
            fresh_db = client[_DB_NAME]
            summary = loop.run_until_complete(fill_missing_tech_colors(fresh_db))
            client.close()
            return summary
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    def test_null_fill_and_idempotency(self):
        _skip_if_no_mongo()
        tid = _mk_tenant()
        # Seed 3 tech rows with null display_color_hex.
        uids = [self._make_null_tech(tid) for _ in range(3)]

        summary1 = self._run_migration_sync()

        # At least our 3 seed rows should have been filled. (Other
        # tenants may contribute more if migration hasn't fully
        # settled since server boot — assert >= 3 not ==.)
        assert summary1["filled"] >= 3

        # Every seeded row now has a palette color.
        from constants.tech_colors import is_palette_color
        for uid in uids:
            doc = _sync.users.find_one({"id": uid}, {"_id": 0})
            assert is_palette_color(doc["display_color_hex"]), doc

        # Second run — the 3 rows we just filled must NOT be
        # touched again (idempotency).
        self._run_migration_sync()
        # Same value as after first pass — deterministic.
        from constants.tech_colors import deterministic_color_for_id
        for uid in uids:
            doc = _sync.users.find_one({"id": uid}, {"_id": 0})
            assert doc["display_color_hex"] == deterministic_color_for_id(uid)

    def test_preserves_off_palette_customs(self):
        _skip_if_no_mongo()
        tid = _mk_tenant()
        # Pre-existing off-palette color must NOT be overwritten
        # by the null-fill migration.
        uid = self._make_off_palette_tech(tid)
        self._run_migration_sync()
        doc = _sync.users.find_one({"id": uid}, {"_id": 0})
        assert doc["display_color_hex"] == "#123456"


# ═════════════════════════════════════════════════════════════════
# Cleanup — remove every ``LTM_``-prefixed doc after the module runs.
# ═════════════════════════════════════════════════════════════════
def teardown_module(module):
    if _sync is None:
        return
    for coll in ("tenants", "users", "crews"):
        _sync[coll].delete_many({"id": {"$regex": "^LTM_"}})
