"""LS-B · Feb-2026 — MARCO Lead-Sense intake endpoint tests.

Locks the thirteen invariants of Sub-phase B of the Lead-Sense
track (see ``memory/SPEC_MARCO_LEAD_SENSE.md``):

    (a) POST with valid ls_id + allowed origin → 204 + row written.
    (b) POST with unknown ls_id → 404 (opaque, no enumeration leak).
    (c) POST with disallowed origin → 403 + security_event logged.
    (d) POST with empty allow-list on tenant → 403 (safe default).
    (e) POST without Origin OR Referer → 403 (can't verify).
    (f) X-Forwarded-For present → left-most public IP used.
    (g) No XFF → falls back to request.client.host.
    (h) DB write failure (mocked) → 202 Accepted, no crash.
    (i) ``company: null`` stub confirmed on every row.
    (j) ``source_channel: "MARCO Lead-Sense"`` pre-tag on every row.
    (k) Cross-tenant leak — ls_id belonging to tenant A writes only
        to tenant A's visitor_intent rows.
    (l) Migration idempotent (indexes stable across two runs).
    (m) Widget file exists at frontend/public/widget/lead-sense.js
        and passes a minimal syntax + expected-marker check.

Test-loop convention mirrors ``test_lead_sense_tenant_field.py``:
sync pymongo for seeding, FastAPI TestClient with the real
``config.db`` swapped via monkey-patch when needed.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest
from dotenv import dotenv_values
from fastapi import FastAPI
from pymongo import MongoClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "LSB_"


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    """Drop LSB_-tagged tenant rows + any visitor_intent rows they
    fathered so full-suite runs stay hermetic."""
    seeded_tenant_ids: List[str] = []
    yield seeded_tenant_ids
    if seeded_tenant_ids:
        dbc.tenants.delete_many({"id": {"$in": seeded_tenant_ids}})
        dbc.visitor_intent.delete_many(
            {"tenant_id": {"$in": seeded_tenant_ids}},
        )


def _fresh(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_tenant(dbc, *, ls_id: str, allowed_origins: List[str]) -> str:
    """Insert a tenant carrying the Lead-Sense fields."""
    tid = _fresh("TEN")
    dbc.tenants.insert_one({
        "id": tid,
        "name": f"LSB seed tenant {tid[-8:]}",
        "marco_lead_sense_id": ls_id,
        "lead_sense_allowed_origins": allowed_origins,
        "created_at": "2026-02-15T00:00:00Z",
    })
    return tid


def _client_and_app():
    """Return a mounted FastAPI app for use with
    ``httpx.AsyncClient(app=app)``. httpx runs the request inside
    the caller's asyncio loop so motor futures share the same
    loop as the fixture — avoids the motor-cross-loop RuntimeError
    that ``TestClient`` (via anyio.BlockingPortal) triggers.

    Wires SlowAPI's ``app.state.limiter`` + exception handler so
    the ``@limiter.limit`` decorator on the handler works in the
    isolated test app (matches the wiring in server.py's boot
    sequence)."""
    from routers import lead_sense as _ls
    app = FastAPI()
    app.include_router(_ls.router)
    try:
        from slowapi.errors import RateLimitExceeded
        from slowapi import _rate_limit_exceeded_handler
        if _ls._shared_limiter is not None:
            app.state.limiter = _ls._shared_limiter
            app.add_exception_handler(
                RateLimitExceeded, _rate_limit_exceeded_handler,
            )
    except Exception:
        pass
    return app


def _post(app, json_body, headers=None, wrap_db=None):
    """Fire one POST /api/lead-sense/track via httpx.AsyncClient
    (loop-consistent with motor). Returns the httpx Response.

    IMPORTANT: swap ``routers.lead_sense.db`` for a fresh Motor
    client bound to the coroutine's event loop. The shared
    ``config.db`` was created at module-import time and its
    Motor futures dispatch to the ORIGINAL loop — asyncio.run()
    creates a new loop each test, so without this swap we get
    ``got Future attached to a different loop``.

    ``wrap_db`` — optional callable ``(fresh_db) -> db`` that lets
    a specific test wrap the loop-bound client (e.g. test_h's
    ``_BadDb`` to simulate a Mongo outage on ``visitor_intent``
    while leaving ``tenants`` reads intact).
    """
    from motor.motor_asyncio import AsyncIOMotorClient
    from routers import lead_sense as _ls

    async def _hit():
        loop_client = AsyncIOMotorClient(MONGO_URL)
        try:
            fresh_db = loop_client[DB_NAME]
            _ls.db = wrap_db(fresh_db) if wrap_db else fresh_db
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await client.post(
                    "/api/lead-sense/track",
                    json=json_body,
                    headers=headers or {},
                )
        finally:
            try:
                loop_client.close()
            except Exception:
                pass
    return asyncio.run(_hit())


def _valid_body(ls_id: str, session_id: str = None) -> Dict[str, Any]:
    return {
        "ls_id": ls_id,
        "session_id": session_id or f"sess-{uuid.uuid4().hex[:16]}",
        "current_url": "https://example.com/pricing",
        "referrer": "https://google.com/search?q=pool",
        "user_agent": "Mozilla/5.0 (test) Gecko/20100101 Firefox/999",
        "page_title": "Pricing — Example Pools",
        "viewport": {"w": 1440, "h": 900},
    }


# ═════════════════════════════════════════════════════════════════════
# (a) happy-path — valid ls_id + allowed origin → 204 + row written
# ═════════════════════════════════════════════════════════════════════
def test_a_happy_path_records_row(dbc, cleanup):
    ls_id = f"lsba_{uuid.uuid4().hex[:8]}"
    tid = _seed_tenant(dbc, ls_id=ls_id, allowed_origins=[
        "https://example.com",
    ])
    cleanup.append(tid)
    app = _client_and_app()
    body = _valid_body(ls_id)
    resp = _post(app, json_body=body,
        headers={"Origin": "https://example.com"},)
    assert resp.status_code == 204, resp.text
    # Row persisted.
    row = dbc.visitor_intent.find_one({
        "tenant_id": tid, "session_id": body["session_id"],
    })
    assert row is not None
    assert row.get("current_url") == body["current_url"]
    assert row.get("referrer") == body["referrer"]
    assert row.get("user_agent") == body["user_agent"]
    assert row.get("viewport") == {"w": 1440, "h": 900}


# ═════════════════════════════════════════════════════════════════════
# (b) unknown ls_id → 404, opaque copy
# ═════════════════════════════════════════════════════════════════════
def test_b_unknown_ls_id_returns_404_opaque(dbc, cleanup):
    app = _client_and_app()
    resp = _post(app, json_body=_valid_body(f"unknown_{uuid.uuid4().hex[:8]}"),
        headers={"Origin": "https://any.example.com"},)
    assert resp.status_code == 404, resp.text
    body = resp.json()
    detail = (body.get("detail") or "").lower()
    # Opaque error copy — never "tenant not found" or similar
    # enumeration hints.
    assert "tenant" not in detail
    assert "invalid_tracker" in detail or detail == "invalid_tracker"


# ═════════════════════════════════════════════════════════════════════
# (c) disallowed origin → 403 + security_event logged
# ═════════════════════════════════════════════════════════════════════
def test_c_disallowed_origin_returns_403_and_logs(dbc, cleanup, caplog):
    ls_id = f"lsbc_{uuid.uuid4().hex[:8]}"
    tid = _seed_tenant(dbc, ls_id=ls_id, allowed_origins=[
        "https://example.com",
    ])
    cleanup.append(tid)
    app = _client_and_app()
    with caplog.at_level(logging.WARNING, logger="pool_crm"):
        resp = _post(app, json_body=_valid_body(ls_id),
            headers={"Origin": "https://evil.attacker.tld"},)
    assert resp.status_code == 403, resp.text
    # Security event surfaced.
    matched = [
        r for r in caplog.records
        if "lead_sense.security" in r.getMessage()
        and "origin_rejected" in r.getMessage()
    ]
    assert matched, (
        "expected a lead_sense.security origin_rejected warning; "
        f"got {[r.getMessage() for r in caplog.records]!r}"
    )
    # No visitor_intent row written.
    assert dbc.visitor_intent.count_documents({"tenant_id": tid}) == 0


# ═════════════════════════════════════════════════════════════════════
# (d) empty allow-list → 403 (safe default)
# ═════════════════════════════════════════════════════════════════════
def test_d_empty_allow_list_blocks_all_origins(dbc, cleanup):
    ls_id = f"lsbd_{uuid.uuid4().hex[:8]}"
    tid = _seed_tenant(dbc, ls_id=ls_id, allowed_origins=[])
    cleanup.append(tid)
    app = _client_and_app()
    resp = _post(app, json_body=_valid_body(ls_id),
        headers={"Origin": "https://example.com"},)
    assert resp.status_code == 403, resp.text
    assert dbc.visitor_intent.count_documents({"tenant_id": tid}) == 0


# ═════════════════════════════════════════════════════════════════════
# (e) no Origin AND no Referer → 403
# ═════════════════════════════════════════════════════════════════════
def test_e_no_origin_no_referer_returns_403(dbc, cleanup):
    ls_id = f"lsbe_{uuid.uuid4().hex[:8]}"
    tid = _seed_tenant(dbc, ls_id=ls_id, allowed_origins=[
        "https://example.com",
    ])
    cleanup.append(tid)
    app = _client_and_app()
    # NO Origin, NO Referer.
    resp = _post(app, json_body=_valid_body(ls_id))
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert "origin_required" in (body.get("detail") or "")


def test_e2_referer_fallback_extracts_origin(dbc, cleanup):
    """When Origin is absent but Referer carries a full URL, the
    handler should extract the origin from the Referer and match
    it against the allow-list."""
    ls_id = f"lsbe2_{uuid.uuid4().hex[:8]}"
    tid = _seed_tenant(dbc, ls_id=ls_id, allowed_origins=[
        "https://example.com",
    ])
    cleanup.append(tid)
    app = _client_and_app()
    resp = _post(app, json_body=_valid_body(ls_id),
        headers={
            "Referer": "https://example.com/marketing/lp?utm=x",
        },)
    assert resp.status_code == 204, resp.text


# ═════════════════════════════════════════════════════════════════════
# (f) X-Forwarded-For — left-most entry wins
# ═════════════════════════════════════════════════════════════════════
def test_f_xff_leftmost_ip_captured(dbc, cleanup):
    ls_id = f"lsbf_{uuid.uuid4().hex[:8]}"
    tid = _seed_tenant(dbc, ls_id=ls_id, allowed_origins=[
        "https://example.com",
    ])
    cleanup.append(tid)
    app = _client_and_app()
    body = _valid_body(ls_id)
    resp = _post(app, json_body=body,
        headers={
            "Origin": "https://example.com",
            "X-Forwarded-For": "203.0.113.42, 10.0.0.1, 10.0.0.2",
        },)
    assert resp.status_code == 204, resp.text
    row = dbc.visitor_intent.find_one({
        "tenant_id": tid, "session_id": body["session_id"],
    })
    assert row["ip"] == "203.0.113.42"


# ═════════════════════════════════════════════════════════════════════
# (g) No XFF → falls back to request.client.host
# ═════════════════════════════════════════════════════════════════════
def test_g_no_xff_falls_back_to_client_host(dbc, cleanup):
    ls_id = f"lsbg_{uuid.uuid4().hex[:8]}"
    tid = _seed_tenant(dbc, ls_id=ls_id, allowed_origins=[
        "https://example.com",
    ])
    cleanup.append(tid)
    app = _client_and_app()
    body = _valid_body(ls_id)
    resp = _post(app, json_body=body,
        headers={"Origin": "https://example.com"},)
    assert resp.status_code == 204, resp.text
    row = dbc.visitor_intent.find_one({
        "tenant_id": tid, "session_id": body["session_id"],
    })
    # TestClient sets request.client.host to "testclient" — the
    # fallback path is exercised (NOT the XFF path).
    assert row["ip"] and row["ip"] != "0.0.0.0"
    assert "," not in row["ip"], "single-token fallback expected"


# ═════════════════════════════════════════════════════════════════════
# (h) DB write failure → 202 Accepted (best-effort)
# ═════════════════════════════════════════════════════════════════════
def test_h_db_write_failure_returns_202(dbc, cleanup):
    ls_id = f"lsbh_{uuid.uuid4().hex[:8]}"
    tid = _seed_tenant(dbc, ls_id=ls_id, allowed_origins=[
        "https://example.com",
    ])
    cleanup.append(tid)

    class _BadCollection:
        async def insert_one(self, doc):
            raise RuntimeError("simulated Mongo outage")

    class _BadDb:
        """Wraps a real loop-bound Motor db instance. ``.tenants``
        (and everything else) proxies through to the real db so the
        happy-path reads still work; ``.visitor_intent`` is replaced
        with the failing stub."""
        def __init__(self, real_db):
            self._real = real_db
            self.visitor_intent = _BadCollection()

        def __getattr__(self, name):
            return getattr(self._real, name)

    app = _client_and_app()
    resp = _post(
        app,
        json_body=_valid_body(ls_id),
        headers={"Origin": "https://example.com"},
        wrap_db=lambda fresh: _BadDb(fresh),
    )
    # 202 Accepted — beacon caller shouldn't see a 5xx.
    assert resp.status_code == 202, resp.text
    # No row written (we mocked the failure).
    assert dbc.visitor_intent.count_documents({"tenant_id": tid}) == 0


# ═════════════════════════════════════════════════════════════════════
# (i) company: null stub confirmed
# ═════════════════════════════════════════════════════════════════════
def test_i_company_stubbed_to_null(dbc, cleanup):
    ls_id = f"lsbi_{uuid.uuid4().hex[:8]}"
    tid = _seed_tenant(dbc, ls_id=ls_id, allowed_origins=[
        "https://example.com",
    ])
    cleanup.append(tid)
    app = _client_and_app()
    body = _valid_body(ls_id)
    resp = _post(app, json_body=body,
        headers={"Origin": "https://example.com"},)
    assert resp.status_code == 204
    row = dbc.visitor_intent.find_one({
        "tenant_id": tid, "session_id": body["session_id"],
    })
    # Explicit null (not missing).
    assert row["company"] is None
    assert "company" in row


# ═════════════════════════════════════════════════════════════════════
# (j) source_channel pre-tag
# ═════════════════════════════════════════════════════════════════════
def test_j_source_channel_pre_tagged(dbc, cleanup):
    ls_id = f"lsbj_{uuid.uuid4().hex[:8]}"
    tid = _seed_tenant(dbc, ls_id=ls_id, allowed_origins=[
        "https://example.com",
    ])
    cleanup.append(tid)
    app = _client_and_app()
    body = _valid_body(ls_id)
    resp = _post(app, json_body=body,
        headers={"Origin": "https://example.com"},)
    assert resp.status_code == 204
    row = dbc.visitor_intent.find_one({
        "tenant_id": tid, "session_id": body["session_id"],
    })
    assert row["source_channel"] == "MARCO Lead-Sense"


# ═════════════════════════════════════════════════════════════════════
# (k) Cross-tenant isolation — ls_id A writes ONLY to tenant A
# ═════════════════════════════════════════════════════════════════════
def test_k_cross_tenant_isolation(dbc, cleanup):
    ls_id_a = f"lsbkA_{uuid.uuid4().hex[:8]}"
    ls_id_b = f"lsbkB_{uuid.uuid4().hex[:8]}"
    tid_a = _seed_tenant(dbc, ls_id=ls_id_a, allowed_origins=[
        "https://a.example.com",
    ])
    tid_b = _seed_tenant(dbc, ls_id=ls_id_b, allowed_origins=[
        "https://b.example.com",
    ])
    cleanup.extend([tid_a, tid_b])
    app = _client_and_app()
    body_a = _valid_body(ls_id_a)
    body_a["current_url"] = "https://a.example.com/pricing"
    resp = _post(app, json_body=body_a,
        headers={"Origin": "https://a.example.com"},)
    assert resp.status_code == 204, resp.text
    # Tenant A got the row; tenant B untouched.
    assert dbc.visitor_intent.count_documents({"tenant_id": tid_a}) == 1
    assert dbc.visitor_intent.count_documents({"tenant_id": tid_b}) == 0
    # And using tenant A's origin with tenant B's ls_id → 403 (origin
    # is not in tenant B's allow-list).
    body_b = _valid_body(ls_id_b)
    resp2 = _post(app, json_body=body_b,
        headers={"Origin": "https://a.example.com"})  # A's origin
    assert resp2.status_code == 403


# ═════════════════════════════════════════════════════════════════════
# (l) Migration idempotency
# ═════════════════════════════════════════════════════════════════════
def test_l_migration_idempotent_second_run_skipped_by_marker():
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from migrations.visitor_intent_v1 import run

    async def _apply():
        loop_client = AsyncIOMotorClient(MONGO_URL)
        try:
            adb = loop_client[DB_NAME]
            # First pass with --force to guarantee a fresh execution
            # even if the sentinel is already set from an earlier
            # boot.
            first = await run(dry_run=False, force=True, db_client=adb)
            second = await run(dry_run=False, force=False, db_client=adb)
            return first, second
        finally:
            loop_client.close()

    first, second = asyncio.run(_apply())
    assert first["indexes_ensured"] == 3
    assert first["skipped_by_marker"] is False
    assert second["skipped_by_marker"] is True
    assert second["indexes_ensured"] == 0


# ═════════════════════════════════════════════════════════════════════
# (m) Widget file exists + minimal syntax sanity
# ═════════════════════════════════════════════════════════════════════
def test_m_widget_file_exists_with_expected_markers():
    widget_path = (
        Path(__file__).resolve().parents[2]
        / "frontend" / "public" / "widget" / "lead-sense.js"
    )
    assert widget_path.exists(), (
        f"lead-sense widget missing at {widget_path}"
    )
    src = widget_path.read_text(encoding="utf-8")
    # Expected markers that lock the behavior contract.
    assert "MARCO Lead-Sense" in src, "brand marker missing"
    assert "/api/lead-sense/track" in src, "endpoint URL missing"
    assert "data-ls-id" in src, "script-tag attr read missing"
    assert "sendBeacon" in src, "beacon transport missing"
    assert "keepalive" in src, "fetch fallback missing"
    assert "marco_ls_session" in src, "session storage key missing"
    assert "window.MARCO_LS" in src, "global surface missing"
    # Balanced braces smoke — not a real parser, but catches
    # gross corruption from a merge conflict.
    assert src.count("{") == src.count("}"), (
        "brace imbalance in widget bundle"
    )
    # Size discipline — keep <10KB unminified as a soft ceiling.
    # The <5KB minified target is a follow-up (no minifier yet
    # wired for this widget).
    assert len(src) < 10 * 1024, (
        f"widget bundle too large: {len(src)} bytes"
    )
    # No obvious secret leaks.
    assert not re.search(r"(AKIA|sk_live_|sk_test_)", src)
