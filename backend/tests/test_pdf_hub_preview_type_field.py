"""PDF-HUB · Feb-2026 — preview response ``doc_kind`` exposure.

Locks the wire contract that the poll endpoint
(``GET /api/imports/pdf-invoice/{batch_id}``) surfaces the AI-
classified document kind on every ``mapper_previews[*]`` row.

Field name confirmed: ``doc_kind`` (set on ``MapperReport`` at
``services/imports/pdf_mapper.py:259``). Value is one of
``"invoice"`` / ``"estimate"`` / ``"payment_receipt"``.

This test seeds a preview_complete batch directly (no LLM call),
polls the endpoint, and asserts each preview row exposes
``doc_kind`` in the response body — so the FE Type-column render
has a stable field to bind to.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_TEST_DIR = Path(__file__).resolve().parent
_FE = dotenv_values(_TEST_DIR.parent.parent / "frontend" / ".env")
_BE = dotenv_values(_TEST_DIR.parent / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def aquaterra_id(dbc):
    return dbc.tenants.find_one({"slug": "aquaterra"}, {"id": 1})["id"]


@pytest.fixture(scope="module")
def admin_h():
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "admin@aquaterra.com", "password": "password123"},
        timeout=20,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed_preview_complete_batch(dbc, tenant_id: str,
                                  previews: List[Dict[str, Any]]) -> str:
    """Insert a ``preview_complete`` batch row with the given
    mapper_previews payload — bypasses the LLM extract pipeline
    so we can assert wire-shape invariants deterministically."""
    batch_id = str(uuid.uuid4())
    dbc.import_batches.insert_one({
        "id": batch_id,
        "tenant_id": tenant_id,
        "status": "preview_complete",
        "stage": None,
        "source_filename": "pdf-hub-preview-seed.pdf",
        "page_count": 1,
        "source_byte_count": 100,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "pdf-hub-test",
        "mapper_previews": previews,
    })
    return batch_id


# ═══════════════════════════════════════════════════════════════════
# §1 · Poll response exposes doc_kind on every mapper_preview row
# ═══════════════════════════════════════════════════════════════════
def test_preview_response_exposes_doc_kind(dbc, admin_h, aquaterra_id):
    """Given a preview_complete batch with three previews (one
    invoice, one estimate, one payment_receipt), the poll response
    must surface ``doc_kind`` on every ``mapper_previews[*]`` row."""
    previews = [
        {
            "source_doc_index": 0,
            "doc_kind": "invoice",
            "mapped_target": "quote_in",
            "customer_resolution": "resolved",
            "quote_in": {"doc_number": "INV-001", "grand_total": 100.0},
        },
        {
            "source_doc_index": 1,
            "doc_kind": "estimate",
            "mapped_target": "quote_in",
            "customer_resolution": "resolved",
            "quote_in": {"doc_number": "EST-001", "grand_total": 250.0},
        },
        {
            "source_doc_index": 2,
            "doc_kind": "payment_receipt",
            "mapped_target": "payment_in",
            "customer_resolution": "resolved",
            "payment_in": {"doc_number": "PMT-001", "amount_paid": 50.0},
        },
    ]
    batch_id = _seed_preview_complete_batch(dbc, aquaterra_id, previews)
    try:
        r = requests.get(
            f"{API}/imports/pdf-invoice/{batch_id}",
            headers=admin_h, timeout=10,
        )
        assert r.status_code == 200, r.text
        row = r.json()
        mp = row.get("mapper_previews") or []
        assert len(mp) == 3

        # Field name + values must match what the FE binds to.
        by_index = {p["source_doc_index"]: p for p in mp}
        assert by_index[0]["doc_kind"] == "invoice"
        assert by_index[1]["doc_kind"] == "estimate"
        assert by_index[2]["doc_kind"] == "payment_receipt"

        # Field must be on EVERY row (not just the ones the FE
        # currently renders through the quote_in filter).
        for p in mp:
            assert "doc_kind" in p, (
                f"mapper_preview row missing doc_kind: {p}"
            )
    finally:
        dbc.import_batches.delete_one({"id": batch_id})


def test_preview_doc_kind_field_name_is_stable(dbc, admin_h, aquaterra_id):
    """Regression guard: the field MUST be named ``doc_kind`` — not
    ``document_kind`` or ``type`` or ``kind``. FE Type-column render
    is bound to this exact key."""
    previews = [{
        "source_doc_index": 0,
        "doc_kind": "invoice",
        "mapped_target": "quote_in",
        "customer_resolution": "resolved",
        "quote_in": {"doc_number": "INV-FIELD-NAME", "grand_total": 1.0},
    }]
    batch_id = _seed_preview_complete_batch(dbc, aquaterra_id, previews)
    try:
        r = requests.get(
            f"{API}/imports/pdf-invoice/{batch_id}",
            headers=admin_h, timeout=10,
        )
        row = r.json()
        p = (row.get("mapper_previews") or [{}])[0]
        # These names would silently break the FE Type pill — assert
        # they are NOT present.
        assert "document_kind" not in p
        assert "type" not in p
        assert "kind" not in p
        # Only ``doc_kind`` is canonical.
        assert p.get("doc_kind") == "invoice"
    finally:
        dbc.import_batches.delete_one({"id": batch_id})
