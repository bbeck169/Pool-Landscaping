"""YY · Feb-2026 — Mass Messaging composer "No card on file" filter.

Opens the ``has_card_on_file=False`` branch of ``_resolve_audience``
(the inverse-cohort filter — "customers who do NOT have a card
on file") while keeping the sibling ``has_portal_login`` filter
strict (``True`` | ``None`` only).

Pins (all against ``POST /api/mass-messaging/preview`` + direct
dispatch against ``_resolve_audience`` / ``_validate_filters`` /
``_consume_confirm_token`` for the K72 real-tenant guarded paths):

  1. ``has_card_on_file=null`` → unfiltered audience
     (regression lock, P2 #7 default stays).
  2. ``has_card_on_file=true`` → only customers whose
     ``has_card_on_file`` denorm is ``True``
     (regression lock, P2 #7 positive branch stays).
  3. ``has_card_on_file=false`` → customers whose
     ``has_card_on_file`` denorm is ``False`` OR null OR missing
     (YY fix — the "no card on file" cohort).
  4. ``has_portal_login=false`` is still rejected at the boundary
     with 400 ``INVALID_FILTER_VALUE`` + ``field=has_portal_login``
     (strict-sibling lock — the YY opt-in pattern is per-field).
  5. ``_consume_confirm_token`` round-trips all three
     ``has_card_on_file`` states — ``False`` passes the three-way
     ``!=`` guard unchanged (regression lock on the drift binding
     added in P2 #7 Case 4).
  6. The ``send`` endpoint carries the same tri-state through to
     ``filters_applied`` — K72 real-tenant guard blocks a live
     ``/send`` on this pod (aquaterra is_real=True), so this
     pins the batch-row insert source literal (same pattern as
     P2 #7 Case 5).

Why no live ``/send`` test
---------------------------
Aquaterra is flagged ``is_real=True`` and the dev pod's
``APP_ENV=development``. The ``K72_REAL_TENANT_NON_PROD_BLOCKED``
guard in ``send_broadcast`` fires BEFORE token consumption, so a
live ``/send`` from this pod always 403s — regardless of filter
state. Case 5 drives ``_consume_confirm_token`` directly via the
``batch_safe_run`` helper used by the Phase-34 suite, and Case 6
pins the batch-write source so the mapping stays enforced once
the real-tenant guard lifts.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

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


# ── Per-test clean slate (confirm_tokens + batches) ──────────────
@pytest.fixture(autouse=True)
def _clean_slate():
    _sync.mass_messaging_batches.delete_many({"tenant_id": _TENANT_ID})
    _sync.mass_messaging_confirm_tokens.delete_many({"tenant_id": _TENANT_ID})
    yield
    _sync.mass_messaging_batches.delete_many({"tenant_id": _TENANT_ID})
    _sync.mass_messaging_confirm_tokens.delete_many({"tenant_id": _TENANT_ID})


# ── Seed fixture: 3 customers covering every YY-relevant branch ──
# * ``yy_a``: has_card_on_file=True  — positive-branch member
# * ``yy_b``: has_card_on_file=False — "card detached" branch
#                                       (negative-branch member)
# * ``yy_c``: has_card_on_file field ABSENT — "never attached"
#             branch (negative-branch member via $ne: True)
@pytest.fixture
def seeded_cohort():
    marker = f"yy-{uuid.uuid4().hex[:6]}"
    cids = [f"{marker}-a", f"{marker}-b", f"{marker}-c"]
    _sync.customers.insert_many([
        {"id": cids[0], "tenant_id": _TENANT_ID,
         "name": f"YY A {marker}", "first_name": "Alice",
         "email": f"alice-{marker}@ex.local", "phone": "+15550004441",
         "is_active": True, "has_card_on_file": True},
        {"id": cids[1], "tenant_id": _TENANT_ID,
         "name": f"YY B {marker}", "first_name": "Bob",
         "email": f"bob-{marker}@ex.local", "phone": "+15550004442",
         "is_active": True, "has_card_on_file": False},
        {"id": cids[2], "tenant_id": _TENANT_ID,
         "name": f"YY C {marker}", "first_name": "Cara",
         "email": f"cara-{marker}@ex.local", "phone": "+15550004443",
         "is_active": True},  # has_card_on_file ABSENT
    ])
    yield {"marker": marker, "customer_ids": cids}
    _sync.customers.delete_many({"id": {"$in": cids}})


def _preview(headers: dict, extra: dict):
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
    return requests.post(f"{API}/mass-messaging/preview", json=payload,
                          headers=headers, timeout=15)


def _resolve_cohort_ids_from_token(token: str, cohort_cids: list) -> set:
    """Replay the token's bound filters through ``_resolve_audience``
    directly (same pattern as P2 #7 Case 1). Returns the set of
    cohort ids that survived the filter."""
    from routers.mass_messaging import _resolve_audience
    row = _sync.mass_messaging_confirm_tokens.find_one({"token": token})
    assert row is not None, "confirm_token row missing"
    f = row.get("filters") or {}
    customers = _run(_resolve_audience(
        _TENANT_ID,
        category_ids=f.get("category_ids") or [],
        service_days=f.get("service_days") or [],
        assigned_tech_user_ids=f.get("assigned_tech_user_ids") or [],
        audience_status="active",
        has_card_on_file=f.get("has_card_on_file"),
        has_portal_login=f.get("has_portal_login"),
    ))
    cohort_set = set(cohort_cids)
    return {c["id"] for c in customers if c.get("id") in cohort_set}


# ── Case 1 · has_card_on_file=null → unfiltered (regression) ─────
def test_preview_card_on_file_null_is_unfiltered(admin_headers, seeded_cohort):
    r = _preview(admin_headers, {})  # has_card_on_file defaults to None
    assert r.status_code == 200, r.text
    tok = r.json()["confirm_token"]
    survived = _resolve_cohort_ids_from_token(tok, seeded_cohort["customer_ids"])
    assert survived == set(seeded_cohort["customer_ids"]), (
        f"null filter must pass all 3 cohort rows; got {sorted(survived)}"
    )
    # Token row carries explicit None sentinel.
    row = _sync.mass_messaging_confirm_tokens.find_one({"token": tok})
    assert row["filters"]["has_card_on_file"] is None


# ── Case 2 · has_card_on_file=true → only positive-branch member ─
def test_preview_card_on_file_true_filters_to_positive_cohort(admin_headers, seeded_cohort):
    r = _preview(admin_headers, {"has_card_on_file": True})
    assert r.status_code == 200, r.text
    tok = r.json()["confirm_token"]
    survived = _resolve_cohort_ids_from_token(tok, seeded_cohort["customer_ids"])
    # Only yy_a has the denorm set to True.
    assert survived == {seeded_cohort["customer_ids"][0]}, (
        f"true filter must pass only the has_card_on_file=True row; "
        f"got {sorted(survived)}"
    )
    row = _sync.mass_messaging_confirm_tokens.find_one({"token": tok})
    assert row["filters"]["has_card_on_file"] is True


# ── Case 3 · has_card_on_file=false → "no card" cohort (YY fix) ──
def test_preview_card_on_file_false_matches_no_card_cohort(admin_headers, seeded_cohort):
    r = _preview(admin_headers, {"has_card_on_file": False})
    assert r.status_code == 200, r.text
    tok = r.json()["confirm_token"]
    survived = _resolve_cohort_ids_from_token(tok, seeded_cohort["customer_ids"])
    # yy_b (False) + yy_c (field absent) survive; yy_a (True) excluded.
    expected = {seeded_cohort["customer_ids"][1], seeded_cohort["customer_ids"][2]}
    assert survived == expected, (
        f"false filter must match False + null + missing cohort "
        f"(exact inverse of true branch); got {sorted(survived)}, "
        f"expected {sorted(expected)}"
    )
    row = _sync.mass_messaging_confirm_tokens.find_one({"token": tok})
    assert row["filters"]["has_card_on_file"] is False


# ── Case 4 · has_portal_login=false still rejected (strict lock) ─
def test_preview_portal_login_false_still_rejected(admin_headers):
    """The YY opt-in is per-field. ``has_portal_login=False`` must
    still fail at the boundary with the strict-sibling 400 so a
    future accidental shipment of portal-login negation can't slip
    through."""
    r = _preview(admin_headers, {"has_portal_login": False})
    assert r.status_code == 400, r.text
    body = r.json()
    detail = body.get("detail") if isinstance(body, dict) else None
    assert isinstance(detail, dict), f"expected dict detail; got {body!r}"
    assert detail.get("code") == "INVALID_FILTER_VALUE"
    assert detail.get("field") == "has_portal_login"


# ── Case 5 · confirm-token round-trips all three card states ─────
def test_consume_confirm_token_roundtrip_tri_state(admin_headers):
    """``_consume_confirm_token`` must accept each of
    ``None`` / ``True`` / ``False`` as-stored. The three-way ``!=``
    binding guard added in P2 #7 Case 4 is already correct for a
    three-value domain, but YY opens ``False`` on the write side —
    this case locks the read-side round-trip."""
    from routers.mass_messaging import (
        _issue_confirm_token, _consume_confirm_token,
    )

    for card_state in (None, True, False):
        base_filters = {
            "category_ids": [],
            "service_days": [],
            "assigned_tech_user_ids": [],
            "has_card_on_file": card_state,
            "has_portal_login": None,
        }
        tok = _run(_issue_confirm_token(
            tenant_id=_TENANT_ID, user_id="u-test",
            channels=["email"], template_id=None,
            subject="x", body="x",
            audience="all_active_customers",
            filters=base_filters,
        ))
        # Consume with matching filters — must succeed (no raise).
        _run(_consume_confirm_token(
            tok, _TENANT_ID, ["email"], None, "x", "x",
            "all_active_customers", base_filters,
        ))


# ── Case 6 · send batch-row persists tri-state (source grep) ─────
def test_send_batch_row_still_persists_has_card_on_file_tri_state():
    """Mirror of P2 #7 Case 5 — the ``send_broadcast`` batch-row
    insert MUST continue to persist ``has_card_on_file`` under
    ``filters_applied``. YY expands the value domain from
    ``None | True`` to ``None | True | False``; the insert
    literal is unchanged (it just dereferences
    ``filters["has_card_on_file"]``) and this test fails loud if
    a future refactor drops either key from the insert."""
    src = Path(__file__).resolve().parents[1] / "routers" / "mass_messaging.py"
    text = src.read_text()
    assert '"has_card_on_file": filters["has_card_on_file"]' in text, (
        "mass_messaging.send_broadcast batch-row insert must persist "
        "has_card_on_file in filters_applied — missing from source "
        "(YY tri-state must round-trip through the send path)"
    )
    # Negation branch must exist in the resolver.
    assert 'elif has_card_on_file is False:' in text, (
        "YY negation branch missing from _resolve_audience — "
        "has_card_on_file=False must map to the inverse query"
    )
    assert 'q["has_card_on_file"] = {"$ne": True}' in text, (
        "YY negation branch must use the ``$ne: True`` denorm "
        "clause to match False + null + missing (TD-10 banner "
        "agreement carries over)"
    )
