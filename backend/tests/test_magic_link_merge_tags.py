"""Feb 2026 · Portal magic-link merge tags — resolver coverage.

Covers the two new tags introduced in
``services/marketing/merge_tags.py``:

* ``CUSTOMER_PORTAL_LOGIN_LINK`` — auto-login → ``/portal/home``
  (scope ``portal_home``, 14-day TTL).
* ``SERVICE_RECORD_LINK`` — auto-login → ``/portal/service-reports/{sr_id}``
  (scope ``job_view``, 14-day TTL) with cascade fallback to
  ``CUSTOMER_PORTAL_LOGIN_LINK`` when no job is in scope.

Pure unit tests — no DB. Interstitial redemption + IP rate limit
coverage lives in ``test_portal_auto_login_route.py``.
"""
from __future__ import annotations

import os
from urllib.parse import parse_qs, urlparse

import jwt
import pytest

from config import JWT_ALGO, JWT_SECRET
from services.marketing.merge_tags import (
    MERGE_TAGS, catalog_grouped, render_context, render_template,
)


# The env sets APP_PUBLIC_URL for preview; tests assume it exists.
@pytest.fixture(autouse=True)
def _require_app_url(monkeypatch):
    if not os.environ.get("APP_PUBLIC_URL"):
        monkeypatch.setenv("APP_PUBLIC_URL", "https://app.plofv.com")
    yield


def _ctx(job_id: str | None = None,
         customer_portal_login_link: str | None = None,
         service_record_link: str | None = None) -> dict:
    ctx = render_context(
        customer={"id": "cust-42", "name": "Sam Preview"},
        tenant={"id": "tenant-99", "name": "Pool & Landscaping of Vistancia"},
        job=({"id": job_id, "title": "Weekly Pool"} if job_id else {}),
    )
    if customer_portal_login_link is not None:
        ctx["customer_portal_login_link"] = customer_portal_login_link
    if service_record_link is not None:
        ctx["service_record_link"] = service_record_link
    return ctx


def _extract_jwt(url: str) -> str:
    qs = parse_qs(urlparse(url).query)
    tokens = qs.get("t") or []
    assert tokens, f"no ?t= param on URL: {url!r}"
    return tokens[0]


# ═════════════════════════════════════════════════════════════════════
# Catalog registration
# ═════════════════════════════════════════════════════════════════════
def test_new_tags_registered_in_catalog():
    tokens = {t["token"] for t in MERGE_TAGS}
    assert "CUSTOMER_PORTAL_LOGIN_LINK" in tokens
    assert "SERVICE_RECORD_LINK" in tokens


def test_new_tags_grouped_under_portal_category():
    grouped = catalog_grouped()
    portal_tokens = {t["token"] for t in grouped.get("Portal", [])}
    assert "CUSTOMER_PORTAL_LOGIN_LINK" in portal_tokens
    assert "SERVICE_RECORD_LINK" in portal_tokens
    # Legacy plain-login tag stays put (additive).
    assert "CUSTOMER_PORTAL_LINK" in portal_tokens


def test_lowercase_alias_registered_in_comm_tokens_catalog():
    from services.comm_tokens import AVAILABLE_TOKENS
    assert "customer_portal_login_link" in AVAILABLE_TOKENS
    assert "service_record_link" in AVAILABLE_TOKENS


# ═════════════════════════════════════════════════════════════════════
# CUSTOMER_PORTAL_LOGIN_LINK
# ═════════════════════════════════════════════════════════════════════
def test_customer_portal_login_link_renders_auto_login_url():
    ctx = _ctx()
    out, missing = render_template("{{CUSTOMER_PORTAL_LOGIN_LINK}}", ctx)
    assert missing == []
    assert "/api/portal/auto-login?t=" in out


def test_customer_portal_login_link_mints_portal_home_scope():
    ctx = _ctx()
    out, _ = render_template("{{CUSTOMER_PORTAL_LOGIN_LINK}}", ctx)
    token = _extract_jwt(out)
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    assert payload["sub"] == "portal_home"
    assert payload["customer_id"] == "cust-42"
    assert payload["tenant_id"] == "tenant-99"


