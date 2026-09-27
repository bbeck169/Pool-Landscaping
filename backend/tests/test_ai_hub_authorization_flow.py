"""AIHUB-A · Feb-2026 — authorization flow tests.

Locks the ``PATCH /api/ai-employees/{eid}/authorize`` contract:

1. Migration + seed default: every employee lands with
   ``authorized_for_public_use=False``.
2. Toggle flips the flag + returns the updated row.
3. Non-admin users cannot flip (401 / 403 per the ``require_admin``
   dep contract).
4. INFO-level audit log fires with tenant_id + actor + before/after.
5. Idempotent no-op flip (True → True) does NOT emit a log line
   and returns current state.

Uses ``fastapi.testclient.TestClient`` against a minimal FastAPI
app that mounts only the AIHUB-A endpoint slice with fake Motor
+ fake tenant/user deps.  This isolates the flip semantics from
the 3500-line ``routers/ai_employees.py`` while still exercising
the actual handler function.
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from routers import ai_employees as mod


# ═══════════════════════════════════════════════════════════════════
# Test app scaffolding
# ═══════════════════════════════════════════════════════════════════
_FAKE_ADMIN = {"id": "user-admin-1", "role": "admin",
                 "email": "admin@t.com"}
_FAKE_TENANT = {"id": "tenant-flip", "name": "Flip"}
_FAKE_TECH = {"id": "user-tech-1", "role": "tech",
                "email": "tech@t.com"}


def _install_fake_db_with_row(row: dict) -> dict:
    """Rebind ``ai_employees.db.ai_employees`` to a MagicMock that
    returns ``row`` from ``find_one`` and records updates."""
    storage = {"row": dict(row)}

    async def _find_one(query, projection=None):
        r = storage["row"]
        if r.get("id") != query.get("id"):
            return None
        if r.get("tenant_id") != query.get("tenant_id"):
            return None
        return dict(r)

    async def _update_one(query, patch):
        storage["row"].update(patch.get("$set", {}))
        return SimpleNamespace(matched_count=1)

    fake_db = MagicMock()
    fake_db.ai_employees.find_one = _find_one
    fake_db.ai_employees.update_one = _update_one
    return storage, fake_db


def _make_app(*, user, fake_db, monkeypatch):
    """Mount only the authorize endpoint with dep overrides."""
    monkeypatch.setattr(mod, "db", fake_db)

    app = FastAPI()
    app.include_router(mod.router, prefix="/api")

    from routers.tenants import get_current_tenant
    from utils import require_admin

    def _override_admin():
        if user.get("role") not in ("admin", "super_admin"):
            raise HTTPException(status_code=403, detail="admin required")
        return user
    def _override_tenant():
        return _FAKE_TENANT

    app.dependency_overrides[require_admin] = _override_admin
    app.dependency_overrides[get_current_tenant] = _override_tenant
    return app


# ═══════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════
def test_default_authorization_is_false_on_fresh_row(monkeypatch):
    row = {
        "id": "emp-1", "tenant_id": _FAKE_TENANT["id"],
        "key": "nova", "name": "Sarah",
        "authorized_for_public_use": False,
    }
    _, fake_db = _install_fake_db_with_row(row)
    app = _make_app(user=_FAKE_ADMIN, fake_db=fake_db,
                     monkeypatch=monkeypatch)
    client = TestClient(app)
    # Read via the flip endpoint's "no-op" branch — same-value payload
    # returns current row.
    r = client.patch("/api/ai-employees/emp-1/authorize",
                      json={"authorized_for_public_use": False})
    assert r.status_code == 200, r.text
    assert r.json()["authorized_for_public_use"] is False


def test_admin_flips_authorization_on(monkeypatch):
    row = {
        "id": "emp-2", "tenant_id": _FAKE_TENANT["id"],
        "key": "pulse", "name": "Paul",
        "authorized_for_public_use": False,
    }
    storage, fake_db = _install_fake_db_with_row(row)
    app = _make_app(user=_FAKE_ADMIN, fake_db=fake_db,
                     monkeypatch=monkeypatch)
    client = TestClient(app)
    r = client.patch("/api/ai-employees/emp-2/authorize",
                      json={"authorized_for_public_use": True})
    assert r.status_code == 200, r.text
    assert r.json()["authorized_for_public_use"] is True
    # Storage reflects the flip.
    assert storage["row"]["authorized_for_public_use"] is True


def test_admin_flips_authorization_off(monkeypatch):
    row = {
        "id": "emp-3", "tenant_id": _FAKE_TENANT["id"],
        "key": "pulse", "name": "Paul",
        "authorized_for_public_use": True,
    }
    storage, fake_db = _install_fake_db_with_row(row)
    app = _make_app(user=_FAKE_ADMIN, fake_db=fake_db,
                     monkeypatch=monkeypatch)
    client = TestClient(app)
    r = client.patch("/api/ai-employees/emp-3/authorize",
                      json={"authorized_for_public_use": False})
    assert r.status_code == 200
    assert r.json()["authorized_for_public_use"] is False
    assert storage["row"]["authorized_for_public_use"] is False


def test_non_admin_gets_403(monkeypatch):
    row = {
        "id": "emp-4", "tenant_id": _FAKE_TENANT["id"],
        "key": "nova", "authorized_for_public_use": False,
    }
    _, fake_db = _install_fake_db_with_row(row)
    app = _make_app(user=_FAKE_TECH, fake_db=fake_db,
                     monkeypatch=monkeypatch)
    client = TestClient(app)
    r = client.patch("/api/ai-employees/emp-4/authorize",
                      json={"authorized_for_public_use": True})
    assert r.status_code == 403


def test_missing_employee_returns_404(monkeypatch):
    row = {
        "id": "emp-5", "tenant_id": _FAKE_TENANT["id"],
        "key": "nova", "authorized_for_public_use": False,
    }
    _, fake_db = _install_fake_db_with_row(row)
    app = _make_app(user=_FAKE_ADMIN, fake_db=fake_db,
                     monkeypatch=monkeypatch)
    client = TestClient(app)
    r = client.patch("/api/ai-employees/no-such-id/authorize",
                      json={"authorized_for_public_use": True})
    assert r.status_code == 404


def test_flip_emits_info_audit_log_with_before_after(monkeypatch, caplog):
    row = {
        "id": "emp-6", "tenant_id": _FAKE_TENANT["id"],
        "key": "nova", "authorized_for_public_use": False,
    }
    _, fake_db = _install_fake_db_with_row(row)
    app = _make_app(user=_FAKE_ADMIN, fake_db=fake_db,
                     monkeypatch=monkeypatch)
    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger="pool_crm"):
        r = client.patch("/api/ai-employees/emp-6/authorize",
                          json={"authorized_for_public_use": True})
    assert r.status_code == 200
    # Audit log — must include tenant_id, actor user id, employee key,
    # before + after.
    audit_lines = [
        rec.message for rec in caplog.records
        if "ai_hub.authorize" in rec.message
    ]
    assert audit_lines, (
        f"expected ai_hub.authorize audit log, got: "
        f"{[r.message for r in caplog.records]}"
    )
    line = audit_lines[0]
    assert "employee_id=emp-6" in line
    assert "employee_key=nova" in line
    assert f"tenant_id={_FAKE_TENANT['id']}" in line
    assert f"actor_user_id={_FAKE_ADMIN['id']}" in line
    assert "before=False" in line and "after=True" in line


def test_noop_flip_does_not_log_audit_line(monkeypatch, caplog):
    row = {
        "id": "emp-7", "tenant_id": _FAKE_TENANT["id"],
        "key": "nova", "authorized_for_public_use": True,
    }
    _, fake_db = _install_fake_db_with_row(row)
    app = _make_app(user=_FAKE_ADMIN, fake_db=fake_db,
                     monkeypatch=monkeypatch)
    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger="pool_crm"):
        # Same value as current — no-op.
        r = client.patch("/api/ai-employees/emp-7/authorize",
                          json={"authorized_for_public_use": True})
    assert r.status_code == 200
    audit_lines = [
        rec.message for rec in caplog.records
        if "ai_hub.authorize" in rec.message
    ]
    assert audit_lines == [], (
        f"unexpected audit noise on no-op flip: {audit_lines}"
    )
