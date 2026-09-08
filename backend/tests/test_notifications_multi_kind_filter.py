"""Feb-2026 · Notifications filter dropdown — backend multi-kind test.

Pins the contract for ``GET /api/notifications?kind=<comma-list>``:

* Empty ``kind`` → no filter applied (all rows).
* Single token ``?kind=job_assigned`` → exact-match ``kind == job_assigned``.
* Multi-token ``?kind=job_assigned,invoice_paid`` → Mongo ``$in`` semantics.
* Trailing/interior empty tokens (``?kind=,job_assigned,,``) → dropped.

Scope: NARROW.  Calls the endpoint coroutine directly with a stub Motor
collection so we don't need the full app boot and don't pollute
neighbour test suites' event loops.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, *a, **kw): return self
    def skip(self, *a, **kw): return self
    def limit(self, *a, **kw): return self

    async def to_list(self, _limit):
        return list(self._rows)


class _FakeCollection:
    """Records the ``find`` filter and returns a stub cursor.  Enough to
    prove the router builds the right Mongo query without hitting DB."""

    def __init__(self):
        self.last_filter: Optional[Dict[str, Any]] = None
        self.rows: List[Dict[str, Any]] = []

    def find(self, filt, projection=None):
        self.last_filter = filt
        return _FakeCursor(self.rows)

    async def count_documents(self, filt):
        self.last_filter = filt
        return 0


class _FakeDB:
    def __init__(self):
        self.notifications = _FakeCollection()


def _seed_router(monkeypatch):
    from routers import notifications as notif_mod

    fake = _FakeDB()
    monkeypatch.setattr(notif_mod, "db", fake)
    return notif_mod, fake


def _admin_user():
    return {"id": "u-admin", "role": "admin",
            "tenant_id": "t-notif-1", "email": "admin@x.com"}


def _tenant():
    return {"id": "t-notif-1"}


# ─────────────────────────────────────────────────────────────────────
# 1. No kind filter → the resulting Mongo query has NO ``kind`` field
# ─────────────────────────────────────────────────────────────────────
def test_list_notifications_no_kind_filter(monkeypatch):
    notif_mod, fake = _seed_router(monkeypatch)
    _run(notif_mod.list_notifications(
        limit=50, offset=0, kind=None, unread_only=False,
        user=_admin_user(), tenant=_tenant(),
    ))
    assert "kind" not in fake.notifications.last_filter


# ─────────────────────────────────────────────────────────────────────
# 2. Single kind → equality match (NOT ``$in`` — keeps the query index-
#    friendly and back-compatible with pre-Feb-2026 callers)
# ─────────────────────────────────────────────────────────────────────
def test_list_notifications_single_kind_equality(monkeypatch):
    notif_mod, fake = _seed_router(monkeypatch)
    _run(notif_mod.list_notifications(
        limit=50, offset=0, kind="job_assigned", unread_only=False,
        user=_admin_user(), tenant=_tenant(),
    ))
    assert fake.notifications.last_filter["kind"] == "job_assigned"


# ─────────────────────────────────────────────────────────────────────
# 3. Multi kind → ``$in`` semantics with all tokens preserved.
# ─────────────────────────────────────────────────────────────────────
def test_list_notifications_multi_kind_uses_in(monkeypatch):
    notif_mod, fake = _seed_router(monkeypatch)
    _run(notif_mod.list_notifications(
        limit=50, offset=0,
        kind="job_assigned,invoice_paid,rc_sms_inbound",
        unread_only=False,
        user=_admin_user(), tenant=_tenant(),
    ))
    kf = fake.notifications.last_filter["kind"]
    assert isinstance(kf, dict) and "$in" in kf
    assert set(kf["$in"]) == {"job_assigned", "invoice_paid", "rc_sms_inbound"}


# ─────────────────────────────────────────────────────────────────────
# 4. Whitespace + empty tokens are dropped defensively.
# ─────────────────────────────────────────────────────────────────────
def test_list_notifications_multi_kind_drops_empty_tokens(monkeypatch):
    notif_mod, fake = _seed_router(monkeypatch)
    _run(notif_mod.list_notifications(
        limit=50, offset=0,
        kind=",job_assigned, ,invoice_paid,",
        unread_only=False,
        user=_admin_user(), tenant=_tenant(),
    ))
    kf = fake.notifications.last_filter["kind"]
    assert set(kf["$in"]) == {"job_assigned", "invoice_paid"}


# ─────────────────────────────────────────────────────────────────────
# 5. Trailing-commas single-token collapses to equality (not $in).
# ─────────────────────────────────────────────────────────────────────
def test_list_notifications_trailing_comma_single_token_is_equality(monkeypatch):
    notif_mod, fake = _seed_router(monkeypatch)
    _run(notif_mod.list_notifications(
        limit=50, offset=0, kind="job_assigned,", unread_only=False,
        user=_admin_user(), tenant=_tenant(),
    ))
    assert fake.notifications.last_filter["kind"] == "job_assigned"


# ─────────────────────────────────────────────────────────────────────
# 6. ``unread_only`` composes with a multi-kind $in filter.
# ─────────────────────────────────────────────────────────────────────
def test_list_notifications_multi_kind_with_unread_only(monkeypatch):
    notif_mod, fake = _seed_router(monkeypatch)
    _run(notif_mod.list_notifications(
        limit=50, offset=0, kind="job_assigned,invoice_paid",
        unread_only=True,
        user=_admin_user(), tenant=_tenant(),
    ))
    assert fake.notifications.last_filter["kind"] == {
        "$in": ["job_assigned", "invoice_paid"],
    }
    assert fake.notifications.last_filter["read"] == {"$ne": True}
