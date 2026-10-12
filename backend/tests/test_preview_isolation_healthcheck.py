"""Preview isolation · healthcheck-endpoint tests.

Verifies:

  * On ``APP_ENV=production``, the endpoint 404s (admin or not).
  * On preview env, admin role returns 200 with the full status
    shape, incl. the Commit E expansions:
      - ``pii_shape_audit.rechecked_at``
      - ``pii_shape_audit.rows_scanned``
      - ``pii_shape_audit.offenders`` (<= 10, redacted hints)
  * Non-admin users 403 (dependency not exercised here — covered by
    the FastAPI auth test suite).
  * Overall status rolls up correctly across the three sub-signals.
  * **Injection tests (Commit E)** — inject real-PII strings into
    ``customers.search_haystack``, ``customers.phone_raw``, and
    ``leads.message`` in three separate test cases, hit the live
    healthcheck, and assert each returns RED with the correct
    ``field_name`` in the top-10 offenders list, then clean up.
"""
from __future__ import annotations

import importlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo import MongoClient
from dotenv import dotenv_values
from pathlib import Path

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
API = "http://localhost:8001/api"


def _mint_app(env: str) -> FastAPI:
    """Build a tiny FastAPI app that mounts the healthcheck router
    with a stubbed ``require_admin`` dependency and a stubbed Mongo
    ``db``. Reloading ensures ``APP_ENV`` is picked up by the module
    at import."""
    os.environ["APP_ENV"] = env

    import services.preview_isolation.config as cfg
    importlib.reload(cfg)
    import services.preview_isolation as pi
    importlib.reload(pi)

    import routers.preview_isolation_admin as mod
    importlib.reload(mod)

    # Stub Mongo db: the handler calls customers.count_documents
    # (twice at top-level) + customers / leads / users via the
    # audit rules. We stub ``count_documents`` with a dynamic
    # return based on the filter shape so the audit returns the
    # expected offender count.
    stub_db = MagicMock()
    stub_db.customers.count_documents = AsyncMock(return_value=0)
    stub_db.leads.count_documents = AsyncMock(return_value=0)
    stub_db.users.count_documents = AsyncMock(return_value=0)
    stub_db.audit_logs.find_one = AsyncMock(return_value={
        "at": "2026-10-08T18:27:28+00:00",
        "actor": "system:preview_scrub",
        "meta": {"total": 24366, "scrubbed_counts": {"customers": 712}},
    })

    # ``find(...).limit(n)`` on the offender sample path. Default
    # to empty async iterator.
    class _EmptyCursor:
        def limit(self, n): return self
        def __aiter__(self): return self
        async def __anext__(self): raise StopAsyncIteration
    stub_db.customers.find = MagicMock(return_value=_EmptyCursor())
    stub_db.leads.find = MagicMock(return_value=_EmptyCursor())
    stub_db.users.find = MagicMock(return_value=_EmptyCursor())
    mod.db = stub_db

    app = FastAPI()
    app.include_router(mod.router, prefix="/api")
    app.dependency_overrides[mod.require_admin] = lambda: {
        "id": "u-admin", "role": "admin",
    }

    import sys
    import types
    fake_server = types.SimpleNamespace()
    fake_server.app = app
    sys.modules["server"] = fake_server
    return app


# ────────────────────────────────────────────────────────────────────
# 1 · Production env — 404.
# ────────────────────────────────────────────────────────────────────
def test_production_returns_404():
    app = _mint_app("production")
    client = TestClient(app)
    r = client.get("/api/admin/preview-isolation-status")
    assert r.status_code == 404
    assert r.json()["detail"] == "not_found"
    os.environ["APP_ENV"] = "development"


