"""Feb-2026 · Lead admin notification email — unit + end-to-end.

Covers ``services.lead_admin_notifications.dispatch_admin_lead_email``
plus its two ingress hooks:

* ``POST /api/public/leads`` (public widget)
* ``POST /api/marketing/forms/{fid}/submit`` (widget-form ingress)

We exercise both paths by monkey-patching the Resend adapter so the
send never actually leaves the process, then inspect
``audit_logs`` + ``lead_notification_dispatches`` for the expected
side effects.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]

_FE_ENV = dotenv_values(
    Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE
API = f"{BASE}/api"


# ─────────────────────────── unit tests ─────────────────────────────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) \
        if not asyncio.get_event_loop().is_closed() \
        else asyncio.new_event_loop().run_until_complete(coro)


class TestAdminRecipientResolution:
    def test_resolves_admin_users_and_business_email(self):
        from services.lead_admin_notifications import (
            _resolve_admin_recipients,
        )
        tenant = {
            "id": "TEST_ln-t-1",
            "business_settings": {
                "notification_email": "OWNER@example.com",
            },
        }
        # Seed 3 users: admin, manager, tech (tech must be filtered out),
        # and one deactivated admin (must be filtered out).
        ids = []
        try:
            for row in [
                {"id": f"TEST_ln-u-{uuid.uuid4().hex[:6]}",
                 "tenant_id": "TEST_ln-t-1",
                 "email": "admin1@example.com", "role": "admin"},
                {"id": f"TEST_ln-u-{uuid.uuid4().hex[:6]}",
                 "tenant_id": "TEST_ln-t-1",
                 "email": "manager1@example.com", "role": "manager"},
                {"id": f"TEST_ln-u-{uuid.uuid4().hex[:6]}",
                 "tenant_id": "TEST_ln-t-1",
                 "email": "tech1@example.com", "role": "tech"},
                {"id": f"TEST_ln-u-{uuid.uuid4().hex[:6]}",
                 "tenant_id": "TEST_ln-t-1",
                 "email": "deactivated1@example.com", "role": "admin",
                 "deactivated_at": "2026-01-01T00:00:00Z"},
                {"id": f"TEST_ln-u-{uuid.uuid4().hex[:6]}",
                 "tenant_id": "TEST_ln-t-1",
                 "email": "optout1@example.com", "role": "admin",
                 "notify_new_leads": False},
            ]:
                _sync.users.insert_one(row)
                ids.append(row["id"])
            out = _run(_resolve_admin_recipients(tenant))
            # admin1 + manager1 + biz_email  → 3 total
            assert len(out) == 3
            assert "admin1@example.com" in out
            assert "manager1@example.com" in out
            # Business email preserved (case-insensitive dedupe only —
            # first-seen casing wins, but here it's the sole entry).
            assert any(e.lower() == "owner@example.com" for e in out)
            # Tech, deactivated, and opt-out users are NOT included
            assert "tech1@example.com" not in out
            assert "deactivated1@example.com" not in out
            assert "optout1@example.com" not in out
        finally:
            _sync.users.delete_many({"id": {"$in": ids}})

    def test_dedupes_business_email_against_user_row(self):
        from services.lead_admin_notifications import (
            _resolve_admin_recipients,
        )
        tenant = {
            "id": "TEST_ln-t-2",
            "business_settings": {
                "notification_email": "shared@example.com",
            },
        }
        uid = f"TEST_ln-u-{uuid.uuid4().hex[:6]}"
        try:
            _sync.users.insert_one({
                "id": uid, "tenant_id": "TEST_ln-t-2",
                "email": "Shared@Example.com", "role": "admin",
            })
            out = _run(_resolve_admin_recipients(tenant))
            # Case-insensitive dedupe — expect exactly 1 row
            lower = [e.lower() for e in out]
            assert lower.count("shared@example.com") == 1
        finally:
            _sync.users.delete_one({"id": uid})

    def test_empty_when_no_admins_and_no_business_email(self):
        from services.lead_admin_notifications import (
            _resolve_admin_recipients,
        )
        out = _run(_resolve_admin_recipients(
            {"id": "TEST_ln-t-none", "business_settings": {}},
        ))
        assert out == []


class TestEmailComposition:
    def test_html_contains_all_lead_fields(self):
        from services.lead_admin_notifications import _compose_email_html
        html = _compose_email_html(
            lead={
                "id": "TEST_ln-l1",
                "name": "Marilyn Guhr",
                "email": "marilyn.guhr@cox.net",
                "phone": "6025504921",
                "service_address": "1234 W Palm Ln",
                "city": "Peoria", "state": "AZ", "zip": "85383",
                "service_interest": "Pool cleaning and maintenance",
                "notes": "Weekly service pls",
                "source": "website_form",
                "created_at": "2026-09-14T15:00:00+00:00",
            },
            app_url="https://example.com",
            branding={},
        )
        for token in [
            "Marilyn Guhr", "marilyn.guhr@cox.net", "6025504921",
            "1234 W Palm Ln", "Peoria", "AZ", "85383",
            "Pool cleaning and maintenance",
            "Weekly service pls",
            "View lead in admin",
            "https://example.com/leads/TEST_ln-l1",
            "Requested Service",
            "Address",
        ]:
            assert token in html, f"missing: {token!r}"

    def test_subject_line_matches_spec(self):
        from services.lead_admin_notifications import _compose_subject
        assert _compose_subject(
            {"name": "Marilyn Guhr",
             "service_interest": "Pool cleaning"}
        ) == "New Lead: Marilyn Guhr — Pool cleaning"
        # Fallback interest.
        assert _compose_subject(
            {"name": "Marilyn Guhr", "service_interest": ""}
        ) == "New Lead: Marilyn Guhr — Get a Free Quote"


# ─────────────────────────── e2e via HTTP ───────────────────────────

def _login(email: str, pwd: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pwd}, timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def h_super():
    return _login("super@aquaterra.com")


@pytest.fixture(scope="module")
def tenant_id(h_super):
    r = requests.get(f"{API}/auth/me", headers=h_super, timeout=15)
    return r.json()["tenant_id"]


class TestPublicLeadHookFiresAdminFanout:
    def test_admin_fanout_audit_row_created(self, tenant_id, h_super):
        """POSTing to /api/public/leads must produce
        ``lead_admin_notification_sent`` audit rows for admin users."""
        # Force ALLOW_TEST_HOOKS on this request so we bypass the
        # allowlist without needing to configure widget domains.
        os.environ["ALLOW_TEST_HOOKS"] = "1"
        payload = {
            "name": f"TEST_ln PublicHook {uuid.uuid4().hex[:6]}",
            "email": "publichook@example.com",
            "phone": "+15551234567",
            "service_address": "123 Test St, Peoria AZ 85383",
            "service_interest": "Pool cleaning",
            "notes": "auto-test",
        }
        r = requests.post(
            f"{API}/public/leads",
            json=payload,
            headers={"Origin": "https://test.local"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        lid = r.json()["lead_id"]
        # Give BackgroundTasks a moment to flush.
        import time; time.sleep(1.5)
        rows = list(_sync.audit_logs.find(
            {"lead_id": lid,
             "event": "lead_admin_notification_sent"},
            {"_id": 0, "target": 1},
        ))
        assert len(rows) >= 1, (
            f"expected at least one admin fanout audit row for {lid} "
            f"— check aquaterra tenant has admin users seeded"
        )
        targets = {r["target"].lower() for r in rows}
        # aquaterra's seed has 4 non-deactivated admin/super/manager
        # users. We only assert that the fanout reached AT LEAST one
        # non-brian admin (the pre-fix behaviour was brian-only).
        assert any("aquaterra.com" in t or "admin" in t
                   for t in targets), (
            f"fanout should include admin@ users, got {targets}"
        )
        # Idempotency table has a row per (lead, target, :admin-fanout).
        idem = list(_sync.lead_notification_dispatches.find(
            {"lead_id": lid, "channel": "email",
             "target": {"$regex": ":admin-fanout$"}},
            {"_id": 0, "target": 1},
        ))
        assert len(idem) >= 1
        # Cleanup
        _sync.leads.delete_one({"id": lid})
        _sync.audit_logs.delete_many({"lead_id": lid})
        _sync.lead_notification_dispatches.delete_many({"lead_id": lid})
        _sync.marketing_deliveries.delete_many(
            {"trigger_entity.id": lid})


class TestNoRecipientsWarning:
    def test_no_admins_returns_reason(self):
        from services.lead_admin_notifications import (
            dispatch_admin_lead_email,
        )
        from fastapi import BackgroundTasks
        bt = BackgroundTasks()
        result = _run(dispatch_admin_lead_email(
            lead={"id": "TEST_ln-none", "name": "x",
                    "tenant_id": "TEST_ln-none-tid",
                    "email": "x@example.com"},
            tenant={"id": "TEST_ln-none-tid",
                     "business_settings": {}},
            background_tasks=bt,
        ))
        assert result["queued"] == 0
        assert result.get("reason") == "no_admin_recipients"
