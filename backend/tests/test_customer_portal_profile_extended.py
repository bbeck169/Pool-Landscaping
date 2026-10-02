"""Feb-2026 · Portal Profile — secondary email + address sync + security allowlist.

Locks in the ``PATCH /api/customer-portal/profile`` extension:

  * Secondary email persists into ``customer.emails[]`` alongside
    the primary — dedup by lowercased address, single-primary
    invariant preserved by ``normalize_emails``.
  * Empty ``secondary_email`` payload clears every non-primary
    entry without disturbing the primary slot.
  * Same-as-primary → 400 with a clear error.
  * Invalid RFC-lite → 400 with the primary email validator's
    message pattern.
  * Address change fires the shared
    ``routers.customers._mirror_address_to_primary_property`` helper
    so ``db.properties`` stays in step with the customer doc.
  * Security allowlist — admin-only fields (``vip_status``,
    ``tags``, ``billing_settings``, ``credit_limit``,
    ``payment_terms``) are silently dropped by Pydantic
    ``extra="ignore"`` before the endpoint body sees them.
  * Multi-tenant scoping — cross-tenant records never leak.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import pytest
import requests
from dotenv import load_dotenv
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()


def _register_customer(tenant_id: str) -> Dict[str, str]:
    """Register a fresh customer via the public signup path so
    ``users`` + ``customers`` rows are linked with a session-scoped
    JWT the portal endpoints will accept."""
    marker = uuid.uuid4().hex[:10]
    email = f"pp_{marker}@t.co"
    password = "TestPass1!"
    # Resolve the tenant slug so ``/auth/signup`` binds the new
    # customer to the right tenant via the ``X-Tenant-Slug`` header.
    tenant_row = _db.tenants.find_one({"id": tenant_id}, {"_id": 0, "slug": 1})
    if not tenant_row or not tenant_row.get("slug"):
        pytest.skip(f"tenant {tenant_id!r} missing slug")
    r = requests.post(
        f"{API}/auth/signup",
        json={
            "email": email, "password": password,
            "name": f"Pp Sec{marker}",
            "phone": "5555550100",
            "address": "1234 Old St, Springfield IL 62701",
        },
        headers={"X-Tenant-Slug": tenant_row["slug"]},
        timeout=15,
    )
    if r.status_code != 200:
        pytest.skip(f"signup unavailable: {r.status_code} {r.text}")
    tok = r.json().get("access_token")
    me = requests.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"},
        timeout=10,
    ).json()
    cid = me.get("customer_id")
    if not cid:
        pytest.skip("signup did not produce a customer_id")
    return {"tok": tok, "email": email, "customer_id": cid, "user_id": me["id"]}


def _admin_login() -> Dict[str, str]:
    for _ in range(3):
        try:
            r = requests.post(
                f"{API}/auth/login",
                json={"email": "super@aquaterra.com", "password": "password123"},
                timeout=15,
            )
            if r.status_code == 200:
                tok = r.json()["access_token"]
                me = requests.get(
                    f"{API}/auth/me",
                    headers={"Authorization": f"Bearer {tok}"}, timeout=10,
                ).json()
                return {"tok": tok, "tenant_id": me["tenant_id"]}
        except requests.exceptions.RequestException:
            pass
    pytest.skip("admin login unavailable")


def _patch_profile(tok: str, body: dict) -> requests.Response:
    return requests.patch(
        f"{API}/customer-portal/profile", json=body,
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )


@pytest.fixture
def portal_customer():
    admin = _admin_login()
    ctx = _register_customer(admin["tenant_id"])
    ctx["tenant_id"] = admin["tenant_id"]
    try:
        yield ctx
    finally:
        _db.customers.delete_one({"id": ctx["customer_id"]})
        _db.users.delete_one({"id": ctx["user_id"]})
        _db.properties.delete_many({"customer_id": ctx["customer_id"]})
        _db.audit_logs.delete_many({"actor_customer_id": ctx["customer_id"]})


# ═════════════════════════════════════════════════════════════════════
# 1) PATCH with secondary_email populates customer.emails[] + dedup
# ═════════════════════════════════════════════════════════════════════
def test_secondary_email_appends_to_emails_array_with_dedup_guard(portal_customer):
    ctx = portal_customer
    r = _patch_profile(ctx["tok"], {"secondary_email": "alt@example.com"})
    assert r.status_code == 200, r.text
    doc = _db.customers.find_one({"id": ctx["customer_id"]})
    arr = doc.get("emails") or []
    addrs = [(e or {}).get("address") for e in arr]
    assert "alt@example.com" in addrs
    primaries = [e for e in arr if (e or {}).get("is_primary")]
    assert len(primaries) == 1, (
        f"expected single primary, got {primaries!r}"
    )

    # Dedup guard — re-PATCH the same value; array length stays flat.
    r2 = _patch_profile(ctx["tok"], {"secondary_email": "alt@example.com"})
    assert r2.status_code == 200
    arr2 = (_db.customers.find_one({"id": ctx["customer_id"]}) or {}).get("emails") or []
    assert sum(1 for e in arr2 if (e or {}).get("address") == "alt@example.com") == 1


# ═════════════════════════════════════════════════════════════════════
# 2) Empty secondary_email clears the slot
# ═════════════════════════════════════════════════════════════════════
def test_empty_secondary_email_clears_non_primary_entries(portal_customer):
    ctx = portal_customer
    _patch_profile(ctx["tok"], {"secondary_email": "alt2@example.com"})
    # Now clear it.
    r = _patch_profile(ctx["tok"], {"secondary_email": ""})
    assert r.status_code == 200
    arr = (_db.customers.find_one({"id": ctx["customer_id"]}) or {}).get("emails") or []
    assert all((e or {}).get("is_primary") for e in arr), (
        f"non-primary entries survived clear: {arr!r}"
    )
    assert sum(1 for e in arr if (e or {}).get("address") == "alt2@example.com") == 0


# ═════════════════════════════════════════════════════════════════════
# 3) Secondary == primary → 400
# ═════════════════════════════════════════════════════════════════════
def test_secondary_email_matching_primary_is_rejected(portal_customer):
    ctx = portal_customer
    r = _patch_profile(ctx["tok"], {"secondary_email": ctx["email"]})
    assert r.status_code == 400, r.text
    detail = (r.json().get("detail") or "").lower()
    assert "must differ" in detail or "same" in detail or "primary" in detail


# ═════════════════════════════════════════════════════════════════════
# 4) Invalid RFC-lite → 400
# ═════════════════════════════════════════════════════════════════════
def test_secondary_email_invalid_format_is_rejected(portal_customer):
    ctx = portal_customer
    r = _patch_profile(ctx["tok"], {"secondary_email": "not-an-email"})
    assert r.status_code == 400, r.text
    detail = (r.json().get("detail") or "").lower()
    assert "email" in detail


# ═════════════════════════════════════════════════════════════════════
# 5) Address change → primary property record mirrored
# ═════════════════════════════════════════════════════════════════════
def test_address_change_mirrors_to_primary_property(portal_customer):
    ctx = portal_customer
    # Seed a primary property row so the mirror helper has somewhere
    # to write. Zero-property customers are skipped by design (safer
    # Option-B semantics inherited from the admin path).
    prop_id = f"prop-{uuid.uuid4().hex[:8]}"
    _db.properties.insert_one({
        "id": prop_id,
        "tenant_id": ctx["tenant_id"],
        "customer_id": ctx["customer_id"],
        "is_primary": True,
        "active": True,
        "sort_order": 0,
        "label": "Main",
        "address": {"line1": "1234 Old St", "city": "Springfield",
                    "state": "IL", "postal_code": "62701"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r = _patch_profile(ctx["tok"], {
        "address": "9876 New Ave, Metropolis, IL 62960",
    })
    assert r.status_code == 200, r.text
    after = _db.properties.find_one({"id": prop_id}) or {}
    addr = after.get("address") or {}
    assert addr.get("line1") == "9876 New Ave", (
        f"line1 not mirrored: {addr!r}"
    )
    assert addr.get("city") == "Metropolis"
    assert addr.get("state") == "IL"
    assert addr.get("postal_code") == "62960"


# ═════════════════════════════════════════════════════════════════════
# 6) Security allowlist — admin-only fields silently dropped
# ═════════════════════════════════════════════════════════════════════
def test_admin_only_fields_are_silently_dropped(portal_customer):
    ctx = portal_customer
    # Seed the row with pre-existing admin-only values so we can
    # prove the PATCH doesn't overwrite them.
    _db.customers.update_one(
        {"id": ctx["customer_id"]},
        {"$set": {
            "vip_status": "gold",
            "tags": ["seed-tag"],
            "billing_settings": {"terms": "net_30"},
            "credit_limit": 5000,
            "payment_terms": "net_15",
        }},
    )
    r = _patch_profile(ctx["tok"], {
        "phone": "5555550101",  # a benign allowlisted field to make the PATCH valid
        "vip_status": "platinum",     # forbidden
        "tags": ["intruder"],          # forbidden
        "billing_settings": {"terms": "net_90"},  # forbidden
        "credit_limit": 999_999_999,   # forbidden
        "payment_terms": "net_1",      # forbidden
        "tenant_id": "other-tenant",   # forbidden
        "id": "other-id",              # forbidden
        "created_at": "2000-01-01",    # forbidden
    })
    assert r.status_code == 200, r.text
    after = _db.customers.find_one({"id": ctx["customer_id"]}) or {}
    # Admin-only values UNCHANGED from the seed.
    assert after.get("vip_status") == "gold"
    assert after.get("tags") == ["seed-tag"]
    assert after.get("billing_settings") == {"terms": "net_30"}
    assert after.get("credit_limit") == 5000
    assert after.get("payment_terms") == "net_15"
    # Structural identity NEVER mutable by the portal.
    assert after.get("tenant_id") == ctx["tenant_id"]
    assert after.get("id") == ctx["customer_id"]
    # Allowlisted field DID land.
    assert after.get("phone") in ("+15555550101", "5555550101"), (
        f"benign phone update didn't stick: {after.get('phone')!r}"
    )


# ═════════════════════════════════════════════════════════════════════
# 7) Multi-tenant scoping — cross-tenant customer row untouched
# ═════════════════════════════════════════════════════════════════════
def test_multi_tenant_scoping_preserved(portal_customer):
    ctx = portal_customer
    # Seed a customer row with the SAME id under a different tenant.
    # (Not realistic in production — the collision guard would
    # normally reject a duplicate id — but a targeted seed proves
    # the PATCH's ``{"id": cid, "tenant_id": tenant["id"]}`` filter
    # respects the tenant scope.)
    _db.customers.insert_one({
        "id": ctx["customer_id"],
        "tenant_id": "TEST-OTHER-TENANT-portal",
        "name": "Cross-tenant DoNotTouch",
        "email": "leak@t.co", "phone": "+15550000000",
        "address": "0 Untouched Ln",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = _patch_profile(ctx["tok"], {"phone": "5555550199"})
        assert r.status_code == 200
        cross = _db.customers.find_one({
            "id": ctx["customer_id"],
            "tenant_id": "TEST-OTHER-TENANT-portal",
        })
        # Cross-tenant row unchanged.
        assert cross.get("phone") == "+15550000000", (
            f"cross-tenant row was mutated: {cross!r}"
        )
        assert cross.get("name") == "Cross-tenant DoNotTouch"
    finally:
        _db.customers.delete_one({
            "id": ctx["customer_id"],
            "tenant_id": "TEST-OTHER-TENANT-portal",
        })


# ═════════════════════════════════════════════════════════════════════
# 8) Address sync helper is SHARED — admin + portal call the same fn
# ═════════════════════════════════════════════════════════════════════
def test_address_sync_helper_is_shared_between_admin_and_portal():
    """Regression lock — both write paths must resolve to the same
    function object.  Ensures a future refactor that ships one path
    with a divergent mirror implementation trips this test."""
    # Admin path — the customer PUT handler imports the helper by
    # its private name from ``routers.customers``.
    from routers.customers import _mirror_address_to_primary_property as admin_fn
    # Portal path — the customer-portal PATCH handler imports the
    # SAME symbol from ``routers.customers``.  (Import lives inside
    # the handler body — grep the source to prove the wiring
    # without invoking the endpoint again here.)
    from pathlib import Path as _P
    src = _P("routers/customer_portal.py").read_text()
    assert (
        "from routers.customers import _mirror_address_to_primary_property"
        in src
    ), "portal handler must import the SHARED mirror helper"
    assert callable(admin_fn), "admin path must expose the helper"


# ═════════════════════════════════════════════════════════════════════
# 9) Response body echoes the merged emails array so the client can
#    hydrate without a second GET
# ═════════════════════════════════════════════════════════════════════
def test_response_body_includes_emails_array(portal_customer):
    ctx = portal_customer
    r = _patch_profile(ctx["tok"], {"secondary_email": "echo@example.com"})
    assert r.status_code == 200, r.text
    profile = r.json().get("profile") or {}
    assert "emails" in profile, f"response missing emails array: {profile!r}"
    addrs = [(e or {}).get("address") for e in profile.get("emails") or []]
    assert "echo@example.com" in addrs


# ══════════════════════════════════════════════════════════════════════
# Phase 3c-portal · Feb-2026 — current-email confirmation gate on
# primary-email change. Compares against ``db.customers.email``
# (fallback ``db.users.email``); skipped for impersonated sessions;
# mismatch → 400 "Current email confirmation does not match."
# ══════════════════════════════════════════════════════════════════════
_CONFIRM_MISMATCH = "current email confirmation does not match"


def test_email_change_without_confirmation_rejected(portal_customer):
    """PATCH with a new email but NO ``confirm_current_email`` → 400."""
    ctx = portal_customer
    new_email = f"changed_{uuid.uuid4().hex[:8]}@t.co"
    r = _patch_profile(ctx["tok"], {"email": new_email})
    assert r.status_code == 400, r.text
    detail = (r.json().get("detail") or "").lower()
    assert _CONFIRM_MISMATCH in detail, detail
    # Side-channel: stored email must not have mutated.
    doc = _db.customers.find_one({"id": ctx["customer_id"]}) or {}
    assert (doc.get("email") or "").lower() == ctx["email"].lower()


def test_email_change_with_wrong_confirmation_rejected(portal_customer):
    """Wrong ``confirm_current_email`` → 400 (same message)."""
    ctx = portal_customer
    new_email = f"changed_{uuid.uuid4().hex[:8]}@t.co"
    r = _patch_profile(ctx["tok"], {
        "email": new_email,
        "confirm_current_email": "obviously_wrong@elsewhere.co",
    })
    assert r.status_code == 400, r.text
    detail = (r.json().get("detail") or "").lower()
    assert _CONFIRM_MISMATCH in detail, detail
    doc = _db.customers.find_one({"id": ctx["customer_id"]}) or {}
    assert (doc.get("email") or "").lower() == ctx["email"].lower()


def test_email_change_with_correct_confirmation_succeeds(portal_customer):
    """Correct ``confirm_current_email`` → 200; new email persisted to
    BOTH ``db.customers`` and ``db.users``."""
    ctx = portal_customer
    new_email = f"changed_{uuid.uuid4().hex[:8]}@t.co"
    r = _patch_profile(ctx["tok"], {
        "email": new_email,
        "confirm_current_email": ctx["email"],
    })
    assert r.status_code == 200, r.text
    cust = _db.customers.find_one({"id": ctx["customer_id"]}) or {}
    usr = _db.users.find_one({"id": ctx["user_id"]}) or {}
    assert (cust.get("email") or "").lower() == new_email.lower()
    assert (usr.get("email") or "").lower() == new_email.lower()


def test_email_unchanged_does_not_require_confirmation(portal_customer):
    """Same email on the wire + no confirmation → 200."""
    ctx = portal_customer
    r = _patch_profile(ctx["tok"], {"email": ctx["email"]})
    assert r.status_code == 200, r.text
    # Also: email field entirely omitted → 200.
    r2 = _patch_profile(ctx["tok"], {"first_name": "Pp"})
    assert r2.status_code == 200, r2.text


def test_other_fields_change_does_not_require_confirmation(portal_customer):
    """PATCH with only a new phone (no ``email`` in body) → 200."""
    ctx = portal_customer
    r = _patch_profile(ctx["tok"], {"phone": "5555550199"})
    assert r.status_code == 200, r.text


def test_auto_swap_primary_matches_secondary(portal_customer):
    """D8: new primary matches an existing secondary slot → the
    secondary is dropped; emails[] holds a single entry for the new
    address, flagged primary."""
    ctx = portal_customer
    # Seed a secondary first.
    _patch_profile(ctx["tok"], {"secondary_email": "swap_target@t.co"})
    arr_before = (_db.customers.find_one(
        {"id": ctx["customer_id"]}) or {}).get("emails") or []
    assert any((e or {}).get("address") == "swap_target@t.co"
               and not (e or {}).get("is_primary") for e in arr_before)
    # Now promote the secondary to primary via the primary-email
    # change path — the auto-swap must dedup.
    r = _patch_profile(ctx["tok"], {
        "email": "swap_target@t.co",
        "confirm_current_email": ctx["email"],
    })
    assert r.status_code == 200, r.text
    arr_after = (_db.customers.find_one(
        {"id": ctx["customer_id"]}) or {}).get("emails") or []
    swap_slots = [
        e for e in arr_after
        if (e or {}).get("address") == "swap_target@t.co"
    ]
    assert len(swap_slots) == 1, (
        f"auto-swap left duplicate rows: {arr_after!r}"
    )
    assert swap_slots[0].get("is_primary") is True, swap_slots[0]
    # Scalar mirror follows the new primary.
    cust = _db.customers.find_one({"id": ctx["customer_id"]}) or {}
    assert (cust.get("email") or "").lower() == "swap_target@t.co"


def test_impersonation_skips_confirmation_gate(portal_customer):
    """When the token carries ``impersonator_id``, the confirmation
    gate is skipped (admin cannot know the customer's email from
    memory; impersonation already implies admin authority)."""
    ctx = portal_customer
    admin = _admin_login()
    # Mint an impersonation token for this customer.
    r_imp = requests.post(
        f"{API}/admin/impersonate/{ctx['customer_id']}",
        headers={"Authorization": f"Bearer {admin['tok']}"},
        timeout=15,
    )
    if r_imp.status_code != 200:
        pytest.skip(
            f"impersonation endpoint unavailable: "
            f"{r_imp.status_code} {r_imp.text}",
        )
    imp_tok = r_imp.json().get("access_token")
    assert imp_tok, r_imp.text
    new_email = f"imp_{uuid.uuid4().hex[:8]}@t.co"
    r = _patch_profile(imp_tok, {"email": new_email})
    assert r.status_code == 200, r.text
    cust = _db.customers.find_one({"id": ctx["customer_id"]}) or {}
    assert (cust.get("email") or "").lower() == new_email.lower()
