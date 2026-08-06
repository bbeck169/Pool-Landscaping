"""Feb-2026 · SHOW_DEMO_LOGINS default flip — pytest.

The ``GET /api/config/public`` endpoint now defaults to
``show_demo_logins=false`` when the env var is unset, so production
hides the demo-account block out of the box (no env paste required).
Preview / dev keep the affordance by explicitly setting
``SHOW_DEMO_LOGINS=true`` in ``backend/.env``.

In-process test — patches ``os.environ.SHOW_DEMO_LOGINS`` and calls
the async endpoint directly. Never touches the running supervisor
uvicorn (so it doesn't stomp the preview override).
"""
from __future__ import annotations
import asyncio
import os

import pytest

from routers import config as _cfg


@pytest.fixture(autouse=True)
def _preserve_env(monkeypatch):
    """Isolate the env for every test — the preview .env has the flag
    set to ``true`` and we don't want that leaking between assertions."""
    monkeypatch.delenv("SHOW_DEMO_LOGINS", raising=False)
    yield


def _call_public():
    """Batch-safe async driver — `asyncio.get_event_loop()` can raise
    ``RuntimeError: There is no current event loop`` on Py 3.11+ when
    a prior test in the batch closed the main-thread's default loop.
    Always create a fresh loop so the helper is order-independent."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_cfg.config_public())
    finally:
        loop.close()


def test_default_is_false_when_env_var_is_unset(monkeypatch):
    monkeypatch.delenv("SHOW_DEMO_LOGINS", raising=False)
    r = _call_public()
    assert r["show_demo_logins"] is False


def test_true_when_env_var_is_true(monkeypatch):
    monkeypatch.setenv("SHOW_DEMO_LOGINS", "true")
    r = _call_public()
    assert r["show_demo_logins"] is True


def test_true_accepts_common_truthy_values(monkeypatch):
    for v in ("true", "TRUE", "True", "1", "yes", "on"):
        monkeypatch.setenv("SHOW_DEMO_LOGINS", v)
        r = _call_public()
        assert r["show_demo_logins"] is True, f"got False for env={v!r}"


def test_false_when_env_var_is_explicit_false(monkeypatch):
    monkeypatch.setenv("SHOW_DEMO_LOGINS", "false")
    r = _call_public()
    assert r["show_demo_logins"] is False


def test_false_for_unknown_or_garbage_values(monkeypatch):
    for v in ("no", "0", "off", "maybe", "", "  "):
        monkeypatch.setenv("SHOW_DEMO_LOGINS", v)
        r = _call_public()
        assert r["show_demo_logins"] is False, f"got True for env={v!r}"


def test_response_shape_still_includes_show_demo_logins(monkeypatch):
    """Post-LZ4 contract — ``show_demo_logins`` + Feb-2026 hotfix
    adds ``app_env`` to the payload.

    The old Phase-4B ``/config/public`` payload also carried
    ``stripe_publishable_key`` / ``stripe_mode`` / ``app_public_url``
    / ``brand_name`` for the checkout modal. Those fields were dropped
    when the Stripe SDK was retired (Phase LZ4). The Feb-2026 P0
    hotfix adds ``app_env`` so the web + mobile login pages can gate
    the preview-only demo-tiles section at RUNTIME.
    """
    monkeypatch.delenv("SHOW_DEMO_LOGINS", raising=False)
    r = _call_public()
    assert "show_demo_logins" in r
    assert isinstance(r["show_demo_logins"], bool)
    assert "app_env" in r
    assert isinstance(r["app_env"], str)


# ═══════════════════════════════════════════════════════════════════
# Feb 2026 · Demo-Login P0 hotfix — app_env exposure contract.
# The web + mobile login gates rely on the SERVER-SIDE runtime value
# to avoid the build-time env-var leak that shipped the preview
# tiles to production. Assert the endpoint reports the current
# APP_ENV verbatim (lower-cased, whitelisted), and falls back to
# "production" for missing / unknown values so the frontend
# fail-safe path (hide) is the default.
# ═══════════════════════════════════════════════════════════════════
def test_app_env_defaults_to_production_when_unset(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    r = _call_public()
    assert r["app_env"] == "production"


def test_app_env_reports_preview(monkeypatch):
    monkeypatch.setenv("APP_ENV", "preview")
    r = _call_public()
    assert r["app_env"] == "preview"


def test_app_env_reports_development(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    r = _call_public()
    assert r["app_env"] == "development"


def test_app_env_reports_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    r = _call_public()
    assert r["app_env"] == "production"


def test_app_env_is_lowercased(monkeypatch):
    for v in ("PRODUCTION", "Preview", "  development  "):
        monkeypatch.setenv("APP_ENV", v)
        r = _call_public()
        assert r["app_env"] == v.strip().lower()


def test_app_env_unknown_value_falls_back_to_production(monkeypatch):
    """Whitelist guard — an attacker or a mis-typed env value must
    never accidentally satisfy ``app_env !== "production"`` on the
    client. Anything outside the known set is coerced back to the
    safe default so the tiles stay hidden."""
    for v in ("weird", "prod", "PRODUCTIION", "somethingnew"):
        monkeypatch.setenv("APP_ENV", v)
        r = _call_public()
        assert r["app_env"] == "production", f"unexpected app_env for env={v!r}: {r['app_env']!r}"
