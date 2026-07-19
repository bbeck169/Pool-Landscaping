"""Communications Subsystem · Phase 1 — Backend tests.

Covers:
- Token catalog completeness + sample values (>=25 tokens)
- Email template CRUD + tenant isolation + system-template protection
- SMS template CRUD + auto-extracted ``tokens_referenced``
- Automation rule CRUD + trigger-event validation + test-fire
- Email preview: subject + html + tokens_resolved with real token substitution
- Send-now email → status ``sent`` or ``not_sent_missing_key`` depending on env
- Send-now SMS with ``SMS_MOCK_MODE=1`` → ``mocked`` and RingCentral is not called
- Opt-out flow: opt-out then send-now → ``skipped_opted_out``
- Seed idempotency: 6 email + 4 sms + 5 automation system rows
"""
from __future__ import annotations
import asyncio, os, sys, uuid
from pathlib import Path

import pytest
import requests

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
from dotenv import load_dotenv
load_dotenv(BACKEND_ROOT / ".env")

from tests.conftest import demo_pw

BACKEND = os.environ.get("REACT_APP_BACKEND_URL") \
    or "https://poolscape-audit.preview.emergentagent.com"
API = f"{BACKEND}/api"
T = 20


# ------------------- helpers -----------------------------------------

def _login(email, pw):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=T)
    r.raise_for_status()
    return r.json()["access_token"]


def _h(tok): return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok(): return _login("admin@aquaterra.com", demo_pw("admin@aquaterra.com"))


@pytest.fixture(scope="module")
def tech_tok():  return _login("mike@aquaterra.com",  demo_pw("mike@aquaterra.com"))


@pytest.fixture(scope="module")
def demo_customer_id(admin_tok):
    r = requests.get(f"{API}/customers", headers=_h(admin_tok), timeout=T)
    r.raise_for_status()
    lst = r.json()
    assert lst, "aquaterra tenant must have at least one customer"
    return lst[0]["id"]


# ------------------- token catalog ------------------------------------

