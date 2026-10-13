"""P2 interrupt · Feb-2026 — Login-selection patch for duplicate
role=customer rows (Option A-smart+log).

Complements, does NOT replace, the human-gated prod remediation plan.

Locks seven invariants on the ``POST /auth/login`` handler when the
candidate list carries ≥2 role=customer rows with distinct customer_ids:

  1. Orphan-drop preference: a row whose ``customer_id`` resolves to a
     deleted / merged / missing customer doc is dropped; a live-cid
     row wins even if orphan was more recent.
  2. Live-row sort by ``temp_password_issued_at`` DESC: when two
     live-cid rows both match, the one with the newer temp-password
     timestamp wins.
  3. Password-verify wins after sort: ``matches`` is already filtered
     on verify_password upstream, so the sort just picks WHICH matching
     row to return — a row whose hash doesn't verify never enters
     ``matches`` in the first place.  This test exercises the implicit
     invariant via a two-row setup where only the older row's hash
     matches.
  4. All-orphan fallback: if every candidate has a dead customer_id,
     the live-filter leaves 0 rows — fall through to the original
     ``matches[0]`` so the user is NOT locked out.
  5. Single-candidate no-op: a plain non-duplicate login does NOT
     touch the duplicate-resolution block (no WARN log, no audit row).
  6. WARN log payload shape: structured ``email_sha8`` key, never raw
     email; ``selection_source="temp_password_issued_at"``.
  7. ``auth.login.duplicate_resolved`` audit row written on
     duplicate-resolved login (``email_sha8`` only, no PII).

The pre-existing Commit-2 "PORTAL-INVITE-EMAIL-COLLISION-FIX
observability" WARN fires at a DIFFERENT stage (post-selection, on
``matches`` enumeration) — unchanged by this patch and NOT asserted
on here.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from models import LoginRequest


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_ENV = {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
        for k, v in _ENV.items()}
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db_everywhere():
    import config
    config.db = _DB
    for mod in ("routers.auth", "routers.tenants"):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"p2il-{uuid4().hex[:8]}"
TENANT = f"{PREFIX}-tenant"
EMAIL = f"{PREFIX}-dup@example.com"
PASSWORD = "sharedpass123"


class _FakeRequest:
    def __init__(self):
        self.client = type("c", (), {"host": "127.0.0.1"})
        self.headers = {}


async def _seed_tenant():
    await _DB.tenants.insert_one({"id": TENANT, "name": "T",
        "timezone": "America/Phoenix", "settings": {}})


async def _seed_customer(cid, *, deleted=False, merged_into=None):
    doc = {"id": cid, "tenant_id": TENANT, "name": f"C-{cid[:6]}"}
    if deleted:
        doc["deleted_at"] = "2026-02-01T00:00:00+00:00"
    if merged_into:
        doc["merged_into_id"] = merged_into
    await _DB.customers.insert_one(doc)


async def _seed_user(uid, cid, *, pw_hash, temp_issued_at=None):
    doc = {
        "id": uid, "tenant_id": TENANT,
        "email": EMAIL, "password_hash": pw_hash,
        "role": "customer", "customer_id": cid,
    }
    if temp_issued_at:
        doc["temp_password_issued_at"] = temp_issued_at
    await _DB.users.insert_one(doc)


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("users", "customers", "audit_logs", "auth_audit"):
        await _DB[coll].delete_many({"$or": [
            {"id": rx}, {"tenant_id": rx}, {"customer_id": rx},
            {"email": EMAIL},
        ]})
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


async def _login():
    import routers.auth as auth_mod
    body = LoginRequest(email=EMAIL, password=PASSWORD)
    return await auth_mod.login(_FakeRequest(), body)


def _hash(pw):
    from utils import hash_password
    return hash_password(pw)


# ------------------------------------------------------------------
# Case 1 — orphan-drop preference
# ------------------------------------------------------------------
def test_orphan_drop_prefers_live_cid_even_when_orphan_is_more_recent():
    _run(_seed_tenant())
    live_cid = f"{PREFIX}-cust-live"
    orphan_cid = f"{PREFIX}-cust-orphan"
    _run(_seed_customer(live_cid))
    _run(_seed_customer(orphan_cid, deleted=True))
    pw_hash = _hash(PASSWORD)
    _run(_seed_user(f"{PREFIX}-u-live", live_cid, pw_hash=pw_hash,
                       temp_issued_at="2026-02-01T00:00:00+00:00"))
    _run(_seed_user(f"{PREFIX}-u-orphan", orphan_cid, pw_hash=pw_hash,
                       temp_issued_at="2026-02-10T00:00:00+00:00"))
    out = _run(_login())
    assert out.get("access_token")
    assert out["user"]["customer_id"] == live_cid
    assert out["user"]["id"] == f"{PREFIX}-u-live"


# ------------------------------------------------------------------
# Case 2 — live-row sort by temp_password_issued_at DESC
# ------------------------------------------------------------------
def test_live_rows_sort_by_temp_password_issued_at_desc_newer_wins():
    _run(_seed_tenant())
    old_cid = f"{PREFIX}-cust-old"
    new_cid = f"{PREFIX}-cust-new"
    _run(_seed_customer(old_cid))
    _run(_seed_customer(new_cid))
    pw_hash = _hash(PASSWORD)
    _run(_seed_user(f"{PREFIX}-u-old", old_cid, pw_hash=pw_hash,
                       temp_issued_at="2026-01-15T00:00:00+00:00"))
    _run(_seed_user(f"{PREFIX}-u-new", new_cid, pw_hash=pw_hash,
                       temp_issued_at="2026-02-20T00:00:00+00:00"))
    out = _run(_login())
    assert out["user"]["customer_id"] == new_cid


# ------------------------------------------------------------------
# Case 3 — password-verify wins after sort (newer row's hash doesn't
# match, older row's does → older wins because newer isn't in matches)
# ------------------------------------------------------------------
def test_password_verify_filters_before_sort_so_only_matching_rows_sort():
    _run(_seed_tenant())
    old_cid = f"{PREFIX}-cust-pw-old"
    new_cid = f"{PREFIX}-cust-pw-new"
    _run(_seed_customer(old_cid))
    _run(_seed_customer(new_cid))
    # Older row's hash matches PASSWORD; newer row's hash matches a
    # different password so verify_password returns False on it.
    _run(_seed_user(f"{PREFIX}-u-old", old_cid,
                       pw_hash=_hash(PASSWORD),
                       temp_issued_at="2026-01-15T00:00:00+00:00"))
    _run(_seed_user(f"{PREFIX}-u-new", new_cid,
                       pw_hash=_hash("different-password"),
                       temp_issued_at="2026-02-20T00:00:00+00:00"))
    out = _run(_login())
    # Only ONE match (old row); older wins because newer isn't in the
    # verify-filtered set at all.  The Option A-smart block only sees
    # ``matches`` which has 1 element, so single-candidate path runs
    # (no duplicate resolution needed).
    assert out["user"]["customer_id"] == old_cid


# ------------------------------------------------------------------
# Case 4 — all-orphan fallback, no lockout
# ------------------------------------------------------------------
def test_all_orphan_candidates_fall_through_no_lockout():
    _run(_seed_tenant())
    cid1 = f"{PREFIX}-cust-dead-1"
    cid2 = f"{PREFIX}-cust-dead-2"
    _run(_seed_customer(cid1, deleted=True))
    _run(_seed_customer(cid2, merged_into=f"{PREFIX}-ghost"))
    pw_hash = _hash(PASSWORD)
    _run(_seed_user(f"{PREFIX}-u-dead-1", cid1, pw_hash=pw_hash))
    _run(_seed_user(f"{PREFIX}-u-dead-2", cid2, pw_hash=pw_hash))
    out = _run(_login())
    # User is NOT locked out.  Login succeeds against original
    # matches[0] (the first candidate in enumeration order).
    assert out.get("access_token")
    assert out["user"]["customer_id"] in (cid1, cid2)
    # No duplicate-resolved audit row was written (fell through).
    rows = _run(_DB.audit_logs.find({
        "event": "auth.login.duplicate_resolved",
        "email_sha8": {"$exists": True},
    }, {"_id": 0}).to_list(10))
    # Filter to rows for this test's user ids.
    this_run = [r for r in rows
                if r.get("user_id", "").startswith(PREFIX)]
    assert this_run == []


# ------------------------------------------------------------------
# Case 5 — single-candidate no-op
# ------------------------------------------------------------------
def test_single_candidate_no_duplicate_resolution(caplog):
    _run(_seed_tenant())
    cid = f"{PREFIX}-cust-solo"
    _run(_seed_customer(cid))
    _run(_seed_user(f"{PREFIX}-u-solo", cid, pw_hash=_hash(PASSWORD)))
    caplog.set_level(logging.WARNING, logger="server")
    out = _run(_login())
    assert out["user"]["customer_id"] == cid
    assert "duplicate_customer_resolution" not in caplog.text
    rows = _run(_DB.audit_logs.count_documents({
        "event": "auth.login.duplicate_resolved",
        "user_id": f"{PREFIX}-u-solo",
    }))
    assert rows == 0


# ------------------------------------------------------------------
# Case 6 — WARN log payload shape (email_sha8, no PII)
# ------------------------------------------------------------------
def test_warn_log_payload_shape_on_orphan_drop(caplog):
    _run(_seed_tenant())
    live_cid = f"{PREFIX}-cust-warn-live"
    orphan_cid = f"{PREFIX}-cust-warn-orphan"
    _run(_seed_customer(live_cid))
    _run(_seed_customer(orphan_cid, deleted=True))
    pw_hash = _hash(PASSWORD)
    _run(_seed_user(f"{PREFIX}-u-warn-live", live_cid, pw_hash=pw_hash))
    _run(_seed_user(f"{PREFIX}-u-warn-orphan", orphan_cid, pw_hash=pw_hash))
    caplog.set_level(logging.WARNING, logger="server")
    _run(_login())
    # Scope the assertion to MY new warn log line only — the pre-
    # existing Commit-2 observability warning that fires at a later
    # stage (``matches`` enumeration) still logs the raw email per
    # its original design and is NOT what this patch controls.
    _my_warn_lines = [
        rec.getMessage() for rec in caplog.records
        if rec.levelno >= logging.WARNING
        and "duplicate_customer_resolution" in rec.getMessage()
        and "PORTAL-INVITE-EMAIL-COLLISION-FIX" not in rec.getMessage()
    ]
    assert len(_my_warn_lines) == 1, (
        f"expected exactly one duplicate_customer_resolution WARN; "
        f"got {len(_my_warn_lines)}: {_my_warn_lines!r}"
    )
    msg = _my_warn_lines[0]
    assert "email_sha8=" in msg
    # Raw email NEVER appears in the structured warn log that this
    # patch controls.
    assert EMAIL not in msg
    assert "orphan_count_dropped=1" in msg
    assert "selection_source=temp_password_issued_at" in msg
    # SHA8 is deterministic — compute it and assert it lands.
    import hashlib
    expected_sha8 = hashlib.sha256(EMAIL.encode("utf-8")).hexdigest()[:8]
    assert f"email_sha8={expected_sha8}" in msg


# ------------------------------------------------------------------
# Case 7 — auth.login.duplicate_resolved audit row written
# ------------------------------------------------------------------
def test_duplicate_resolved_audit_row_written():
    _run(_seed_tenant())
    live_cid = f"{PREFIX}-cust-aud-live"
    orphan_cid = f"{PREFIX}-cust-aud-orphan"
    _run(_seed_customer(live_cid))
    _run(_seed_customer(orphan_cid, deleted=True))
    pw_hash = _hash(PASSWORD)
    _run(_seed_user(f"{PREFIX}-u-aud-live", live_cid, pw_hash=pw_hash))
    _run(_seed_user(f"{PREFIX}-u-aud-orphan", orphan_cid, pw_hash=pw_hash))
    _run(_login())
    row = _run(_DB.audit_logs.find_one({
        "event": "auth.login.duplicate_resolved",
        "user_id": f"{PREFIX}-u-aud-live",
    }, {"_id": 0}))
    assert row is not None
    assert row["customer_id"] == live_cid
    assert row["tenant_id"] == TENANT
    assert row["orphan_count_dropped"] == 1
    assert row["actor"] == "login_handler"
    # Raw email never persisted.
    assert "email" not in row
    import hashlib
    assert row["email_sha8"] == (
        hashlib.sha256(EMAIL.encode("utf-8")).hexdigest()[:8]
    )
