"""Feb-2026 · Item 4 — AI knowledge base + Copilot backend tests."""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
_TENANT_ID = _sync.tenants.find_one({"slug": "aquaterra"})["id"]
API = "http://localhost:8001/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_headers():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_headers():
    return _login("mike@aquaterra.com")


def test_knowledge_crud_lifecycle(admin_headers):
    marker = uuid.uuid4().hex[:6]
    # Create.
    r = requests.post(f"{API}/ai/knowledge", headers=admin_headers,
                       json={"kind": "faq",
                              "title": f"Test FAQ {marker}",
                              "content_md": "# hello\n\nWorld.",
                              "is_active": True, "tags": ["test"]},
                       timeout=10)
    assert r.status_code == 200, r.text
    row = r.json()
    kid = row["id"]
    assert row["kind"] == "faq" and row["is_active"] is True

    # List includes it.
    r = requests.get(f"{API}/ai/knowledge", headers=admin_headers, timeout=10)
    ids = {x["id"] for x in r.json()["items"]}
    assert kid in ids

    # Patch.
    r = requests.patch(f"{API}/ai/knowledge/{kid}", headers=admin_headers,
                        json={"title": f"Updated {marker}"}, timeout=10)
    assert r.status_code == 200
    assert r.json()["title"] == f"Updated {marker}"

    # System-prompt concat surfaces the entry.
    r = requests.get(f"{API}/ai/knowledge/system-prompt",
                      headers=admin_headers, timeout=10)
    prompt = r.json()["system_prompt"]
    assert f"Updated {marker}" in prompt
    assert "## [faq]" in prompt

    # Soft-delete.
    r = requests.delete(f"{API}/ai/knowledge/{kid}", headers=admin_headers, timeout=10)
    assert r.status_code == 200
    # Post-delete, no longer surfaces in system prompt.
    r = requests.get(f"{API}/ai/knowledge/system-prompt",
                      headers=admin_headers, timeout=10)
    assert f"Updated {marker}" not in r.json()["system_prompt"]

    _sync.ai_knowledge_base.delete_one({"id": kid})


def test_technician_forbidden(tech_headers):
    r = requests.get(f"{API}/ai/knowledge", headers=tech_headers, timeout=10)
    assert r.status_code == 403


def test_copilot_returns_reply_and_logs_conversation(admin_headers):
    # Backend LLM path degrades gracefully when EMERGENT_LLM_KEY isn't
    # set — that's the safe branch and it still writes to the audit log.
    r = requests.post(f"{API}/ai/copilot/message", headers=admin_headers,
                       json={"message": "How many active customers do we have?"},
                       timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"]
    assert body["thread_id"]
    # Audit log written.
    log = _sync.ai_copilot_log.find_one(
        {"tenant_id": _TENANT_ID, "thread_id": body["thread_id"]},
        {"_id": 0})
    assert log is not None
    assert log["prompt"].startswith("How many")


def test_copilot_tool_scoping_denies_cross_tenant(admin_headers):
    """The get_customer tool auto-injects tenant_id, so requesting a
    customer id that belongs to a different tenant (or doesn't exist)
    returns ``not_found`` — never the actual document."""
    from routers.ai_brain import _tool_get_customer
    import asyncio
    # Create a customer in a separate synthetic tenant.
    fake_tenant = f"fake-tenant-{uuid.uuid4().hex[:6]}"
    fake_cid = f"fake-cust-{uuid.uuid4().hex[:6]}"
    _sync.customers.insert_one({
        "id": fake_cid, "tenant_id": fake_tenant,
        "name": "CROSS TENANT LEAK", "is_active": True,
    })
    try:
        # Query as aquaterra tenant — must NOT reveal the fake tenant's row.
        result = asyncio.get_event_loop().run_until_complete(
            _tool_get_customer(_TENANT_ID, fake_cid))
        assert result.get("error") == "not_found"
        assert "customer" not in result
    finally:
        _sync.customers.delete_one({"id": fake_cid})


def test_copilot_technician_forbidden(tech_headers):
    r = requests.post(f"{API}/ai/copilot/message", headers=tech_headers,
                       json={"message": "hi"}, timeout=10)
    assert r.status_code == 403


def test_mass_messaging_audience_status_filters(admin_headers):
    """Preview with ``audience_status=inactive`` returns only inactive
    customers; ``both`` returns the union; ``active`` (default) unchanged."""
    marker = uuid.uuid4().hex[:6]
    a_id = f"aud-active-{marker}"
    i_id = f"aud-inactive-{marker}"
    _sync.customers.insert_many([
        {"id": a_id, "tenant_id": _TENANT_ID, "name": "Active Alpha",
          "email": f"a-{marker}@ex.local", "phone": "+15550001111",
          "is_active": True, "first_name": "Alpha"},
        {"id": i_id, "tenant_id": _TENANT_ID, "name": "Inactive Ivy",
          "email": f"i-{marker}@ex.local", "phone": "+15550002222",
          "is_active": False, "first_name": "Ivy"},
    ])
    try:
        def _preview(status):
            r = requests.post(f"{API}/mass-messaging/preview",
                              headers=admin_headers,
                              json={"channels": ["email"],
                                     "audience": "all_active_customers",
                                     "subject": "hi", "body": "Hello {{CUSTOMER_FIRST_NAME}}",
                                     "audience_status": status}, timeout=15)
            assert r.status_code == 200, r.text
            return r.json()

        active = _preview("active")
        inactive = _preview("inactive")
        both = _preview("both")

        active_ids = {c.get("id") for c in (active.get("audience_sample") or [])}
        inactive_ids = {c.get("id") for c in (inactive.get("audience_sample") or [])}
        # audience_sample is capped; check the counts + presence.
        assert active["estimated_recipients"]["email"] >= 1
        assert inactive["estimated_recipients"]["email"] >= 1
        # Inactive-only preview shouldn't include the active alpha row.
        assert a_id not in inactive_ids
        # Both >= max(active, inactive) - typical union invariant.
        assert both["estimated_recipients"]["email"] >= max(
            active["estimated_recipients"]["email"],
            inactive["estimated_recipients"]["email"],
        )
    finally:
        _sync.customers.delete_many({"id": {"$in": [a_id, i_id]}})


def test_service_title_merge_tag_prefers_title_over_name():
    from services.marketing.merge_tags import _TAG_INDEX
    assert "SERVICE_TITLE" in _TAG_INDEX
    resolver = _TAG_INDEX["SERVICE_TITLE"]
    # Prefers title over name.
    assert resolver({"job": {"service_template": {"title": "Weekly Pool Cleaning",
                                                     "name": "pool.weekly"}}}) == "Weekly Pool Cleaning"
    # Falls back to name when title missing.
    assert resolver({"job": {"service_template": {"name": "Landscape mow"}}}) == "Landscape mow"
    # Falls back to job.title.
    assert resolver({"job": {"title": "One-off repair"}}) == "One-off repair"
    # Empty when nothing resolves.
    assert resolver({"job": {}}) == ""
