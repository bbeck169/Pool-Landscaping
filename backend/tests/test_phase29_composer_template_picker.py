"""Phase 29 · Feb 2026 — Customer contact composer preview endpoint.

Covers:

* ``POST /customers/{cid}/preview-message`` renders the caller-provided
  subject + body against the real customer's merge context — same
  UPPERCASE + Mustache pipeline the send endpoints use.
* Email channel returns ``subject_rendered`` + HTML ``body_rendered``.
* SMS channel strips HTML and returns ``subject_rendered = None``.
* Bogus channels are refused with 422.
* Customer id that doesn't exist → 404.
* Existing send endpoints already accept caller-supplied ``subject`` +
  ``body`` — verified via source inspection (no change required).
* The templates list endpoint filters by channel, matching what the
  composer's picker sidebar fetches.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db()
def _mk(prefix: str) -> str:
    return f"TEST_{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture(scope="module")
def api_base():
    frontend_env = Path(__file__).resolve().parents[2] / "frontend" / ".env"
    react = dotenv_values(frontend_env) if frontend_env.is_file() else {}
    public = (react.get("REACT_APP_BACKEND_URL")
              or os.environ.get("REACT_APP_BACKEND_URL"))
    return ((public.rstrip("/") + "/api") if public else
            "http://localhost:8001/api")


@pytest.fixture()
def seeded_admin_and_customer():
    tid = _mk("tenant")
    _sync.tenants.insert_one({"id": tid, "name": "TEST_ Vistancia Pools",
                                 "active": True,
                                 "slug": f"testtenant{uuid.uuid4().hex[:6]}",
                                 "email": "contact@vistancia.test.com"})

    def _hash(pw: str) -> str:
        import bcrypt
        return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode()

    admin_email = f"admin_{uuid.uuid4().hex[:6]}@example.com"
    _sync.users.insert_one({
        "id": _mk("admin"), "tenant_id": tid, "email": admin_email,
        "password_hash": _hash("Testpass1!"),
        "role": "admin", "name": "TEST_ Admin",
        "primary_tenant_id": tid, "tenant_ids": [tid],
    })

    cid = _mk("cust")
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": "Jane Homeowner",
        "first_name": "Jane", "last_name": "Homeowner",
        "email": "jane@example.com",
        "emails": [{"address": "jane@example.com", "label": "Primary"}],
        "phone": "+16025551234",
        "phones": [{"number": "+16025551234", "label": "Mobile"}],
        "address": "18420 W. Cactus Bloom Ln.",
        "address_line_1": "18420 W. Cactus Bloom Ln.",
        "city": "Peoria", "state": "AZ", "zip": "85383",
        "balance_due": 125.50,
    })

    ctx = {"tenant_id": tid, "admin_email": admin_email, "customer_id": cid}
    yield ctx

    _sync.customers.delete_many({"tenant_id": tid})
    _sync.users.delete_many({"tenant_id": tid})
    _sync.tenants.delete_one({"id": tid})


def _login(api_base: str, email: str, password: str) -> str:
    r = requests.post(f"{api_base}/auth/login",
                       json={"email": email, "password": password},
                       timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ═══════════ Preview endpoint ══════════════════════════════════════════
def test_preview_email_renders_customer_first_name(seeded_admin_and_customer, api_base):
    tok = _login(api_base, seeded_admin_and_customer["admin_email"], "Testpass1!")
    r = requests.post(
        f"{api_base}/customers/{seeded_admin_and_customer['customer_id']}/preview-message",
        json={"channel": "email",
                "subject": "Hi {{CUSTOMER_FIRST_NAME}}!",
                "body": "<p>Your address is {{CUSTOMER_ADDRESS}}.</p>"},
        headers=_headers(tok), timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["channel"] == "email"
    assert body["subject_rendered"] == "Hi Jane!"
    assert "18420 W. Cactus Bloom Ln." in body["body_rendered"]
    assert "Peoria" in body["body_rendered"]
    assert "AZ 85383" in body["body_rendered"]


def test_preview_sms_strips_html_and_no_subject(seeded_admin_and_customer, api_base):
    tok = _login(api_base, seeded_admin_and_customer["admin_email"], "Testpass1!")
    r = requests.post(
        f"{api_base}/customers/{seeded_admin_and_customer['customer_id']}/preview-message",
        json={"channel": "sms",
                "body": "<p>Hi <b>{{CUSTOMER_FIRST_NAME}}</b>! Balance due.</p>"},
        headers=_headers(tok), timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["channel"] == "sms"
    assert body["subject_rendered"] is None
    # HTML tags stripped, merge tag resolved.
    assert "<b>" not in body["body_rendered"]
    assert "<p>" not in body["body_rendered"]
    assert "Jane" in body["body_rendered"]


def test_preview_rejects_invalid_channel(seeded_admin_and_customer, api_base):
    tok = _login(api_base, seeded_admin_and_customer["admin_email"], "Testpass1!")
    r = requests.post(
        f"{api_base}/customers/{seeded_admin_and_customer['customer_id']}/preview-message",
        json={"channel": "fax", "body": "hi"},
        headers=_headers(tok), timeout=15,
    )
    assert r.status_code == 422


def test_preview_404_for_missing_customer(seeded_admin_and_customer, api_base):
    tok = _login(api_base, seeded_admin_and_customer["admin_email"], "Testpass1!")
    r = requests.post(
        f"{api_base}/customers/does-not-exist/preview-message",
        json={"channel": "email", "subject": "s", "body": "b"},
        headers=_headers(tok), timeout=15,
    )
    assert r.status_code == 404


def test_preview_flags_unresolved_tokens(seeded_admin_and_customer, api_base):
    """A merge tag with no data source in the ctx must appear in
    ``unresolved_tokens`` so the composer UI can warn the operator."""
    tok = _login(api_base, seeded_admin_and_customer["admin_email"], "Testpass1!")
    r = requests.post(
        f"{api_base}/customers/{seeded_admin_and_customer['customer_id']}/preview-message",
        json={"channel": "email",
                "body": "Hi {{CUSTOMER_FIRST_NAME}} — {{NONSENSE_TOKEN}} ends."},
        headers=_headers(tok), timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "NONSENSE_TOKEN" in body["unresolved_tokens"]


# ═══════════ Send endpoints — source contract (unchanged) ══════════════
def test_send_email_endpoint_still_accepts_subject_and_body():
    """Guard — the existing customer-scoped send-email endpoint must
    still take ``subject`` + ``body`` in the payload. Regression-only
    check; we don't fire a real email during tests."""
    import inspect
    from routers import customers as _c
    body_model = _c._SendEmailBody
    assert "subject" in body_model.model_fields
    assert "body" in body_model.model_fields
    # Also verify the send-email handler passes them to send_email().
    src = inspect.getsource(_c.customer_send_email)
    assert "body.subject" in src
    assert "body.body" in src


