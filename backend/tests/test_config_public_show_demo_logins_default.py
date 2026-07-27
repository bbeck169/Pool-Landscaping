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

from routers import payments_stripe_live as _psl


@pytest.fixture(autouse=True)
def _preserve_env(monkeypatch):
    """Isolate the env for every test — the preview .env has the flag
    set to ``true`` and we don't want that leaking between assertions."""
    monkeypatch.delenv("SHOW_DEMO_LOGINS", raising=False)
    yield


def _call_public():
    return asyncio.get_event_loop().run_until_complete(_psl.config_public()) \
        if not asyncio.get_event_loop().is_closed() \
        else asyncio.new_event_loop().run_until_complete(_psl.config_public())


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


def test_response_shape_still_includes_the_other_fields(monkeypatch):
    """Additive contract — the flip must not drop existing keys."""
    monkeypatch.delenv("SHOW_DEMO_LOGINS", raising=False)
    r = _call_public()
    for key in ("stripe_publishable_key", "stripe_mode", "app_public_url",
                  "brand_name", "show_demo_logins"):
        assert key in r, f"missing key: {key}"
