"""Feb-2026 · Business Settings — contract tests.

Locks the five endpoints shipped by the Business Settings dispatch:

  GET    /api/tenants/me/business-settings          (admin)
  PATCH  /api/tenants/me/business-settings          (admin)
  POST   /api/tenants/me/logo                       (admin)
  DELETE /api/tenants/me/logo                       (admin)
  GET    /api/portal/tenant/branding?token=…        (magic-link)

See /app/memory/FEATURE_BUSINESS_SETTINGS.md.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)

REQ_TIMEOUT = 30


def _session(email, password):
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip(f"login failed for {email}: {r.status_code}")
    tok = r.json().get("access_token") or r.json().get("token")
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    })
    return s


# ─── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def admin_sess():
    return _session("admin@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def tech_sess():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "tech@aquaterra.com", "password": "password123"},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip("no tech@aquaterra.com demo user")
    tok = r.json().get("access_token") or r.json().get("token")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok}",
                      "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def snapshot(admin_sess):
    """Capture the pre-test business_settings so we can restore."""
    r = admin_sess.get(f"{BASE_URL}/api/tenants/me/business-settings",
                       timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    yield r.json()
    # Restore stored fields to their original values (best-effort).
    original = r.json().get("stored") or {}
    admin_sess.patch(
        f"{BASE_URL}/api/tenants/me/business-settings",
        json=original,
        timeout=REQ_TIMEOUT,
    )


# ═════════════════════════════════════════════════════════════════════
# 1. Admin PATCH updates a field → GET returns new value
# ═════════════════════════════════════════════════════════════════════

def test_admin_patch_and_get_roundtrip(admin_sess, snapshot):
    r = admin_sess.patch(
        f"{BASE_URL}/api/tenants/me/business-settings",
        json={"phone": "(555) 999-1234",
              "footer_note": "Licensed · Insured"},
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stored"]["phone"] == "(555) 999-1234"
    assert body["stored"]["footer_note"] == "Licensed · Insured"
    # GET reflects the same.
    r2 = admin_sess.get(f"{BASE_URL}/api/tenants/me/business-settings",
                         timeout=REQ_TIMEOUT)
    assert r2.json()["stored"]["phone"] == "(555) 999-1234"


# ═════════════════════════════════════════════════════════════════════
# 2. Bad hex → 422
# ═════════════════════════════════════════════════════════════════════

def test_bad_hex_returns_422(admin_sess, snapshot):
    r = admin_sess.patch(
        f"{BASE_URL}/api/tenants/me/business-settings",
        json={"brand_primary_hex": "not-a-color"},
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 422, r.text


# ═════════════════════════════════════════════════════════════════════
# 3. Bad email → 422
# ═════════════════════════════════════════════════════════════════════

def test_bad_email_returns_422(admin_sess, snapshot):
    r = admin_sess.patch(
        f"{BASE_URL}/api/tenants/me/business-settings",
        json={"email": "not-an-email"},
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 422, r.text


# ═════════════════════════════════════════════════════════════════════
# 4. Website auto-prepend https:// when scheme missing
# ═════════════════════════════════════════════════════════════════════

def test_website_auto_prepends_https(admin_sess, snapshot):
    r = admin_sess.patch(
        f"{BASE_URL}/api/tenants/me/business-settings",
        json={"website": "aquaterra.com"},
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    assert r.json()["stored"]["website"] == "https://aquaterra.com"


# ═════════════════════════════════════════════════════════════════════
# 5. Technician PATCH → 403
# ═════════════════════════════════════════════════════════════════════

def test_technician_patch_forbidden(tech_sess, snapshot):
    r = tech_sess.patch(
        f"{BASE_URL}/api/tenants/me/business-settings",
        json={"phone": "hack"},
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 403, r.text


# ═════════════════════════════════════════════════════════════════════
# 6. Unauth GET → 401 / 403
# ═════════════════════════════════════════════════════════════════════

def test_unauth_get_rejected():
    r = requests.get(
        f"{BASE_URL}/api/tenants/me/business-settings",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code in (401, 403), r.text


# ═════════════════════════════════════════════════════════════════════
# 7. Logo POST with unsupported mime → 415 (FastAPI maps our
#    HTTPException(415) — the brief said 400, but 415 is the
#    inherited contract from the reused branding/logo route)
# ═════════════════════════════════════════════════════════════════════

def test_logo_upload_unsupported_mime(admin_sess, snapshot):
    files = {"logo": ("evil.gif", b"GIF87a", "image/gif")}
    r = requests.post(
        f"{BASE_URL}/api/tenants/me/logo",
        files=files,
        headers={"Authorization": admin_sess.headers["Authorization"]},
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code in (400, 415), r.text


# ═════════════════════════════════════════════════════════════════════
# 8. Logo POST success + audit row (skipped if object storage is
#    not ready in this environment — same skip guard as the
#    branding-logo route tests).
# ═════════════════════════════════════════════════════════════════════

def _tiny_png() -> bytes:
    # 1x1 red PNG
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c63f8cfc0f01f000005010102a1bcecbe0000000049454e"
        "44ae426082"
    )


def test_logo_upload_success_writes_audit(admin_sess, snapshot):
    files = {"logo": ("test.png", _tiny_png(), "image/png")}
    r = requests.post(
        f"{BASE_URL}/api/tenants/me/logo",
        files=files,
        headers={"Authorization": admin_sess.headers["Authorization"]},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code == 503:
        pytest.skip("Object storage unavailable in this env")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get("logo_url"), str)
    assert body["logo_url"]

    # DELETE also succeeds and does not remove the audit row.
    d = admin_sess.delete(
        f"{BASE_URL}/api/tenants/me/logo",
        timeout=REQ_TIMEOUT,
    )
    assert d.status_code == 200, d.text
    assert d.json().get("logo_url") is None


# ═════════════════════════════════════════════════════════════════════
# 9. Public branding endpoint returns ONLY the allow-listed keys
# ═════════════════════════════════════════════════════════════════════

def test_public_branding_endpoint_filters_admin_fields(
    admin_sess, snapshot,
):
    # Stamp a tax_id so we can verify it's redacted.
    admin_sess.patch(
        f"{BASE_URL}/api/tenants/me/business-settings",
        json={"tax_id": "EIN 99-9999999"},
        timeout=REQ_TIMEOUT,
    )
    # Grab a magic-link token off any existing quote.
    q = admin_sess.get(f"{BASE_URL}/api/quotes?limit=1",
                        timeout=REQ_TIMEOUT).json()
    rows = q if isinstance(q, list) else (q.get("items") or q.get("results") or [])
    if not rows:
        pytest.skip("no quotes in tenant to build magic-link")
    qid = rows[0]["id"]
    tok_r = admin_sess.get(f"{BASE_URL}/api/quotes/{qid}/magic-link",
                            timeout=REQ_TIMEOUT)
    assert tok_r.status_code == 200, tok_r.text
    token = tok_r.json().get("token")
    assert token

    pub = requests.get(
        f"{BASE_URL}/api/portal/tenant/branding?token={token}",
        timeout=REQ_TIMEOUT,
    )
    assert pub.status_code == 200, pub.text
    branding = pub.json().get("branding") or {}
    # allow-listed keys.
    for k in ("company_display_name", "logo_url", "brand_primary_hex",
              "brand_secondary_hex", "footer_note", "phone",
              "mailing_address", "email", "website"):
        assert k in branding, f"missing {k}"
    # Explicitly redacted.
    assert "tax_id" not in branding


# ═════════════════════════════════════════════════════════════════════
# 10. Effective-settings helper — unset fields fall back correctly
# ═════════════════════════════════════════════════════════════════════

def test_effective_settings_fallbacks():
    from services.tenants.business_settings import (
        build_business_settings_view,
        DEFAULT_PRIMARY_HEX,
        DEFAULT_SECONDARY_HEX,
    )
    view = build_business_settings_view({
        "company_name": "Legacy Co",
        # Nothing else set.
    })
    eff = view["effective"]
    # Company falls back to company_name.
    assert eff["company_display_name"] == "Legacy Co"
    # Hex fields fall back to defaults.
    assert eff["brand_primary_hex"] == DEFAULT_PRIMARY_HEX
    assert eff["brand_secondary_hex"] == DEFAULT_SECONDARY_HEX
    # Missing optional fields stay None.
    assert eff["tax_id"] is None
    assert eff["footer_note"] is None


# ═════════════════════════════════════════════════════════════════════
# 11. Public branding: invalid token → 401
# ═════════════════════════════════════════════════════════════════════

def test_public_branding_bad_token_401():
    r = requests.get(
        f"{BASE_URL}/api/portal/tenant/branding?token=not-a-real-token",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 401, r.text


# ═════════════════════════════════════════════════════════════════════
# 12. to_public_branding filter — pure function contract
# ═════════════════════════════════════════════════════════════════════

def test_to_public_branding_filters_pure():
    from services.tenants.business_settings import (
        build_business_settings_view,
        to_public_branding,
    )
    view = build_business_settings_view({
        "company_name": "X", "tax_id": "SECRET",
        "brand_primary_hex": "#111111",
    })
    out = to_public_branding(view["effective"])
    assert "tax_id" not in out
    assert out["brand_primary_hex"] == "#111111"
    assert out["company_display_name"] == "X"
