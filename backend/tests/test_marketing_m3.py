"""Feb-2026 · Marketing Slice M3 — Template library tests."""
from __future__ import annotations

import asyncio
import os

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


# ═══════════════════════════════════════════════════════════════════════
# Renderer unit tests — pure, no HTTP
# ═══════════════════════════════════════════════════════════════════════
def test_render_basic_substitution():
    from services.marketing.render import render_template
    out, missing = render_template(
        "Hi {{customer.first_name}}!",
        {"customer": {"first_name": "Sam"}},
    )
    assert out == "Hi Sam!"
    assert missing == []


def test_render_missing_key_returns_empty_and_lists():
    from services.marketing.render import render_template
    out, missing = render_template(
        "Hi {{customer.first_name}} — balance {{customer.balance}}.",
        {"customer": {"first_name": "Sam"}},
    )
    assert out == "Hi Sam — balance ."
    assert missing == ["customer.balance"]


def test_render_nested_dotted_path():
    from services.marketing.render import render_template
    out, missing = render_template(
        "From {{tenant.name}} · {{tenant.phone}}",
        {"tenant": {"name": "Acme", "phone": "555"}},
    )
    assert out == "From Acme · 555"
    assert missing == []


def test_render_preserves_html_in_body():
    from services.marketing.render import render_template
    out, _ = render_template(
        "<b>Hi {{customer.first_name}}</b>",
        {"customer": {"first_name": "Sam"}},
    )
    assert out == "<b>Hi Sam</b>"


def test_strip_html_for_sms():
    from services.marketing.render import strip_html
    assert strip_html("<b>Hi</b>&nbsp;there") == "Hi there"
    assert strip_html("no tags") == "no tags"
    assert strip_html("") == ""


def test_render_ignores_single_braces():
    """We only substitute ``{{...}}``. Legacy ``{name}`` shape used by
    other campaigns must pass through untouched."""
    from services.marketing.render import render_template
    out, missing = render_template("Hi {name}", {"name": "Sam"})
    assert out == "Hi {name}"
    assert missing == []


def test_variables_registry_populated():
    from services.marketing.render import VARIABLES_REGISTRY
    assert len(VARIABLES_REGISTRY) >= 8
    for entry in VARIABLES_REGISTRY:
        assert "name" in entry and "description" in entry


# ═══════════════════════════════════════════════════════════════════════
# Endpoint RBAC
# ═══════════════════════════════════════════════════════════════════════
def test_list_variables_admin_only(admin_headers, tech_headers, customer_headers):
    r = requests.get(f"{API}/marketing/templates/variables",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json().get("variables"), list)
    for h in (tech_headers, customer_headers):
        r = requests.get(f"{API}/marketing/templates/variables",
                          headers=h, timeout=15)
        assert r.status_code in (401, 403)


def test_list_variables_anon_forbidden():
    r = requests.get(f"{API}/marketing/templates/variables", timeout=15)
    assert r.status_code in (401, 403)


