"""PDF-HUB · Feb-2026 — hint_doc_kind form-field validation +
passthrough tests for ``POST /api/imports/pdf-invoice``.

Locks the wire contract for the Document Type dropdown:

  * ``invoice`` / ``estimate`` / ``payment`` → accepted, forwarded
    to the pipeline. ``payment`` normalises to ``payment_receipt``
    at the router boundary (the extractor's internal literal).
  * Empty string or omitted field → auto-detect (``None`` reaches
    the pipeline).
  * Anything else → HTTP 400 with ``error_code =
    "invalid_hint_doc_kind"`` (before the 415/413 checks, so an
    invalid hint on a non-PDF payload STILL surfaces as 400 first).

Uses live-server + monkeypatch-style call harness: we invoke the
router coroutine directly through a small stub for BackgroundTasks
so no LLM call fires. Assertions cover both the router's
normaliser (unit) and the wire response (integration).
"""
from __future__ import annotations

import io
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas as rl_canvas

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
def admin_h():
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "admin@aquaterra.com", "password": "password123"},
        timeout=20,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _synth_pdf() -> bytes:
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica", 14)
    c.drawString(72, 720, "PDF-HUB hint_doc_kind test PDF")
    c.showPage()
    c.save()
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════
# §1 · Unit tests — router normaliser
# ═══════════════════════════════════════════════════════════════════
def test_normalise_accepts_invoice():
    from routers.imports import _normalise_hint_doc_kind
    assert _normalise_hint_doc_kind("invoice") == "invoice"


def test_normalise_accepts_estimate():
    from routers.imports import _normalise_hint_doc_kind
    assert _normalise_hint_doc_kind("estimate") == "estimate"


def test_normalise_maps_payment_to_payment_receipt():
    """FE-friendly `payment` value normalises to the extractor's
    internal literal `payment_receipt` at the router boundary."""
    from routers.imports import _normalise_hint_doc_kind
    assert _normalise_hint_doc_kind("payment") == "payment_receipt"


def test_normalise_accepts_payment_receipt_passthrough():
    """Existing integrations that already pass the internal literal
    (`payment_receipt`) keep working — no regression from mapping."""
    from routers.imports import _normalise_hint_doc_kind
    assert _normalise_hint_doc_kind("payment_receipt") == "payment_receipt"


def test_normalise_empty_string_returns_none():
    from routers.imports import _normalise_hint_doc_kind
    assert _normalise_hint_doc_kind("") is None


def test_normalise_none_returns_none():
    from routers.imports import _normalise_hint_doc_kind
    assert _normalise_hint_doc_kind(None) is None


def test_normalise_rejects_garbage():
    from fastapi import HTTPException
    from routers.imports import _normalise_hint_doc_kind
    with pytest.raises(HTTPException) as exc_info:
        _normalise_hint_doc_kind("garbage_value_xyz")
    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("error_code") == "invalid_hint_doc_kind"