def test_customer_portal_login_link_ttl_is_14_days():
    ctx = _ctx()
    out, _ = render_template("{{CUSTOMER_PORTAL_LOGIN_LINK}}", ctx)
    token = _extract_jwt(out)
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    delta_seconds = int(payload["exp"] - payload["iat"])
    # 14 days = 1,209,600 s. Allow ±5-minute drift for env timing.
    assert 1_209_600 - 300 <= delta_seconds <= 1_209_600 + 300


def test_customer_portal_login_link_empty_when_customer_id_missing():
    ctx = render_context(customer={"name": "Sam"}, tenant={"id": "t-1"})
    out, _ = render_template("{{CUSTOMER_PORTAL_LOGIN_LINK}}", ctx)
    assert out == ""


def test_customer_portal_login_link_send_path_override_wins():
    override = "https://custom.example/portal/auto-login?t=preminted"
    ctx = _ctx(customer_portal_login_link=override)
    out, _ = render_template("{{CUSTOMER_PORTAL_LOGIN_LINK}}", ctx)
    assert out == override


def test_customer_portal_login_link_reused_across_occurrences():
    """Second reference in the same body reuses the cached URL — one
    JWT per render, not one per occurrence."""
    ctx = _ctx()
    body = "Hi — link 1: {{CUSTOMER_PORTAL_LOGIN_LINK}} and link 2: {{CUSTOMER_PORTAL_LOGIN_LINK}}"
    out, _ = render_template(body, ctx)
    tokens = [_extract_jwt(u) for u in out.split() if "auto-login" in u]
    assert len(tokens) == 2
    assert tokens[0] == tokens[1]


# ═════════════════════════════════════════════════════════════════════
# SERVICE_RECORD_LINK
# ═════════════════════════════════════════════════════════════════════
def test_service_record_link_renders_job_view_url_when_job_in_scope():
    ctx = _ctx(job_id="job-77")
    out, _ = render_template("{{SERVICE_RECORD_LINK}}", ctx)
    assert "/api/portal/auto-login?t=" in out
    token = _extract_jwt(out)
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    assert payload["sub"] == "job_view"
    assert payload["customer_id"] == "cust-42"
    assert payload["job_id"] == "job-77"
    assert payload["tenant_id"] == "tenant-99"


def test_service_record_link_ttl_is_14_days():
    ctx = _ctx(job_id="job-77")
    out, _ = render_template("{{SERVICE_RECORD_LINK}}", ctx)
    payload = jwt.decode(_extract_jwt(out), JWT_SECRET,
                          algorithms=[JWT_ALGO])
    delta_seconds = int(payload["exp"] - payload["iat"])
    assert 1_209_600 - 300 <= delta_seconds <= 1_209_600 + 300


def test_service_record_link_cascades_to_portal_home_when_no_job():
    """No ``job.id`` in scope → cascade to CUSTOMER_PORTAL_LOGIN_LINK
    (matches INVOICE_PAY_MAGIC_URL → INVOICE_PAY_URL precedent)."""
    ctx = _ctx()  # no job
    out, _ = render_template("{{SERVICE_RECORD_LINK}}", ctx)
    assert "/api/portal/auto-login?t=" in out
    # Fallback URL must be a ``portal_home`` scope, NOT ``job_view``.
    payload = jwt.decode(_extract_jwt(out), JWT_SECRET,
                          algorithms=[JWT_ALGO])
    assert payload["sub"] == "portal_home"
    assert "job_id" not in payload


def test_service_record_link_send_path_override_wins():
    override = "https://custom.example/portal/auto-login?t=preminted-sr"
    ctx = _ctx(job_id="job-77", service_record_link=override)
    out, _ = render_template("{{SERVICE_RECORD_LINK}}", ctx)
    assert out == override


def test_service_record_link_empty_when_customer_and_tenant_missing():
    """Full-empty cascade: no job, no customer.id, no tenant.id →
    empty string (never a literal ``{{SERVICE_RECORD_LINK}}``)."""
    out, _ = render_template("{{SERVICE_RECORD_LINK}}", {})
    assert out == ""


