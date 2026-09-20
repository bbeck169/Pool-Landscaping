"""Feb-2026 · Priority 3 — Autobilling opt-in endpoints.

Ships alongside the payment-complete CTA. After a customer completes
checkout with ``save_for_future_billing=true``, the frontend surfaces
a card asking them to enable autobilling for future invoices. The
CTA lands on ``POST /api/customer-portal/autobilling/enable`` which
flips ``customers.autobilling_enabled`` true.

Rules the suite locks:

  1. Customer with a saved default PM can enable → 200, flag flips.
  2. Customer without a saved PM gets 409 ``no_default_payment_method``
     (frontend nudges them to add a card first).
  3. Enable is idempotent — repeat calls return ``changed=false``.
  4. Disable mirrors enable — same shape, opposite effect.
  5. ``GET /customer-portal/autobilling`` returns both flags so the
     frontend can decide whether to render the CTA at all.
  6. Non-customer roles are 403 (portal-scoped endpoint).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()
# ─── Login helper — customer seed ─────────────────────────────────────
_TOK_CACHE: dict = {}


def _login(email: str, password: str = "password123") -> tuple[str, dict]:
    key = f"tok:{email}"
    if _TOK_CACHE.get(key):
        return _TOK_CACHE[key]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password}, timeout=30,
    )
    r.raise_for_status()
    tok = r.json()["access_token"]
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    ).json()
    _TOK_CACHE[key] = (tok, me)
    return tok, me


CUSTOMER_EMAIL = "customer@aquaterra.com"


def _customer_headers() -> tuple[dict, str, str]:
    """Return (auth headers, customer_id, tenant_id) for the seeded
    customer account. Chatty — never cache across tests since we mutate
    the customer doc between them."""
    tok, me = _login(CUSTOMER_EMAIL)
    return (
        {"Authorization": f"Bearer {tok}"},
        me.get("customer_id"),
        me.get("tenant_id"),
    )


# ─── Snapshot / restore helper ────────────────────────────────────────
def _snapshot_customer(cid: str, tid: str) -> dict:
    doc = _db.customers.find_one(
        {"id": cid, "tenant_id": tid},
        {"_id": 0, "autobilling_enabled": 1,
          "autobilling_enabled_at": 1,
          "autobilling_disabled_at": 1,
          "default_payment_method_id": 1},
    ) or {}
    return doc


def _restore_customer(cid: str, tid: str, snapshot: dict) -> None:
    """Reset the fields the test mutates so we don't leak state across
    a test suite run."""
    _db.customers.update_one(
        {"id": cid, "tenant_id": tid},
        {"$set": {
            "autobilling_enabled": snapshot.get("autobilling_enabled", False),
            "default_payment_method_id":
                snapshot.get("default_payment_method_id"),
        }},
    )


# ══════════════════════════════════════════════════════════════════════
# Rule 5 — GET status endpoint mirrors current DB state.
# ══════════════════════════════════════════════════════════════════════
def test_get_autobilling_status_reports_current_flags():
    hdr, cid, tid = _customer_headers()
    snap = _snapshot_customer(cid, tid)
    try:
        # Seed known state — enable + saved PM.
        _db.customers.update_one(
            {"id": cid, "tenant_id": tid},
            {"$set": {
                "autobilling_enabled": True,
                "default_payment_method_id": f"pm_test_{uuid.uuid4().hex[:8]}",
            }},
        )
        r = requests.get(
            f"{API}/customer-portal/autobilling",
            headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["autobilling_enabled"] is True
        assert body["has_default_payment_method"] is True
    finally:
        _restore_customer(cid, tid, snap)


# ══════════════════════════════════════════════════════════════════════
# Rule 1 — customer with saved PM can enable.
# ══════════════════════════════════════════════════════════════════════
def test_enable_flips_flag_when_default_payment_method_present():
    hdr, cid, tid = _customer_headers()
    snap = _snapshot_customer(cid, tid)
    try:
        _db.customers.update_one(
            {"id": cid, "tenant_id": tid},
            {"$set": {
                "autobilling_enabled": False,
                "default_payment_method_id": f"pm_test_{uuid.uuid4().hex[:8]}",
            }},
        )
        r = requests.post(
            f"{API}/customer-portal/autobilling/enable",
            headers=hdr, json={}, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["autobilling_enabled"] is True
        assert body["changed"] is True
        # Persistence check.
        doc = _db.customers.find_one(
            {"id": cid, "tenant_id": tid},
            {"_id": 0, "autobilling_enabled": 1,
              "autobilling_enabled_at": 1},
        )
        assert doc["autobilling_enabled"] is True
        assert doc.get("autobilling_enabled_at"), "timestamp must be set"
    finally:
        _restore_customer(cid, tid, snap)


# ══════════════════════════════════════════════════════════════════════
# Rule 2 — no saved PM → 409.
# ══════════════════════════════════════════════════════════════════════
def test_enable_without_default_payment_method_returns_409():
    hdr, cid, tid = _customer_headers()
    snap = _snapshot_customer(cid, tid)
    try:
        _db.customers.update_one(
            {"id": cid, "tenant_id": tid},
            # $unset so the field is actually absent (mirrors a
            # brand-new customer who never saved a card).
            {"$set": {"autobilling_enabled": False},
              "$unset": {"default_payment_method_id": ""}},
        )
        r = requests.post(
            f"{API}/customer-portal/autobilling/enable",
            headers=hdr, json={}, timeout=30,
        )
        assert r.status_code == 409, r.text
        assert "no_default_payment_method" in r.text
    finally:
        _restore_customer(cid, tid, snap)


# ══════════════════════════════════════════════════════════════════════
# Rule 3 — enable is idempotent.
# ══════════════════════════════════════════════════════════════════════
def test_enable_is_idempotent_when_already_enabled():
    hdr, cid, tid = _customer_headers()
    snap = _snapshot_customer(cid, tid)
    try:
        _db.customers.update_one(
            {"id": cid, "tenant_id": tid},
            {"$set": {
                "autobilling_enabled": True,
                "default_payment_method_id": f"pm_test_{uuid.uuid4().hex[:8]}",
            }},
        )
        r = requests.post(
            f"{API}/customer-portal/autobilling/enable",
            headers=hdr, json={}, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["autobilling_enabled"] is True
        assert body["changed"] is False
    finally:
        _restore_customer(cid, tid, snap)


# ══════════════════════════════════════════════════════════════════════
# Rule 4 — disable mirrors enable.
# ══════════════════════════════════════════════════════════════════════
def test_disable_flips_flag_off_and_is_idempotent():
    hdr, cid, tid = _customer_headers()
    snap = _snapshot_customer(cid, tid)
    try:
        _db.customers.update_one(
            {"id": cid, "tenant_id": tid},
            {"$set": {"autobilling_enabled": True}},
        )
        r = requests.post(
            f"{API}/customer-portal/autobilling/disable",
            headers=hdr, json={}, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["autobilling_enabled"] is False
        assert body["changed"] is True

        # Second call — no-op.
        r2 = requests.post(
            f"{API}/customer-portal/autobilling/disable",
            headers=hdr, json={}, timeout=30,
        )
        assert r2.status_code == 200
        assert r2.json()["changed"] is False
    finally:
        _restore_customer(cid, tid, snap)


# ══════════════════════════════════════════════════════════════════════
# Rule 6 — non-customer role is rejected.
# ══════════════════════════════════════════════════════════════════════
def test_admin_role_cannot_use_portal_autobilling_endpoint():
    tok, _me = _login("admin@aquaterra.com")
    r = requests.post(
        f"{API}/customer-portal/autobilling/enable",
        headers={"Authorization": f"Bearer {tok}"}, json={}, timeout=30,
    )
    assert r.status_code == 403, r.text
