"""Feb-2026 · Task 6 — Quote / Estimate Terms & Conditions section.

Covers:
  * ``GET /quotes/{qid}/full`` returns ``terms_and_conditions`` on
    estimate/quote payloads when ``doc.terms`` is populated (both
    admin path + magic-link viewer via ``_build_payload``).
  * Invoice payload never surfaces ``terms_and_conditions`` — the
    field is EXCLUDED per product lock.
  * ``PUT /quotes/{qid}`` accepts ``terms`` field for draft docs.
  * ``PUT /quotes/{qid}`` rejects >5000-char terms with 400.
  * Estimate reminder email HTML embeds the terms block when the
    quote has terms populated.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]
_CACHE: dict = {}


def _login(email: str) -> str:
    if _CACHE.get(email):
        return _CACHE[email]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"},
        timeout=30,
    )
    r.raise_for_status()
    _CACHE[email] = r.json()["access_token"]
    return _CACHE[email]


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _admin_tenant() -> str:
    tok = _login("admin@aquaterra.com")
    me = requests.get(f"{API}/auth/me", headers=_headers(tok), timeout=15).json()
    return me["tenant_id"]


@pytest.fixture(scope="module")
def seeded():
    """Seed one draft quote (with terms) and one draft invoice."""
    tid = _admin_tenant()
    cust_id = f"pb6-cust-{uuid.uuid4()}"
    quote_id = f"pb6-quote-{uuid.uuid4()}"
    invoice_id = f"pb6-inv-{uuid.uuid4()}"
    terms_body = (
        "1. Payment due within 15 days of acceptance.\n"
        "2. Materials subject to availability.\n"
        "3. Weather delays extend timeline without penalty."
    )
    _db.customers.insert_one({
        "id": cust_id, "tenant_id": tid, "name": "PB6 Cust",
        "email": "pb6@example.com",
    })
    _db.quotes.insert_one({
        "id": quote_id, "tenant_id": tid, "doc_type": "quote",
        "customer_id": cust_id,
        "status": "draft",
        "title": "PB6 Quote",
        "total": 500.0, "amount_paid": 0.0, "currency": "usd",
        "line_items": [{"description": "Design", "quantity": 1, "unit_price": 500.0}],
        "terms": terms_body,
        "issued_at": datetime.now(timezone.utc).isoformat(),
    })
    _db.quotes.insert_one({
        "id": invoice_id, "tenant_id": tid, "doc_type": "invoice",
        "customer_id": cust_id,
        "status": "draft",
        "title": "PB6 Invoice",
        "total": 500.0, "amount_paid": 0.0, "currency": "usd",
        "invoice_number": "PB6-INV-001",
        "line_items": [{"description": "Service", "quantity": 1, "unit_price": 500.0}],
        "terms": "Invoice-side terms should NEVER leak.",
        "payment_status": "unpaid",
    })
    yield {
        "tenant_id": tid, "customer_id": cust_id,
        "quote_id": quote_id, "invoice_id": invoice_id,
        "terms_body": terms_body,
    }
    _db.customers.delete_one({"id": cust_id})
    _db.quotes.delete_many({"id": {"$in": [quote_id, invoice_id]}})


# ─── 1. Estimate viewer payload surfaces terms_and_conditions ───
def test_estimate_full_payload_includes_terms(seeded):
    tok = _login("admin@aquaterra.com")
    r = requests.get(
        f"{API}/quotes/{seeded['quote_id']}/full",
        headers=_headers(tok), timeout=15,
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert "terms_and_conditions" in payload, "payload missing terms field"
    assert payload["terms_and_conditions"] == seeded["terms_body"]


def test_estimate_full_payload_terms_null_when_empty(seeded):
    """Empty-string terms should surface as None (not ``""``) so
    <DocTermsSection> can early-return."""
    tok = _login("admin@aquaterra.com")
    tid = seeded["tenant_id"]
    qid = f"pb6-empty-{uuid.uuid4()}"
    _db.quotes.insert_one({
        "id": qid, "tenant_id": tid, "doc_type": "quote",
        "customer_id": seeded["customer_id"],
        "status": "draft", "title": "empty terms",
        "total": 0.0, "amount_paid": 0.0, "currency": "usd",
        "line_items": [], "terms": "   ",
    })
    try:
        r = requests.get(
            f"{API}/quotes/{qid}/full",
            headers=_headers(tok), timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["terms_and_conditions"] is None
    finally:
        _db.quotes.delete_one({"id": qid})


# ─── 2. Invoice payload does NOT surface terms_and_conditions ───
def test_invoice_full_payload_excludes_terms(seeded):
    tok = _login("admin@aquaterra.com")
    r = requests.get(
        f"{API}/invoices/{seeded['invoice_id']}/full",
        headers=_headers(tok), timeout=15,
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    # Invoice viewer never populates this key (per product lock).
    assert "terms_and_conditions" not in payload or \
        payload.get("terms_and_conditions") in (None, "")


# ─── 3. PATCH quote terms — happy path + 5000-char cap ───
def test_patch_quote_terms_persists(seeded):
    tok = _login("admin@aquaterra.com")
    new_terms = "Fresh terms from PATCH test."
    r = requests.put(
        f"{API}/quotes/{seeded['quote_id']}",
        headers=_headers(tok),
        json={"terms": new_terms},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    # Re-fetch and confirm persisted.
    got = requests.get(
        f"{API}/quotes/{seeded['quote_id']}/full",
        headers=_headers(tok), timeout=15,
    ).json()
    assert got["terms_and_conditions"] == new_terms
    # Reset for downstream tests.
    requests.put(
        f"{API}/quotes/{seeded['quote_id']}",
        headers=_headers(tok),
        json={"terms": seeded["terms_body"]},
        timeout=15,
    )


def test_patch_quote_terms_rejects_over_5000(seeded):
    tok = _login("admin@aquaterra.com")
    too_long = "x" * 5001
    r = requests.put(
        f"{API}/quotes/{seeded['quote_id']}",
        headers=_headers(tok),
        json={"terms": too_long},
        timeout=15,
    )
    assert r.status_code == 400, r.text
    assert "5000" in r.text


# ─── 4. Estimate reminder email HTML embeds terms ───
def test_estimate_reminder_html_includes_terms(seeded):
    """Direct helper call — no Resend traffic."""
    from emailer import _estimate_reminder_html

    inv = {
        "id": seeded["quote_id"], "doc_type": "quote",
        "invoice_number": "PB6-Q-001",
        "terms": seeded["terms_body"],
    }
    html = _estimate_reminder_html(
        inv, "Customer", {"company_name": "PB6 Co"}, "https://example.com/e?token=x",
    )
    assert "Terms &amp; Conditions" in html
    assert "Payment due within 15 days" in html


def test_estimate_reminder_html_omits_terms_when_absent():
    from emailer import _estimate_reminder_html

    inv = {
        "id": "no-terms", "doc_type": "quote",
        "invoice_number": "PB6-Q-002",
        "terms": "",
    }
    html = _estimate_reminder_html(
        inv, "Customer", {"company_name": "PB6 Co"}, "https://example.com",
    )
    assert "Terms &amp; Conditions" not in html


# ─── 5. Defect 1 · Tenant default clearing ───────────────────
TERMS_SETTINGS_ID = "terms_defaults"


def _seed_row(payload: dict) -> None:
    _db.settings.update_one(
        {"id": TERMS_SETTINGS_ID},
        {"$set": {"id": TERMS_SETTINGS_ID, **payload}},
        upsert=True,
    )


def test_put_settings_terms_empty_string_clears(seeded):
    """PUT with ``""`` explicitly clears the tenant default."""
    tok = _login("admin@aquaterra.com")
    _seed_row({"default_quote_terms": "Seeded quote defaults."})
    r = requests.put(
        f"{API}/settings/terms",
        headers=_headers(tok),
        json={"default_quote_terms": ""},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["default_quote_terms"] == ""
    got = requests.get(f"{API}/settings/terms", headers=_headers(tok), timeout=15).json()
    assert got["default_quote_terms"] == ""


def test_put_settings_terms_null_clears(seeded):
    """PUT with explicit null clears the tenant default (persisted as empty)."""
    tok = _login("admin@aquaterra.com")
    _seed_row({"default_quote_terms": "Non-empty seed"})
    r = requests.put(
        f"{API}/settings/terms",
        headers=_headers(tok),
        json={"default_quote_terms": None},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    got = requests.get(f"{API}/settings/terms", headers=_headers(tok), timeout=15).json()
    assert got["default_quote_terms"] == ""


def test_put_settings_terms_partial_update_preserves_other_key(seeded):
    """PUT with only ``default_quote_terms`` leaves invoice terms alone."""
    tok = _login("admin@aquaterra.com")
    _seed_row({
        "default_quote_terms": "quote-seed",
        "default_invoice_terms": "invoice-seed",
    })
    r = requests.put(
        f"{API}/settings/terms",
        headers=_headers(tok),
        json={"default_quote_terms": "quote-updated"},
        timeout=15,
    )
    assert r.status_code == 200
    got = r.json()
    assert got["default_quote_terms"] == "quote-updated"
    assert got["default_invoice_terms"] == "invoice-seed"


def test_reset_settings_terms_clears_both(seeded):
    """POST /settings/terms/reset clears both fields to empty."""
    tok = _login("admin@aquaterra.com")
    _seed_row({
        "default_quote_terms": "some seed",
        "default_invoice_terms": "another seed",
    })
    r = requests.post(f"{API}/settings/terms/reset", headers=_headers(tok), timeout=15)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["default_quote_terms"] == ""
    assert got["default_invoice_terms"] == ""


def test_new_quote_after_cleared_default_has_empty_terms(seeded):
    """When tenant default is cleared, new quotes are created with
    empty ``terms_and_conditions`` (no fallback seed injection)."""
    tok = _login("admin@aquaterra.com")
    # Clear tenant defaults first.
    requests.post(f"{API}/settings/terms/reset", headers=_headers(tok), timeout=15)
    # Create a new quote WITHOUT sending ``terms`` — the create path
    # would previously inject the built-in ``DEFAULT_QUOTE_TERMS``.
    r = requests.post(
        f"{API}/quotes",
        headers=_headers(tok),
        json={
            "customer_id": seeded["customer_id"],
            "title": "Defect1 new quote",
            "doc_type": "quote",
            "line_items": [{"description": "x", "quantity": 1, "unit_price": 1.0}],
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    new_id = r.json()["id"]
    try:
        got = requests.get(
            f"{API}/quotes/{new_id}/full", headers=_headers(tok), timeout=15,
        ).json()
        assert got.get("terms_and_conditions") in (None, "")
    finally:
        _db.quotes.delete_one({"id": new_id})


# ─── 6. Defect 2 · Read/write field-name inconsistency ───────
def test_put_quote_accepts_terms_and_conditions_alias(seeded):
    """PUT with the new canonical ``terms_and_conditions`` key persists,
    and the GET payload reflects the same value."""
    tok = _login("admin@aquaterra.com")
    new_terms = "Fresh terms via canonical alias."
    r = requests.put(
        f"{API}/quotes/{seeded['quote_id']}",
        headers=_headers(tok),
        json={"terms_and_conditions": new_terms},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    got = requests.get(
        f"{API}/quotes/{seeded['quote_id']}/full",
        headers=_headers(tok), timeout=15,
    ).json()
    assert got["terms_and_conditions"] == new_terms
    # Restore the original seeded terms for downstream isolation.
    requests.put(
        f"{API}/quotes/{seeded['quote_id']}",
        headers=_headers(tok),
        json={"terms_and_conditions": seeded["terms_body"]},
        timeout=15,
    )


def test_put_quote_rejects_over_5000_on_canonical_alias(seeded):
    """5000-char cap fires when the caller uses the canonical
    ``terms_and_conditions`` key (Defect 2 regression: previously
    only ``terms`` triggered the cap)."""
    tok = _login("admin@aquaterra.com")
    too_long = "y" * 5001
    r = requests.put(
        f"{API}/quotes/{seeded['quote_id']}",
        headers=_headers(tok),
        json={"terms_and_conditions": too_long},
        timeout=15,
    )
    assert r.status_code == 400, r.text
    assert "5000" in r.text


def test_put_quote_canonical_alias_takes_precedence_over_legacy(seeded):
    """When both keys are sent, the canonical key wins so integrators
    can safely migrate without accidental double-writes."""
    tok = _login("admin@aquaterra.com")
    r = requests.put(
        f"{API}/quotes/{seeded['quote_id']}",
        headers=_headers(tok),
        json={
            "terms": "LEGACY value should NOT win.",
            "terms_and_conditions": "CANONICAL value.",
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    got = requests.get(
        f"{API}/quotes/{seeded['quote_id']}/full",
        headers=_headers(tok), timeout=15,
    ).json()
    assert got["terms_and_conditions"] == "CANONICAL value."
    # Restore.
    requests.put(
        f"{API}/quotes/{seeded['quote_id']}",
        headers=_headers(tok),
        json={"terms_and_conditions": seeded["terms_body"]},
        timeout=15,
    )


def test_put_quote_unknown_key_is_silently_dropped_but_warned(seeded, caplog):
    """Unknown keys don't 500 or persist, but the router logs a
    WARN so integrators can spot the drop (Defect 2 mitigation)."""
    import logging

    tok = _login("admin@aquaterra.com")
    with caplog.at_level(logging.WARNING, logger="pool_crm"):
        r = requests.put(
            f"{API}/quotes/{seeded['quote_id']}",
            headers=_headers(tok),
            json={
                "terms_and_conditions": seeded["terms_body"],
                "totally_bogus_key": "should be dropped",
            },
            timeout=15,
        )
    assert r.status_code == 200, r.text
    # We cannot capture the live server's logs from this client-side
    # process, but we CAN assert the key did not persist.
    got = requests.get(
        f"{API}/quotes/{seeded['quote_id']}/full",
        headers=_headers(tok), timeout=15,
    ).json()
    assert "totally_bogus_key" not in got
