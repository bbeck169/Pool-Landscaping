"""Feb-2026 · Editable Sent Docs · Phase 1 — end-to-end pytest.

Locks in the acceptance criteria for the first phase:

  1. Baseline snapshot invariant — the FIRST edit of a doc that
     has no ``document_versions`` history inserts a v1 baseline
     capturing the pre-edit state, THEN inserts a v2 for the edit.
  2. Second edit inserts v3 (no second baseline).
  3. Confirm-dialog ack unlocks PATCH on paid invoices via
     ``acknowledged_lock_bypass=True``. Missing ack → 409.
  4. ``invoice_number`` / ``quote_number`` mutations are rejected.
  5. Signature invalidation fires on content edits when a signed
     signature row exists.
  6. ``GET /api/documents/{doc_type}/{doc_id}/versions`` returns
     the versions list (metadata only, newest-first).

All tests exercise the live backend via HTTP + pymongo for seeding
(matches ``test_dispatch_route_insert.py`` conventions).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _tenant_of(email: str) -> str:
    return _sync.users.find_one({"email": email})["tenant_id"]


def _seed_paid_invoice(*, status: str = "paid",
                         invoice_number: str = "INV-P0-001") -> dict:
    """Seed a paid invoice on ``db.quotes`` with doc_type='invoice'.

    Returns dict with ``id`` (mongo doc id) and ``marker`` (used
    to clean up).
    """
    tenant_id = _tenant_of("super@aquaterra.com")
    marker = f"P1DOC_{uuid.uuid4().hex[:6]}"
    qid = f"{marker}_INV"
    _sync.quotes.insert_one({
        "id": qid,
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "status": status,
        "payment_status": "paid" if status == "paid" else "unpaid",
        "invoice_number": invoice_number,
        "customer_id": None,
        "title": "Phase 1 paid-invoice fixture",
        "notes": "before-edit notes",
        "terms": "net-30",
        "tax_rate": 0.0,
        "line_items": [{"id": "li1", "description": "Base service",
                          "quantity": 1, "unit_price": 100.0,
                          "extended_price": 100.0}],
        "subtotal": 100.0, "tax": 0.0, "total": 100.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"id": qid, "marker": marker, "tenant_id": tenant_id}


def _seed_draft_quote() -> dict:
    """Seed a draft quote on ``db.quotes``."""
    tenant_id = _tenant_of("super@aquaterra.com")
    marker = f"P1QT_{uuid.uuid4().hex[:6]}"
    qid = f"{marker}_QT"
    _sync.quotes.insert_one({
        "id": qid,
        "tenant_id": tenant_id,
        "doc_type": "quote",
        "status": "draft",
        "customer_id": None,
        "title": "Phase 1 draft quote",
        "notes": "quote notes",
        "line_items": [{"id": "li1", "description": "Item A",
                          "quantity": 2, "unit_price": 50.0,
                          "extended_price": 100.0}],
        "subtotal": 100.0, "tax": 0.0, "total": 100.0,
        "tax_rate": 0.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"id": qid, "marker": marker, "tenant_id": tenant_id}


def _seed_signed_sent_quote() -> dict:
    """Draft quote + a signed signature row so we can trigger
    invalidation on edit."""
    tenant_id = _tenant_of("super@aquaterra.com")
    marker = f"P1SIG_{uuid.uuid4().hex[:6]}"
    qid = f"{marker}_SIG"
    _sync.quotes.insert_one({
        "id": qid,
        "tenant_id": tenant_id,
        "doc_type": "quote",
        "status": "sent",
        "signature_status": "signed",
        "customer_id": None,
        "title": "Phase 1 signed sent quote",
        "notes": "signed quote",
        "line_items": [{"id": "li1", "description": "Item",
                          "quantity": 1, "unit_price": 200.0,
                          "extended_price": 200.0}],
        "subtotal": 200.0, "tax": 0.0, "total": 200.0,
        "tax_rate": 0.0,
    })
    sig_id = f"{marker}_SIG_ROW"
    _sync.signatures.insert_one({
        "id": sig_id,
        "tenant_id": tenant_id,
        "doc_id": qid,
        "signed_at": datetime.now(timezone.utc).isoformat(),
        "signer_email": "customer@x.com",
        "superseded_at": None,
    })
    return {"id": qid, "marker": marker, "tenant_id": tenant_id,
             "sig_id": sig_id}


def _cleanup(marker: str) -> None:
    _sync.quotes.delete_many({"id": {"$regex": f"^{marker}"}})
    _sync.signatures.delete_many({"id": {"$regex": f"^{marker}"}})
    _sync.document_versions.delete_many({"doc_id": {"$regex": f"^{marker}"}})


# ── 1. Baseline snapshot on first edit + v2 for the edit ──────────
def test_first_edit_writes_baseline_and_edit_version():
    seed = _seed_draft_quote()
    try:
        tok = _login("super@aquaterra.com")
        r = requests.put(
            f"{API}/quotes/{seed['id']}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"notes": "updated notes v1"}, timeout=10,
        )
        assert r.status_code == 200, r.text
        rows = list(_sync.document_versions.find(
            {"doc_id": seed["id"]}, {"_id": 0}).sort("version", 1))
        assert len(rows) == 2, f"expected v1+v2, got {[x['version'] for x in rows]}"
        assert rows[0]["version"] == 1 and rows[0]["is_baseline"] is True
        assert rows[0]["snapshot"]["notes"] == "quote notes"
        assert rows[1]["version"] == 2 and rows[1]["is_baseline"] is False
        assert rows[1]["snapshot"]["notes"] == "quote notes"  # PRE-edit
        assert rows[1]["saved_by_user_email"] == "super@aquaterra.com"
    finally:
        _cleanup(seed["marker"])


# ── 2. Second edit → v3 (no second baseline) ──────────────────────
def test_second_edit_appends_v3_no_second_baseline():
    seed = _seed_draft_quote()
    try:
        tok = _login("super@aquaterra.com")
        requests.put(f"{API}/quotes/{seed['id']}",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"notes": "edit A"}, timeout=10).raise_for_status()
        requests.put(f"{API}/quotes/{seed['id']}",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"notes": "edit B"}, timeout=10).raise_for_status()
        rows = list(_sync.document_versions.find(
            {"doc_id": seed["id"]}, {"_id": 0}).sort("version", 1))
        vs = [x["version"] for x in rows]
        assert vs == [1, 2, 3], vs
        # Only one baseline row.
        baselines = [x for x in rows if x["is_baseline"]]
        assert len(baselines) == 1
        # v3 snapshot captures the "edit A" state (pre-edit for v3).
        assert rows[2]["snapshot"]["notes"] == "edit A"
    finally:
        _cleanup(seed["marker"])


# ── 3. Paid invoice — ack unlocks; missing ack → 409 ──────────────
def test_paid_invoice_requires_ack_for_patch():
    seed = _seed_paid_invoice()
    try:
        tok = _login("super@aquaterra.com")
        # Without ack (and without typed invoice_number) → 409.
        r = requests.patch(
            f"{API}/quotes/{seed['id']}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"notes": "sneaky edit"}, timeout=10,
        )
        assert r.status_code == 409, r.text
        # With ack → 200.
        r = requests.patch(
            f"{API}/quotes/{seed['id']}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"notes": "authorized edit",
                    "acknowledged_lock_bypass": True}, timeout=10,
        )
        assert r.status_code == 200, r.text
        # Version row captured lock_bypass_ack=True on v2 (the edit).
        edit_v = _sync.document_versions.find_one(
            {"doc_id": seed["id"], "version": 2}, {"_id": 0})
        assert edit_v is not None
        assert edit_v["lock_bypass_ack"] is True
    finally:
        _cleanup(seed["marker"])


# ── 4. invoice_number / quote_number mutation rejected ────────────
def test_invoice_number_mutation_rejected():
    seed = _seed_paid_invoice(invoice_number="INV-LOCK-1")
    try:
        tok = _login("super@aquaterra.com")
        r = requests.put(
            f"{API}/quotes/{seed['id']}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"invoice_number": "INV-HACK-2",
                    "acknowledged_lock_bypass": True},
            timeout=10,
        )
        # PUT rejects invoice_number as immutable.
        assert r.status_code == 400, r.text
        # DB row is still the original invoice_number.
        row = _sync.quotes.find_one({"id": seed["id"]},
                                       {"_id": 0, "invoice_number": 1})
        assert row["invoice_number"] == "INV-LOCK-1"
    finally:
        _cleanup(seed["marker"])


def test_quote_number_mutation_rejected():
    seed = _seed_draft_quote()
    # Seed a quote_number on this quote so PUT sees a change attempt.
    _sync.quotes.update_one({"id": seed["id"]},
                              {"$set": {"quote_number": "Q-LOCK-1"}})
    try:
        tok = _login("super@aquaterra.com")
        r = requests.put(
            f"{API}/quotes/{seed['id']}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"quote_number": "Q-HACK-2"}, timeout=10,
        )
        assert r.status_code == 400, r.text
        row = _sync.quotes.find_one({"id": seed["id"]},
                                       {"_id": 0, "quote_number": 1})
        assert row["quote_number"] == "Q-LOCK-1"
    finally:
        _cleanup(seed["marker"])


# ── 5. Signature invalidation on content edit ─────────────────────
def test_signature_invalidated_on_content_edit():
    seed = _seed_signed_sent_quote()
    try:
        tok = _login("super@aquaterra.com")
        # Edit a content field (notes) — should invalidate signature.
        r = requests.put(
            f"{API}/quotes/{seed['id']}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"notes": "content changed after signature",
                    "acknowledged_lock_bypass": True},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        sig = _sync.signatures.find_one({"id": seed["sig_id"]},
                                          {"_id": 0})
        assert sig["superseded_at"] is not None, sig
        assert sig.get("superseded_reason") == "doc_edited_after_signature"
        doc = _sync.quotes.find_one({"id": seed["id"]},
                                       {"_id": 0, "signature_status": 1})
        assert doc["signature_status"] == "superseded"
        # Version row flagged.
        edit_v = _sync.document_versions.find_one(
            {"doc_id": seed["id"], "version": 2}, {"_id": 0})
        assert edit_v["signature_invalidated"] is True
    finally:
        _cleanup(seed["marker"])


# ── 6. GET /documents/{doc_type}/{doc_id}/versions ───────────────
def test_get_document_versions_lists_newest_first():
    seed = _seed_draft_quote()
    try:
        tok = _login("super@aquaterra.com")
        requests.put(f"{API}/quotes/{seed['id']}",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"notes": "A"}, timeout=10).raise_for_status()
        requests.put(f"{API}/quotes/{seed['id']}",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"notes": "B"}, timeout=10).raise_for_status()

        r = requests.get(
            f"{API}/documents/quote/{seed['id']}/versions",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["doc_type"] == "quote"
        assert d["doc_id"] == seed["id"]
        assert d["total"] == 3
        # Newest first.
        versions = [x["version"] for x in d["items"]]
        assert versions == [3, 2, 1], versions
        # Metadata-only — no snapshot body leaked.
        for row in d["items"]:
            assert "snapshot" not in row, "snapshot must not be in list view"
            assert "saved_at" in row
            assert "is_baseline" in row
        # URL alias should also resolve.
        r2 = requests.get(
            f"{API}/documents/quotes/{seed['id']}/versions",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        assert r2.status_code == 200
        assert r2.json()["doc_type"] == "quote"
    finally:
        _cleanup(seed["marker"])


# ── 6a. Admin-only ────────────────────────────────────────────────
def test_versions_endpoint_admin_only():
    tok = _login("landscaper@aquaterra.com")  # tech role
    r = requests.get(
        f"{API}/documents/quote/nonexistent/versions",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 403, r.text


# ── 6b. Unknown doc_type → 400 ────────────────────────────────────
def test_versions_endpoint_rejects_unknown_doc_type():
    tok = _login("super@aquaterra.com")
    r = requests.get(
        f"{API}/documents/bogus/some-id/versions",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 400, r.text
