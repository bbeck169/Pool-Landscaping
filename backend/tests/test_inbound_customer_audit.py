"""Inbound customer-message notification audit test (Feb 2026).

Proves the RingCentral inbound-SMS webhook fires the unified
``inbound_customer_message`` category (in addition to the legacy
``rc_sms_inbound``), and that the admin's push channel is default ON.

Covers item #4 of the audit checklist by mocking
``services.expo_push.send_push_to_user`` and asserting it was
invoked when the notification fires.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
T = 30


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _login(email, pw):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=T)
    r.raise_for_status()
    d = r.json()
    return d["access_token"], (d.get("user") or {}).get("id")


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com", demo_pw("admin@aquaterra.com"))[0]


class TestPrefsDefaults:
    def test_admin_defaults_have_inbound_bell_and_push_on(self, admin_tok):
        r = requests.get(f"{API}/settings/notifications",
                          headers=_h(admin_tok), timeout=T).json()
        chans = r.get("channels") or {}
        row = chans.get("inbound_customer_message") or {}
        assert row.get("bell") is True, "bell must default ON for admin"
        assert row.get("push") is True, "push must default ON for admin"


class TestInboundFiresUnifiedNotification:
    """Simulate an inbound SMS webhook payload → the unified
    ``inbound_customer_message`` notification kind lands + push-mock
    is called."""

    def test_rc_inbound_creates_unified_row(self, admin_tok):
        # Read the current admin's tenant to seed a phone.
        me = requests.get(f"{API}/tenants/current",
                            headers=_h(admin_tok), timeout=T).json()
        # Ensure at least one customer with a phone we can match.
        import uuid
        phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
        cust = requests.post(f"{API}/customers",
                              json={"name": f"TEST_inbound_{uuid.uuid4().hex[:6]}",
                                     "phone": phone,
                                     "email": f"inb-{uuid.uuid4().hex[:6]}@example.com"},
                              headers=_h(admin_tok), timeout=T).json()
        assert cust.get("id")

        # Directly invoke the RC ingest coroutine so we don't need a
        # valid webhook signature. This exercises the exact code path
        # the ringcentral webhook uses.
        with patch("routers.mobile_push.send_push_to_user",
                     new=AsyncMock(return_value={"pushed": True})) as push_mock:
            from routers.ringcentral import _handle_sms_event
            asyncio.get_event_loop().run_until_complete(_handle_sms_event({
                "body": {
                    "id": f"test-rc-{uuid.uuid4().hex[:6]}",
                    "direction": "Inbound",
                    "from": {"phoneNumber": phone},
                    "to": [{"phoneNumber": "+15005550000"}],
                    "subject": "hello from mock",
                    "messageStatus": "Received",
                },
            }))
            # Poll admin's inbox up to 3s for the unified kind.
            import time
            for _ in range(6):
                rows = requests.get(f"{API}/notifications",
                                      params={"kind": "inbound_customer_message",
                                               "limit": 20},
                                      headers=_h(admin_tok), timeout=T).json()
                if any(n.get("kind") == "inbound_customer_message" for n in rows):
                    break
                time.sleep(0.5)
            assert any(n.get("kind") == "inbound_customer_message" for n in rows), \
                "expected inbound_customer_message notification row"
            # Push mock must have been called at least once — admin
            # default push=ON for this kind.
            assert push_mock.await_count >= 1, \
                f"expected push mock to be awaited, got {push_mock.await_count}"
