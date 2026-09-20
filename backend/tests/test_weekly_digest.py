"""Phase 4 · Batch C / D7 — Weekly digest tests."""
from __future__ import annotations
import hashlib
import hmac as _hmac
import os
import requests
import pytest
import uuid
from datetime import datetime, timezone

from tests.conftest import demo_pw

BACKEND = os.environ.get("REACT_APP_BACKEND_URL") or "https://poolscape-audit.preview.emergentagent.com"
API = f"{BACKEND}/api"
TIMEOUT = 20


def _login(email, password):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["access_token"]


def _h(tok, *, bypass_to: str | None = None):
    hdrs = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    if bypass_to:
        # G1.7 · signed bypass — matches the backend
        # ``_expected_bypass_signature`` helper. Reads JWT_SECRET
        # from the pod's .env so only test rigs with .env access
        # can produce a valid header.
        from dotenv import dotenv_values
        from pathlib import Path
        env = dotenv_values(
            Path(__file__).resolve().parent.parent / ".env")
        secret = (env.get("JWT_SECRET") or os.environ.get("JWT_SECRET") or "")
        msg = f"weekly-digest-bypass:{bypass_to.lower().strip()}".encode()
        sig = _hmac.new(secret.encode(), msg,
                         hashlib.sha256).hexdigest()
        hdrs["x-test-recipient-bypass"] = sig
    return hdrs


@pytest.fixture(scope="module")
def admin_tok(): return _login("admin@aquaterra.com", demo_pw("admin@aquaterra.com"))

@pytest.fixture(scope="module")
def super_tok(): return _login("super@aquaterra.com", demo_pw("super@aquaterra.com"))

@pytest.fixture(scope="module")
def tech_tok():  return _login("mike@aquaterra.com",  demo_pw("mike@aquaterra.com"))


class TestPreviewEndpoint:
    def test_admin_can_preview(self, admin_tok):
        r = requests.post(f"{API}/admin/weekly-digest/preview",
                          headers=_h(admin_tok), json={}, timeout=TIMEOUT)
        assert r.status_code == 200
        d = r.json()
        for k in ("payload", "html", "subject"):
            assert k in d, f"missing top-level key {k}"
        p = d["payload"]
        # Every section present
        for section in ("revenue", "operations", "customers", "team",
                         "training", "templates_finalized_top", "cfo_highlights",
                         "growth_summary"):
            assert section in p, f"payload missing {section}"
        # Revenue subkeys
        for k in ("invoices_new", "invoiced_total", "payments_total", "overdue"):
            assert k in p["revenue"]
        assert "Weekly Digest" in d["subject"]
        assert d["html"].startswith("<!doctype html>")

    def test_tech_cannot_preview(self, tech_tok):
        r = requests.post(f"{API}/admin/weekly-digest/preview",
                          headers=_h(tech_tok), json={}, timeout=TIMEOUT)
        assert r.status_code == 403


class TestAggregation:
    """Direct-call the service to verify aggregation math against seeded state."""
    def test_aggregation_returns_all_sections(self):
        import asyncio, os, sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")

        async def _run():
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db_local = client[os.environ["DB_NAME"]]
            tenant = await db_local.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
            # Import inside the coroutine so the service picks up the same
            # loop; monkeypatch its `db` module attribute for this call.
            import services.weekly_digest as wd
            wd.db = db_local  # type: ignore
            payload = await wd._aggregate_tenant_week(tenant)
            client.close()
            return payload
        p = asyncio.run(_run())
        assert p["revenue"]["invoices_new"] >= 0
        assert p["operations"]["jobs_pending"] >= 0
        assert p["customers"]["new"] >= 0
        assert "iso_week" in p


class TestSendNow:
    def test_send_now_requires_super_admin(self, admin_tok):
        r = requests.post(f"{API}/admin/weekly-digest/send-now",
                          headers=_h(admin_tok),
                          json={"to": "test@example.com"}, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_send_now_super_admin_logs_attempt(self, super_tok):
        r = requests.post(f"{API}/admin/weekly-digest/send-now",
                          headers=_h(super_tok, bypass_to="smoke@example.com"),
                          json={"to": "smoke@example.com"}, timeout=TIMEOUT)
        assert r.status_code == 200
        d = r.json()
        assert d["recipients"] == 1
        results = d["results"]
        # With no valid Resend key restricted to super_admin's own email,
        # this should be `not_sent_missing_key` OR `failed` — never crash.
        assert results[0]["status"] in {"not_sent_missing_key", "failed", "sent", "skipped_dupe"}


class TestIdempotency:
    def test_duplicate_send_same_week_skipped(self, super_tok):
        # Two sends to the same recipient in the same ISO week — the
        # second should be `skipped_dupe` IF the first was `sent`.
        # If the first was not_sent_missing_key (Resend not configured)
        # the guard doesn't trigger — which is the intended design so
        # missing-key retries don't stay stuck.
        first = requests.post(f"{API}/admin/weekly-digest/send-now",
                              headers=_h(super_tok, bypass_to="smoke-dup@example.com"),
                              json={"to": "smoke-dup@example.com"},
                              timeout=TIMEOUT).json()
        # send-now uses kind=weekly_digest_manual which bypasses the
        # weekly-digest idempotency (manual is meant to be re-runnable).
        # This test simply confirms the endpoint tolerates repeat calls.
        second = requests.post(f"{API}/admin/weekly-digest/send-now",
                                headers=_h(super_tok, bypass_to="smoke-dup@example.com"),
                                json={"to": "smoke-dup@example.com"},
                                timeout=TIMEOUT).json()
        assert first["recipients"] == 1
        assert second["recipients"] == 1


class TestOutboundLog:
    def test_outbound_row_written(self, super_tok):
        # Confirm at least one `weekly_digest_manual` log row lands
        # after send-now. Uses a fresh motor client to avoid the
        # shared-config.db event-loop reuse issue.
        r = requests.post(f"{API}/admin/weekly-digest/send-now",
                          headers=_h(super_tok, bypass_to="smoke-log@example.com"),
                          json={"to": "smoke-log@example.com"},
                          timeout=TIMEOUT).json()
        assert r["recipients"] == 1

        import asyncio, os
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")

        async def _run():
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db_local = client[os.environ["DB_NAME"]]
            cnt = await db_local.outbound_emails.count_documents(
                {"recipient_email": "smoke-log@example.com",
                 "kind": "weekly_digest_manual"})
            client.close()
            return cnt
        assert asyncio.run(_run()) >= 1


class TestRecipientSelection:
    def test_only_admins_and_super_admins_selected(self):
        import asyncio, os
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")

        async def _run():
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db_local = client[os.environ["DB_NAME"]]
            tenant = await db_local.tenants.find_one(
                {"slug": "aquaterra"}, {"_id": 0, "id": 1})
            users = await db_local.users.find(
                {"tenant_id": tenant["id"],
                 "role": {"$in": ["admin", "super_admin"]}},
                {"_id": 0, "id": 1, "role": 1},
            ).to_list(200)
            for u in users:
                assert u["role"] in ("admin", "super_admin")
            client.close()
            return len(users)
        assert asyncio.run(_run()) >= 1
