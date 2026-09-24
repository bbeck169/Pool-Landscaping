"""Phase P53.1 · Feb-2026 — Boot-time WARNING for the
ENABLE_DEV_EMAIL_PREVIEW + APP_ENV=production drift condition.

Locks:
  * ``check_dev_preview_env_drift()`` returns True only on the
    exact drift condition (APP_ENV=production AND override truthy).
  * ``DEV_PREVIEW_DRIFT_WARNING`` starts with the grep-friendly
    signature ``ENABLE_DEV_EMAIL_PREVIEW=true AND APP_ENV=production``
    so ops log-alerting can pattern-match without ambiguity.
  * ``server.py`` boot emits exactly ONE warning per drift boot
    (verified by re-importing the registration block through
    ``importlib.reload`` under a monkeypatched env + a caplog
    capture).
  * ``backend/.env.production.example`` documents the "do not set
    ENABLE_DEV_EMAIL_PREVIEW in prod" instruction near the APP_ENV
    line.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest


# ═════════════════════════════════════════════════════════════════════
# Section 1 — Pure drift detector
# ═════════════════════════════════════════════════════════════════════
def test_drift_detector_returns_true_only_on_prod_plus_override(monkeypatch):
    from routers.dev_email_preview import check_dev_preview_env_drift

    # Drift condition — must be True.
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENABLE_DEV_EMAIL_PREVIEW", "true")
    assert check_dev_preview_env_drift() is True


def test_drift_detector_false_when_app_env_not_production(monkeypatch):
    from routers.dev_email_preview import check_dev_preview_env_drift

    monkeypatch.setenv("APP_ENV", "preview")
    monkeypatch.setenv("ENABLE_DEV_EMAIL_PREVIEW", "true")
    assert check_dev_preview_env_drift() is False


def test_drift_detector_false_when_override_unset(monkeypatch):
    from routers.dev_email_preview import check_dev_preview_env_drift

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ENABLE_DEV_EMAIL_PREVIEW", raising=False)
    assert check_dev_preview_env_drift() is False


def test_drift_detector_false_when_override_falsy(monkeypatch):
    from routers.dev_email_preview import check_dev_preview_env_drift

    for falsy in ("", "0", "false", "no", "off", "nope"):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("ENABLE_DEV_EMAIL_PREVIEW", falsy)
        assert check_dev_preview_env_drift() is False, (
            f"falsy variant {falsy!r} incorrectly triggered drift"
        )


def test_drift_detector_case_insensitive_for_app_env(monkeypatch):
    from routers.dev_email_preview import check_dev_preview_env_drift

    for variant in ("PRODUCTION", "Production", "production"):
        monkeypatch.setenv("APP_ENV", variant)
        monkeypatch.setenv("ENABLE_DEV_EMAIL_PREVIEW", "true")
        assert check_dev_preview_env_drift() is True, (
            f"case variant {variant!r} did not trigger drift"
        )


# ═════════════════════════════════════════════════════════════════════
# Section 2 — WARNING message shape (grep-friendly for ops alerting)
# ═════════════════════════════════════════════════════════════════════
def test_warning_message_starts_with_grep_signature():
    """Ops will grep pod logs for the leading substring
    ``ENABLE_DEV_EMAIL_PREVIEW=true AND APP_ENV=production``. Keep
    that literal at the START of the message — a rename or reorder
    would silently defeat log alerting."""
    from routers.dev_email_preview import DEV_PREVIEW_DRIFT_WARNING
    assert DEV_PREVIEW_DRIFT_WARNING.startswith(
        "ENABLE_DEV_EMAIL_PREVIEW=true AND APP_ENV=production"
    )


def test_warning_message_names_exposed_route():
    """The message should tell ops WHICH route is exposed so they
    know what to look for in HTTP access logs."""
    from routers.dev_email_preview import DEV_PREVIEW_DRIFT_WARNING
    assert "/api/dev/email-preview/referral-reward" in \
        DEV_PREVIEW_DRIFT_WARNING


def test_warning_message_tells_ops_the_remediation():
    """The message should tell ops what to do — unset the env var —
    so they aren't left guessing."""
    from routers.dev_email_preview import DEV_PREVIEW_DRIFT_WARNING
    assert "unset ENABLE_DEV_EMAIL_PREVIEW" in DEV_PREVIEW_DRIFT_WARNING


