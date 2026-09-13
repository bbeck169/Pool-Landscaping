"""Feb-2026 · UX Polish Batch B follow-up — Email preview endpoint.

Locks the contract on ``GET /api/tenants/me/email-preview``:

  1. Each of the 4 supported templates renders wrapped HTML.
  2. Unknown template → 400.
  3. Technician → 403.
  4. Response payload carries exactly one ``<html>`` tag (uses the
     same shell as production sends).

See /app/memory/FEATURE_SEND_COPY_LINK_AND_EMAIL_PREVIEW.md.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

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


@pytest.fixture(scope="module")
def admin_sess():
    return _session("admin@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def tech_sess():
    return _session("mike@aquaterra.com", "password123")


_URL = "/api/tenants/me/email-preview"
_HTML_RE = re.compile(r"<html\b", re.IGNORECASE)


@pytest.mark.parametrize("template", [
    "quote_sent", "invoice_reminder", "password_reset", "portal_invite",
])
def test_admin_renders_each_template(admin_sess, template):
    r = admin_sess.get(f"{BASE_URL}{_URL}?template={template}",
                        timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["template"] == template
    html = body["html"]
    # Exactly one <html> tag — truthful to production single-wrap.
    assert len(_HTML_RE.findall(html)) == 1
    # Template content leaks through the shell (anchor per template).
    if template == "quote_sent":
        assert "Review quote" in html or "quote is ready" in html
    if template == "invoice_reminder":
        assert "Invoice reminder" in html or "Pay now" in html
    if template == "password_reset":
        assert "Reset your password" in html or "Reset password" in html
    if template == "portal_invite":
        assert "Password reset by admin" in html \
            or "temporary password" in html.lower()


def test_unknown_template_returns_400(admin_sess):
    r = admin_sess.get(f"{BASE_URL}{_URL}?template=bogus-not-real",
                        timeout=REQ_TIMEOUT)
    assert r.status_code == 400, r.text
    assert "unknown" in r.text.lower() or "expected" in r.text.lower()


def test_technician_cannot_preview(tech_sess):
    r = tech_sess.get(f"{BASE_URL}{_URL}?template=quote_sent",
                        timeout=REQ_TIMEOUT)
    assert r.status_code == 403, r.text