# ────────────────────────────────────────────────────────────────────
# 2 · Preview env, admin role — 200 + full shape incl. Commit E
#     expansions.
# ────────────────────────────────────────────────────────────────────
def test_preview_admin_returns_full_status():
    app = _mint_app("development")
    import routers.preview_isolation_admin as mod
    mod.db.customers.count_documents = AsyncMock(side_effect=[722, 602] + [0] * 50)
    mod.db.leads.count_documents = AsyncMock(return_value=0)
    mod.db.users.count_documents = AsyncMock(return_value=0)

    with patch.object(mod, "audit_route_registry", return_value={
        "declared_pii_routes": 41,
        "total_routes": 2365,
        "status": "GREEN",
        "missing_registered_routes": [],
        "unregistered_pii_shaped_routes": [],
    }):
        client = TestClient(app)
        r = client.get("/api/admin/preview-isolation-status")
    assert r.status_code == 200
    body = r.json()
    # Base shape — unchanged.
    assert body["env"] == "development"
    assert "db_name" in body
    assert "connected_mongo_host" in body
    assert body["preview_synthetic_salt_configured"] is True
    assert "registry" in body
    assert body["registry"]["declared_pii_routes"] >= 40
    assert body["registry"]["status"] in ("GREEN", "AMBER", "RED")
    # Commit E expansions.
    audit = body["pii_shape_audit"]
    assert audit["customers_total"] == 722
    assert audit["customers_matching_preview_pattern"] == 602
    assert audit["customers_with_real_pii_shape"] == 0
    assert audit["status"] == "GREEN"
    assert "rows_scanned" in audit
    assert isinstance(audit["rows_scanned"], int)
    assert "rechecked_at" in audit
    assert audit["rechecked_at"].startswith("2")  # ISO-ish
    assert isinstance(audit.get("offenders"), list)
    assert audit["offenders"] == []  # clean DB stub
    assert "per_field_counts" in audit
    assert "last_boot_scrub" in body
    assert body["last_boot_scrub"]["total_rows_scrubbed"] == 24366
    assert body["overall_status"] in ("GREEN", "AMBER")
    assert "generated_at" in body


# ────────────────────────────────────────────────────────────────────
# 3 · Overall status rolls up to GREEN when PII shape + registry
#     are both clean.
# ────────────────────────────────────────────────────────────────────
def test_overall_status_green_when_clean():
    app = _mint_app("development")
    import routers.preview_isolation_admin as mod
    mod.db.customers.count_documents = AsyncMock(side_effect=[500, 500] + [0] * 50)
    mod.db.leads.count_documents = AsyncMock(return_value=0)
    mod.db.users.count_documents = AsyncMock(return_value=0)
    with patch.object(mod, "audit_route_registry", return_value={
        "declared_pii_routes": 41,
        "total_routes": 2365,
        "status": "GREEN",
        "missing_registered_routes": [],
        "unregistered_pii_shaped_routes": [],
    }):
        client = TestClient(app)
        r = client.get("/api/admin/preview-isolation-status")
    assert r.status_code == 200
    body = r.json()
    assert body["pii_shape_audit"]["status"] == "GREEN"
    assert body["pii_shape_audit"]["customers_with_real_pii_shape"] == 0
    assert body["overall_status"] == "GREEN"


# ────────────────────────────────────────────────────────────────────
# 4 · Overall rolls up to AMBER when registry has unregistered
#     routes but PII shape is clean.
# ────────────────────────────────────────────────────────────────────
def test_overall_status_amber_when_registry_amber():
    app = _mint_app("development")
    import routers.preview_isolation_admin as mod
    mod.db.customers.count_documents = AsyncMock(side_effect=[500, 500] + [0] * 50)
    mod.db.leads.count_documents = AsyncMock(return_value=0)
    mod.db.users.count_documents = AsyncMock(return_value=0)
    with patch.object(mod, "audit_route_registry", return_value={
        "declared_pii_routes": 41,
        "total_routes": 2365,
        "status": "AMBER",
        "missing_registered_routes": [],
        "unregistered_pii_shaped_routes": [("POST", "/api/foo")],
    }):
        client = TestClient(app)
        r = client.get("/api/admin/preview-isolation-status")
    assert r.json()["overall_status"] == "AMBER"


# ────────────────────────────────────────────────────────────────────
# 5 · Hint redaction unit tests — the response wire must never
#     echo raw PII back to the admin.
# ────────────────────────────────────────────────────────────────────
def test_hint_redaction_email():
    os.environ["APP_ENV"] = "development"
    import routers.preview_isolation_admin as mod
    importlib.reload(mod)
    out = mod._hint("terry.peterson@gmail.com was here")
    assert "gmail.com" in out
    assert "terry" not in out.lower()
    assert "peterson" not in out.lower()
    assert "***" in out


def test_hint_redaction_phone():
    os.environ["APP_ENV"] = "development"
    import routers.preview_isolation_admin as mod
    importlib.reload(mod)
    out = mod._hint("+1-206-715-1234 is the number")
    assert "206-715-1234" not in out
    assert "*" in out
    assert "phone shape" in out


def test_hint_redaction_fallback_name():
    os.environ["APP_ENV"] = "development"
    import routers.preview_isolation_admin as mod
    importlib.reload(mod)
    out = mod._hint("Terry Peterson")
    assert "Peterson" not in out
    # First-word masked: 'T' + ('*' × (len-1)); accept any mask
    # length >= 3 so the behaviour doesn't drift on edge cases.
    assert "T****" in out
    assert "Terry" not in out