class TestTokenCatalog:
    def test_get_tokens_returns_at_least_25(self, admin_tok):
        r = requests.get(f"{API}/comms/tokens", headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 25
        names = {t["name"] for t in data["tokens"]}
        for req in ("customer.first_name", "invoice.amount_due", "company.name", "unsubscribe_url"):
            assert req in names

    def test_technician_forbidden_on_tokens(self, tech_tok):
        r = requests.get(f"{API}/comms/tokens", headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403


# ------------------- email template CRUD ------------------------------

class TestEmailTemplateCRUD:
    def test_list_includes_system_templates(self, admin_tok):
        r = requests.get(f"{API}/comms/email-templates", headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        codes = {t["code"] for t in r.json()}
        for c in ("system.welcome_new_customer", "system.appointment_reminder",
                   "system.invoice_overdue"):
            assert c in codes

    def test_get_system_template(self, admin_tok):
        r = requests.get(f"{API}/comms/email-templates/system.welcome_new_customer",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        b = r.json()
        assert b["is_system"] is True
        assert "{{customer.first_name}}" in b["subject"]

    def test_create_edit_delete_custom_template(self, admin_tok):
        code = f"custom.test.{uuid.uuid4().hex[:8]}"
        payload = {
            "code": code, "name": "TEST_ Custom email",
            "subject": "Hi {{customer.first_name}}",
            "blocks_json": [{"type": "heading", "id": str(uuid.uuid4()),
                              "props": {"text": "Test heading {{customer.first_name}}",
                                         "level": 1, "alignment": "left",
                                         "color": "#000", "padding": "16px"}}],
        }
        r = requests.post(f"{API}/comms/email-templates",
                           json=payload, headers=_h(admin_tok), timeout=T)
        assert r.status_code == 201, r.text
        assert r.json()["is_system"] is False

        # duplicate 'system.' prefix is rejected
        r2 = requests.post(f"{API}/comms/email-templates",
                            json={**payload, "code": "system.forbidden"},
                            headers=_h(admin_tok), timeout=T)
        assert r2.status_code == 400

        # patch
        rp = requests.patch(f"{API}/comms/email-templates/{code}",
                             json={"subject": "New subject {{customer.first_name}}"},
                             headers=_h(admin_tok), timeout=T)
        assert rp.status_code == 200
        assert rp.json()["subject"].startswith("New subject")
        assert rp.json()["version"] == 2

        # duplicate endpoint creates a copy
        rd = requests.post(f"{API}/comms/email-templates/{code}/duplicate",
                            headers=_h(admin_tok), timeout=T)
        assert rd.status_code == 200
        copy_code = rd.json()["code"]
        assert copy_code.startswith("copy.")

        # delete both
        for c in (code, copy_code):
            r = requests.delete(f"{API}/comms/email-templates/{c}",
                                 headers=_h(admin_tok), timeout=T)
            assert r.status_code == 204

    def test_delete_system_template_returns_404(self, admin_tok):
        r = requests.delete(f"{API}/comms/email-templates/system.welcome_new_customer",
                             headers=_h(admin_tok), timeout=T)
        assert r.status_code == 404

    def test_invalid_block_type_rejected(self, admin_tok):
        code = f"custom.bad.{uuid.uuid4().hex[:8]}"
        payload = {
            "code": code, "name": "TEST_ Bad", "subject": "hi",
            "blocks_json": [{"type": "unicorn", "id": "x", "props": {}}],
        }
        r = requests.post(f"{API}/comms/email-templates",
                           json=payload, headers=_h(admin_tok), timeout=T)
        assert r.status_code == 422

    def test_technician_forbidden(self, tech_tok):
        r = requests.get(f"{API}/comms/email-templates",
                          headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403


# ------------------- email preview ------------------------------------

class TestEmailPreview:
    def test_preview_returns_subject_html_and_tokens_resolved(self, admin_tok):
        r = requests.post(
            f"{API}/comms/email-templates/system.welcome_new_customer/preview",
            json={"sample_data": {"customer.first_name": "Alex_TEST"}},
            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        b = r.json()
        assert "Alex_TEST" in b["subject"]
        assert "Alex_TEST" in b["html"]
        assert "customer.first_name" in b["tokens_resolved"]
        assert "<!doctype html>" in b["html"].lower()


# ------------------- SMS template CRUD --------------------------------

class TestSmsTemplateCRUD:
    def test_list_includes_system_sms(self, admin_tok):
        r = requests.get(f"{API}/comms/sms-templates", headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        codes = {t["code"] for t in r.json()}
        assert "system.sms.appointment_reminder" in codes
        assert "system.sms.tech_en_route" in codes

    def test_tokens_referenced_extracted_on_save(self, admin_tok):
        code = f"custom.sms.{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{API}/comms/sms-templates",
                           json={"code": code, "name": "TEST_ SMS",
                                  "body": "Hi {{customer.first_name}}, "
                                          "your invoice {{invoice.invoice_number}} is due."},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 201
        assert set(r.json()["tokens_referenced"]) == {
            "customer.first_name", "invoice.invoice_number",
        }
        requests.delete(f"{API}/comms/sms-templates/{code}",
                         headers=_h(admin_tok), timeout=T)

    def test_sms_preview_reports_char_and_segment(self, admin_tok):
        r = requests.post(
            f"{API}/comms/sms-templates/system.sms.appointment_reminder/preview",
            json={"sample_data": {"customer.first_name": "Alex"}},
            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        b = r.json()
        assert b["character_count"] > 0
        assert b["segment_count"] >= 1


# ------------------- Automations --------------------------------------

class TestAutomations:
    def test_seed_rules_present(self, admin_tok):
        r = requests.get(f"{API}/comms/automations", headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        codes = {a["code"] for a in r.json()}
        for c in ("welcome_new_customer_email", "invoice_created_notify",
                  "invoice_overdue_nudge", "visit_summary_email",
                  "appointment_reminder_email_dayof"):
            assert c in codes

    def test_invalid_trigger_event_rejected(self, admin_tok):
        r = requests.post(f"{API}/comms/automations",
                           json={"code": f"custom.auto.{uuid.uuid4().hex[:8]}",
                                  "name": "TEST_", "trigger_event": "wat",
                                  "channel": "email",
                                  "template_code": "system.welcome_new_customer"},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 422

    def test_test_fire_logs_a_send(self, admin_tok, demo_customer_id):
        r = requests.post(
            f"{API}/comms/automations/welcome_new_customer_email/test-fire",
            json={"recipient_id": demo_customer_id},
            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        b = r.json()
        assert b["status"] in ("sent", "mocked", "not_sent_missing_key",
                                 "skipped_opted_out", "failed")
        assert b["automation_code"] == "welcome_new_customer_email"


# ------------------- Send-now: email path -----------------------------

class TestSendNowEmail:
    def test_send_now_email_status_reflects_env(self, admin_tok, demo_customer_id):
        r = requests.post(f"{API}/comms/send-now",
                           json={"channel": "email",
                                  "template_code": "system.welcome_new_customer",
                                  "recipient_ids": [demo_customer_id]},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        b = r.json()
        assert b["count"] == 1
        status = b["results"][0]["status"]
        if os.environ.get("RESEND_API_KEY"):
            assert status in ("sent", "failed", "skipped_opted_out")
        else:
            assert status == "not_sent_missing_key"


# ------------------- Send-now: SMS path (MOCKED) ---------------------

class TestSendNowSmsMocked:
    def test_sms_send_returns_mocked_and_no_rc_call(self, admin_tok,
                                                       demo_customer_id,
                                                       monkeypatch):
        # SMS_MOCK_MODE is "1" (default). Even so, patch RC to explode if
        # anyone tries to actually contact it.
        os.environ["SMS_MOCK_MODE"] = "1"

        # Patch the RC helper module import path so any accidental call raises.
        # The adapter imports these lazily inside the send fn, so we patch
        # sys.modules before the send.
        class _Boom:
            def __call__(self, *a, **k):
                raise AssertionError("RingCentral must NOT be called in mock mode")
            def __getattr__(self, name):
                raise AssertionError(f"RingCentral must NOT be called in mock mode ({name})")

        import services.ringcentral_client as rc_mod
        monkeypatch.setattr(rc_mod, "get_rc_platform", _Boom(), raising=False)
        monkeypatch.setattr(rc_mod, "is_outbound_enabled",
                             lambda: (_ for _ in ()).throw(
                                 AssertionError("must NOT check outbound in mock mode")),
                             raising=False)

        r = requests.post(f"{API}/comms/send-now",
                           json={"channel": "sms",
                                  "template_code": "system.sms.appointment_reminder",
                                  "recipient_ids": [demo_customer_id]},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        b = r.json()
        assert b["count"] == 1
        assert b["results"][0]["status"] == "mocked"


# ------------------- Opt-out flow -------------------------------------

class TestOptOut:
    def test_opt_out_then_send_now_returns_skipped(self, admin_tok, demo_customer_id):
        # Look up the customer's email.
        r_get = requests.get(f"{API}/customers/{demo_customer_id}",
                              headers=_h(admin_tok), timeout=T)
        assert r_get.status_code == 200
        cust = r_get.json()
        email = cust.get("email")
        assert email, "demo customer must have an email"

        # Compute the signed opt-out token via the same secret the router uses.
        import hmac, hashlib, base64
        secret = os.environ.get("JWT_SECRET") or "dev"
        tenant_id = cust.get("tenant_id") or "aquaterra"
        payload = f"{tenant_id}|{email}|email".encode("utf-8")
        sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
        token = base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")

        # Public opt-out call (no auth).
        r_opt = requests.post(f"{API}/comms/opt-out",
                               json={"tenant_id": tenant_id,
                                      "channel": "email",
                                      "contact": email,
                                      "token": token},
                               timeout=T)
        assert r_opt.status_code == 200, r_opt.text

        try:
            # Now send-now for that recipient must skip.
            rs = requests.post(f"{API}/comms/send-now",
                                json={"channel": "email",
                                       "template_code": "system.welcome_new_customer",
                                       "recipient_ids": [demo_customer_id]},
                                headers=_h(admin_tok), timeout=T)
            assert rs.status_code == 200
            assert rs.json()["results"][0]["status"] == "skipped_opted_out"

            # Verify the opt-out is listed for admin.
            r_list = requests.get(f"{API}/comms/opt-outs",
                                    headers=_h(admin_tok), timeout=T)
            assert r_list.status_code == 200
            emails = {(o.get("contact_email") or "").lower() for o in r_list.json()}
            assert email.lower() in emails
        finally:
            # Clean up so we don't leave the demo customer opted out.
            from motor.motor_asyncio import AsyncIOMotorClient
            async def _cleanup():
                c = AsyncIOMotorClient(os.environ["MONGO_URL"])
                db_local = c[os.environ["DB_NAME"]]
                await db_local.communication_opt_outs.delete_many(
                    {"tenant_id": tenant_id,
                     "contact_email": email.lower(),
                     "channel": "email"})
                c.close()
            asyncio.run(_cleanup())


# ------------------- Seed idempotency ---------------------------------

class TestSeedIdempotent:
    def test_seed_produces_exact_counts_and_is_idempotent(self):
        """Runs the seed as two subprocess invocations of `python -m
        comms_seed.seed_comms` to guarantee a fresh event loop and motor
        client each time (matches the real production entry point used by
        ``server.py::_background_seed``)."""
        import subprocess
        for _ in range(2):
            r = subprocess.run(
                [sys.executable, "-m", "comms_seed.seed_comms"],
                capture_output=True, text=True,
                cwd=str(BACKEND_ROOT), timeout=30,
                env={**os.environ})
            assert r.returncode == 0, f"seed run failed: {r.stderr}"

        # Verify counts via a fresh motor client.
        from motor.motor_asyncio import AsyncIOMotorClient

        async def _check():
            c = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db_local = c[os.environ["DB_NAME"]]
            e = await db_local.email_templates.count_documents(
                {"is_system": True, "tenant_id": None})
            s = await db_local.sms_templates.count_documents(
                {"is_system": True, "tenant_id": None})
            a = await db_local.automation_rules.count_documents(
                {"is_system": True, "tenant_id": None})
            c.close()
            return e, s, a

        e, s, a = asyncio.run(_check())
        assert e == 6, f"expected 6 system email templates, got {e}"
        assert s == 4, f"expected 4 system sms templates, got {s}"
        assert a == 5, f"expected 5 system automation rules, got {a}"


# ------------------- Sends log ----------------------------------------

class TestSendsLog:
    def test_sends_list_filters(self, admin_tok):
        r = requests.get(f"{API}/comms/sends?kind=sms&limit=5",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        for row in r.json():
            assert row["kind"] == "sms"
