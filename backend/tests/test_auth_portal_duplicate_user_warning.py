"""PORTAL-INVITE-EMAIL-COLLISION-FIX · Feb-2026 (P0 #1 + P0 #2)
observability pytest for the ``auth.login`` structured warning.

When a login succeeds via a users-table row that has duplicate
``role=customer`` siblings with DISTINCT customer_ids under the
same email, ``routers/auth.py::login`` now emits a WARNING tagged
``PORTAL-INVITE-EMAIL-COLLISION-FIX observability`` so ops can
grep for the exact duplicate-user pattern that broke P0 #1 + #2.

Two cases:
  (i)  Two role=customer rows, SAME email, DIFFERENT customer_ids
       → login succeeds AND the structured warning fires.
  (ii) Two role=customer rows, SAME email, SAME customer_id
       → login succeeds AND the structured warning does NOT fire
       (uses the generic multi-record warning instead).

Synthetic data only.  Passwords are literal fixtures.
"""
from __future__ import annotations

import logging
import uuid

from dotenv import load_dotenv
from fastapi import Request

from tests._f7_loop_fixture import run_test
from utils import hash_password


load_dotenv("/app/backend/.env")

_FIXED_PASSWORD = "ObservePw123!"


def _mock_request() -> Request:
    """Minimal Starlette-shaped Request for the login handler.

    The handler only reads ``request.client.host`` + a few headers;
    a scope dict is enough to construct a usable Request.
    """
    scope = {
        "type": "http", "method": "POST", "path": "/api/auth/login",
        "headers": [(b"x-forwarded-for", b"203.0.113.5")],
        "client": ("203.0.113.5", 0), "query_string": b"",
    }
    return Request(scope)


async def _seed_two_customer_users(
    db, tid: str, email: str,
    cid_a: str, cid_b: str,
):
    """Create two role=customer rows with the same email + tenant
    but distinct customer_ids.  Both rows share the same password
    so ``verify_password`` returns matches for BOTH records."""
    hashed = hash_password(_FIXED_PASSWORD)
    uid_a = str(uuid.uuid4())
    uid_b = str(uuid.uuid4())
    await db.users.insert_many([
        {
            "id": uid_a, "tenant_id": tid, "role": "customer",
            "email": email, "password_hash": hashed,
            "customer_id": cid_a, "active": True,
            "has_ever_logged_in": True,  # bypass temp-password fork
            "created_at": "2026-02-01T00:00:00+00:00",
        },
        {
            "id": uid_b, "tenant_id": tid, "role": "customer",
            "email": email, "password_hash": hashed,
            "customer_id": cid_b, "active": True,
            "has_ever_logged_in": True,
            "created_at": "2026-02-02T00:00:00+00:00",
        },
    ])
    return uid_a, uid_b


# ─── (i) Distinct customer_ids → observability warning fires ──────
def test_login_logs_collision_warning_for_distinct_customer_ids(caplog):
    tid = f"test-collision-obs-{uuid.uuid4()}"
    email = f"obs-{uuid.uuid4().hex[:8]}@synthetic.test"
    cid_a = str(uuid.uuid4())
    cid_b = str(uuid.uuid4())

    async def _run(db):
        try:
            await _seed_two_customer_users(db, tid, email, cid_a, cid_b)
            # Seed a tenant row so the login path's downstream
            # tenant lookups don't 404.
            await db.tenants.insert_one({"id": tid, "name": "T"})
            from routers.auth import LoginRequest, login
            body = LoginRequest(email=email, password=_FIXED_PASSWORD)
            with caplog.at_level(logging.WARNING):
                res = await login(_mock_request(), body)
            # Login proceeds (returns an auth_response dict).  Only
            # thing we assert about the response is that it's not an
            # error — the warning is the structural signal.
            assert res is not None
            matched = [
                r for r in caplog.records
                if "PORTAL-INVITE-EMAIL-COLLISION-FIX observability"
                in r.getMessage()
            ]
            assert matched, (
                "expected the structured collision-observability "
                "warning to fire; got records: "
                + str([r.getMessage()[:80] for r in caplog.records])
            )
            msg = matched[0].getMessage()
            assert "match_count=2" in msg
            assert "distinct_customer_id_count=2" in msg
            # Only prefixes, no full ids / PII.
            assert cid_a[:8] in msg or cid_b[:8] in msg
        finally:
            await db.tenants.delete_many({"id": tid})
            await db.users.delete_many({"tenant_id": tid})

    run_test(_run)


# ─── (ii) Same customer_id → warning does NOT fire ────────────────
def test_login_does_not_log_collision_warning_when_customer_id_matches(caplog):
    tid = f"test-collision-obs-{uuid.uuid4()}"
    email = f"obs-{uuid.uuid4().hex[:8]}@synthetic.test"
    cid = str(uuid.uuid4())

    async def _run(db):
        try:
            # Both rows point to the SAME customer_id — this is a
            # less-harmful duplicate pattern (same customer, two
            # user rows).  Observability warning should NOT fire
            # — only the generic multi-record warning.
            await _seed_two_customer_users(db, tid, email, cid, cid)
            await db.tenants.insert_one({"id": tid, "name": "T"})
            from routers.auth import LoginRequest, login
            body = LoginRequest(email=email, password=_FIXED_PASSWORD)
            with caplog.at_level(logging.WARNING):
                res = await login(_mock_request(), body)
            assert res is not None
            assert not any(
                "PORTAL-INVITE-EMAIL-COLLISION-FIX observability"
                in r.getMessage()
                for r in caplog.records
            ), (
                "observability warning MUST NOT fire when all "
                "matches share the same customer_id"
            )
        finally:
            await db.tenants.delete_many({"id": tid})
            await db.users.delete_many({"tenant_id": tid})

    run_test(_run)
