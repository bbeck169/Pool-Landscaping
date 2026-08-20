"""Feb-2026 hotfix · Door-hanger portal auto-login redemption tests.

Covers the ``GET /api/portal/auto-login`` interstitial endpoint that
turns a magic-link JWT into a customer-scoped session + a JS redirect
to the service-report page.

Contract under test:
  1. Valid token → 200 HTML with the target ``/portal/service-reports/{sr_id}``
     path + a ``localStorage.setItem('token', …)`` line seeding the
     access token.
  2. Expired token → 302 to ``/portal/login?reason=link_expired`` +
     NO access token in the body.
  3. Tampered token → same 302; no session.
  4. Valid token but customer / user missing (wrong-scope-like) →
     same 302; no session.
  5. ``redirect`` param NOT starting with ``/portal/`` → ignored,
     falls back to the token-derived target (open-redirect guard).
  6. ``redirect`` param starting with ``/portal/`` → honoured.
  7. Log line records ``outcome=<state>`` but NEVER the raw token
     value.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from config import JWT_ALGO, JWT_SECRET


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    import routers.portal_auto_login as _mod
    _mod.db = fresh_db
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


class _FakeRequest:
    """Minimal Starlette-like request stub for the redemption
    handler.  Only ``headers`` + ``client.host`` are read."""
    def __init__(self, ip: str = "10.0.0.1"):
        self.headers = {"x-forwarded-for": ip}
        self.client = type("C", (), {"host": ip})()


async def _seed_customer_and_user(tenant_id: str) -> tuple[str, str]:
    cid = f"al-cust-{uuid.uuid4().hex[:10]}"
    uid = f"al-user-{uuid.uuid4().hex[:10]}"
    await _db().customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "Test Customer", "first_name": "Test", "last_name": "Customer",
        "email": f"{cid}@example.com",
    })
    await _db().users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "customer",
        "customer_id": cid, "email": f"{cid}@example.com",
        "name": "Test Customer",
    })
    return cid, uid


async def _seed_service_report(tenant_id: str, job_id: str) -> str:
    sr_id = f"al-sr-{uuid.uuid4().hex[:10]}"
    await _db().service_reports.insert_one({
        "id": sr_id, "tenant_id": tenant_id, "job_id": job_id,
    })
    return sr_id


async def _drain(tenant_id: str) -> None:
    for coll in ("customers", "users", "service_reports"):
        await _db()[coll].delete_many({"tenant_id": tenant_id})


def _mk_tenant() -> str:
    return f"TEST_al_tenant_{uuid.uuid4().hex[:8]}"


# ═════════════════════════════════════════════════════════════════════
# 1. Valid token → 200 HTML with access-token seed + correct redirect.
# ═════════════════════════════════════════════════════════════════════
def test_valid_token_returns_interstitial_with_access_token_and_report_redirect():
    async def _go():
        tid = _mk_tenant()
        cid, _uid = await _seed_customer_and_user(tid)
        jid = f"al-job-{uuid.uuid4().hex[:10]}"
        sr_id = await _seed_service_report(tid, jid)
        try:
            from services.portal_magic_links import mint_job_view_token
            from routers.portal_auto_login import portal_auto_login
            tok = mint_job_view_token(cid, jid, tid)
            resp = await portal_auto_login(
                _FakeRequest(), t=tok, redirect=None,
            )
            assert resp.status_code == 200
            body = resp.body.decode("utf-8")
            # Redirect target IS the service-report page.
            assert f"/portal/service-reports/{sr_id}" in body
            # Access token got seeded into localStorage.
            assert "localStorage.setItem('token'," in body
            # A real JWT string (has two dots) is present in the body.
            assert body.count(".") >= 3
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 2. Expired token → 302 to /portal/login?reason=link_expired.
# ═════════════════════════════════════════════════════════════════════
def test_expired_token_redirects_to_login_with_link_expired_reason():
    async def _go():
        tid = _mk_tenant()
        cid, _ = await _seed_customer_and_user(tid)
        jid = f"al-job-{uuid.uuid4().hex[:10]}"
        try:
            now = datetime.now(timezone.utc)
            expired = jwt.encode(
                {"sub": "job_view", "customer_id": cid,
                 "job_id": jid, "tenant_id": tid,
                 "iat": now - timedelta(hours=25),
                 "exp": now - timedelta(hours=1)},
                JWT_SECRET, algorithm=JWT_ALGO,
            )
            from routers.portal_auto_login import portal_auto_login
            resp = await portal_auto_login(
                _FakeRequest(), t=expired, redirect=None,
            )
            assert resp.status_code == 302
            assert resp.headers["location"] == "/portal/login?reason=link_expired"
            # No token seed in the body.
            body_bytes = getattr(resp, "body", b"") or b""
            assert b"localStorage.setItem" not in body_bytes
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 3. Tampered token → same 302.
# ═════════════════════════════════════════════════════════════════════
def test_tampered_token_redirects_to_login_no_session():
    async def _go():
        tid = _mk_tenant()
        cid, _ = await _seed_customer_and_user(tid)
        jid = f"al-job-{uuid.uuid4().hex[:10]}"
        try:
            from services.portal_magic_links import mint_job_view_token
            from routers.portal_auto_login import portal_auto_login
            tok = mint_job_view_token(cid, jid, tid)
            header, payload, sig = tok.split(".")
            tampered = f"{header}.{payload[:-1]}{'A' if payload[-1] != 'A' else 'B'}.{sig}"
            resp = await portal_auto_login(
                _FakeRequest(), t=tampered, redirect=None,
            )
            assert resp.status_code == 302
            assert resp.headers["location"] == "/portal/login?reason=link_expired"
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 4. Valid token but customer / user record missing → 302.
# ═════════════════════════════════════════════════════════════════════
def test_wrong_scope_customer_missing_redirects_to_login():
    async def _go():
        tid = _mk_tenant()
        # Do NOT seed a customer / user — the token references a
        # customer_id that doesn't exist in this tenant.
        try:
            from services.portal_magic_links import mint_job_view_token
            from routers.portal_auto_login import portal_auto_login
            tok = mint_job_view_token(
                "ghost-cust", "ghost-job", tid,
            )
            resp = await portal_auto_login(
                _FakeRequest(), t=tok, redirect=None,
            )
            assert resp.status_code == 302
            assert resp.headers["location"] == "/portal/login?reason=link_expired"
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 5. redirect that doesn't start with /portal/ → ignored (open-redirect guard).
# ═════════════════════════════════════════════════════════════════════
def test_redirect_param_off_domain_is_ignored():
    async def _go():
        tid = _mk_tenant()
        cid, _ = await _seed_customer_and_user(tid)
        jid = f"al-job-{uuid.uuid4().hex[:10]}"
        sr_id = await _seed_service_report(tid, jid)
        try:
            from services.portal_magic_links import mint_job_view_token
            from routers.portal_auto_login import portal_auto_login
            tok = mint_job_view_token(cid, jid, tid)
            resp = await portal_auto_login(
                _FakeRequest(), t=tok,
                redirect="https://attacker.example/steal",
            )
            assert resp.status_code == 200
            body = resp.body.decode("utf-8")
            # Attacker URL MUST NOT appear anywhere; the interstitial
            # falls back to the token-derived service-report path.
            assert "attacker.example" not in body
            assert f"/portal/service-reports/{sr_id}" in body
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 6. redirect starting with /portal/ is honoured.
# ═════════════════════════════════════════════════════════════════════
def test_redirect_param_portal_path_is_honoured():
    async def _go():
        tid = _mk_tenant()
        cid, _ = await _seed_customer_and_user(tid)
        jid = f"al-job-{uuid.uuid4().hex[:10]}"
        await _seed_service_report(tid, jid)
        try:
            from services.portal_magic_links import mint_job_view_token
            from routers.portal_auto_login import portal_auto_login
            tok = mint_job_view_token(cid, jid, tid)
            resp = await portal_auto_login(
                _FakeRequest(), t=tok,
                redirect="/portal/invoices/xyz",
            )
            assert resp.status_code == 200
            body = resp.body.decode("utf-8")
            assert "/portal/invoices/xyz" in body
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 7. Log line contains outcome but NEVER the raw token value.
# ═════════════════════════════════════════════════════════════════════
def test_log_line_records_outcome_and_omits_raw_token(caplog):
    async def _go():
        tid = _mk_tenant()
        cid, _ = await _seed_customer_and_user(tid)
        jid = f"al-job-{uuid.uuid4().hex[:10]}"
        await _seed_service_report(tid, jid)
        try:
            from services.portal_magic_links import mint_job_view_token
            from routers.portal_auto_login import portal_auto_login
            tok = mint_job_view_token(cid, jid, tid)
            with caplog.at_level("INFO", logger="portal.auto_login"):
                await portal_auto_login(
                    _FakeRequest(), t=tok, redirect=None,
                )
            joined = " ".join(rec.message for rec in caplog.records)
            assert "outcome=success" in joined
            assert f"customer_id={cid}" in joined
            assert f"job_id={jid}" in joined
            # The raw token MUST NEVER hit the log stream.
            assert tok not in joined
        finally:
            await _drain(tid)

    _run(_go())
