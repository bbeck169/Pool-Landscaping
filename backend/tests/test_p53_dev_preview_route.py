"""Phase P53 · Feb-2026 — Dev-only BOOM email preview route.

Locks the two behaviors of ``GET /api/dev/email-preview/referral-reward``:

  1. Dev/preview env → 200 with rendered BOOM HTML.
  2. Production env → 404 (defensive runtime guard — the primary
     defense is registration-time gating in ``server.py``).

Test uses FastAPI's ``TestClient`` with the router mounted directly,
so we don't depend on the boot sequence.
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def preview_client(monkeypatch):
    """Build an isolated FastAPI app with just the P53 preview
    router mounted so the test is hermetic (no dependency on the
    full server boot)."""
    from routers.dev_email_preview import router

    def _make(env_val: str):
        monkeypatch.setenv("APP_ENV", env_val)
        # Fallback for callers that unset PUBLIC_APP_URL between tests.
        app = FastAPI()
        app.include_router(router, prefix="/api")
        return TestClient(app)

    return _make


# ═════════════════════════════════════════════════════════════════════
# Section 1 — Dev env renders BOOM HTML
# ═════════════════════════════════════════════════════════════════════
def test_dev_env_returns_200_with_boom_markers(preview_client):
    client = preview_client("preview")

    r = client.get("/api/dev/email-preview/referral-reward")

    assert r.status_code == 200, r.text
    body = r.text
    # BOOM design markers survive render + shell wrap.
    assert "BOOM! 🚀" in body
    assert "Refer another friend" in body
    assert "#10B981" in body
    assert "linear-gradient(135deg,#1B1F5C 0%,#16A34A 100%)" in body
    # Stub context landed.
    assert "Prasad Mikkilineni" in body
    assert "$55.00" in body
    assert "Alex" in body
    # No unrendered placeholders leaked through.
    for token in ("{{CUSTOMER_FIRST_NAME}}", "{{REFERRAL_FRIEND_NAME}}",
                  "{{REFERRAL_CREDIT_AMOUNT}}",
                  "{{CUSTOMER_CREDIT_BALANCE}}",
                  "{{COMPANY_NAME}}", "{{PORTAL_REFERRALS_URL}}"):
        assert token not in body, f"placeholder leak: {token}"


def test_dev_env_content_type_is_html(preview_client):
    client = preview_client("preview")
    r = client.get("/api/dev/email-preview/referral-reward")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


def test_dev_env_default_when_env_missing(preview_client, monkeypatch):
    """No ``APP_ENV`` at all → the codebase default ``preview`` wins,
    so the route responds 200."""
    monkeypatch.delenv("APP_ENV", raising=False)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.dev_email_preview import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)

    r = client.get("/api/dev/email-preview/referral-reward")

    assert r.status_code == 200


# ═════════════════════════════════════════════════════════════════════
# Section 2 — Production env — defensive 404
# ═════════════════════════════════════════════════════════════════════
def test_prod_env_returns_404(preview_client):
    """If a bad merge causes the route to be mounted in prod, the
    runtime guard still fires — 404 NOT FOUND, indistinguishable
    from an unmounted route."""
    client = preview_client("production")

    r = client.get("/api/dev/email-preview/referral-reward")

    assert r.status_code == 404


def test_prod_env_case_insensitive(preview_client):
    """``APP_ENV`` comparison must be case-insensitive so PRODUCTION,
    Production, production all lock the route."""
    for variant in ("PRODUCTION", "Production", "production"):
        client = preview_client(variant)
        r = client.get("/api/dev/email-preview/referral-reward")
        assert r.status_code == 404, (
            f"variant {variant!r} did NOT lock the route "
            f"(status={r.status_code})"
        )


# ═════════════════════════════════════════════════════════════════════
# Section 3 — ENABLE_DEV_EMAIL_PREVIEW escape hatch
# ═════════════════════════════════════════════════════════════════════
def test_enable_dev_email_preview_override_unlocks_prod(monkeypatch):
    """The preview pod's ``backend/.env`` ships
    ``APP_ENV=production`` as a legacy config-drift artifact. Setting
    ``ENABLE_DEV_EMAIL_PREVIEW=true`` on that pod unlocks the route
    without flipping APP_ENV globally (which would have broader
    knock-on effects on comms guardrails, mocking, etc.)."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENABLE_DEV_EMAIL_PREVIEW", "true")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.dev_email_preview import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)

    r = client.get("/api/dev/email-preview/referral-reward")

    assert r.status_code == 200
    assert "BOOM!" in r.text


def test_enable_dev_email_preview_accepts_truthy_variants(monkeypatch):
    """Match the codebase's other flag-detection conventions: accept
    ``1``, ``true``, and ``yes`` (case-insensitive)."""
    for variant in ("1", "true", "TRUE", "yes", "YES"):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("ENABLE_DEV_EMAIL_PREVIEW", variant)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.dev_email_preview import router
        app = FastAPI()
        app.include_router(router, prefix="/api")
        client = TestClient(app)
        r = client.get("/api/dev/email-preview/referral-reward")
        assert r.status_code == 200, (
            f"variant {variant!r} did NOT unlock the route "
            f"(status={r.status_code})"
        )


def test_enable_dev_email_preview_does_not_leak_when_unset(monkeypatch):
    """Sanity check — when the override is unset (or falsy), prod
    APP_ENV still locks the route."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ENABLE_DEV_EMAIL_PREVIEW", raising=False)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.dev_email_preview import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)

    r = client.get("/api/dev/email-preview/referral-reward")

    assert r.status_code == 404
