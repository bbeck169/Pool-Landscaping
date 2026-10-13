"""WINGMAN-ESCALATION-EMAIL-FIX · Feb-2026 — pytest for the shared
``absolute_portal_url`` helper in ``services/email_urls.py``.

Four cases:
  (i)   Relative path + configured ``APP_PUBLIC_URL`` → absolute
        URL on that host.
  (ii)  Absolute URL (http/https) passed through unchanged.
  (iii) ``None`` / empty string → returns ``None`` so the caller
        can drop the link element entirely.
  (iv)  Relative path + MISSING ``APP_PUBLIC_URL`` → ERROR log is
        emitted naming the template + a VISIBLE placeholder host
        is returned (NOT ``file:///``).

The config env var is manipulated at runtime via module patching
so we can exercise the "missing" branch without touching the real
``.env`` file.
"""
from __future__ import annotations

import logging

import pytest
from dotenv import load_dotenv


load_dotenv("/app/backend/.env")


# ─── (i) relative + configured base → absolute join ───────────────
def test_absolute_portal_url_relative_path_gets_configured_base(monkeypatch):
    import services.email_urls as mod
    import config as cfg
    monkeypatch.setattr(cfg, "APP_PUBLIC_URL", "https://app.plofv.com/")
    monkeypatch.setattr(mod, "APP_PUBLIC_URL", "https://app.plofv.com/")

    out = mod.absolute_portal_url(
        "/communication/abc-123",
        template_name="admin_notification_fanout",
    )
    assert out == "https://app.plofv.com/communication/abc-123"


# ─── (ii) already absolute → passthrough ──────────────────────────
def test_absolute_portal_url_absolute_input_passthrough():
    import services.email_urls as mod
    for url in (
        "https://example.com/x",
        "http://example.com/x",
        "HTTPS://EXAMPLE.COM/X",  # case-insensitive scheme detection
    ):
        out = mod.absolute_portal_url(url, template_name="whatever")
        assert out == url


# ─── (iii) None / empty → None ────────────────────────────────────
def test_absolute_portal_url_none_or_empty_returns_none():
    import services.email_urls as mod
    assert mod.absolute_portal_url(None, template_name="t") is None
    assert mod.absolute_portal_url("", template_name="t") is None
    assert mod.absolute_portal_url("   ", template_name="t") is None


# ─── (iv) relative + missing env → ERROR log + visible placeholder ─
def test_absolute_portal_url_missing_env_logs_error_and_emits_placeholder(
    monkeypatch, caplog,
):
    import services.email_urls as mod
    import config as cfg
    monkeypatch.setattr(cfg, "APP_PUBLIC_URL", "")
    monkeypatch.setattr(mod, "APP_PUBLIC_URL", "")

    with caplog.at_level(logging.ERROR):
        out = mod.absolute_portal_url(
            "/communication/abc-123",
            template_name="admin_notification_fanout",
        )

    # Visible placeholder — NOT ``file:///``.
    assert out is not None
    assert out.startswith("https://CONFIGURATION_MISSING_APP_PUBLIC_URL")
    assert out.endswith("/communication/abc-123")
    assert "file:///" not in out  # regression guard

    # ERROR log fired AND names the template so ops can grep.
    err_records = [
        r for r in caplog.records
        if r.levelno == logging.ERROR
        and "[email-urls]" in r.getMessage()
    ]
    assert err_records, (
        "expected an ERROR log tagged [email-urls]; "
        f"got: {[r.getMessage()[:80] for r in caplog.records]}"
    )
    assert "admin_notification_fanout" in err_records[0].getMessage()