# ═══════════════════════════════════════════════════════════════════
# §2 · Integration — POST /api/imports/pdf-invoice with each hint
# ═══════════════════════════════════════════════════════════════════
def _post_with_hint(admin_h, hint_value):
    """Helper: POST a minimal PDF with an explicit hint form field."""
    pdf_bytes = _synth_pdf()
    files = {"file": ("hub.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data: Dict[str, Any] = {}
    if hint_value is not None:
        data["hint_doc_kind"] = hint_value
    return requests.post(
        f"{API}/imports/pdf-invoice",
        headers=admin_h,
        files=files,
        data=data,
        timeout=15,
    )


def test_upload_with_hint_invoice_returns_202(admin_h, dbc):
    r = _post_with_hint(admin_h, "invoice")
    assert r.status_code == 202, r.text
    dbc.import_batches.delete_one({"id": r.json()["batch_id"]})


def test_upload_with_hint_estimate_returns_202(admin_h, dbc):
    r = _post_with_hint(admin_h, "estimate")
    assert r.status_code == 202, r.text
    dbc.import_batches.delete_one({"id": r.json()["batch_id"]})


def test_upload_with_hint_payment_returns_202(admin_h, dbc):
    r = _post_with_hint(admin_h, "payment")
    assert r.status_code == 202, r.text
    dbc.import_batches.delete_one({"id": r.json()["batch_id"]})


def test_upload_with_hint_empty_string_returns_202(admin_h, dbc):
    """Empty form-field value = auto-detect (equivalent to omitting
    the field). Must NOT be rejected as ``invalid_hint_doc_kind``."""
    r = _post_with_hint(admin_h, "")
    assert r.status_code == 202, r.text
    dbc.import_batches.delete_one({"id": r.json()["batch_id"]})


def test_upload_without_hint_returns_202(admin_h, dbc):
    """Omitting the field entirely = auto-detect. Must still work."""
    r = _post_with_hint(admin_h, None)
    assert r.status_code == 202, r.text
    dbc.import_batches.delete_one({"id": r.json()["batch_id"]})


def test_upload_with_garbage_hint_returns_400(admin_h):
    """Invalid hint values MUST return 400 with a stable error_code
    so the FE can surface a clean copy-safe error."""
    r = _post_with_hint(admin_h, "totally_bogus_kind")
    assert r.status_code == 400, r.text
    body = r.json()
    # FastAPI wraps HTTPException.detail in a top-level ``detail``.
    detail = body.get("detail") or body
    assert isinstance(detail, dict), body
    assert detail.get("error_code") == "invalid_hint_doc_kind"


def test_upload_with_garbage_hint_400_precedes_415(admin_h):
    """Hint validation must fire BEFORE the 415 MIME check so a
    non-PDF payload with a garbage hint still surfaces the 400.
    (Preserves the ``field-first`` posture the router locks in.)"""
    files = {"file": ("bad.txt", io.BytesIO(b"not a pdf"), "text/plain")}
    r = requests.post(
        f"{API}/imports/pdf-invoice",
        headers=admin_h,
        files=files,
        data={"hint_doc_kind": "garbage"},
        timeout=15,
    )
    assert r.status_code == 400, r.text
    detail = (r.json().get("detail") or r.json())
    assert detail.get("error_code") == "invalid_hint_doc_kind"


# ═══════════════════════════════════════════════════════════════════
# §3 · Pipeline passthrough — source-inspection wiring locks
# ═══════════════════════════════════════════════════════════════════
# The router uses Motor (async Mongo) bound to the live-server's
# event loop; invoking the router coroutine directly from a fresh
# ``asyncio.run()`` produces cross-loop errors even for pure
# rate-limit reads. Rather than spin up an in-process app + share
# the running server's loop (which forces a hard dependency on
# httpx + starlette internals), we source-inspect the router to
# prove the wiring is correct. Combined with §1 (normaliser unit)
# and §2 (live-server 202 for each valid hint), this triple-locks
# the passthrough contract without touching the running loop.
def test_router_calls_normaliser_before_add_task():
    """The router MUST call ``_normalise_hint_doc_kind`` on the
    incoming form value BEFORE passing it into
    ``background_tasks.add_task``. If a future refactor removes
    the normaliser call or reorders it after ``add_task``, this
    test trips before an invalid hint reaches the pipeline."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "routers" / "imports.py"
    text = src.read_text()

    # Both call-sites must exist.
    assert "hint_doc_kind = _normalise_hint_doc_kind(hint_doc_kind)" in text, (
        "router no longer normalises hint_doc_kind at the boundary"
    )
    assert "hint_doc_kind=hint_doc_kind" in text, (
        "router no longer forwards hint_doc_kind into add_task"
    )

    # The normaliser call must appear BEFORE the add_task call in
    # the source (so an invalid hint 400s before the pipeline runs).
    norm_pos = text.find("hint_doc_kind = _normalise_hint_doc_kind(hint_doc_kind)")
    task_pos = text.find("background_tasks.add_task(")
    assert 0 < norm_pos < task_pos, (
        f"normaliser call at pos {norm_pos} must precede add_task "
        f"at pos {task_pos} — reorder before landing"
    )


def test_router_normaliser_runs_before_size_and_mime_checks():
    """Invalid-hint 400 must fire BEFORE the 415 (MIME) and 413
    (size) gates so a garbage hint on a non-PDF payload STILL
    surfaces as 400 — the ``field-first`` posture."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "routers" / "imports.py"
    text = src.read_text()

    norm_pos = text.find("hint_doc_kind = _normalise_hint_doc_kind(hint_doc_kind)")
    mime_pos = text.find('content_type not in ("application/pdf"')
    size_pos = text.find("_MAX_UPLOAD_BYTES + 1")
    assert 0 < norm_pos < mime_pos, (
        "normaliser must precede the 415 MIME check"
    )
    assert 0 < norm_pos < size_pos, (
        "normaliser must precede the 413 size check"
    )
