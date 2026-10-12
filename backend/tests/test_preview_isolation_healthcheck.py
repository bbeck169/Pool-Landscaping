"""Preview isolation · healthcheck-endpoint tests.

Verifies:

  * On ``APP_ENV=production``, the endpoint 404s (admin or not).
  * On preview env, admin role returns 200 with the full status
    shape.
  * Non-admin users 403.
  * The shape includes env, db_name, mongo host, registry +
    pii_shape_audit + last_boot_scrub + overall_status.
"""
from __future__ import annotations

import importlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _mint_app(env: str) -> FastAPI:
    """Build a tiny FastAPI app that mounts the healthcheck router
    with a stubbed ``require_admin`` dependency and a stubbed Mongo
    ``db``. Reloading ensures ``APP_ENV`` is picked up by the module
    at import."""
    os.environ["APP_ENV"] = env

    # Reload the config module so is_production_env sees the new env.
    import services.preview_isolation.config as cfg
    importlib.reload(cfg)
    import services.preview_isolation as pi
    importlib.reload(pi)

    # Stub db + require_admin on the router module.
    import routers.preview_isolation_admin as mod
    importlib.reload(mod)

    stub_db = MagicMock()
    stub_db.customers.count_documents = AsyncMock(side_effect=[722, 602])
    stub_db.audit_logs.find_one = AsyncMock(return_value={
        "at": "2026-10-08T18:27:28+00:00",
        "actor": "system:preview_scrub",
        "meta": {"total": 24366, "scrubbed_counts": {"customers": 712}},
    })
    mod.db = stub_db

    # Dependency-override replacement to skip the real auth.
    app = FastAPI()
    app.include_router(mod.router, prefix="/api")
    app.dependency_overrides[mod.require_admin] = lambda: {
        "id": "u-admin", "role": "admin",
    }

    # ``audit_route_registry`` imports ``server.app`` lazily. Stub
    # that symbol so the handler sees a predictable report.
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
    # Clean up env for subsequent tests.
    os.environ["APP_ENV"] = "development"


# ────────────────────────────────────────────────────────────────────
# 2 · Preview env, admin role — 200 + shape.
# ────────────────────────────────────────────────────────────────────
def test_preview_admin_returns_full_status():
    app = _mint_app("development")
    client = TestClient(app)
    r = client.get("/api/admin/preview-isolation-status")
    assert r.status_code == 200
    body = r.json()
    assert body["env"] == "development"
    assert "db_name" in body
    assert "connected_mongo_host" in body
    assert body["preview_synthetic_salt_configured"] is True
    assert "registry" in body
    assert "declared_pii_routes" in body["registry"]
    assert body["registry"]["declared_pii_routes"] >= 40
    assert body["registry"]["status"] in ("GREEN", "AMBER", "RED")
    assert "pii_shape_audit" in body
    assert body["pii_shape_audit"]["customers_total"] == 722
    assert body["pii_shape_audit"]["customers_matching_preview_pattern"] == 602
    assert body["pii_shape_audit"]["customers_with_real_pii_shape"] == 120
    assert body["pii_shape_audit"]["status"] == "RED"
    assert "last_boot_scrub" in body
    assert body["last_boot_scrub"]["total_rows_scrubbed"] == 24366
    assert body["overall_status"] == "RED"
    assert "generated_at" in body


# ────────────────────────────────────────────────────────────────────
# 3 · Overall status rolls up to GREEN when PII shape + registry
#     are both clean.
# ────────────────────────────────────────────────────────────────────
def test_overall_status_green_when_clean():
    app = _mint_app("development")
    # Flip the stubs: zero real-PII rows + GREEN registry.
    import routers.preview_isolation_admin as mod
    mod.db.customers.count_documents = AsyncMock(side_effect=[500, 500])
    # Patch audit_route_registry to return GREEN.
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
    mod.db.customers.count_documents = AsyncMock(side_effect=[500, 500])
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
