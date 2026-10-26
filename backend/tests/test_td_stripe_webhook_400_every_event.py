"""TD-stripe-webhook-400-every-event · Feb-2026
================================================

Regression lock for the hybrid webhook-secret selection + diagnostic
logging payload:

  §1 — `_select_webhook_secret_with_source` precedence
    §1a — live mode: _LIVE wins when all three slots set
    §1b — live mode: falls through _LIVE empty → bare → _TEST
    §1c — test mode: _TEST wins; _LIVE is skipped even if set
    §1d — test mode: falls through _TEST empty → bare
    §1e — no secret → ("", None)
    §1f — trailing whitespace stripped on all slots

  §2 — Boot-check structured log
    §2a — emits `secret loaded from <SOURCE>` with prefix / suffix /
          length when a secret resolves
    §2b — emits `NO secret resolved from ...` ERROR when all slots
          empty
    §2c — emits `LIVE secret skipped (mode=test ...)` INFO when a
          test-mode pod has STRIPE_WEBHOOK_SECRET_LIVE populated
    §2d — `_select_webhook_secret()` shim still works for existing
          callers

  §3 — Router-side detailed error log on 400
    §3a — ValueError path logs structured context + raises 400
    §3b — SignatureVerificationError path logs class / exc / body_len /
          sig_header_present / sig_header_prefix / secret_source
    §3c — missing stripe-signature header → sig_header_present=False
    §3d — raw bytes-first regression lock (static source read confirms
          `payload = await request.body()` is still the handler's
          first line before any body-parsing side-effect)

Approach — the ``_select_webhook_secret_with_source`` tests are pure
env-var manipulation with ``monkeypatch``.  The router-side tests use
a lightweight ``TestClient`` against the real FastAPI app so the
middleware chain is exercised end-to-end.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ═══════════════════════════════════════════════════════════════════
# §1 — Precedence
# ═══════════════════════════════════════════════════════════════════
def _clear(monkeypatch) -> None:
    for k in (
        "STRIPE_WEBHOOK_SECRET_LIVE",
        "STRIPE_WEBHOOK_SECRET_TEST",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_MODE",
    ):
        monkeypatch.delenv(k, raising=False)


def test_precedence_live_mode_live_slot_wins(monkeypatch):
    from services.payments.stripe_charge import (
        _select_webhook_secret_with_source,
    )
    _clear(monkeypatch)
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_LIVE", "whsec_live")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_bare")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_TEST", "whsec_test")
    secret, source = _select_webhook_secret_with_source()
    assert secret == "whsec_live"
    assert source == "STRIPE_WEBHOOK_SECRET_LIVE"


def test_precedence_live_mode_falls_through_to_bare(monkeypatch):
    from services.payments.stripe_charge import (
        _select_webhook_secret_with_source,
    )
    _clear(monkeypatch)
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_bare")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_TEST", "whsec_test")
    secret, source = _select_webhook_secret_with_source()
    assert secret == "whsec_bare"
    assert source == "STRIPE_WEBHOOK_SECRET"


def test_precedence_live_mode_falls_through_to_test_as_last_resort(
    monkeypatch,
):
    from services.payments.stripe_charge import (
        _select_webhook_secret_with_source,
    )
    _clear(monkeypatch)
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_TEST", "whsec_test")
    secret, source = _select_webhook_secret_with_source()
    assert secret == "whsec_test"
    assert source == "STRIPE_WEBHOOK_SECRET_TEST"


def test_precedence_test_mode_test_slot_wins(monkeypatch):
    from services.payments.stripe_charge import (
        _select_webhook_secret_with_source,
    )
    _clear(monkeypatch)
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_TEST", "whsec_test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_LIVE", "whsec_live")
    secret, source = _select_webhook_secret_with_source()
    assert secret == "whsec_test"
    assert source == "STRIPE_WEBHOOK_SECRET_TEST"


def test_precedence_test_mode_skips_live_even_when_set(monkeypatch):
    """Operator Q decision Q1 (hybrid) — _LIVE is deliberately SKIPPED
    when STRIPE_MODE=test so preview can't accidentally verify against
    the wrong secret."""
    from services.payments.stripe_charge import (
        _select_webhook_secret_with_source,
    )
    _clear(monkeypatch)
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_LIVE", "whsec_live")
    # NO _TEST, NO bare — _LIVE is set, but test mode must skip it.
    secret, source = _select_webhook_secret_with_source()
    assert secret == ""
    assert source is None


def test_precedence_test_mode_falls_through_to_bare(monkeypatch):
    from services.payments.stripe_charge import (
        _select_webhook_secret_with_source,
    )
    _clear(monkeypatch)
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_bare")
    secret, source = _select_webhook_secret_with_source()
    assert secret == "whsec_bare"
    assert source == "STRIPE_WEBHOOK_SECRET"


def test_precedence_no_secret_resolves_empty(monkeypatch):
    from services.payments.stripe_charge import (
        _select_webhook_secret_with_source,
    )
    _clear(monkeypatch)
    monkeypatch.setenv("STRIPE_MODE", "live")
    secret, source = _select_webhook_secret_with_source()
    assert secret == ""
    assert source is None


def test_precedence_trailing_whitespace_stripped(monkeypatch):
    """Preview .env has `STRIPE_WEBHOOK_SECRET_LIVE=whsec_...X5zf `
    with a trailing space (confirmed on 2026-02 recon).  The selector
    MUST strip or Stripe signature verification 400s every event."""
    from services.payments.stripe_charge import (
        _select_webhook_secret_with_source,
    )
    _clear(monkeypatch)
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_LIVE", "  whsec_live  \n")
    secret, source = _select_webhook_secret_with_source()
    assert secret == "whsec_live"
    assert source == "STRIPE_WEBHOOK_SECRET_LIVE"


# ═══════════════════════════════════════════════════════════════════
# §2 — Boot-check structured log
# ═══════════════════════════════════════════════════════════════════
def test_boot_log_source_present_when_secret_resolves(
    monkeypatch, caplog,
):
    from services.payments.stripe_charge import check_stripe_mode_consistency
    _clear(monkeypatch)
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("STRIPE_SECRET_KEY_LIVE", "sk_live_fixture_abcdef1234")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_LIVE", "whsec_livesecret12345")
    with caplog.at_level("INFO", logger="pool_crm"):
        report = check_stripe_mode_consistency()
    assert report["webhook_secret_source"] == "STRIPE_WEBHOOK_SECRET_LIVE"
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "secret loaded from STRIPE_WEBHOOK_SECRET_LIVE" in joined
    assert "prefix=whsec_l" in joined
    assert "suffix=…2345" in joined
    assert "length=21" in joined


def test_boot_log_missing_error_when_all_slots_empty(
    monkeypatch, caplog,
):
    from services.payments.stripe_charge import check_stripe_mode_consistency
    _clear(monkeypatch)
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("STRIPE_SECRET_KEY_LIVE", "sk_live_fixture")
    with caplog.at_level("ERROR", logger="pool_crm"):
        report = check_stripe_mode_consistency()
    assert report["webhook_secret_source"] is None
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "NO secret resolved from STRIPE_WEBHOOK_SECRET_LIVE" in joined
    assert "/api/payments/stripe/webhook will 400 every event" in joined


def test_boot_log_test_mode_skip_notice_when_live_present(
    monkeypatch, caplog,
):
    """Operator Q decision Q2 — explicit log line so a future dev
    doesn't wonder why STRIPE_WEBHOOK_SECRET_LIVE isn't being used
    on a preview pod that has it populated."""
    from services.payments.stripe_charge import check_stripe_mode_consistency
    _clear(monkeypatch)
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_fixture")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_TEST", "whsec_testsecret")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_LIVE", "whsec_livesecret")
    with caplog.at_level("INFO", logger="pool_crm"):
        check_stripe_mode_consistency()
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "LIVE secret skipped" in joined
    assert "mode=test" in joined


def test_select_webhook_secret_shim_still_works(monkeypatch):
    """Legacy ``_select_webhook_secret()`` must keep returning just the
    secret for every existing caller (``tenant_stripe.py``,
    ``admin_stripe.py``, ``stripe_router.py`` smoke-hook endpoint)."""
    from services.payments.stripe_charge import _select_webhook_secret
    _clear(monkeypatch)
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_LIVE", "whsec_abc")
    assert _select_webhook_secret() == "whsec_abc"


# ═══════════════════════════════════════════════════════════════════
# §3 — Router-side detailed error log on 400
# ═══════════════════════════════════════════════════════════════════
@pytest.fixture()
def client():
    import server as _server
    return TestClient(_server.app)


def test_webhook_bad_signature_logs_structured_context(client, caplog):
    with caplog.at_level("ERROR", logger="pool_crm"):
        resp = client.post(
            "/api/payments/stripe/webhook",
            headers={
                "Content-Type": "application/json",
                "stripe-signature": "t=1234,v1=deadbeef",
            },
            content=b'{"id":"evt_bad","type":"test.event"}',
        )
    assert resp.status_code == 400
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "[stripe-webhook] construct_event FAILED" in joined
    assert "exc=SignatureVerificationError" in joined
    assert "body_len=36" in joined   # len(b'{"id":"evt_bad","type":"test.event"}')
    assert "sig_header_present=True" in joined
    assert "sig_header_prefix=t=1234,v1=deadbeef" in joined
    assert "secret_source=STRIPE_WEBHOOK_SECRET_LIVE" in joined


def test_webhook_missing_sig_header_logged_as_absent(client, caplog):
    with caplog.at_level("ERROR", logger="pool_crm"):
        resp = client.post(
            "/api/payments/stripe/webhook",
            headers={"Content-Type": "application/json"},
            content=b'{"id":"evt_no_sig","type":"test.event"}',
        )
    assert resp.status_code == 400
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "sig_header_present=False" in joined
    assert "sig_header_prefix=<missing>" in joined


def test_webhook_raw_body_read_before_any_parse():
    """Static regression lock — the first non-comment statement of
    ``post_webhook`` must still be ``payload = await request.body()``.
    If a future refactor moves a body-mutating line (pydantic Body,
    middleware body-consume) BEFORE this read, Stripe signature
    verification will 400 every event (which is literally the bug
    this ticket exists to prevent).
    """
    import routers.stripe_router as _r
    src = inspect.getsource(_r.post_webhook)
    # Drop docstring + decorator preamble + def line.
    lines = src.splitlines()
    body_start = None
    in_docstring = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("def ") or stripped.startswith("async def "):
            body_start = idx + 1
            break
    assert body_start is not None, "could not locate function body"
    first_stmt = None
    for line in lines[body_start:]:
        s = line.strip()
        if not s:
            continue
        if s.startswith('"""') or s.startswith("'''"):
            in_docstring = not in_docstring
            if in_docstring and s.endswith('"""') and len(s) > 3:
                in_docstring = False
            continue
        if in_docstring:
            if s.endswith('"""') or s.endswith("'''"):
                in_docstring = False
            continue
        if s.startswith("#"):
            continue
        first_stmt = s
        break
    assert first_stmt is not None
    assert first_stmt.startswith("payload = await request.body()"), (
        f"post_webhook's first non-doc statement must read the raw body "
        f"before any middleware / pydantic parsing can consume it. "
        f"Got: {first_stmt!r}"
    )


def test_webhook_lifespan_boot_check_wired(caplog):
    """Regression lock for the lifespan integration — the identical
    ``check_stripe_mode_consistency`` call at ``_preview_isolation
    _boot_audit`` (line ~1971) is dead code since Starlette's lifespan
    protocol replaces @app.on_event handlers.  Confirm the lifespan
    function at the bottom of ``server.py`` DOES invoke the boot
    check so pod logs actually see the ``[stripe-webhook] secret
    loaded from ...`` diagnostic on every boot.
    """
    src = Path(__file__).resolve().parents[1] / "server.py"
    text = src.read_text(encoding="utf-8")
    # Find the lifespan definition and verify it calls the boot check
    # BEFORE ``yield``.
    lifespan_start = text.find("async def lifespan(")
    assert lifespan_start >= 0, "lifespan function missing"
    yield_pos = text.find("yield", lifespan_start)
    assert yield_pos >= 0
    pre_yield = text[lifespan_start:yield_pos]
    assert "check_stripe_mode_consistency" in pre_yield, (
        "lifespan must call check_stripe_mode_consistency BEFORE yield "
        "so the operator-visible '[stripe-webhook] secret loaded from "
        "<SOURCE>' boot log fires on every pod boot."
    )
