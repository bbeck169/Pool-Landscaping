"""Admin Stripe webhook diagnostic — P0c Stage 2 S2-2 regression.

Pins:
  · super_admin role gate (admin / tech / customer → 403).
  · Response shape stable (fields the UI panel consumes).
  · ``config.mode_match`` ∈ {live, test, mismatch, unknown}.
  · ``suggested_next_action`` always non-empty.
  · Secret values never appear in full — only ``*_prefix``
    (first-8 characters) + ``*_length``.
  · Ledger + dead-letter rows render redacted (no raw payloads).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def super_admin_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture
def regular_admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


# ────────────────────────────────────────────────────────────────────
# 1 · super_admin only (admin → 403).
# ────────────────────────────────────────────────────────────────────
def test_regular_admin_cannot_access_diagnostic(regular_admin_headers):
    r = requests.get(f"{API}/admin/stripe/webhook-diagnostic",
                       headers=regular_admin_headers, timeout=10)
    assert r.status_code == 403, r.text[:200]


def test_unauthenticated_cannot_access_diagnostic():
    r = requests.get(f"{API}/admin/stripe/webhook-diagnostic", timeout=10)
    assert r.status_code in (401, 403)


# ────────────────────────────────────────────────────────────────────
# 2 · Response shape — all UI-consumed fields present.
# ────────────────────────────────────────────────────────────────────
def test_super_admin_gets_full_diagnostic_payload(super_admin_headers):
    r = requests.get(f"{API}/admin/stripe/webhook-diagnostic",
                       headers=super_admin_headers, timeout=15)
    assert r.status_code == 200, r.text[:400]
    body = r.json()

    # Top-level shape.
    for k in ("generated_at", "registered_webhook_paths", "config",
              "recent_events_total", "recent_events",
              "recent_dead_letters_total", "recent_dead_letters",
              "suggested_next_action"):
        assert k in body, f"missing top-level key: {k}"

    # Registered paths both present.
    paths = body["registered_webhook_paths"]
    assert "/api/payments/stripe/webhook" in paths
    assert "/api/stripe/webhook" in paths

    # Config block shape.
    cfg = body["config"]
    for k in ("mode", "app_env", "api_key_configured", "api_key_prefix",
              "api_key_length", "webhook_secret_configured",
              "webhook_secret_prefix", "webhook_secret_length",
              "mode_match", "issues"):
        assert k in cfg, f"missing config key: {k}"
    assert cfg["mode"] in ("live", "test")
    assert cfg["mode_match"] in ("live", "test", "mismatch", "unknown")
    assert isinstance(cfg["issues"], list)

    # Suggested next action is always non-empty.
    assert body["suggested_next_action"]
    assert len(body["suggested_next_action"]) > 20


# ────────────────────────────────────────────────────────────────────
# 3 · Secret redaction — no secret value leaks on the wire.
# ────────────────────────────────────────────────────────────────────
def test_diagnostic_never_leaks_full_secrets(super_admin_headers):
    r = requests.get(f"{API}/admin/stripe/webhook-diagnostic",
                       headers=super_admin_headers, timeout=15)
    cfg = r.json()["config"]

    # Prefix is at most "<8chars>…" or None.
    for prefix_key in ("api_key_prefix", "webhook_secret_prefix"):
        v = cfg[prefix_key]
        if v is None:
            continue
        assert len(v) <= 12, (
            f"{prefix_key}={v!r} is longer than the 8-char + ellipsis "
            "allowance — the handler is leaking more secret than it "
            "should."
        )

    # Confirm the full secret value from .env is NOT echoed on the
    # response wire. We'd expect only the first 8 chars at most.
    real_wh = (_ENV.get("STRIPE_WEBHOOK_SECRET_LIVE")
               or _ENV.get("STRIPE_WEBHOOK_SECRET_TEST")
               or _ENV.get("STRIPE_WEBHOOK_SECRET") or "")
    if real_wh and len(real_wh) > 12:
        # The full raw secret body MUST NOT appear in the response.
        raw_text = r.text
        assert real_wh not in raw_text, (
            "full webhook signing secret leaked in diagnostic response"
        )


# ────────────────────────────────────────────────────────────────────
# 4 · Recent events + dead letters shape — redacted projections.
# ────────────────────────────────────────────────────────────────────
def test_recent_events_shape_redacted(super_admin_headers):
    r = requests.get(f"{API}/admin/stripe/webhook-diagnostic",
                       headers=super_admin_headers, timeout=15)
    body = r.json()
    assert isinstance(body["recent_events"], list)
    assert isinstance(body["recent_dead_letters"], list)
    # Every ledger row carries only the projected fields — no raw
    # payload, no PII.
    allowed_event_keys = {
        "event_id", "event_type", "received_at", "status",
        "retry_count", "first_handled_at", "last_error",
        "tenant_id_hint",
    }
    for row in body["recent_events"]:
        extra = set(row.keys()) - allowed_event_keys
        assert not extra, (
            f"recent_events row carries unredacted fields: {extra}"
        )
    allowed_dl_keys = {
        "event_id", "event_type", "first_failed_at", "last_retry_at",
        "error_class", "error_message", "retry_count_after_first",
        "tenant_id_hint",
    }
    for row in body["recent_dead_letters"]:
        extra = set(row.keys()) - allowed_dl_keys
        assert not extra, (
            f"recent_dead_letters row carries unredacted fields: {extra}"
        )


# ────────────────────────────────────────────────────────────────────
# 5 · Preview pod shape — live config should be healthy
#     (sanity, not strict — operator could temporarily set a bad env).
# ────────────────────────────────────────────────────────────────────
def test_preview_pod_diagnostic_healthy_or_actionable(super_admin_headers):
    r = requests.get(f"{API}/admin/stripe/webhook-diagnostic",
                       headers=super_admin_headers, timeout=15)
    body = r.json()
    # If misconfigured, the suggested_next_action must mention
    # STRIPE_MODE or STRIPE_WEBHOOK_SECRET so the operator knows
    # exactly what to touch.
    if body["config"]["mode_match"] not in ("live", "test"):
        hint = body["suggested_next_action"].upper()
        assert "STRIPE_MODE" in hint or "STRIPE_WEBHOOK_SECRET" in hint, (
            f"misconfigured but suggested_next_action lacks "
            f"actionable env-var mention: {body['suggested_next_action']}"
        )
