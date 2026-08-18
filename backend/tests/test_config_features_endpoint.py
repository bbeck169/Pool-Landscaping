"""Feb 2026 · Demo-login P0 Hotfix #3 · ``/api/config/features``.

Dedicated endpoint that returns ONLY ``demo_logins_enabled`` — the
minimal contract the frontend needs to gate the demo-logins block.

Env-var contract:
 * ``SHOW_DEMO_LOGINS`` unset  → False.
 * ``SHOW_DEMO_LOGINS=""``    → False.
 * ``SHOW_DEMO_LOGINS="0"``   → False.
 * ``SHOW_DEMO_LOGINS="false"``→ False.
 * ``SHOW_DEMO_LOGINS="true"``→ True.
 * ``SHOW_DEMO_LOGINS="yes"`` → True (mirror of the legacy parser).
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# Import via the module path so the router is registered under the
# same ``/api`` prefix the app uses at runtime.
from server import app


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _restore_show_demo_env():
    prev = os.environ.get("SHOW_DEMO_LOGINS")
    yield
    if prev is None:
        os.environ.pop("SHOW_DEMO_LOGINS", None)
    else:
        os.environ["SHOW_DEMO_LOGINS"] = prev


@pytest.mark.parametrize("val", ["", "0", "false", "no", "FALSE", "off"])
def test_defaults_and_falsy_values_disable(client, val, monkeypatch):
    if val == "":
        monkeypatch.delenv("SHOW_DEMO_LOGINS", raising=False)
    else:
        monkeypatch.setenv("SHOW_DEMO_LOGINS", val)
    r = client.get("/api/config/features")
    assert r.status_code == 200
    body = r.json()
    assert body == {"demo_logins_enabled": False}, body


@pytest.mark.parametrize("val", ["true", "TRUE", "1", "yes", "on"])
def test_truthy_values_enable(client, val, monkeypatch):
    monkeypatch.setenv("SHOW_DEMO_LOGINS", val)
    r = client.get("/api/config/features")
    assert r.status_code == 200
    assert r.json() == {"demo_logins_enabled": True}


def test_endpoint_is_public_no_auth_required(client, monkeypatch):
    # Sanity-check — no ``Authorization`` header, no cookie, still 200.
    monkeypatch.delenv("SHOW_DEMO_LOGINS", raising=False)
    r = client.get("/api/config/features")
    assert r.status_code == 200
