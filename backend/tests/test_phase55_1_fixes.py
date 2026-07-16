"""Phase 55.1 · Stripe RBAC + Notification leak + Unmatched RC + Webhook token
+ CFO Stripe cash weekly.

Focus: backend-only, pre-charge Stripe only (no confirmation).
"""
import os
import json
import time
import subprocess
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://poolscape-audit.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("admin@aquaterra.com", "password123")
TECH = ("mike@aquaterra.com", "password123")
CUST = ("customer@aquaterra.com", "password123")
SUPER = ("super@aquaterra.com", "password123")

CUST_OWNED_INV = "2275d525-0e28-49d8-be68-bdd5a69e25f9"  # customer_id=e36bce2c-...
OTHER_INV = "inv-01"                                       # customer_id=cust-vip-01
AQUATERRA_TID = "3814833a-dd0d-4bd9-90ea-351c24924649"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"], r.json().get("user", {})


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok():
    tok, _ = _login(*ADMIN)
    return tok


@pytest.fixture(scope="module")
def tech_tok():
    tok, _ = _login(*TECH)
    return tok


@pytest.fixture(scope="module")
def cust_tok_user():
    return _login(*CUST)


# ═══════════ 1. STRIPE RBAC ═══════════
class TestStripeRBAC:
    def test_admin_can_create_checkout_for_any_invoice(self, admin_tok):
        r = requests.post(f"{API}/stripe/checkout/session", headers=_h(admin_tok),
                          json={"invoice_id": CUST_OWNED_INV, "origin": "https://example.com"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        assert "session_id" in r.json() or r.json().get("mocked")

    def test_admin_can_create_payment_intent_for_any_invoice(self, admin_tok):
        r = requests.post(f"{API}/stripe/payment-intent", headers=_h(admin_tok),
                          json={"invoice_id": OTHER_INV}, timeout=30)
        assert r.status_code == 200, r.text[:300]

    def test_tech_403_on_checkout_session(self, tech_tok):
        r = requests.post(f"{API}/stripe/checkout/session", headers=_h(tech_tok),
                          json={"invoice_id": CUST_OWNED_INV, "origin": "https://example.com"}, timeout=30)
        assert r.status_code == 403

    def test_tech_403_on_payment_intent(self, tech_tok):
        r = requests.post(f"{API}/stripe/payment-intent", headers=_h(tech_tok),
                          json={"invoice_id": CUST_OWNED_INV}, timeout=30)
        assert r.status_code == 403

    def test_customer_can_pay_own_invoice(self, cust_tok_user):
        tok, _ = cust_tok_user
        r = requests.post(f"{API}/stripe/checkout/session", headers=_h(tok),
                          json={"invoice_id": CUST_OWNED_INV, "origin": "https://example.com"}, timeout=30)
        assert r.status_code == 200, r.text[:300]

    def test_customer_403_on_other_invoice(self, cust_tok_user):
        tok, _ = cust_tok_user
        r = requests.post(f"{API}/stripe/checkout/session", headers=_h(tok),
                          json={"invoice_id": OTHER_INV, "origin": "https://example.com"}, timeout=30)
        assert r.status_code == 403
        r2 = requests.post(f"{API}/stripe/payment-intent", headers=_h(tok),
                           json={"invoice_id": OTHER_INV}, timeout=30)
        assert r2.status_code == 403

    def test_tech_403_on_refunds_subscriptions_products(self, tech_tok):
        r1 = requests.post(f"{API}/stripe/refunds", headers=_h(tech_tok),
                           json={"payment_id": "px"}, timeout=30)
        assert r1.status_code == 403
        r2 = requests.post(f"{API}/stripe/subscriptions", headers=_h(tech_tok),
                           json={"customer_id": "x", "price_id": "y"}, timeout=30)
        assert r2.status_code == 403
        r3 = requests.post(f"{API}/stripe/products", headers=_h(tech_tok),
                           json={"name": "x", "unit_amount_cents": 500}, timeout=30)
        assert r3.status_code == 403

    def test_subscriptions_list_rbac(self, admin_tok, cust_tok_user):
        cust_tok, cust_user = cust_tok_user
        my_cid = cust_user.get("customer_id")
        # admin — allowed
        r = requests.get(f"{API}/stripe/subscriptions?customer_id=cust-vip-01",
                         headers=_h(admin_tok), timeout=30)
        assert r.status_code == 200
        # customer for own id — allowed
        r2 = requests.get(f"{API}/stripe/subscriptions?customer_id={my_cid}",
                          headers=_h(cust_tok), timeout=30)
        assert r2.status_code == 200
        # customer for someone else's — 403
        r3 = requests.get(f"{API}/stripe/subscriptions?customer_id=cust-vip-01",
                          headers=_h(cust_tok), timeout=30)
        assert r3.status_code == 403

    def test_checkout_status_rbac(self, admin_tok, tech_tok, cust_tok_user):
        # Create a session as customer to get a real session_id owned by them
        cust_tok, _ = cust_tok_user
        r = requests.post(f"{API}/stripe/checkout/session", headers=_h(cust_tok),
                          json={"invoice_id": CUST_OWNED_INV, "origin": "https://example.com"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        sid = r.json().get("session_id")
        if not sid:
            pytest.skip("stripe not configured — no session_id returned")
        # Tech → 403
        rt = requests.get(f"{API}/stripe/checkout/status/{sid}", headers=_h(tech_tok), timeout=30)
        assert rt.status_code == 403
        # Admin → 200
        ra = requests.get(f"{API}/stripe/checkout/status/{sid}", headers=_h(admin_tok), timeout=30)
        assert ra.status_code == 200
        # Customer owner → 200
        rc = requests.get(f"{API}/stripe/checkout/status/{sid}", headers=_h(cust_tok), timeout=30)
        assert rc.status_code == 200


# ═══════════ 2. NOTIFICATION AUDIENCE LEAK ═══════════
class TestNotificationLeak:
    def _seed_notif(self, user_id, audience, kind="system_alert", customer_id=None):
        nid = str(uuid.uuid4())
        cust_repr = repr(customer_id)  # 'None' or "'abc'"
        script = f'''
import asyncio, sys
sys.path.insert(0, "/app/backend")
from config import db
async def main():
    await db.notifications.insert_one({{
        "id": "{nid}",
        "tenant_id": "{AQUATERRA_TID}",
        "user_id": "{user_id}",
        "customer_id": {cust_repr},
        "kind": "{kind}",
        "label": "test",
        "title": "P55.1 audience test",
        "body": "leak test body",
        "href": None,
        "priority": "normal",
        "audience": "{audience}",
        "source_ref": {{}},
        "read": False,
        "created_at": "2026-06-01T00:00:00+00:00",
    }})
    print("OK")
asyncio.run(main())
'''
        out = subprocess.check_output(["python", "-c", script], cwd="/app/backend", timeout=30).decode()
        assert "OK" in out, out
        return nid

    def _delete_notif(self, nid):
        script = f'''
import asyncio, sys
sys.path.insert(0, "/app/backend")
from config import db
async def main():
    await db.notifications.delete_one({{"id": "{nid}"}})
asyncio.run(main())
'''
        subprocess.check_output(["python", "-c", script], cwd="/app/backend", timeout=30)

    def test_customer_does_not_see_internal_row(self, cust_tok_user):
        cust_tok, cust_user = cust_tok_user
        nid = self._seed_notif(cust_user["id"], "internal")
        try:
            r = requests.get(f"{API}/notifications?limit=500", headers=_h(cust_tok), timeout=30)
            assert r.status_code == 200
            ids = {row["id"] for row in r.json()}
            assert nid not in ids, "customer leaked internal notification!"
        finally:
            self._delete_notif(nid)

    def test_customer_sees_portal_row(self, cust_tok_user):
        cust_tok, cust_user = cust_tok_user
        nid = self._seed_notif(cust_user["id"], "portal", kind="customer_message")
        try:
            r = requests.get(f"{API}/notifications?limit=500", headers=_h(cust_tok), timeout=30)
            assert r.status_code == 200
            rows = r.json()
            match = next((x for x in rows if x["id"] == nid), None)
            assert match is not None, "customer did not see own portal row"
            assert match["kind"] == "customer_message"
            assert match["body"] == "leak test body"
        finally:
            self._delete_notif(nid)

    def test_admin_does_not_see_portal_customer_row(self, admin_tok, cust_tok_user):
        cust_tok, cust_user = cust_tok_user
        # portal row addressed to customer's user_id
        nid_portal = self._seed_notif(cust_user["id"], "portal")
        # internal row addressed to customer's user_id (should also NOT show up
        # in admin inbox because admin's user_id filter excludes it)
        try:
            r = requests.get(f"{API}/notifications?limit=500", headers=_h(admin_tok), timeout=30)
            assert r.status_code == 200
            ids = {row["id"] for row in r.json()}
            assert nid_portal not in ids
        finally:
            self._delete_notif(nid_portal)


# ═══════════ 3. UNMATCHED RC INBOUND ═══════════
class TestUnmatchedRC:
    def test_kinds_catalog_has_22(self, admin_tok):
        r = requests.get(f"{API}/notifications/kinds", headers=_h(admin_tok), timeout=30)
        assert r.status_code == 200
        kinds = r.json()["kinds"]
        assert len(kinds) == 22, f"expected 22 kinds, got {len(kinds)}"
        keys = {k["key"] for k in kinds}
        for k in ["rc_sms_inbound_unmatched", "rc_call_inbound_unmatched",
                  "rc_voicemail_unmatched", "rc_fax_unmatched"]:
            assert k in keys

    def test_unknown_sms_emits_unmatched(self, admin_tok):
        # Clear then simulate an unknown number
        requests.post(f"{API}/notifications/mark-all-read", headers=_h(admin_tok), timeout=30)
        before = requests.get(f"{API}/notifications?kind=rc_sms_inbound_unmatched&limit=200",
                              headers=_h(admin_tok), timeout=30).json()
        r = requests.post(f"{API}/ringcentral/simulate-inbound", headers=_h(admin_tok),
                          json={"event_type": "instant-message-SMS",
                                "from_number": "+15550001234",
                                "to_number": "+16028870000",
                                "message": "hello there"}, timeout=30)
        assert r.status_code == 200, r.text[:200]
        time.sleep(0.5)
        after = requests.get(f"{API}/notifications?kind=rc_sms_inbound_unmatched&limit=200",
                             headers=_h(admin_tok), timeout=30).json()
        assert len(after) == len(before) + 1
        newest = after[0]
        assert newest["href"] == "/admin/unmatched-communications"
        assert newest["kind"] == "rc_sms_inbound_unmatched"

    def test_known_number_only_fires_matched(self, admin_tok):
        # Ensure aquaterra has a customer whose phones-array contains the known digits.
        script = '''
import asyncio, sys
sys.path.insert(0, "/app/backend")
from config import db
async def main():
    ten = await db.tenants.find_one({"slug":"aquaterra"}, {"_id":0,"id":1})
    c = await db.customers.find_one({"tenant_id": ten["id"]}, {"_id":0,"id":1})
    await db.customers.update_one({"id": c["id"]}, {"$set": {"phones": ["4805550999"]}})
    print("OK")
asyncio.run(main())
'''
        subprocess.check_output(["python", "-c", script], cwd="/app/backend", timeout=30)
        before_m = requests.get(f"{API}/notifications?kind=rc_sms_inbound&limit=500",
                                headers=_h(admin_tok), timeout=30).json()
        before_u = requests.get(f"{API}/notifications?kind=rc_sms_inbound_unmatched&limit=500",
                                headers=_h(admin_tok), timeout=30).json()
        r = requests.post(f"{API}/ringcentral/simulate-inbound", headers=_h(admin_tok),
                          json={"event_type": "instant-message-SMS",
                                "from_number": "+14805550999",
                                "to_number": "+16028870000",
                                "message": "known customer"}, timeout=30)
        assert r.status_code == 200
        time.sleep(0.5)
        after_m = requests.get(f"{API}/notifications?kind=rc_sms_inbound&limit=500",
                               headers=_h(admin_tok), timeout=30).json()
        after_u = requests.get(f"{API}/notifications?kind=rc_sms_inbound_unmatched&limit=500",
                               headers=_h(admin_tok), timeout=30).json()
        assert len(after_m) >= len(before_m) + 1, "expected matched rc_sms_inbound to increment"
        assert len(after_u) == len(before_u), "unmatched must not increment for known number"


# ═══════════ 4. RC WEBHOOK TOKEN ═══════════
class TestRCWebhookToken:
    def test_missing_token_returns_401(self):
        r = requests.post(f"{API}/ringcentral/webhook",
                          headers={"Content-Type": "application/json"},
                          json={"event": "ping"}, timeout=30)
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text[:200]}"

    def test_valid_token_returns_200(self):
        token = os.environ.get("RINGCENTRAL_WEBHOOK_TOKEN")
        if not token:
            # Read from /app/backend/.env directly (server has it loaded).
            for line in open("/app/backend/.env"):
                if line.startswith("RINGCENTRAL_WEBHOOK_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        assert token, "RINGCENTRAL_WEBHOOK_TOKEN must be set"
        r = requests.post(f"{API}/ringcentral/webhook",
                          headers={"Content-Type": "application/json",
                                   "Verification-Token": token},
                          json={"event": "ping"}, timeout=30)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"

    def test_validation_token_short_circuits(self):
        # Validation-Token header must bypass verification check entirely.
        r = requests.post(f"{API}/ringcentral/webhook",
                          headers={"Content-Type": "application/json",
                                   "Validation-Token": "handshake-xyz"},
                          json={}, timeout=30)
        assert r.status_code == 200
        assert r.headers.get("Validation-Token") == "handshake-xyz"


# ═══════════ 5. CFO STRIPE CASH WEEKLY ═══════════
class TestCfoStripeCash:
    def test_admin_gets_weekly_buckets(self, admin_tok):
        r = requests.get(f"{API}/cfo/stripe-cash-weekly?month=2026-06",
                         headers=_h(admin_tok), timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        weeks = data["weeks"]
        assert isinstance(weeks, list) and len(weeks) == 4, f"expected 4 buckets, got {len(weeks)}"
        for w in weeks:
            assert "week_starting" in w
            assert "cash_collected_cents" in w
            assert "refunds_cents" in w
            assert "net_cents" in w
            assert w["net_cents"] == w["cash_collected_cents"] - w["refunds_cents"]
        # Expected totals from seed rows: 15000+22500+18000+32000 = 87500 gross, refund 2500 → net 85000
        gross = sum(w["cash_collected_cents"] for w in weeks)
        refunds = sum(w["refunds_cents"] for w in weeks)
        net = sum(w["net_cents"] for w in weeks)
        assert gross == 87500
        assert refunds == 2500
        assert net == 85000

    def test_tech_403(self, tech_tok):
        r = requests.get(f"{API}/cfo/stripe-cash-weekly?month=2026-06",
                         headers=_h(tech_tok), timeout=30)
        assert r.status_code == 403

    def test_price_increase_prompt_includes_stripe_cash(self):
        """Patch _call_llm_text to capture the prompt and verify it embeds the
        Stripe cash-collected section for the requested month."""
        script = r'''
import asyncio, sys, json
sys.path.insert(0, "/app/backend")
from unittest.mock import patch, AsyncMock
from routers import cfo as cfo_mod
from config import db

captured = {}

async def fake_llm(system, user_prompt, max_tokens):
    captured["user_prompt"] = user_prompt
    return ('{"suggestions":[]}', None, 0)

async def fake_ranked(month, limit, admin, tenant):
    return {"services": [
        {"service_type": "weekly-pool", "job_count": 4, "revenue_cents": 60000,
         "cost_cents": 55000, "margin_pct": 8.3, "avg_hours_per_job": 1.5},
    ]}

async def main():
    ten = await db.tenants.find_one({"slug":"aquaterra"}, {"_id":0,"id":1})
    admin = await db.users.find_one({"email":"admin@aquaterra.com"}, {"_id":0})
    # Clear cache to force LLM path.
    await db.pricing_suggestions_cache.delete_many({"tenant_id": ten["id"], "month": "2026-06"})
    class B: month = "2026-06"
    with patch("routers.cfo._call_llm_text", side_effect=fake_llm), \
         patch("routers.jobs.least_profitable_services", side_effect=fake_ranked):
        try:
            await cfo_mod.price_increase_suggestions(B(), user=admin, tenant=ten)
        except Exception as e:
            print("ERR:", type(e).__name__, str(e)[:200])
    up = captured.get("user_prompt", "")
    print("HAS_SECTION:", "Stripe cash collected by week" in up)
    print("HAS_NET:", "net $" in up)

asyncio.run(main())
'''
        out = subprocess.check_output(["python", "-c", script], cwd="/app/backend", timeout=60).decode()
        print(out)
        assert "HAS_SECTION: True" in out, out
        assert "HAS_NET: True" in out, out
