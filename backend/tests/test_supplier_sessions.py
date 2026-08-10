"""Phase 54h-a · Aug-2026 — Turnstile challenge handoff backend.

Tests split across the two moving parts:
  * ``services.suppliers.sessions`` — Fernet round-trip, expiry,
    tenant scoping, deletion.
  * ``services.suppliers.challenge`` — detector triggers on the 3
    documented signals, does not false-positive on a normal page.
  * Router role gate + supplier opt-in via ``CONNECTORS`` lookup.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest


# ─── Fake Motor collection (subset supporting update_one, delete_one,
# insert_one, find_one, create_index) ─────────────────────────────────
class _DeleteResult:
    def __init__(self, n): self.deleted_count = n


class _FakeCollection:
    def __init__(self, docs=None):
        self.docs: List[Dict[str, Any]] = list(docs or [])

    @staticmethod
    def _match(doc, q):
        for k, v in q.items():
            if doc.get(k) != v:
                return False
        return True

    async def create_index(self, *a, **kw): return "idx"

    async def find_one(self, q, projection=None):
        for d in self.docs:
            if self._match(d, q):
                return dict(d)
        return None

    async def insert_one(self, doc): self.docs.append(dict(doc))

    async def update_one(self, q, upd):
        for d in self.docs:
            if self._match(d, q):
                for k, v in (upd.get("$set") or {}).items():
                    d[k] = v
                return

    async def delete_one(self, q):
        for i, d in enumerate(list(self.docs)):
            if self._match(d, q):
                self.docs.pop(i)
                return _DeleteResult(1)
        return _DeleteResult(0)


@pytest.fixture
def fake_db(monkeypatch):
    from config import db as _real
    sessions_coll = _FakeCollection()
    suppliers_coll = _FakeCollection([
        {"id": "sup-heritage", "tenant_id": "tenant-A",
          "slug": "heritage", "display_name": "Heritage Pool Plus"},
        {"id": "sup-ewing", "tenant_id": "tenant-A",
          "slug": "ewing", "display_name": "Ewing Irrigation"},
        {"id": "sup-poolcorp", "tenant_id": "tenant-A",
          "slug": "poolcorp", "display_name": "Pool360"},
    ])
    monkeypatch.setattr(_real, "supplier_sessions", sessions_coll,
                          raising=False)
    monkeypatch.setattr(_real, "suppliers", suppliers_coll,
                          raising=False)
    # Force helper re-init so ``ensure_index`` runs against the fake.
    from services.suppliers import sessions as _s
    monkeypatch.setattr(_s, "_INDEX_ENSURED", False, raising=False)
    return {"sessions": sessions_coll, "suppliers": suppliers_coll}


ADMIN = {"id": "u-admin", "role": "admin", "tenant_id": "tenant-A"}
MANAGER = {"id": "u-mgr", "role": "manager", "tenant_id": "tenant-A"}
TECH = {"id": "u-tech", "role": "technician", "tenant_id": "tenant-A"}


# ─── sessions.upsert + Fernet round-trip ────────────────────────────────
def test_session_upsert_and_fernet_round_trip(fake_db):
    import asyncio

    async def _run():
        from services.suppliers.sessions import (
            upsert_session, get_active_session,
        )
        cookies = [
            {"name": "cf_clearance", "value": "abc123",
              "domain": "heritagepoolplus.com"},
            {"name": "sess", "value": "def456",
              "domain": "heritagepoolplus.com"},
        ]
        r = await upsert_session(
            "tenant-A", "heritage", cookies, user_id="u1",
        )
        assert r["cookie_count"] == 2
        assert r["expires_at"]
        # Round-trip: read back via ``get_active_session`` decrypts +
        # returns the exact list we uploaded.
        got = await get_active_session("tenant-A", "heritage")
        assert got == cookies
        # Stored row has an encrypted blob, NOT the plaintext cookies.
        row = fake_db["sessions"].docs[0]
        assert "encrypted_cookies" in row
        assert "cf_clearance" not in row.get("encrypted_cookies", "")

    asyncio.run(_run())


# ─── Session expiry semantics ───────────────────────────────────────────
def test_session_status_reports_expired_row_as_inactive(fake_db):
    import asyncio

    async def _run():
        from services.suppliers.sessions import (
            upsert_session, session_status,
        )
        # Upload, then rewind ``expires_at`` past now.
        await upsert_session("tenant-A", "heritage",
                              [{"name": "x", "value": "y"}])
        past = (datetime.now(timezone.utc)
                  - timedelta(minutes=5)).isoformat()
        fake_db["sessions"].docs[0]["expires_at"] = past

        status = await session_status("tenant-A", "heritage")
        assert status["has_active_session"] is False
        assert status["expires_at"] is None

    asyncio.run(_run())


# ─── Tenant scoping ─────────────────────────────────────────────────────
def test_session_get_never_leaks_across_tenants(fake_db):
    import asyncio

    async def _run():
        from services.suppliers.sessions import (
            upsert_session, get_active_session,
        )
        await upsert_session("tenant-A", "heritage",
                              [{"name": "a", "value": "1"}])
        await upsert_session("tenant-B", "heritage",
                              [{"name": "b", "value": "2"}])
        got_a = await get_active_session("tenant-A", "heritage")
        got_b = await get_active_session("tenant-B", "heritage")
        assert got_a == [{"name": "a", "value": "1"}]
        assert got_b == [{"name": "b", "value": "2"}]

    asyncio.run(_run())


# ─── Role gate on POST/GET/DELETE ───────────────────────────────────────
def test_role_gate_admin_and_manager_pass_others_403(fake_db):
    """Design lock §3 — admin + super_admin + manager pass; tech +
    customer are 403."""
    import asyncio
    from routers.suppliers import _require_session_role
    from fastapi import HTTPException
    for u in ({"role": "admin"}, {"role": "super_admin"}, {"role": "manager"}):
        _require_session_role(u)  # no throw
    for u in ({"role": "technician"}, {"role": "customer"},
              {"role": ""}, {}):
        with pytest.raises(HTTPException) as ex:
            _require_session_role(u)
        assert ex.value.status_code == 403
    _ = asyncio  # silence unused


# ─── Supplier opt-in flag enforcement ───────────────────────────────────
def test_ewing_upsert_returns_400_supplier_does_not_support_handoff(fake_db):
    import asyncio
    from fastapi import HTTPException
    from routers.suppliers import _assert_handoff_supported

    with pytest.raises(HTTPException) as ex:
        _assert_handoff_supported("ewing")
    assert ex.value.status_code == 400
    assert ex.value.detail["error"] == "supplier_does_not_support_handoff"

    # ePoolSupply also stays scripted.
    with pytest.raises(HTTPException) as ex:
        _assert_handoff_supported("epoolsupply")
    assert ex.value.status_code == 400
    assert ex.value.detail["error"] == "supplier_does_not_support_handoff"

    # Heritage / Pool360 / SiteOne pass through cleanly.
    for slug in ("heritage", "poolcorp", "siteone"):
        _assert_handoff_supported(slug)   # no throw
    _ = asyncio


# ─── Challenge detector ─────────────────────────────────────────────────
class _FakePage:
    def __init__(self, url="", elements=None, username_visible=True):
        self.url = url
        self._elements = elements or {}
        self._username_visible = username_visible

    async def query_selector(self, sel):
        return self._elements.get(sel)

    async def wait_for_selector(self, sel, state=None, timeout=None):
        if self._username_visible:
            return object()
        raise TimeoutError("not visible")


def test_challenge_detector_triggers_on_cloudflare_url():
    import asyncio
    from services.suppliers.challenge import (
        detect_challenge_on_page, SupplierChallengeRequired,
    )

    async def _run():
        page = _FakePage(url="https://challenges.cloudflare.com/turnstile")
        with pytest.raises(SupplierChallengeRequired):
            await detect_challenge_on_page(page, "heritage")

    asyncio.run(_run())


def test_challenge_detector_triggers_on_dom_marker():
    import asyncio
    from services.suppliers.challenge import (
        detect_challenge_on_page, SupplierChallengeRequired,
    )

    async def _run():
        page = _FakePage(
            url="https://heritagepoolplus.com/login",
            elements={".cf-turnstile": object()},
        )
        with pytest.raises(SupplierChallengeRequired):
            await detect_challenge_on_page(page, "heritage")

    asyncio.run(_run())


def test_challenge_detector_triggers_on_invisible_username_input():
    import asyncio
    from services.suppliers.challenge import (
        detect_challenge_on_page, SupplierChallengeRequired,
    )

    async def _run():
        page = _FakePage(
            url="https://heritagepoolplus.com/login",
            elements={},
            username_visible=False,
        )
        with pytest.raises(SupplierChallengeRequired):
            await detect_challenge_on_page(
                page, "heritage",
                username_selector="#user",
            )

    asyncio.run(_run())


def test_challenge_detector_passes_on_normal_login_page():
    import asyncio
    from services.suppliers.challenge import detect_challenge_on_page

    async def _run():
        page = _FakePage(
            url="https://heritagepoolplus.com/login",
            elements={},
            username_visible=True,
        )
        await detect_challenge_on_page(
            page, "heritage", username_selector="#user",
        )  # no throw

    asyncio.run(_run())


# ─── Delete idempotency ─────────────────────────────────────────────────
def test_delete_session_is_idempotent(fake_db):
    import asyncio

    async def _run():
        from services.suppliers.sessions import (
            upsert_session, delete_session,
        )
        await upsert_session("tenant-A", "heritage",
                              [{"name": "a", "value": "1"}])
        n1 = await delete_session("tenant-A", "heritage")
        n2 = await delete_session("tenant-A", "heritage")
        assert n1 == 1
        assert n2 == 0

    asyncio.run(_run())