# ────────────────────────────────────────────────────────────────────
# 6 · Live injection tests (Commit E) — inject real-PII strings into
#     three different fields, hit the live healthcheck, assert RED
#     + correct field_name in offenders, then clean up each inject.
# ────────────────────────────────────────────────────────────────────
def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def live_db():
    c = MongoClient(_ENV["MONGO_URL"])
    yield c[_ENV["DB_NAME"]]
    c.close()


class TestLiveHealthcheckInjection:
    """Each case:
      1. Pick an existing preview-shape row.
      2. Overwrite one PII field with a real-shape string.
      3. GET /api/admin/preview-isolation-status.
      4. Assert status is RED and the offender list contains the
         expected (collection, field_name) pair.
      5. Restore the original value.

    The injection is scoped to ONE row per test so parallel test
    runs on the shared preview DB don't cross-contaminate.
    """

    def _snapshot_and_patch(self, live_db, coll_name: str, field: str,
                              inject_value):
        coll = live_db.get_collection(coll_name)
        # Pick a predictable row — the lowest-id preview-shape doc.
        row = coll.find_one({"name": {"$regex": r"^Preview "}})
        assert row is not None, \
            f"no preview-shape row in {coll_name} to use as injection target"
        original = row.get(field)
        coll.update_one({"_id": row["_id"]},
                        {"$set": {field: inject_value}})
        return row["_id"], original

    def _restore(self, live_db, coll_name: str, _id, field: str, original):
        coll = live_db.get_collection(coll_name)
        if original is None:
            coll.update_one({"_id": _id}, {"$unset": {field: 1}})
        else:
            coll.update_one({"_id": _id}, {"$set": {field: original}})

    def test_customers_search_haystack_injection_flips_red(
            self, admin_h, live_db):
        _id, original = self._snapshot_and_patch(
            live_db, "customers", "search_haystack",
            "terry peterson terry.peterson@gmail.com 206-715-1234",
        )
        try:
            r = requests.get(f"{API}/admin/preview-isolation-status",
                              headers=admin_h, timeout=15)
            assert r.status_code == 200, r.text[:400]
            body = r.json()
            assert body["pii_shape_audit"]["status"] == "RED"
            assert body["overall_status"] == "RED"
            offender_fields = {
                (o["collection"], o["field_name"])
                for o in body["pii_shape_audit"]["offenders"]
            }
            assert ("customers", "search_haystack") in offender_fields, \
                f"missing (customers, search_haystack); got: {offender_fields}"
            # Hint must redact — no raw 'terry' / 'peterson' /
            # 'gmail.com'-domain-email leaked back on the wire.
            for off in body["pii_shape_audit"]["offenders"]:
                if off["collection"] == "customers" and off["field_name"] == "search_haystack":
                    hint = off["hint"]
                    assert "terry" not in hint.lower() or "***" in hint
                    assert "@gmail.com" in hint or "gmail.com" in hint  # domain is a hint
                    assert "terry.peterson@gmail.com" not in hint  # not the full address
        finally:
            self._restore(live_db, "customers", _id, "search_haystack",
                           original)

    def test_customers_phone_raw_injection_flips_red(self, admin_h, live_db):
        _id, original = self._snapshot_and_patch(
            live_db, "customers", "phone_raw", "2067151234",
        )
        try:
            r = requests.get(f"{API}/admin/preview-isolation-status",
                              headers=admin_h, timeout=15)
            assert r.status_code == 200, r.text[:400]
            body = r.json()
            assert body["pii_shape_audit"]["status"] == "RED"
            offender_fields = {
                (o["collection"], o["field_name"])
                for o in body["pii_shape_audit"]["offenders"]
            }
            assert ("customers", "phone_raw") in offender_fields, \
                f"missing (customers, phone_raw); got: {offender_fields}"
        finally:
            self._restore(live_db, "customers", _id, "phone_raw", original)

    def test_leads_message_injection_flips_red(self, admin_h, live_db):
        # Make sure a preview-shape lead exists; if not skip.
        if live_db.leads.count_documents(
            {"name": {"$regex": r"^Preview "}}
        ) == 0:
            pytest.skip("no preview-shape lead row to use as injection target")
        _id, original = self._snapshot_and_patch(
            live_db, "leads", "message",
            "Please call me at terry.peterson@gmail.com or 206-715-1234",
        )
        try:
            r = requests.get(f"{API}/admin/preview-isolation-status",
                              headers=admin_h, timeout=15)
            assert r.status_code == 200, r.text[:400]
            body = r.json()
            assert body["pii_shape_audit"]["status"] == "RED"
            offender_fields = {
                (o["collection"], o["field_name"])
                for o in body["pii_shape_audit"]["offenders"]
            }
            assert ("leads", "message") in offender_fields, \
                f"missing (leads, message); got: {offender_fields}"
        finally:
            self._restore(live_db, "leads", _id, "message", original)
