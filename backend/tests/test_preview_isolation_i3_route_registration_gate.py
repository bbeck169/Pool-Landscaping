"""Preview isolation · P0 Stage 3 Commit I3 — route-registration gate.

Blocker 2 of the P0a Stage 3 final-verification pass: an unauthenticated
production probe to ``/api/admin/preview-isolation-status`` returned
HTTP 401 (auth gate fires first → endpoint existence confirmed) instead
of HTTP 404 (endpoint not registered → indistinguishable from any
other nonexistent path).

The fix moves the production exclusion from the handler's internal
``if is_production_env(): raise HTTPException(404)`` check to the
include-router call site in ``server.py``: on production env, the
router is NEVER mounted — the path doesn't exist in ``app.routes``.

Two invariants pinned here:

1. With ``APP_ENV=production``, the admin healthcheck path is NOT
   present in the FastAPI app's route table.
2. With ``APP_ENV=production``, hitting the path via the ASGI client
   returns 404 (FastAPI's standard not-found response), NOT 401.

The TestClient path proves the route is not just absent from the
registry list but actually un-routable at HTTP level — same
observation an external attacker would make.
"""
from __future__ import annotations

import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient


_ADMIN_PATH = "/api/admin/preview-isolation-status"


def _rebuild_app(env: str):
    """Set ``APP_ENV`` and rebuild the FastAPI app from scratch.

    The gate at ``server.py`` evaluates ``is_production_env()`` at
    module-import time, so we have to reload the preview-isolation
    config module AND the server module to make the env flip
    deterministic. All sibling router modules get reloaded along
    with server (via its import chain) — safe because this is
    the only test module that mutates the gate, and pytest's
    per-test isolation ensures no concurrent run depends on the
    reloaded state.
    """
    os.environ["APP_ENV"] = env

    # Drop any cached modules that read APP_ENV at import.
    for mod_name in list(sys.modules):
        if (mod_name == "server"
                or mod_name.startswith("services.preview_isolation")
                or mod_name == "routers.preview_isolation_admin"):
            del sys.modules[mod_name]

    import services.preview_isolation.config as cfg  # noqa: F401
    import services.preview_isolation  # noqa: F401
    server = importlib.import_module("server")
    return server.app


# ────────────────────────────────────────────────────────────────────
# 1 · APP_ENV=production — route is NOT registered on the app.
# ────────────────────────────────────────────────────────────────────
def test_production_env_does_not_register_admin_route():
    """Pin the registration gate: ``/api/admin/preview-isolation-
    status`` MUST NOT appear in ``app.routes`` when APP_ENV is
    production."""
    try:
        app = _rebuild_app("production")
        paths = {getattr(r, "path", None) for r in app.routes}
        assert _ADMIN_PATH not in paths, (
            f"preview-isolation-status route is registered on production "
            f"env. Prod MUST NOT mount the route at all — probing with "
            f"no auth should 404, not 401. app.routes contains "
            f"{len([p for p in paths if p and 'preview-isolation' in p])} "
            f"preview-isolation path(s)."
        )
    finally:
        # Reset env + module cache so downstream tests see a clean
        # preview state.
        os.environ["APP_ENV"] = "development"
        for mod_name in list(sys.modules):
            if (mod_name == "server"
                    or mod_name.startswith("services.preview_isolation")
                    or mod_name == "routers.preview_isolation_admin"):
                del sys.modules[mod_name]


# ────────────────────────────────────────────────────────────────────
# 2 · APP_ENV=production — HTTP GET to the path returns 404 at
#     wire level (not 401 from a protected-endpoint auth gate).
# ────────────────────────────────────────────────────────────────────
def test_production_env_returns_404_not_401_over_http():
    """Pin the externally-observable behavior: with no auth and
    APP_ENV=production, GET the path through the ASGI client. Must
    be 404 (standard not-found) — anything else leaks the endpoint
    exists on prod."""
    try:
        app = _rebuild_app("production")
        client = TestClient(app)
        r = client.get(_ADMIN_PATH)  # NO Authorization header
        assert r.status_code == 404, (
            f"got {r.status_code} not 404 — unauthenticated prod probe "
            f"should see the exact same response as any nonexistent path. "
            f"Body: {r.text[:400]}"
        )
        # Also pin that even with a bogus auth header the response is
        # still 404 (no 401/403 discrimination).
        r = client.get(_ADMIN_PATH,
                        headers={"Authorization": "Bearer bogus-token"})
        assert r.status_code == 404, (
            f"got {r.status_code} with bogus Authorization — must be "
            f"404, not 401/403. The route must not exist at all on prod."
        )
    finally:
        os.environ["APP_ENV"] = "development"
        for mod_name in list(sys.modules):
            if (mod_name == "server"
                    or mod_name.startswith("services.preview_isolation")
                    or mod_name == "routers.preview_isolation_admin"):
                del sys.modules[mod_name]


# ────────────────────────────────────────────────────────────────────
# 3 · APP_ENV=development — route IS registered (regression check
#     that the gate didn't break preview).
# ────────────────────────────────────────────────────────────────────
def test_preview_env_still_registers_admin_route():
    """Negative-space check: the registration gate must only
    suppress on production. Preview env still mounts the router."""
    try:
        app = _rebuild_app("development")
        paths = {getattr(r, "path", None) for r in app.routes}
        assert _ADMIN_PATH in paths, (
            "preview-isolation-status route missing on development env — "
            "the registration gate over-matched and broke the preview "
            "healthcheck. Expected the route in app.routes."
        )
    finally:
        os.environ["APP_ENV"] = "development"
        for mod_name in list(sys.modules):
            if (mod_name == "server"
                    or mod_name.startswith("services.preview_isolation")
                    or mod_name == "routers.preview_isolation_admin"):
                del sys.modules[mod_name]
