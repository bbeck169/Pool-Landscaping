"""Feb-2026 · Slice H1 — Public Form Builder backend.

Covers:
* Admin CRUD for form definitions (RBAC + slug uniqueness).
* Public widget schema fetch (widget-auth enforced).
* Public form submit — Turnstile graceful bypass, required-field
  validation, submission persistence, lead upsert, admin bell hook.
* Cross-tenant isolation on submissions.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests

BASE_URL = "http://localhost:8001"
API = f"{BASE_URL}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro): return _LOOP.run_until_complete(coro)


def _rebind_db_to_loop():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    import routers.widget_config as _wc
    _wc.db = fresh_db
    import routers.marketing_forms as _mf
    _mf.db = fresh_db
    return fresh_db


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    _rebind_db_to_loop()
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"],
                               io_loop=_LOOP)[os.environ["DB_NAME"]]


def _widget_key(super_headers):
    r = requests.get(f"{API}/tenants/mine/widget-config",
                      headers=super_headers, timeout=15)
    assert r.status_code == 200
    return r.json()["public_widget_key"]


def _whitelist(super_headers, host):
    r = requests.patch(
        f"{API}/tenants/mine/widget-config/domains",
        headers=super_headers,
        json={"domains": [host]},   # exercise the alias too
        timeout=15,
    )
    assert r.status_code == 200, r.text


def _standard_form_body(name_suffix: str = ""):
    return {
        "name": f"TEST_Contact Form {name_suffix or uuid.uuid4().hex[:6]}",
        "fields": [
            {"name": "name", "label": "Full Name", "type": "text", "required": True},
            {"name": "email", "label": "Email", "type": "email", "required": True},
            {"name": "phone", "label": "Phone", "type": "phone", "required": False},
            {"name": "message", "label": "Message", "type": "textarea", "required": True},
        ],
    }


# ═══════════════════════════════════════════════════════════════════════
# Admin CRUD
# ═══════════════════════════════════════════════════════════════════════
def test_create_form_admin_only(admin_headers, tech_headers):
    body = _standard_form_body()
    # Tech cannot create.
    r = requests.post(f"{API}/admin/forms", headers=tech_headers,
                       json=body, timeout=15)
    assert r.status_code in (401, 403)

    r = requests.post(f"{API}/admin/forms", headers=admin_headers,
                       json=body, timeout=15)
    assert r.status_code == 201, r.text
    form = r.json()
    assert form["name"].startswith("TEST_Contact Form")
    assert form["slug"].startswith("test-contact-form"), form["slug"]
    assert form["active"] is True
    assert form["submission_count"] == 0


def test_create_form_slug_uniqueness(admin_headers):
    unique = f"unique{uuid.uuid4().hex[:6]}"
    body = _standard_form_body(unique)
    r = requests.post(f"{API}/admin/forms", headers=admin_headers,
                       json=body, timeout=15)
    assert r.status_code == 201
    r2 = requests.post(f"{API}/admin/forms", headers=admin_headers,
                       json=body, timeout=15)
    assert r2.status_code == 409, r2.text


def test_form_field_validation(admin_headers):
    # Unsupported field type → 422
    r = requests.post(f"{API}/admin/forms", headers=admin_headers,
                       json={"name": f"TEST_Bad {uuid.uuid4().hex[:6]}",
                             "fields": [{"name": "x", "label": "X",
                                          "type": "colorwheel",
                                          "required": False}]},
                       timeout=15)
    assert r.status_code == 422, r.text

    # Duplicate field names → 422
    r = requests.post(f"{API}/admin/forms", headers=admin_headers,
                       json={"name": f"TEST_Dup {uuid.uuid4().hex[:6]}",
                             "fields": [
                                {"name": "email", "label": "E", "type": "email"},
                                {"name": "email", "label": "E2", "type": "email"},
                             ]},
                       timeout=15)
    assert r.status_code == 422, r.text

    # Select without options → 422
    r = requests.post(f"{API}/admin/forms", headers=admin_headers,
                       json={"name": f"TEST_Sel {uuid.uuid4().hex[:6]}",
                             "fields": [{"name": "svc", "label": "Service",
                                          "type": "select"}]},
                       timeout=15)
    assert r.status_code == 422, r.text


def test_list_and_get_and_patch_form(admin_headers):
    r = requests.post(f"{API}/admin/forms", headers=admin_headers,
                       json=_standard_form_body(f"list{uuid.uuid4().hex[:5]}"),
                       timeout=15)
    fid = r.json()["id"]

    # LIST
    r = requests.get(f"{API}/admin/forms", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert any(f["id"] == fid for f in r.json())

    # GET
    r = requests.get(f"{API}/admin/forms/{fid}",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["id"] == fid

    # PATCH
    r = requests.patch(f"{API}/admin/forms/{fid}",
                        headers=admin_headers,
                        json={"active": False,
                              "success_message": "Custom thanks!"},
                        timeout=15)
    assert r.status_code == 200, r.text
    upd = r.json()
    assert upd["active"] is False
    assert upd["success_message"] == "Custom thanks!"


def test_form_admin_rbac(tech_headers):
    r = requests.get(f"{API}/admin/forms", headers=tech_headers, timeout=15)
    assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════
# Public widget GET/POST — Turnstile bypass mode
# ═══════════════════════════════════════════════════════════════════════
def _widget_headers(key, origin_host):
    return {"X-Widget-Key": key,
            "Origin": f"https://{origin_host}"}


def test_widget_get_form_enforces_widget_auth(admin_headers, super_headers):
    r = requests.post(f"{API}/admin/forms", headers=admin_headers,
                       json=_standard_form_body(f"get{uuid.uuid4().hex[:5]}"),
                       timeout=15)
    fid = r.json()["id"]

    host = f"h1-get-{uuid.uuid4().hex[:6]}.example.com"
    _whitelist(super_headers, host)
    key = _widget_key(super_headers)

    # No key → 401
    r = requests.get(f"{API}/widget/form/{fid}",
                      headers={"Origin": f"https://{host}"}, timeout=15)
    assert r.status_code == 401

    # Foreign origin → 401
    r = requests.get(f"{API}/widget/form/{fid}",
                      headers={"X-Widget-Key": key,
                                "Origin": "https://foreign.evil"},
                      timeout=15)
    assert r.status_code == 401

    # Right → schema returned, no internal fields leaked.
    r = requests.get(f"{API}/widget/form/{fid}",
                      headers=_widget_headers(key, host), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == fid
    # Internal fields must NOT be in the public schema.
    assert "created_by" not in body
    assert "tenant_id" not in body
    assert "submission_count" not in body


def test_widget_submit_creates_submission_and_lead(admin_headers, super_headers):
    r = requests.post(f"{API}/admin/forms", headers=admin_headers,
                       json=_standard_form_body(f"sub{uuid.uuid4().hex[:5]}"),
                       timeout=15)
    fid = r.json()["id"]

    host = f"h1-sub-{uuid.uuid4().hex[:6]}.example.com"
    _whitelist(super_headers, host)
    key = _widget_key(super_headers)

    unique = uuid.uuid4().hex[:6]
    visitor_email = f"form-visitor-{unique}@example.com"
    r = requests.post(
        f"{API}/widget/form/{fid}/submit",
        headers=_widget_headers(key, host),
        json={"data": {
                    "name": f"TEST_Alex {unique}",
                    "email": visitor_email,
                    "phone": "6025550100",
                    "message": "TEST_ I want a quote",
                },
              "page_url": "https://example.com/contact"},
        timeout=15,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ok"] is True
    sub_id = body["submission_id"]
    lead_id = body["lead_id"]
    assert lead_id, "lead must be created from form data"

    # DB checks
    async def _go():
        db = _db()
        sub = await db.form_submissions.find_one({"id": sub_id}, {"_id": 0})
        assert sub["form_id"] == fid
        assert sub["data"]["email"] == visitor_email
        assert sub["lead_id"] == lead_id
        lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
        assert lead["email"] == visitor_email
        assert lead["source"].startswith("form:")
    _run(_go())


def test_widget_submit_required_field_validation(admin_headers, super_headers):
    r = requests.post(f"{API}/admin/forms", headers=admin_headers,
                       json=_standard_form_body(f"req{uuid.uuid4().hex[:5]}"),
                       timeout=15)
    fid = r.json()["id"]

    host = f"h1-req-{uuid.uuid4().hex[:6]}.example.com"
    _whitelist(super_headers, host)
    key = _widget_key(super_headers)

    # Missing required 'email' + 'message'
    r = requests.post(
        f"{API}/widget/form/{fid}/submit",
        headers=_widget_headers(key, host),
        json={"data": {"name": "TEST_partial"}},
        timeout=15,
    )
    assert r.status_code == 422, r.text
    assert "missing required" in r.text.lower()


def test_widget_submit_inactive_form_returns_404(admin_headers, super_headers):
    r = requests.post(f"{API}/admin/forms", headers=admin_headers,
                       json=_standard_form_body(f"inact{uuid.uuid4().hex[:5]}"),
                       timeout=15)
    fid = r.json()["id"]

    # Deactivate.
    r = requests.patch(f"{API}/admin/forms/{fid}",
                        headers=admin_headers,
                        json={"active": False}, timeout=15)
    assert r.status_code == 200

    host = f"h1-inact-{uuid.uuid4().hex[:6]}.example.com"
    _whitelist(super_headers, host)
    key = _widget_key(super_headers)

    # Public GET → 404
    r = requests.get(f"{API}/widget/form/{fid}",
                      headers=_widget_headers(key, host), timeout=15)
    assert r.status_code == 404

    # Public POST submit → 404
    r = requests.post(
        f"{API}/widget/form/{fid}/submit",
        headers=_widget_headers(key, host),
        json={"data": {"name": "x", "email": "x@example.com", "message": "x"}},
        timeout=15,
    )
    assert r.status_code == 404


def test_widget_submit_bumps_counter_and_admin_can_list(admin_headers,
                                                           super_headers):
    r = requests.post(f"{API}/admin/forms", headers=admin_headers,
                       json=_standard_form_body(f"cnt{uuid.uuid4().hex[:5]}"),
                       timeout=15)
    fid = r.json()["id"]

    host = f"h1-cnt-{uuid.uuid4().hex[:6]}.example.com"
    _whitelist(super_headers, host)
    key = _widget_key(super_headers)

    unique = uuid.uuid4().hex[:6]
    for i in range(3):
        r = requests.post(
            f"{API}/widget/form/{fid}/submit",
            headers=_widget_headers(key, host),
            json={"data": {"name": f"TEST_C{i}",
                            "email": f"cnt-{unique}-{i}@example.com",
                            "message": "TEST_ hello"}},
            timeout=15,
        )
        assert r.status_code == 201, r.text

    # Counter bumped.
    r = requests.get(f"{API}/admin/forms/{fid}",
                      headers=admin_headers, timeout=15)
    assert r.json()["submission_count"] >= 3

    # Admin submissions list.
    r = requests.get(f"{API}/admin/forms/{fid}/submissions",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    subs = r.json()
    assert len(subs) >= 3
    # All rows are for THIS form.
    assert all(s["form_id"] == fid for s in subs)


def test_widget_submit_turnstile_bypass_when_secret_missing(
        admin_headers, super_headers, monkeypatch):
    """TURNSTILE_SECRET is not set in .env → the endpoint accepts
    submissions with no turnstile_token. This test asserts the
    graceful-bypass behavior explicitly."""
    # Ensure the process env matches .env (no secret).
    monkeypatch.delenv("TURNSTILE_SECRET", raising=False)

    r = requests.post(f"{API}/admin/forms", headers=admin_headers,
                       json=_standard_form_body(f"tsbp{uuid.uuid4().hex[:5]}"),
                       timeout=15)
    fid = r.json()["id"]

    host = f"h1-tsbp-{uuid.uuid4().hex[:6]}.example.com"
    _whitelist(super_headers, host)
    key = _widget_key(super_headers)

    r = requests.post(
        f"{API}/widget/form/{fid}/submit",
        headers=_widget_headers(key, host),
        json={"data": {"name": "TEST_ts", "email": f"ts-{uuid.uuid4().hex[:6]}@example.com",
                        "message": "TEST_bypass"}},
        timeout=15,
    )
    assert r.status_code == 201, r.text


def test_widget_submit_404_for_wrong_tenant_form(admin_headers, super_headers):
    """A form_id fabricated (or from a different tenant) MUST 404 —
    the widget endpoint scopes strictly to the widget key's tenant."""
    host = f"h1-cross-{uuid.uuid4().hex[:6]}.example.com"
    _whitelist(super_headers, host)
    key = _widget_key(super_headers)

    r = requests.post(
        f"{API}/widget/form/definitely-not-mine-{uuid.uuid4().hex}/submit",
        headers=_widget_headers(key, host),
        json={"data": {"name": "x", "email": "x@example.com",
                        "message": "TEST_"}},
        timeout=15,
    )
    assert r.status_code == 404