def test_send_sms_endpoint_still_accepts_body():
    import inspect
    from routers import customers as _c
    assert "body" in _c._SendSmsBody.model_fields
    src = inspect.getsource(_c.customer_send_sms)
    assert "body.body" in src


# ═══════════ Templates list endpoint — channel filter ══════════════════
def test_templates_list_supports_channel_filter(seeded_admin_and_customer, api_base):
    """The composer's template picker calls this endpoint with
    ``?channel=email`` (or ``sms``). Must return 200 and only rows of
    that channel."""
    tok = _login(api_base, seeded_admin_and_customer["admin_email"], "Testpass1!")
    # Seed a couple of tenant templates so the filter actually filters.
    tid = seeded_admin_and_customer["tenant_id"]
    email_tid = _mk("tpl_email")
    sms_tid = _mk("tpl_sms")
    _sync.marketing_templates.insert_many([
        {"id": email_tid, "tenant_id": tid, "channel": "email",
          "name": "TEST_ Reminder", "subject": "Reminder",
          "body": "<p>Hi</p>", "active": True},
        {"id": sms_tid, "tenant_id": tid, "channel": "sms",
          "name": "TEST_ Reminder SMS", "subject": None,
          "body": "Reminder for {{CUSTOMER_FIRST_NAME}}", "active": True},
    ])
    try:
        r = requests.get(f"{api_base}/marketing/templates?channel=email",
                          headers=_headers(tok), timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json().get("templates") or []
        assert any(t["id"] == email_tid for t in rows)
        assert all(t["channel"] == "email" for t in rows)

        r = requests.get(f"{api_base}/marketing/templates?channel=sms",
                          headers=_headers(tok), timeout=15)
        assert r.status_code == 200
        rows = r.json().get("templates") or []
        assert any(t["id"] == sms_tid for t in rows)
        assert all(t["channel"] == "sms" for t in rows)
    finally:
        _sync.marketing_templates.delete_many({"id": {"$in": [email_tid, sms_tid]}})
