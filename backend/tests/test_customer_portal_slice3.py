"""Feb-2026 · Slice 3 — Customer portal endpoint integration tests.

Covers:
* Slice 3B — ``GET /api/customer-portal/summary``: returns the 4 tile
  numbers for the logged-in customer, RBAC gates non-customers,
  numbers are scoped to the customer's own invoices/jobs.
* Slice 3A — ``POST /api/customer-portal/payment-methods/ach/link-session``:
  RBAC gates non-customers; when ``STRIPE_SECRET_KEY`` is absent the
  endpoint returns ``{ok: false, reason: "stripe_not_configured"}``
  without touching Stripe.

The tests hit the running backend so we exercise the real ingress path.
"""
from __future__ import annotations

import os
import subprocess
import time

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


# ═══════════════════════════════════════════════════════════════════════
# 3B · Summary tiles
# ═══════════════════════════════════════════════════════════════════════
def test_summary_customer_returns_shape(customer_headers):
    r = requests.get(f"{API}/customer-portal/summary",
                     headers=customer_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    # Contract — four numeric tiles + a next_service dict|null.
    assert set(body.keys()) >= {
        "balance_due", "past_due", "credit", "next_service", "breakdown",
    }
    for k in ("balance_due", "past_due", "credit"):
        assert isinstance(body[k], (int, float)), f"{k} not numeric"
        assert body[k] >= 0.0
    assert body["past_due"] <= body["balance_due"] + 1e-6, \
        "past_due can never exceed balance_due"
    # next_service is either None or a dict with at least ``date``.
    ns = body["next_service"]
    if ns is not None:
        assert isinstance(ns, dict)
        assert "date" in ns
        assert "service_type" in ns
    # Breakdown counts must be non-negative ints.
    bd = body.get("breakdown") or {}
    assert bd.get("open_invoice_count", 0) >= 0
    assert bd.get("past_due_invoice_count", 0) >= 0
    assert bd["past_due_invoice_count"] <= bd["open_invoice_count"]


def test_summary_admin_forbidden(admin_headers):
    r = requests.get(f"{API}/customer-portal/summary",
                     headers=admin_headers, timeout=30)
    assert r.status_code == 403, r.text


def test_summary_tech_forbidden(tech_headers):
    r = requests.get(f"{API}/customer-portal/summary",
                     headers=tech_headers, timeout=30)
    assert r.status_code == 403, r.text


def test_summary_anonymous_forbidden():
    r = requests.get(f"{API}/customer-portal/summary", timeout=30)
    assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════
# 3A · ACH stub
# ═══════════════════════════════════════════════════════════════════════
def _stripe_key_present(customer_headers) -> bool:
    """Probe the backend's ``/customer-portal/payment-methods`` route —
    it returns ``stripe_configured`` reflecting whether the live env of
    the running process has a NON-placeholder Stripe secret key.
    Reliable across supervisor + .env-loaded setups."""
    try:
        r = requests.get(f"{API}/customer-portal/payment-methods",
                          headers=customer_headers, timeout=15)
        if r.status_code != 200:
            return False
        return bool(r.json().get("stripe_configured"))
    except Exception:
        return False


def test_ach_placeholder_key_detection_helpers():
    """Unit-test the placeholder-detection helper directly so future
    edits can't silently degrade the shortcut fast-path back to a
    round-trip to Stripe."""
    # Import inside the test so a syntax error surfaces here rather
    # than at module import time.
    from routers.customer_portal import _stripe_key_is_placeholder

    assert _stripe_key_is_placeholder("") is True
    assert _stripe_key_is_placeholder("   ") is True
    assert _stripe_key_is_placeholder('""') is True
    assert _stripe_key_is_placeholder("'sk_test_'") is True
    assert _stripe_key_is_placeholder("sk_test_") is True
    assert _stripe_key_is_placeholder("sk_live_") is True
    assert _stripe_key_is_placeholder("sk_test_placeholder") is True
    assert _stripe_key_is_placeholder("sk_live_placeholder") is True
    assert _stripe_key_is_placeholder("your_key_here") is True
    # Anything shorter than 24 chars total can't be a real Stripe key.
    assert _stripe_key_is_placeholder("sk_test_abc") is True

    # Real-shaped keys must NOT be flagged.
    assert _stripe_key_is_placeholder(
        "sk_test_51NE9ygABCDEFGHIJKLMNOPQRSTUV"
    ) is False
    assert _stripe_key_is_placeholder(
        "sk_live_51NE9ygABCDEFGHIJKLMNOPQRSTUV"
    ) is False


def test_ach_link_session_placeholder_key_short_circuits(customer_headers, monkeypatch):
    """When ``STRIPE_SECRET_KEY`` is a placeholder value, the endpoint
    MUST fast-return ``stripe_not_configured`` without ever calling
    Stripe. Previous behaviour was to attempt the SDK call and
    return ``stripe_error`` — misleading for callers and pointless."""
    # We can't monkeypatch env on the running FastAPI process from
    # here — that would need an in-process test client. Instead we
    # invoke the helper directly with a temp env in an isolated
    # subprocess so the assertion is deterministic.
    import textwrap
    code = textwrap.dedent("""
        import os, asyncio
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_"   # placeholder
        from routers.customer_portal import _stripe_configured
        assert _stripe_configured() is False, "placeholder must be rejected"
        os.environ["STRIPE_SECRET_KEY"] = ""
        assert _stripe_configured() is False, "empty must be rejected"
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_51NE9ygABCDEFGHIJKLMNOPQRSTUV"
        assert _stripe_configured() is True, "real-shaped test key accepted"
        print("OK")
    """)
    out = subprocess.check_output(
        ["python", "-c", code], cwd="/app/backend", timeout=15,
    ).decode().strip()
    assert out.endswith("OK"), out


def test_ach_link_session_customer_ok(customer_headers):
    r = requests.post(
        f"{API}/customer-portal/payment-methods/ach/link-session",
        headers=customer_headers, json={}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Shape — always ``ok`` boolean.
    assert "ok" in body
    if not _stripe_key_present(customer_headers):
        # When Stripe is not configured we get
        # ``reason == "stripe_not_configured"`` and no client_secret.
        assert body["ok"] is False
        assert body.get("reason") == "stripe_not_configured", (
            f"placeholder key should short-circuit to stripe_not_configured, "
            f"got {body!r}"
        )
        assert not body.get("client_secret")
    else:
        # Real Stripe call — either succeeds (client_secret present) or
        # returns ``stripe_error`` when the account isn't enabled for
        # Financial Connections. Both are acceptable — we're just
        # asserting we didn't 500 and that the shape is correct.
        assert body["ok"] in (True, False)
        if body["ok"]:
            assert body.get("client_secret")
        else:
            assert body.get("reason") in (
                "stripe_error", "stripe_customer_error", "stripe_sdk_unavailable",
            )


def test_ach_link_session_admin_forbidden(admin_headers):
    r = requests.post(
        f"{API}/customer-portal/payment-methods/ach/link-session",
        headers=admin_headers, json={}, timeout=30,
    )
    assert r.status_code == 403


def test_ach_link_session_tech_forbidden(tech_headers):
    r = requests.post(
        f"{API}/customer-portal/payment-methods/ach/link-session",
        headers=tech_headers, json={}, timeout=30,
    )
    assert r.status_code == 403


def test_ach_link_session_anonymous_forbidden():
    r = requests.post(
        f"{API}/customer-portal/payment-methods/ach/link-session",
        json={}, timeout=30,
    )
    assert r.status_code in (401, 403)


def test_payment_methods_list_customer(customer_headers):
    r = requests.get(
        f"{API}/customer-portal/payment-methods",
        headers=customer_headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "methods" in body
    assert isinstance(body["methods"], list)
    assert "stripe_configured" in body
    assert isinstance(body["stripe_configured"], bool)


def test_payment_methods_list_admin_forbidden(admin_headers):
    r = requests.get(
        f"{API}/customer-portal/payment-methods",
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# 3D · Service-request → internal message + bell + push
# ═══════════════════════════════════════════════════════════════════════
def _bell_count(headers) -> int:
    r = requests.get(f"{API}/notifications/unread-count",
                     headers=headers, timeout=15)
    if r.status_code != 200:
        return 0
    return int(r.json().get("count") or 0)


def test_service_request_customer_creates_message(customer_headers, admin_headers):
    before_msgs = requests.get(
        f"{API}/admin/messages" if False else f"{API}/customers",
        headers=admin_headers, timeout=15,
    )  # sanity — just proves admin auth still works
    assert before_msgs.status_code in (200, 403), before_msgs.text

    before_bell = _bell_count(admin_headers)

    r = requests.post(
        f"{API}/customer-portal/service-requests",
        headers=customer_headers,
        json={
            "service_type": "Pool Cleaning",
            "preferred_date": "2026-08-05",
            "notes": "Rainbird kicked on, filter looking dirty.",
        },
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("message_id"), "message_id missing"
    msg = body.get("message") or {}
    assert msg.get("kind") == "service_request"
    assert msg.get("sender") == "customer"
    # The server-composed body must include what admin needs to act.
    text = msg.get("text") or ""
    assert "Pool Cleaning" in text
    assert "2026-08-05" in text
    # notified_admins is a count — must be >= 1 for the seeded tenant.
    assert body.get("notified_admins", 0) >= 1

    # The admin's bell counter must have advanced.
    after_bell = _bell_count(admin_headers)
    assert after_bell >= before_bell + 1, (
        f"admin bell did not increment (before={before_bell}, after={after_bell})"
    )


def test_service_request_customer_message_lands_in_portal_thread(customer_headers):
    """The customer sees their outgoing request in /me/messages so the
    chat thread stays authoritative — one source of truth."""
    r = requests.post(
        f"{API}/customer-portal/service-requests",
        headers=customer_headers,
        json={"service_type": "Chemical Rebalance"},
        timeout=30,
    )
    assert r.status_code == 200
    msg_id = r.json().get("message_id")

    thread = requests.get(f"{API}/me/messages",
                          headers=customer_headers, timeout=15)
    assert thread.status_code == 200
    ids = [m.get("id") for m in thread.json()]
    assert msg_id in ids, "service request not present in customer thread"


def test_service_request_admin_forbidden(admin_headers):
    r = requests.post(
        f"{API}/customer-portal/service-requests",
        headers=admin_headers,
        json={"service_type": "Pool Cleaning"},
        timeout=30,
    )
    assert r.status_code == 403


def test_service_request_tech_forbidden(tech_headers):
    r = requests.post(
        f"{API}/customer-portal/service-requests",
        headers=tech_headers,
        json={"service_type": "Pool Cleaning"},
        timeout=30,
    )
    assert r.status_code == 403


def test_service_request_anonymous_forbidden():
    r = requests.post(
        f"{API}/customer-portal/service-requests",
        json={"service_type": "Pool Cleaning"},
        timeout=30,
    )
    assert r.status_code in (401, 403)


def test_service_request_minimal_payload_ok(customer_headers):
    """An empty payload is a valid request — server just fills in
    'Service: Not specified' plus the customer's identity."""
    r = requests.post(
        f"{API}/customer-portal/service-requests",
        headers=customer_headers,
        json={},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert "Not specified" in (body.get("message") or {}).get("text", "")


# ═══════════════════════════════════════════════════════════════════════
# 3D · Deep-link regression — bell entry must open the real admin thread
# ═══════════════════════════════════════════════════════════════════════
def test_service_request_bell_href_resolves_to_real_admin_route(customer_headers, admin_headers):
    """Post a service request as customer → the freshly enqueued admin
    bell entry's ``href`` must:
      (a) match the ``/communication/{customer_id}`` shape and
      (b) be openable by the admin — hitting the underlying API
          ``GET /api/communications/{customer_id}`` must return 200
          with a ``messages`` array (not a 404).
    """
    r = requests.post(
        f"{API}/customer-portal/service-requests",
        headers=customer_headers,
        json={"service_type": "Pool Cleaning"},
        timeout=30,
    )
    assert r.status_code == 200, r.text

    # Peek the admin's newest notifications and locate ours.
    rows = requests.get(
        f"{API}/notifications?limit=50", headers=admin_headers, timeout=15,
    ).json() or []
    target = None
    for n in rows:
        sr = n.get("source_ref") or {}
        if sr.get("kind") == "service_request":
            target = n
            break
    assert target is not None, "no service_request bell row visible to admin"

    href = target.get("href") or ""
    assert href.startswith("/communication/"), (
        f"bell href must deep-link to /communication/:cid — got {href!r}"
    )
    # Old broken pattern must never resurface.
    assert "customer_id=" not in href, (
        f"broken /messages?customer_id=... pattern regressed — {href!r}"
    )

    cid = href.split("/communication/", 1)[1]
    assert cid, "customer_id missing from href"

    # Hit the API the admin thread view calls — this is the exact call
    # ``CommunicationThread.jsx`` makes on mount. A 404 here would
    # reproduce the bug the user reported.
    thread = requests.get(
        f"{API}/communications/{cid}", headers=admin_headers, timeout=15,
    )
    assert thread.status_code == 200, (
        f"admin thread route 404 for href={href!r}: {thread.text}"
    )
    body = thread.json()
    assert "messages" in body and isinstance(body["messages"], list)
    assert len(body["messages"]) >= 1, "thread empty — service request didn't land"