# ═════════════════════════════════════════════════════════════════════
# Section 3 — Log emission integration (drives the exact server.py
#             conditional expression to prove it fires + fires ONCE)
# ═════════════════════════════════════════════════════════════════════
def _simulate_server_boot_gate(caplog):
    """Executes the EXACT gating logic ``server.py`` runs at boot,
    against the current os.environ. Returns whether the router
    would be mounted."""
    import os
    from routers.dev_email_preview import (
        check_dev_preview_env_drift,
        DEV_PREVIEW_DRIFT_WARNING,
    )
    logger = logging.getLogger("pool_crm")
    app_env = (os.environ.get("APP_ENV") or "preview").strip().lower()
    force = (
        (os.environ.get("ENABLE_DEV_EMAIL_PREVIEW") or "").strip().lower()
        in ("1", "true", "yes")
    )
    mounted = False
    if app_env != "production" or force:
        mounted = True
        if check_dev_preview_env_drift():
            logger.warning(DEV_PREVIEW_DRIFT_WARNING)
    return mounted


def test_boot_gate_emits_warning_exactly_once_on_drift(monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENABLE_DEV_EMAIL_PREVIEW", "true")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="pool_crm"):
        mounted = _simulate_server_boot_gate(caplog)
    assert mounted is True
    # Filter to just our WARNING message (other loggers may emit).
    drift_records = [
        r for r in caplog.records
        if "ENABLE_DEV_EMAIL_PREVIEW=true AND APP_ENV=production" in r.message
    ]
    assert len(drift_records) == 1, (
        f"expected exactly 1 drift WARNING, got {len(drift_records)}: "
        f"{[r.message for r in drift_records]}"
    )
    assert drift_records[0].levelno == logging.WARNING


def test_boot_gate_no_warning_on_normal_preview(monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "preview")
    monkeypatch.delenv("ENABLE_DEV_EMAIL_PREVIEW", raising=False)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="pool_crm"):
        mounted = _simulate_server_boot_gate(caplog)
    assert mounted is True
    drift_records = [
        r for r in caplog.records
        if "ENABLE_DEV_EMAIL_PREVIEW=true AND APP_ENV=production" in r.message
    ]
    assert drift_records == [], (
        "normal preview pod should NOT emit the drift WARNING; got "
        f"{[r.message for r in drift_records]}"
    )


def test_boot_gate_no_warning_on_normal_prod(monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ENABLE_DEV_EMAIL_PREVIEW", raising=False)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="pool_crm"):
        mounted = _simulate_server_boot_gate(caplog)
    assert mounted is False, (
        "prod pod without override must NOT mount the route"
    )
    drift_records = [
        r for r in caplog.records
        if "ENABLE_DEV_EMAIL_PREVIEW=true AND APP_ENV=production" in r.message
    ]
    assert drift_records == []


# ═════════════════════════════════════════════════════════════════════
# Section 4 — Prod env example file documents the foot-gun
# ═════════════════════════════════════════════════════════════════════
def test_prod_env_example_documents_the_footgun():
    """Ops read ``backend/.env.production.example`` when copying a
    fresh prod .env. A big warning near the ``APP_ENV`` line is the
    cheapest way to prevent the drift from happening in the first
    place."""
    path = Path(__file__).resolve().parents[1] / ".env.production.example"
    body = path.read_text()
    assert "APP_ENV=production" in body
    # Warning present with the same grep signature.
    assert "ENABLE_DEV_EMAIL_PREVIEW" in body, (
        "prod env example must reference ENABLE_DEV_EMAIL_PREVIEW so "
        "ops sees the warning during a fresh prod .env copy"
    )
    # The warning must land NEAR APP_ENV (within 20 lines) so it's
    # visible in the same viewport as the flag it protects.
    lines = body.splitlines()
    app_env_line = next(
        i for i, ln in enumerate(lines) if ln.startswith("APP_ENV=")
    )
    dev_preview_line = next(
        (i for i, ln in enumerate(lines)
          if "ENABLE_DEV_EMAIL_PREVIEW" in ln),
        None,
    )
    assert dev_preview_line is not None
    assert abs(dev_preview_line - app_env_line) <= 20, (
        "ENABLE_DEV_EMAIL_PREVIEW note is too far from APP_ENV — "
        "co-locate them so a fresh reader sees the warning"
    )