# ═════════════════════════════════════════════════════════════════════
# Cross-scope safety — a portal_home token minted here MUST NOT
# verify as any other scope. Ships the primary security guarantee
# for the new tag: leaking a portal_home URL can never be replayed
# as an invoice-pay or estimate-view link.
# ═════════════════════════════════════════════════════════════════════
def test_portal_home_token_rejected_by_invoice_pay_verifier():
    from services.portal_magic_links import verify_invoice_pay_token
    from fastapi import HTTPException
    ctx = _ctx()
    out, _ = render_template("{{CUSTOMER_PORTAL_LOGIN_LINK}}", ctx)
    token = _extract_jwt(out)
    with pytest.raises(HTTPException) as excinfo:
        verify_invoice_pay_token(token)
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "token_wrong_scope"


def test_job_view_token_rejected_by_portal_home_verifier():
    from services.portal_magic_links import verify_portal_home_token
    from fastapi import HTTPException
    ctx = _ctx(job_id="job-77")
    out, _ = render_template("{{SERVICE_RECORD_LINK}}", ctx)
    token = _extract_jwt(out)
    with pytest.raises(HTTPException) as excinfo:
        verify_portal_home_token(token)
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "token_wrong_scope"


# ═════════════════════════════════════════════════════════════════════
# End-to-end: a URL minted via the tag resolver verifies cleanly
# against its own scope verifier.
# ═════════════════════════════════════════════════════════════════════
def test_customer_portal_login_link_verifies_end_to_end():
    from services.portal_magic_links import verify_portal_home_token
    ctx = _ctx()
    out, _ = render_template("{{CUSTOMER_PORTAL_LOGIN_LINK}}", ctx)
    payload = verify_portal_home_token(_extract_jwt(out))
    assert payload["customer_id"] == "cust-42"
    assert payload["tenant_id"] == "tenant-99"


def test_service_record_link_verifies_end_to_end():
    from services.portal_magic_links import verify_job_view_token
    ctx = _ctx(job_id="job-77")
    out, _ = render_template("{{SERVICE_RECORD_LINK}}", ctx)
    payload = verify_job_view_token(_extract_jwt(out))
    assert payload["customer_id"] == "cust-42"
    assert payload["job_id"] == "job-77"
    assert payload["tenant_id"] == "tenant-99"


# ═════════════════════════════════════════════════════════════════════
# Composability — the tags render correctly inside a real email body
# alongside legacy tags (regression against catalog wiring).
# ═════════════════════════════════════════════════════════════════════
def test_new_tags_compose_with_existing_tags_in_full_body():
    ctx = _ctx(job_id="job-77")
    body = (
        "Hi {{CUSTOMER_FIRST_NAME}},\n\n"
        "View your visit: {{SERVICE_RECORD_LINK}}\n"
        "Log in to your portal: {{CUSTOMER_PORTAL_LOGIN_LINK}}\n\n"
        "Thanks — {{COMPANY_NAME}}"
    )
    out, missing = render_template(body, ctx)
    assert missing == []
    assert "Hi Sam," in out
    assert out.count("/api/portal/auto-login?t=") == 2
    assert "Pool & Landscaping of Vistancia" in out


# ═════════════════════════════════════════════════════════════════════
# APP_PUBLIC_URL guard — resolver returns "" when the env is unset
# rather than emitting a relative or broken URL.
# ═════════════════════════════════════════════════════════════════════
def test_customer_portal_login_link_empty_when_app_public_url_unset(monkeypatch):
    monkeypatch.delenv("APP_PUBLIC_URL", raising=False)
    ctx = _ctx()
    out, _ = render_template("{{CUSTOMER_PORTAL_LOGIN_LINK}}", ctx)
    assert out == ""


def test_service_record_link_falls_back_to_home_which_is_also_empty_when_env_unset(monkeypatch):
    monkeypatch.delenv("APP_PUBLIC_URL", raising=False)
    ctx = _ctx(job_id="job-77")
    out, _ = render_template("{{SERVICE_RECORD_LINK}}", ctx)
    assert out == ""


