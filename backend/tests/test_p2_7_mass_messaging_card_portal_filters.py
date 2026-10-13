"""P2 #7 · Feb-2026 — Mass Messaging composer filters for
Card-on-file + Portal-login.

Pins:
  1. ``has_card_on_file=true`` on the preview restricts the audience
     to customers whose denorm flag is set.
  2. ``has_portal_login=true`` runs the users-scan set-build and
     restricts the audience to customers linked to an active
     portal account (``role=customer`` user with ``password_hash``
     set and not deactivated / soft-deleted).
  3. Both filters compose with AND semantics.
  4. ``_consume_confirm_token`` rejects a filter-signature drift
     on EITHER new key with ``CONFIRM_TOKEN_FILTERS_MISMATCH`` +
     the correct ``mismatched_field`` (BUG G non-regression,
     extended to the two P2 #7 keys).
  5. The ``send`` endpoint writes both new keys into
     ``mass_messaging_batches.filters_applied``. (Source-grep: the
     ``is_real=True`` aquaterra tenant K72 guard blocks any
     ``/send`` from the dev pod, so a byte-for-byte source
     assertion on the dict literal is the strongest coverage
     available here.)
  6. Both filters at ``null`` (default) → unfiltered audience.

Why no live ``/send`` test
---------------------------
Aquaterra is flagged ``is_real=True`` and the dev pod's
``APP_ENV=development``. The ``K72_REAL_TENANT_NON_PROD_BLOCKED``
guard in ``send_broadcast`` fires BEFORE token consumption, so a
live ``/send`` from this pod always 403s — regardless of filter
state. Case 4 therefore drives ``_consume_confirm_token`` directly
via the ``batch_safe_run`` helper used by the Phase-34 suite, and
Case 5 pins the batch-write source so the mapping stays enforced
once the real-tenant guard lifts.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._shared_mongo import shared_db as _shared_db
from tests._phase34_asyncio import batch_safe_run as _run


_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
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


# ── Per-test clean slate ─────────────────────────────────────────
# Purge batches + confirm tokens between cases so back-to-back
# previews don't collide and the 5-min rate limit stays dormant.
@pytest.fixture(autouse=True)
def _clean_slate():
    _sync.mass_messaging_batches.delete_many({"tenant_id": _TENANT_ID})
    _sync.mass_messaging_confirm_tokens.delete_many({"tenant_id": _TENANT_ID})
    yield
    _sync.mass_messaging_batches.delete_many({"tenant_id": _TENANT_ID})
    _sync.mass_messaging_confirm_tokens.delete_many({"tenant_id": _TENANT_ID})


# ── Seed fixture: 3 customers + 2 portal users ───────────────────
# * ``p2_7_a``: has_card_on_file=True, no portal user
# * ``p2_7_b``: has_card_on_file=None, portal user WITH password_hash
# * ``p2_7_c``: has_card_on_file=True, portal user WITH password_hash
#   (satisfies BOTH filters — the AND-compose case)
@pytest.fixture
def seeded_cohort():
    marker = f"p2-7-{uuid.uuid4().hex[:6]}"
    cids = [f"{marker}-a", f"{marker}-b", f"{marker}-c"]
    uids = [f"{marker}-u-b", f"{marker}-u-c"]  # users for b + c only
    _sync.customers.insert_many([
        {"id": cids[0], "tenant_id": _TENANT_ID,
         "name": f"P27 A {marker}", "first_name": "Alice",
         "email": f"alice-{marker}@ex.local", "phone": "+15550001111",
         "is_active": True, "has_card_on_file": True},
        {"id": cids[1], "tenant_id": _TENANT_ID,
         "name": f"P27 B {marker}", "first_name": "Bob",
         "email": f"bob-{marker}@ex.local", "phone": "+15550002222",
         "is_active": True},
        {"id": cids[2], "tenant_id": _TENANT_ID,
         "name": f"P27 C {marker}", "first_name": "Cara",
         "email": f"cara-{marker}@ex.local", "phone": "+15550003333",
         "is_active": True, "has_card_on_file": True},
    ])
    _sync.users.insert_many([
        {"id": uids[0], "tenant_id": _TENANT_ID,
         "customer_id": cids[1], "role": "customer",
         "email": f"bob-{marker}@ex.local",
         "password_hash": "$2b$12$fakehashfakehashfakehashfakeha",
         "is_active": True},
        {"id": uids[1], "tenant_id": _TENANT_ID,
         "customer_id": cids[2], "role": "customer",
         "email": f"cara-{marker}@ex.local",
         "password_hash": "$2b$12$fakehashfakehashfakehashfakeha",
         "is_active": True},
    ])
    yield {"marker": marker, "customer_ids": cids, "user_ids": uids}
    _sync.customers.delete_many({"id": {"$in": cids}})
    _sync.users.delete_many({"id": {"$in": uids}})


def _preview(headers: dict, extra: dict) -> dict:
    payload = {
        "channels": ["email"],
        "audience": "all_active_customers",
        "subject": "x",
        "body": "test body",
        "category_ids": [],
        "service_days": [],
        "assigned_tech_user_ids": [],
        "audience_status": "active",
        "has_card_on_file": None,
        "has_portal_login": None,
    }
    payload.update(extra)
    r = requests.post(f"{API}/mass-messaging/preview", json=payload,
                       headers=headers, timeout=15)
    return r


def _count_cohort_in_token(token: str, cohort_cids: list) -> int:
    """How many of the seeded cohort landed in the preview-resolved
    audience? Rather than parse the preview response (which only
    exposes aggregate ``estimated_recipients``), re-resolve the
    audience server-side-identically by replaying the token's
    stored filters against ``_resolve_audience`` directly."""
    from routers.mass_messaging import _resolve_audience
    row = _sync.mass_messaging_confirm_tokens.find_one({"token": token})
    assert row is not None, "confirm_token row missing"
    f = row.get("filters") or {}
    customers = _run(_resolve_audience(
        _TENANT_ID,
        category_ids=f.get("category_ids") or [],
        service_days=f.get("service_days") or [],
        assigned_tech_user_ids=f.get("assigned_tech_user_ids") or [],
        audience_status=row.get("audience") or "all_active_customers",
        has_card_on_file=f.get("has_card_on_file"),
        has_portal_login=f.get("has_portal_login"),
    ))
    cohort_set = set(cohort_cids)
    return sum(1 for c in customers if c.get("id") in cohort_set)


# ── Case 1 · has_card_on_file=true filters by denorm ─────────────
def test_preview_has_card_on_file_filters_by_denorm(admin_headers, seeded_cohort):
    r = _preview(admin_headers, {"has_card_on_file": True})
    assert r.status_code == 200, r.text
    tok = r.json()["confirm_token"]
    # Cohort has a + c with the denorm set (2 of 3).
    n = _count_cohort_in_token(tok, seeded_cohort["customer_ids"])
    assert n == 2, f"expected 2 cohort rows w/ card-on-file; got {n}"


# ── Case 2 · has_portal_login=true scans users ───────────────────
def test_preview_has_portal_login_scans_users(admin_headers, seeded_cohort):
    r = _preview(admin_headers, {"has_portal_login": True})
    assert r.status_code == 200, r.text
    tok = r.json()["confirm_token"]
    # Cohort b + c have portal users (2 of 3).
    n = _count_cohort_in_token(tok, seeded_cohort["customer_ids"])
    assert n == 2, f"expected 2 cohort rows w/ portal login; got {n}"


# ── Case 3 · both filters AND-compose ────────────────────────────
def test_preview_both_filters_and_compose(admin_headers, seeded_cohort):
    r = _preview(admin_headers,
                 {"has_card_on_file": True, "has_portal_login": True})
    assert r.status_code == 200, r.text
    tok = r.json()["confirm_token"]
    # Only cohort c satisfies BOTH (1 of 3).
    n = _count_cohort_in_token(tok, seeded_cohort["customer_ids"])
    assert n == 1, f"expected 1 cohort row w/ card+portal; got {n}"


# ── Case 4 · confirm-token binds new keys; drift → 400 ───────────
def test_consume_confirm_token_rejects_drift_on_new_keys(admin_headers, seeded_cohort):
    """Direct-dispatch against ``_consume_confirm_token``. The HTTP
    ``/send`` path is K72-blocked on this pod (aquaterra is_real),
    so we invoke the guard function itself with mismatched filters
    and assert the ``CONFIRM_TOKEN_FILTERS_MISMATCH`` raise +
    ``mismatched_field`` payload."""
    from fastapi import HTTPException
    from routers.mass_messaging import (
        _issue_confirm_token, _consume_confirm_token,
    )

    base_filters = {
        "category_ids": [],
        "service_days": [],
        "assigned_tech_user_ids": [],
        "has_card_on_file": True,
        "has_portal_login": None,
    }
    tok = _run(_issue_confirm_token(
        tenant_id=_TENANT_ID, user_id="u-test",
        channels=["email"], template_id=None,
        subject="x", body="x",
        audience="all_active_customers",
        filters=base_filters,
    ))

    # Drift on has_card_on_file → mismatch.
    drift_a = {**base_filters, "has_card_on_file": None}
    with pytest.raises(HTTPException) as exc_a:
        _run(_consume_confirm_token(
            tok, _TENANT_ID, ["email"], None, "x", "x",
            "all_active_customers", drift_a,
        ))
    assert exc_a.value.status_code == 400
    assert exc_a.value.detail.get("code") == "CONFIRM_TOKEN_FILTERS_MISMATCH"
    assert exc_a.value.detail.get("mismatched_field") == "has_card_on_file"

    # Fresh token for the second drift case (first one was consumed).
    tok2 = _run(_issue_confirm_token(
        tenant_id=_TENANT_ID, user_id="u-test",
        channels=["email"], template_id=None,
        subject="x", body="x",
        audience="all_active_customers",
        filters=base_filters,
    ))
    # Drift on has_portal_login → mismatch.
    drift_b = {**base_filters, "has_portal_login": True}
    with pytest.raises(HTTPException) as exc_b:
        _run(_consume_confirm_token(
            tok2, _TENANT_ID, ["email"], None, "x", "x",
            "all_active_customers", drift_b,
        ))
    assert exc_b.value.status_code == 400
    assert exc_b.value.detail.get("code") == "CONFIRM_TOKEN_FILTERS_MISMATCH"
    assert exc_b.value.detail.get("mismatched_field") == "has_portal_login"


# ── Case 5 · send writes new keys to filters_applied (source-grep) ─
def test_send_writes_new_keys_to_filters_applied_source():
    """Byte-for-byte source assertion on the ``send_broadcast``
    batch-row insert. The ``/send`` endpoint cannot be exercised
    live against aquaterra from this pod (K72 real-tenant guard,
    see module docstring), so this test pins the mapping at the
    source layer. Combined with Case 4's binding guard, the
    end-to-end "preview filter → batch audit" invariant is
    enforced.

    If a future refactor splits the batch-row dict literal
    across helpers, update the regex to match the new shape — do
    NOT drop the assertion."""
    src = Path(__file__).resolve().parents[1] / "routers" / "mass_messaging.py"
    text = src.read_text()
    # The batch-row insert MUST include both new keys inside the
    # ``filters_applied`` dict literal.
    assert '"has_card_on_file": filters["has_card_on_file"]' in text, (
        "mass_messaging.send_broadcast batch-row insert must persist "
        "has_card_on_file in filters_applied — missing from source"
    )
    assert '"has_portal_login": filters["has_portal_login"]' in text, (
        "mass_messaging.send_broadcast batch-row insert must persist "
        "has_portal_login in filters_applied — missing from source"
    )


# ── Case 6 · default (both None) is unfiltered ───────────────────
def test_preview_default_both_null_is_unfiltered(admin_headers, seeded_cohort):
    r = _preview(admin_headers, {})  # both default None
    assert r.status_code == 200, r.text
    tok = r.json()["confirm_token"]
    # All 3 cohort rows survive.
    n = _count_cohort_in_token(tok, seeded_cohort["customer_ids"])
    assert n == 3, f"expected all 3 cohort rows; got {n}"
    # Token's bound filters carry explicit None sentinels (not absent).
    row = _sync.mass_messaging_confirm_tokens.find_one({"token": tok})
    f = row.get("filters") or {}
    assert "has_card_on_file" in f, "token row must carry has_card_on_file key explicitly"
    assert "has_portal_login" in f, "token row must carry has_portal_login key explicitly"
    assert f["has_card_on_file"] is None
    assert f["has_portal_login"] is None
