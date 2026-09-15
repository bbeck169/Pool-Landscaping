"""Phase L3 · Feb-2026 · Lead-scoped SMS send.

Backend acceptance tests for ``POST /api/leads/{lead_id}/send-sms``:

* Happy path — persists row, dispatches via RC adapter, marks status
  ``sent`` on success, returns the fresh row.
* Missing phone — 400.
* Consent gate — ``sms_ok=false`` → 400 ``consent_required``.
* Consent override — same row, ``override_consent=true`` succeeds.
* Tenant isolation — a lead from another tenant returns 404.
* Role guard — technician / customer role → 403.
* Provider failure — marks row status ``failed``, keeps error.
* Uniform-status normalization — RC ``provider_status="mocked"`` still
  maps to our ``sent`` enum with ``provider_status_raw="mocked"``
  stashed on the row.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _run(coro):
    return asyncio.run(coro)


# ── Motor-shaped in-memory stub ──────────────────────────────────────
class _AsyncCursor:
    def __init__(self, rows): self._rows = list(rows)
    def __aiter__(self): self._i = 0; return self

    async def __anext__(self):
        if self._i >= len(self._rows): raise StopAsyncIteration
        r = self._rows[self._i]; self._i += 1; return r


def _match(row, query):
    """Recursive Motor-shaped query matcher — supports the subset the
    L3 aggregator uses: eq, ``$or``, ``$lt``."""
    for k, v in (query or {}).items():
        if k == "$or":
            if not any(_match(row, sub) for sub in v):
                return False
            continue
        if k == "$and":
            if not all(_match(row, sub) for sub in v):
                return False
            continue
        rv = row.get(k)
        if isinstance(v, dict):
            if "$lt" in v:
                if rv is None or not (rv < v["$lt"]):
                    return False
            if "$gte" in v:
                if rv is None or rv < v["$gte"]:
                    return False
            if "$lte" in v:
                if rv is None or rv > v["$lte"]:
                    return False
            if "$in" in v:
                if rv not in v["$in"]:
                    return False
            if "$exists" in v:
                if (k in row) != v["$exists"]:
                    return False
        else:
            if rv != v:
                return False
    return True


class _SortableCursor:
    def __init__(self, rows):
        self._rows = list(rows)
        self._sort_keys = None
        self._limit = None

    def sort(self, keys, *_a, **_kw):
        # keys is either a list of (field, dir) tuples or a single string
        if isinstance(keys, str):
            self._sort_keys = [(keys, _a[0] if _a else 1)]
        else:
            self._sort_keys = list(keys)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _materialize(self):
        rows = list(self._rows)
        if self._sort_keys:
            for field, direction in reversed(self._sort_keys):
                rows.sort(
                    key=lambda r, f=field: (r.get(f) is None, r.get(f)),
                    reverse=(direction == -1),
                )
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows

    def __aiter__(self):
        self._iter_rows = self._materialize()
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self._iter_rows): raise StopAsyncIteration
        r = self._iter_rows[self._i]; self._i += 1; return r

    async def to_list(self, n=None):
        rows = self._materialize()
        return rows if n is None else rows[:n]


class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.inserts: List[Dict[str, Any]] = []
        self.updates: List[Dict[str, Any]] = []
        self.indexes_created = []

    async def find_one(self, q, p=None):
        for r in self.rows:
            if _match(r, q):
                return dict(r)
        return None

    def find(self, q=None, p=None):
        return _SortableCursor([r for r in self.rows if _match(r, q or {})])

    async def insert_one(self, doc):
        self.rows.append(dict(doc))
        self.inserts.append(dict(doc))
        return type("R", (), {"inserted_id": "x"})()

    async def update_one(self, q, upd):
        for r in self.rows:
            if _match(r, q):
                r.update(upd.get("$set", {}))
                self.updates.append({"q": q, "set": upd["$set"]})
                return
        return None

    async def create_index(self, keys, name=None, **_kw):
        self.indexes_created.append((tuple(keys), name))


class _DB:
    def __init__(self):
        self.leads = _Coll()
        self.lead_communications = _Coll()
        self.sms_inbound = _Coll()


def _build_app(user, tenant, db_stub):
    from routers import lead_communications as _l3
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    # Patch the module-level ``db`` symbol so all queries hit the stub.
    _l3.db = db_stub
    app = FastAPI()
    app.include_router(_l3.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    return app


def _seed_lead(db_stub, *, tenant_id="t1", lid="lead-1",
                phone="+15555550100", email="lead@example.com",
                sms_ok=None, email_ok=None):
    row = {
        "id": lid, "tenant_id": tenant_id,
        "name": "Test Lead", "email": email, "phone": phone,
        "status": "new", "created_at": "2026-02-01T10:00:00Z",
        "timeline": [],
    }
    if sms_ok is not None: row["sms_ok"] = sms_ok
    if email_ok is not None: row["email_ok"] = email_ok
    db_stub.leads.rows.append(row)
    return row


# ─── Happy path ─────────────────────────────────────────────────────
def test_send_sms_happy_path_persists_and_sends():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub)
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1", "rc_sms_from_number": "+15555550001"}
        app = _build_app(user, tenant, db_stub)

        with patch(
            "services.sms.rc_adapter.send",
            new_callable=AsyncMock,
        ) as _mock_send:
            _mock_send.return_value = {
                "provider": "ringcentral",
                "provider_status": "sent",
                "provider_response_id": "rc-123",
                "attempts": 1,
                "error": None,
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/leads/lead-1/send-sms",
                    json={"body": "Hi, following up on your quote request"},
                )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "sent"
        assert body["channel"] == "sms"
        assert body["direction"] == "outbound"
        assert body["provider_message_id"] == "rc-123"
        assert body["to_identity"] == "+15555550100"
        assert body["from_identity"] == "+15555550001"
        assert body["sent_by_user_id"] == "u-admin"
        # Row was persisted BEFORE dispatch (invariant).  So the
        # inserts collection should have one row and the updates
        # collection should have exactly one flip afterwards.
        assert len(db_stub.lead_communications.inserts) == 1
        assert db_stub.lead_communications.inserts[0]["status"] == "queued"
        assert len(db_stub.lead_communications.updates) == 1

    _run(run())


def test_send_sms_missing_phone_returns_400():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub, phone="")
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
        ) as ac:
            r = await ac.post(
                "/api/leads/lead-1/send-sms",
                json={"body": "Hi"},
            )
        assert r.status_code == 400, r.text
        assert "phone" in r.text.lower()
        # No row was persisted.
        assert db_stub.lead_communications.inserts == []

    _run(run())


def test_send_sms_consent_gate_blocks_when_opted_out():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub, sms_ok=False)
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
        ) as ac:
            r = await ac.post(
                "/api/leads/lead-1/send-sms",
                json={"body": "Hi"},
            )
        assert r.status_code == 400, r.text
        assert "consent_required" in r.text
        assert db_stub.lead_communications.inserts == []

    _run(run())


def test_send_sms_consent_override_allows_send():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub, sms_ok=False)
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        with patch(
            "services.sms.rc_adapter.send",
            new_callable=AsyncMock,
        ) as _mock_send:
            _mock_send.return_value = {
                "provider": "ringcentral",
                "provider_status": "sent",
                "provider_response_id": "rc-ov-1",
                "error": None,
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/leads/lead-1/send-sms",
                    json={"body": "Hi", "override_consent": True},
                )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "sent"

    _run(run())


def test_send_sms_tenant_isolation_404():
    async def run():
        db_stub = _DB()
        # Lead exists on a DIFFERENT tenant.
        _seed_lead(db_stub, tenant_id="t-other")
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
        ) as ac:
            r = await ac.post(
                "/api/leads/lead-1/send-sms",
                json={"body": "Hi"},
            )
        assert r.status_code == 404, r.text

    _run(run())


def test_send_sms_role_guard_403():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub)
        # Technician tries to compose — not allowed.
        user = {"id": "u-tech", "role": "technician"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
        ) as ac:
            r = await ac.post(
                "/api/leads/lead-1/send-sms",
                json={"body": "Hi"},
            )
        assert r.status_code == 403, r.text

    _run(run())


def test_send_sms_provider_failure_marks_row_failed():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub)
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        with patch(
            "services.sms.rc_adapter.send",
            new_callable=AsyncMock,
        ) as _mock_send:
            _mock_send.return_value = {
                "provider": "ringcentral",
                "provider_status": "failed",
                "provider_response_id": None,
                "error": "boom",
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/leads/lead-1/send-sms",
                    json={"body": "Hi"},
                )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "failed"
        assert body["error"] == "boom"
        assert body["provider_status_raw"] == "failed"

    _run(run())


def test_send_sms_normalizes_mocked_to_sent_and_stashes_raw():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub)
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        with patch(
            "services.sms.rc_adapter.send",
            new_callable=AsyncMock,
        ) as _mock_send:
            _mock_send.return_value = {
                "provider": "mock", "provider_status": "mocked",
                "provider_response_id": None, "error": None,
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/leads/lead-1/send-sms",
                    json={"body": "Hi"},
                )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "sent"
        assert body["provider_status_raw"] == "mocked"

    _run(run())