def test_list_templates_seeded_for_tenant(admin_headers):
    r = requests.get(f"{API}/marketing/templates",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    # 12 seeded templates (6 categories × 2 channels) minimum.
    assert body["count"] >= 12
    for row in body["templates"]:
        assert row["tenant_id"], "tenant_id missing on serialised row"


def test_list_filters(admin_headers):
    r = requests.get(f"{API}/marketing/templates?channel=sms",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    for row in r.json()["templates"]:
        assert row["channel"] == "sms"
    r = requests.get(f"{API}/marketing/templates?category=past_due",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    for row in r.json()["templates"]:
        assert row["category"] == "past_due"


def test_crud_flow(admin_headers):
    # Create
    r = requests.post(f"{API}/marketing/templates",
                       headers=admin_headers,
                       json={"name": "M3 test email",
                             "channel": "email",
                             "category": "general",
                             "subject": "Hey {{customer.first_name}}",
                             "body": "Balance: {{customer.balance_due}}"},
                       timeout=15)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    # Detail
    r = requests.get(f"{API}/marketing/templates/{tid}",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["subject"].startswith("Hey")

    # Patch
    r = requests.patch(f"{API}/marketing/templates/{tid}",
                        headers=admin_headers,
                        json={"body": "Updated body"},
                        timeout=15)
    assert r.status_code == 200
    assert r.json()["body"] == "Updated body"

    # Preview
    r = requests.post(f"{API}/marketing/templates/{tid}/preview",
                       headers=admin_headers, json={}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["subject_rendered"].startswith("Hey Sam")
    assert body["body_rendered"] == "Updated body"

    # Preview with custom context — override customer.first_name
    r = requests.post(f"{API}/marketing/templates/{tid}/preview",
                       headers=admin_headers,
                       json={"sample_context": {"customer": {"first_name": "Custom"}}},
                       timeout=15)
    assert r.status_code == 200
    assert "Hey Custom" in r.json()["subject_rendered"]

    # Soft-delete
    r = requests.delete(f"{API}/marketing/templates/{tid}",
                         headers=admin_headers, timeout=15)
    assert r.status_code == 204
    r = requests.get(f"{API}/marketing/templates/{tid}",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["active"] is False


def test_email_requires_subject(admin_headers):
    r = requests.post(f"{API}/marketing/templates",
                       headers=admin_headers,
                       json={"name": "No subject email",
                             "channel": "email",
                             "body": "hi"},
                       timeout=15)
    assert r.status_code == 422


def test_invalid_channel_rejected(admin_headers):
    r = requests.post(f"{API}/marketing/templates",
                       headers=admin_headers,
                       json={"name": "Invalid channel",
                             "channel": "carrier-pigeon",
                             "body": "hi"},
                       timeout=15)
    assert r.status_code == 422


def test_rbac_non_admin_blocked(tech_headers, customer_headers):
    for h in (tech_headers, customer_headers):
        assert requests.get(f"{API}/marketing/templates",
                             headers=h, timeout=15).status_code in (401, 403)
        assert requests.post(f"{API}/marketing/templates",
                              headers=h,
                              json={"name": "x", "channel": "sms",
                                    "body": "y"},
                              timeout=15).status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════
# Preview: missing_vars + SMS HTML strip via router
# ═══════════════════════════════════════════════════════════════════════
def test_preview_missing_vars(admin_headers):
    r = requests.post(f"{API}/marketing/templates",
                       headers=admin_headers,
                       json={"name": "M3 missing-var probe",
                             "channel": "email",
                             "subject": "Hi",
                             "body": "Hi {{customer.first_name}} — "
                                     "reference: {{customer.foo}} — "
                                     "bogus: {{does.not.exist}}"},
                       timeout=15)
    tid = r.json()["id"]
    p = requests.post(f"{API}/marketing/templates/{tid}/preview",
                       headers=admin_headers, json={}, timeout=15)
    assert p.status_code == 200
    missing = p.json()["missing_vars"]
    assert "customer.foo" in missing
    assert "does.not.exist" in missing
    assert "customer.first_name" not in missing


def test_preview_sms_strips_html(admin_headers):
    r = requests.post(f"{API}/marketing/templates",
                       headers=admin_headers,
                       json={"name": "M3 SMS strip",
                             "channel": "sms",
                             "body": "Hi <b>{{customer.first_name}}</b>&nbsp;— call now"},
                       timeout=15)
    tid = r.json()["id"]
    p = requests.post(f"{API}/marketing/templates/{tid}/preview",
                       headers=admin_headers, json={}, timeout=15)
    body_rendered = p.json()["body_rendered"]
    assert body_rendered == "Hi Sam — call now"
    assert p.json()["subject_rendered"] is None


# ═══════════════════════════════════════════════════════════════════════
# Soft-delete guard when referenced by a live campaign
# ═══════════════════════════════════════════════════════════════════════
def test_delete_blocked_when_referenced_by_live_campaign(admin_headers):
    # Create the template.
    tr = requests.post(f"{API}/marketing/templates",
                        headers=admin_headers,
                        json={"name": "M3 ref-guard test",
                              "channel": "email", "subject": "s",
                              "body": "b"},
                        timeout=15).json()
    tid = tr["id"]

    # Inject a fake campaign that references this template in
    # ``scheduled`` state directly into Mongo — the M2 create endpoint
    # doesn't yet accept ``email_template_id`` so this is the
    # lightest path to exercise the delete-guard branch.
    async def _inject_campaign():
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        db = AsyncIOMotorClient(
            os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        u = await db.users.find_one({"email": "admin@aquaterra.com"},
                                      {"_id": 0, "tenant_id": 1})
        cid = f"m3-guard-camp-{tid[:8]}"
        await db.marketing_campaigns.insert_one({
            "id": cid, "tenant_id": u["tenant_id"],
            "name": "M3 guard fake campaign",
            "status": "scheduled",
            "email_template_id": tid,
        })
        return cid, u["tenant_id"]

    cid, ten = asyncio.new_event_loop().run_until_complete(
        _inject_campaign(),
    )

    try:
        # DELETE must 409 while the referenced campaign is live.
        r = requests.delete(f"{API}/marketing/templates/{tid}",
                             headers=admin_headers, timeout=15)
        assert r.status_code == 409, r.text
    finally:
        # Cleanup fake campaign.
        async def _clean():
            from motor.motor_asyncio import AsyncIOMotorClient
            from dotenv import load_dotenv
            load_dotenv("/app/backend/.env")
            db = AsyncIOMotorClient(
                os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
            await db.marketing_campaigns.delete_one({"id": cid})
        asyncio.new_event_loop().run_until_complete(_clean())

    # Now the campaign is gone → delete must succeed.
    r = requests.delete(f"{API}/marketing/templates/{tid}",
                         headers=admin_headers, timeout=15)
    assert r.status_code == 204


# ═══════════════════════════════════════════════════════════════════════
# Cross-tenant isolation
# ═══════════════════════════════════════════════════════════════════════
def test_cross_tenant_isolation(admin_headers):
    """A template in tenant B must not be readable / patchable /
    deletable by an admin in tenant A."""
    async def _seed_foreign_template():
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        from utils import new_id, now_iso
        load_dotenv("/app/backend/.env")
        db = AsyncIOMotorClient(
            os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        u = await db.users.find_one({"email": "admin@aquaterra.com"},
                                      {"_id": 0, "tenant_id": 1})
        tenants = await db.tenants.find(
            {"id": {"$ne": u["tenant_id"]}}, {"_id": 0, "id": 1},
        ).to_list(1)
        assert tenants, "need a second tenant for this test"
        foreign_tid = tenants[0]["id"]
        tid = new_id()
        await db.marketing_templates.insert_one({
            "id": tid, "tenant_id": foreign_tid,
            "name": "foreign", "channel": "sms",
            "category": "general", "subject": None,
            "body": "hi", "active": True,
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        return tid, foreign_tid

    tid, foreign_tid = asyncio.new_event_loop().run_until_complete(
        _seed_foreign_template(),
    )
    try:
        # GET → 404 (not 200, not 403 — we don't leak existence)
        r = requests.get(f"{API}/marketing/templates/{tid}",
                          headers=admin_headers, timeout=15)
        assert r.status_code == 404
        # PATCH → 404
        r = requests.patch(f"{API}/marketing/templates/{tid}",
                            headers=admin_headers,
                            json={"name": "hijack"},
                            timeout=15)
        assert r.status_code == 404
        # DELETE → 404
        r = requests.delete(f"{API}/marketing/templates/{tid}",
                             headers=admin_headers, timeout=15)
        assert r.status_code == 404
    finally:
        async def _clean():
            from motor.motor_asyncio import AsyncIOMotorClient
            from dotenv import load_dotenv
            load_dotenv("/app/backend/.env")
            db = AsyncIOMotorClient(
                os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
            await db.marketing_templates.delete_one({"id": tid})
        asyncio.new_event_loop().run_until_complete(_clean())
