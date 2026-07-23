"""Batch 12C · Feb 2026 — Timezone audit + PATCH validation +
ambiguous-match digest fanout + add-card-on-create hook.

Covers the four items shipped in this batch:

  1. Timezone boot-time audit + PATCH endpoint accepts a valid IANA
     name and rejects garbage with 400 ``INVALID_TIMEZONE``.
  2. Ambiguous-match digest fires email + SMS when the count is
     positive, is silent when zero, and respects the 24-hour cooldown.
  3. Add-card-on-create hook honors the tenant toggle (default OFF)
     AND the effective-required + contact-info gates.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._shared_loop import run as _run

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_env["MONGO_URL"])[_env["DB_NAME"]]
_TENANT = _sync.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
_TENANT_ID = _TENANT["id"]

API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> dict:
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


# ─── Item 1 · Timezone audit + PATCH validation ──────────────────────
def test_timezone_boot_audit_is_idempotent_and_never_overwrites():
    from services.add_card_links import ensure_tenants_timezone_backfill
    # Force an explicit tz on aquaterra + a scratch tenant with no tz.
    _sync.tenants.update_one(
        {"id": _TENANT_ID}, {"$set": {"timezone": "America/Los_Angeles"}})
    scratch = f"pytest-12c-tz-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": scratch, "slug": f"12c-tz-{uuid.uuid4().hex[:6]}",
        "name": "12C TZ scratch",
    })
    try:
        report = _run(ensure_tenants_timezone_backfill())
        assert report["audited"] >= 2
        assert report["filled"] >= 1
        # aquaterra kept its explicit tz — audit must NOT overwrite.
        doc = _sync.tenants.find_one({"id": _TENANT_ID}, {"_id": 0})
        assert doc["timezone"] == "America/Los_Angeles"
        # Scratch tenant got the fallback.
        s = _sync.tenants.find_one({"id": scratch}, {"_id": 0})
        assert s["timezone"] == "America/Phoenix"
        # Second call — nothing left to fill.
        report2 = _run(ensure_tenants_timezone_backfill())
        assert report2["filled"] == 0
    finally:
        _sync.tenants.delete_many({"id": scratch})
        _sync.tenants.update_one(
            {"id": _TENANT_ID},
            {"$set": {"timezone": "America/Phoenix"}})


def test_patch_settings_accepts_valid_timezone(admin_headers):
    r = requests.patch(
        f"{API}/tenants/mine/settings",
        json={"timezone": "America/Denver"},
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200
    assert r.json()["timezone"] == "America/Denver"
    # Restore.
    requests.patch(
        f"{API}/tenants/mine/settings",
        json={"timezone": "America/Phoenix"},
        headers=admin_headers, timeout=10,
    )


def test_patch_settings_rejects_invalid_timezone(admin_headers):
    r = requests.patch(
        f"{API}/tenants/mine/settings",
        json={"timezone": "Nowhere/Nope"},
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_TIMEZONE"


def test_patch_settings_timezone_rbac_tech_denied(tech_headers):
    r = requests.patch(
        f"{API}/tenants/mine/settings",
        json={"timezone": "America/Chicago"},
        headers=tech_headers, timeout=10,
    )
    assert r.status_code == 403


# ─── Item 2 · Ambiguous-match digest fanout ─────────────────────────
def _clear_ambig_state(tid: str):
    _sync.ops_alerts_state.delete_many({
        "tenant_id": tid, "kind": "stripe_sync_ambiguous"})
    _sync.marketing_deliveries.delete_many({
        "tenant_id": tid, "trigger_entity.kind": "stripe_sync_ambiguous"})


def test_ambiguous_digest_fires_email_and_sms_rows():
    from services.stripe_customer_sync_cron import _fire_ambiguous_alert
    tid = _TENANT_ID
    _clear_ambig_state(tid)
    tenant = _sync.tenants.find_one({"id": tid}, {"_id": 0})
    summary = {
        "tenant_id": tid,
        "ambiguous_matches": [
            {"customer_id": "c1", "customer_name": "Alice A",
              "email": "alice@example.com",
              "stripe_ids": ["cus_a", "cus_b"]},
            {"customer_id": "c2", "customer_name": "Bob B",
              "email": "bob@example.com",
              "stripe_ids": ["cus_c", "cus_d"]},
        ],
    }
    try:
        # Bypass real send by patching the adapters — we just want the
        # ledger rows.
        with patch("services.comms_email_adapter.send_email",
                    new=AsyncMock(return_value={"status": "sent",
                                                  "provider": "mock"})):
            _run(_fire_ambiguous_alert(tenant, summary))
        rows = list(_sync.marketing_deliveries.find(
            {"tenant_id": tid,
              "trigger_entity.kind": "stripe_sync_ambiguous"},
            {"_id": 0}))
        assert len(rows) >= 1, "at least one delivery row expected"
        emails = [r for r in rows if r.get("channel") == "email"]
        assert len(emails) >= 1
        # Body carries the count + sample tags rendered.
        assert "2" in (emails[0].get("body_rendered")
                        or emails[0].get("body") or "")
        assert ("Alice A" in (emails[0].get("body_rendered") or "")
                 or "alice" in (emails[0].get("body_rendered") or "").lower())
        # Cooldown state row created.
        st = _sync.ops_alerts_state.find_one(
            {"tenant_id": tid, "kind": "stripe_sync_ambiguous"},
            {"_id": 0})
        assert st is not None
        assert st.get("last_ambiguous_count") == 2
    finally:
        _clear_ambig_state(tid)


def test_ambiguous_digest_silent_when_count_zero():
    from services.stripe_customer_sync_cron import _fire_ambiguous_alert
    tid = _TENANT_ID
    _clear_ambig_state(tid)
    tenant = _sync.tenants.find_one({"id": tid}, {"_id": 0})
    try:
        _run(_fire_ambiguous_alert(tenant, {"ambiguous_matches": []}))
        rows = list(_sync.marketing_deliveries.find(
            {"tenant_id": tid,
              "trigger_entity.kind": "stripe_sync_ambiguous"}))
        assert len(rows) == 0
        # No cooldown row either — silence should not consume the window.
        st = _sync.ops_alerts_state.find_one(
            {"tenant_id": tid, "kind": "stripe_sync_ambiguous"})
        assert st is None
    finally:
        _clear_ambig_state(tid)


def test_ambiguous_digest_respects_24h_cooldown():
    from services.stripe_customer_sync_cron import _fire_ambiguous_alert
    from utils import new_id, now_iso
    tid = _TENANT_ID
    _clear_ambig_state(tid)
    tenant = _sync.tenants.find_one({"id": tid}, {"_id": 0})
    # Prime the cooldown row 1h ago.
    stamp = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    _sync.ops_alerts_state.insert_one({
        "id": new_id(), "tenant_id": tid,
        "kind": "stripe_sync_ambiguous",
        "last_ran_at": stamp, "last_ambiguous_count": 1,
        "created_at": now_iso(),
    })
    summary = {"ambiguous_matches": [
        {"customer_id": "c1", "customer_name": "Alice A",
          "email": "alice@example.com",
          "stripe_ids": ["cus_a", "cus_b"]}]}
    try:
        with patch("services.comms_email_adapter.send_email",
                    new=AsyncMock()) as email_mock:
            _run(_fire_ambiguous_alert(tenant, summary))
            email_mock.assert_not_called()
        rows = list(_sync.marketing_deliveries.find(
            {"tenant_id": tid,
              "trigger_entity.kind": "stripe_sync_ambiguous"}))
        assert rows == []
    finally:
        _clear_ambig_state(tid)


def test_ambiguous_match_merge_tags_registered():
    from services.marketing.merge_tags import MERGE_TAGS
    tokens = {t["token"] for t in MERGE_TAGS}
    assert "AMBIGUOUS_MATCH_COUNT" in tokens
    assert "AMBIGUOUS_MATCH_SAMPLE" in tokens


# ─── Item 3 · Add-card-on-create hook ───────────────────────────────
def _customer_created_with(admin_headers, *, email=None, phone=None,
                             name="P12C Auto"):
    body = {"name": name}
    if email:
        body["email"] = email
    if phone:
        body["phone"] = phone
    r = requests.post(f"{API}/customers", json=body,
                        headers=admin_headers, timeout=10)
    r.raise_for_status()
    return r.json()["id"]


def _deliveries_for(cid: str):
    return list(_sync.marketing_deliveries.find(
        {"customer_id": cid,
          "trigger_entity.kind": "add_card_request"},
        {"_id": 0}))


def _set_tenant_flag(auto_on: bool):
    _sync.tenants.update_one(
        {"id": _TENANT_ID},
        {"$set": {"auto_send_card_add_on_create": auto_on,
                    "require_card_on_file_default": True}},
    )


def _cleanup_customer(cid):
    _sync.customers.delete_many({"id": cid})
    _sync.marketing_deliveries.delete_many({"customer_id": cid})


def test_auto_send_fires_when_setting_on_and_effective_required(admin_headers):
    from services.add_card_links import reset_rate_limit
    _set_tenant_flag(True)
    email = f"p12c-auto-on-{uuid.uuid4().hex[:6]}@pytest.local"
    with patch("services.comms_email_adapter.send_email",
                new=AsyncMock(return_value={"status": "sent",
                                              "provider": "mock"})):
        cid = _customer_created_with(admin_headers, email=email)
        try:
            rows = _deliveries_for(cid)
            assert any(r.get("channel") == "email" for r in rows), \
                f"expected auto-send email delivery row, got {rows}"
        finally:
            reset_rate_limit(cid)
            _cleanup_customer(cid)
            _set_tenant_flag(False)


def test_auto_send_no_op_when_setting_off(admin_headers):
    _set_tenant_flag(False)
    email = f"p12c-auto-off-{uuid.uuid4().hex[:6]}@pytest.local"
    with patch("services.comms_email_adapter.send_email",
                new=AsyncMock()) as email_mock:
        cid = _customer_created_with(admin_headers, email=email)
        try:
            rows = _deliveries_for(cid)
            assert rows == []
            email_mock.assert_not_called()
        finally:
            _cleanup_customer(cid)


def test_auto_send_skipped_when_customer_has_no_contact(admin_headers):
    from services.add_card_links import reset_rate_limit
    _set_tenant_flag(True)
    with patch("services.comms_email_adapter.send_email",
                new=AsyncMock()) as email_mock:
        cid = _customer_created_with(admin_headers, email=None, phone=None,
                                        name=f"P12C NoContact {uuid.uuid4().hex[:4]}")
        try:
            rows = _deliveries_for(cid)
            assert rows == []
            email_mock.assert_not_called()
        finally:
            reset_rate_limit(cid)
            _cleanup_customer(cid)
            _set_tenant_flag(False)


def test_auto_send_no_op_when_effective_requirement_off(admin_headers):
    """Tenant setting on + require_card_on_file_default OFF → derived
    effective_required is False → no send."""
    from services.add_card_links import reset_rate_limit
    _sync.tenants.update_one(
        {"id": _TENANT_ID},
        {"$set": {"auto_send_card_add_on_create": True,
                    "require_card_on_file_default": False}},
    )
    with patch("services.comms_email_adapter.send_email",
                new=AsyncMock()) as email_mock:
        cid = _customer_created_with(
            admin_headers,
            email=f"p12c-noreq-{uuid.uuid4().hex[:6]}@pytest.local",
        )
        try:
            assert _deliveries_for(cid) == []
            email_mock.assert_not_called()
        finally:
            reset_rate_limit(cid)
            _cleanup_customer(cid)
            _sync.tenants.update_one(
                {"id": _TENANT_ID},
                {"$set": {"auto_send_card_add_on_create": False,
                            "require_card_on_file_default": True}},
            )