# ═════════════════════════════════════════════════════════════════════
# Feb 2026 · Composer preview fidelity — the marketing composer's
# ``POST /api/marketing/templates/{tid}/preview`` builds a demo_ctx
# that previously dropped ``customer.id`` (whitelist rebuild), which
# made both tags render empty in the composer preview pane. The fix
# forwards ``customer.id`` + flags the render as a preview so tokens
# get a ``preview: True`` claim and can't be redeemed accidentally.
# ═════════════════════════════════════════════════════════════════════
def test_preview_endpoint_ctx_shape_renders_both_tags_non_empty():
    """Regression against the composer preview forwarding fix in
    ``routers/marketing_templates.py::preview_template``. Mimics the
    demo_ctx shape the endpoint now emits and asserts both tags
    render to non-empty auto-login URLs."""
    from services.marketing.merge_tags import (
        render_context, render_template,
    )
    demo_ctx = render_context(
        customer={
            "id": "cust-sample-preview",
            "name": "Sam Preview",
            "first_name": "Sam",
        },
        tenant={"id": "tenant-sample-preview", "name": "PLOFV"},
        job={"id": "job-sample-preview", "title": "Weekly Pool"},
        _is_preview=True,
    )
    body = ("Login: {{CUSTOMER_PORTAL_LOGIN_LINK}}\n"
             "Report: {{SERVICE_RECORD_LINK}}")
    out, missing = render_template(body, demo_ctx)
    assert missing == []
    assert out.count("/api/portal/auto-login?t=") == 2
    # Both URLs are distinct (different scopes → different JWTs).
    urls = [line.split(": ", 1)[1] for line in out.splitlines()]
    assert urls[0] != urls[1]


def test_preview_flagged_portal_home_token_cannot_be_redeemed():
    """A preview-flagged ``portal_home`` token must be rejected at
    verify time so accidentally-copied preview links never grant a
    real customer session."""
    from fastapi import HTTPException
    from services.portal_magic_links import (
        mint_portal_home_token, verify_portal_home_token,
    )
    tok = mint_portal_home_token("cust-42", "tenant-99", preview=True)
    with pytest.raises(HTTPException) as excinfo:
        verify_portal_home_token(tok)
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "preview_token_cannot_be_redeemed"


def test_preview_flagged_job_view_token_cannot_be_redeemed():
    from fastapi import HTTPException
    from services.portal_magic_links import (
        mint_job_view_token, verify_job_view_token,
    )
    tok = mint_job_view_token("cust-42", "job-77", "tenant-99", preview=True)
    with pytest.raises(HTTPException) as excinfo:
        verify_job_view_token(tok)
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "preview_token_cannot_be_redeemed"


def test_non_preview_tokens_still_redeem_cleanly():
    """Send-path (non-preview) tokens must NOT be rejected — the
    preview flag is opt-in only. Belt-and-suspenders regression
    against a bug where the verifier reads ``payload.get("preview")``
    as truthy on a claim that isn't there."""
    from services.portal_magic_links import (
        mint_portal_home_token, verify_portal_home_token,
        mint_job_view_token, verify_job_view_token,
    )
    tok_home = mint_portal_home_token("cust-42", "tenant-99")  # preview=False
    payload_home = verify_portal_home_token(tok_home)
    assert payload_home["sub"] == "portal_home"
    assert "preview" not in payload_home
    tok_job = mint_job_view_token("cust-42", "job-77", "tenant-99")
    payload_job = verify_job_view_token(tok_job)
    assert payload_job["sub"] == "job_view"
    assert "preview" not in payload_job


def test_preview_resolver_flag_produces_preview_claim_in_jwt():
    """The resolver forwards ``_is_preview=True`` from ctx to the
    mint helper — this test decodes the JWT and asserts the
    ``preview: True`` claim is present."""
    ctx = _ctx()
    ctx["_is_preview"] = True
    out, _ = render_template("{{CUSTOMER_PORTAL_LOGIN_LINK}}", ctx)
    token = _extract_jwt(out)
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    assert payload.get("preview") is True
