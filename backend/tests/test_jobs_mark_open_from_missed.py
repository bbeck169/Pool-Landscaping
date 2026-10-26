"""Ticket X · Feb-2026 — ``POST /jobs/{jid}/mark-open``.

Locks the behaviour of the missed → scheduled ("Open" in the
Schedule palette) admin transition endpoint.

Covers:
  1. Happy path — admin flips a ``missed`` job to ``scheduled``,
     reopened_from_missed_at timestamp is set, missed_at is
     cleared, 200 payload is the updated job.
  2. Precondition — non-missed status returns 409
     ``invalid_status_transition`` + no mutation on the row.
  3. Permission gate — non-admin role returns 403
     ``mark_open_forbidden`` + no mutation.
  4. Cross-tenant — 404 (same posture every other job endpoint
     uses so the existence of the target job doesn't leak).
  5. Audit log contents — type ``mark_open_from_missed``, actor,
     before_status / after_status metadata, job + tenant IDs.
  6. Idempotency — same ``X-Idempotency-Key`` replays the cached
     response + does NOT write a second audit entry.
  7. Nonexistent job — 404.

Hits live Mongo via the same scaffolding P47 missed-cleanup
tests already use, so the endpoint is tested end-to-end rather
than through a fake collection.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


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
    for mod in ("routers.jobs",):
        __import__(mod)
        import sys as _sys
        if hasattr(_sys.modules[mod], "db"):
            _sys.modules[mod].db = _DB


PREFIX = f"tx-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
TENANT_B = f"{PREFIX}-tenant-b"
ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin",
         "name": "Admin Alice"}
TECH = {"id": f"{PREFIX}-u-tech", "role": "technician",
        "name": "Tech Terry"}
CUSTOMER = {"id": f"{PREFIX}-u-cust", "role": "customer",
            "name": "Cust Carl"}


async def _seed_job(jid, tenant_id=TENANT_A, status="missed",
                      missed_at="2026-02-01T12:00:00Z"):
    doc = {
        "id": jid, "tenant_id": tenant_id,
        "customer_id": f"{PREFIX}-c1", "customer_name": "ACME Co",
        "service_type": "Pool",
        "status": status,
        "scheduled_date": "2026-02-01",
        "created_at": "2026-02-01T00:00:00Z",
    }
    if status == "missed":
        doc["missed_at"] = missed_at
    await _DB.jobs.insert_one(doc)


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in (_DB.jobs, _DB.activity_logs, _DB.idempotency_keys):
        try:
            await coll.delete_many({
                "$or": [{"id": rx}, {"job_id": rx},
                         {"tenant_id": rx}],
            })
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


class _Req:
    """Minimal Request stand-in — the endpoint only reads headers
    for the idempotency envelope (``X-Idempotency-Key``). Mirror
    the shape every other mark-* / reopen test in this suite uses."""
    def __init__(self, idem_key=None):
        self.headers = {}
        if idem_key:
            self.headers["X-Idempotency-Key"] = idem_key


async def _call(jid, user=ADMIN, tenant_id=TENANT_A, idem_key=None):
    from routers.jobs import mark_job_open_from_missed
    return await mark_job_open_from_missed(
        jid=jid,
        request=_Req(idem_key=idem_key),
        user=user,
        tenant={"id": tenant_id},
    )


# ═════════════════════════════════════════════════════════════
# Test 1 — Happy path
# ═════════════════════════════════════════════════════════════
def test_missed_to_open_happy_path():
    jid = f"{PREFIX}-j-happy"
    _run(_seed_job(jid, status="missed"))
    out = _run(_call(jid))
    assert out["id"] == jid
    assert out["status"] == "scheduled"
    assert "reopened_from_missed_at" in out
    assert "missed_at" not in out, (
        "missed_at should be cleared by the mark-open flip "
        "so the auto-missed scheduler doesn't re-fire on a "
        "stale timestamp"
    )
    # Verify the row on disk.
    row = _run(_DB.jobs.find_one({"id": jid}))
    assert row["status"] == "scheduled"
    assert "missed_at" not in row
    assert row["reopened_from_missed_at"]


# ═════════════════════════════════════════════════════════════
# Test 2 — Precondition rejects non-missed statuses
# ═════════════════════════════════════════════════════════════
@pytest.mark.parametrize("initial", [
    "scheduled", "active", "completed", "cancelled", "pending",
])
def test_non_missed_status_is_409_with_no_mutation(initial):
    from fastapi import HTTPException
    jid = f"{PREFIX}-j-{initial}"
    _run(_seed_job(jid, status=initial))
    with pytest.raises(HTTPException) as exc:
        _run(_call(jid))
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert detail["code"] == "invalid_status_transition"
    assert detail["current_status"] == initial
    # No mutation on the row.
    row = _run(_DB.jobs.find_one({"id": jid}))
    assert row["status"] == initial
    assert "reopened_from_missed_at" not in row


# ═════════════════════════════════════════════════════════════
# Test 3 — Non-admin → 403, no mutation
# ═════════════════════════════════════════════════════════════
@pytest.mark.parametrize("non_admin_user", [TECH, CUSTOMER])
def test_non_admin_role_is_403_with_no_mutation(non_admin_user):
    from fastapi import HTTPException
    jid = f"{PREFIX}-j-{non_admin_user['role']}"
    _run(_seed_job(jid, status="missed"))
    with pytest.raises(HTTPException) as exc:
        _run(_call(jid, user=non_admin_user))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "mark_open_forbidden"
    row = _run(_DB.jobs.find_one({"id": jid}))
    assert row["status"] == "missed"


# ═════════════════════════════════════════════════════════════
# Test 4 — Admin-equivalent roles all pass
# ═════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", [
    "admin", "super_admin", "owner", "manager",
])
def test_every_admin_equivalent_role_accepted(role):
    jid = f"{PREFIX}-j-admin-{role}"
    _run(_seed_job(jid, status="missed"))
    user = {"id": f"{PREFIX}-u-{role}", "role": role, "name": role}
    out = _run(_call(jid, user=user))
    assert out["status"] == "scheduled"


# ═════════════════════════════════════════════════════════════
# Test 5 — Cross-tenant → 404 (existence of target doesn't leak)
# ═════════════════════════════════════════════════════════════
def test_cross_tenant_is_404():
    from fastapi import HTTPException
    jid = f"{PREFIX}-j-xtenant"
    _run(_seed_job(jid, status="missed", tenant_id=TENANT_B))
    with pytest.raises(HTTPException) as exc:
        _run(_call(jid, tenant_id=TENANT_A))
    assert exc.value.status_code == 404
    # Row untouched.
    row = _run(_DB.jobs.find_one({"id": jid}))
    assert row["status"] == "missed"


# ═════════════════════════════════════════════════════════════
# Test 6 — Nonexistent job → 404
# ═════════════════════════════════════════════════════════════
def test_nonexistent_job_is_404():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _run(_call(f"{PREFIX}-j-ghost"))
    assert exc.value.status_code == 404


# ═════════════════════════════════════════════════════════════
# Test 7 — Audit log entry contents
# ═════════════════════════════════════════════════════════════
def test_audit_log_entry_contents():
    jid = f"{PREFIX}-j-audit"
    _run(_seed_job(jid, status="missed"))
    _run(_call(jid))
    entries = _run(_DB.activity_logs.find({
        "job_id": jid, "type": "mark_open_from_missed",
    }).to_list(None))
    assert len(entries) == 1
    e = entries[0]
    assert e["tenant_id"] == TENANT_A
    assert e["actor_id"] == ADMIN["id"]
    assert e["actor_role"] == "admin"
    assert e["metadata"]["before_status"] == "missed"
    assert e["metadata"]["after_status"] == "scheduled"
    assert "at" in e


# ═════════════════════════════════════════════════════════════
# Test 8 — Idempotency: same key replays, no duplicate audit
# ═════════════════════════════════════════════════════════════
def test_idempotency_replays_response_and_no_duplicate_audit():
    jid = f"{PREFIX}-j-idem"
    _run(_seed_job(jid, status="missed"))
    key = f"idem-{uuid4().hex[:12]}"
    first = _run(_call(jid, idem_key=key))
    second = _run(_call(jid, idem_key=key))
    assert first["status"] == second["status"] == "scheduled"
    assert first["id"] == second["id"]
    # Only one audit entry across the two calls.
    entries = _run(_DB.activity_logs.find({
        "job_id": jid, "type": "mark_open_from_missed",
    }).to_list(None))
    assert len(entries) == 1, (
        f"idempotency replay must not double-write audit; "
        f"got {len(entries)} entries"
    )
