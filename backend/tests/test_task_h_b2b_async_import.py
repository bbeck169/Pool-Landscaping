"""Task H · Phase B2.B · Feb-2026 — Async PDF-invoice import
router tests.  Locks the async kickoff (202) + status polling
(GET) endpoint contracts + partial-progress preservation on
failure.

Live-server tests hit the running uvicorn process on ``$API``
(rate-limit, kickoff latency, poll 404/cross-tenant); pure-unit
tests exercise the router-internal helpers + ``_run_pipeline``
against monkeypatched extractor/mapper stubs.

Tenant-isolation posture: cross-tenant polls MUST return
``404 batch_not_found`` (never ``403``) so the poll surface
cannot be used as a tenant-membership probe.  See
``test_poll_404_on_cross_tenant_batch``.
"""
from __future__ import annotations

import asyncio
import io
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas as rl_canvas

_TEST_DIR = Path(__file__).resolve().parent
_PDF_DIR = _TEST_DIR / "fixtures" / "pdf"

_FE = dotenv_values(_TEST_DIR.parent.parent / "frontend" / ".env")
_BE = dotenv_values(_TEST_DIR.parent / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture()
def adb():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


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


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


def _synth_pdf(title: str = "B2.B Synth") -> bytes:
    """Tiny valid PDF for tests that don't need real invoices."""
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica", 14)
    c.drawString(72, 720, title)
    c.showPage()
    c.save()
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# §1 · Kickoff-envelope regression guard
# ─────────────────────────────────────────────────────────────
def test_kickoff_returns_202_envelope(admin_h, aquaterra_id, dbc):
    """POST /api/imports/pdf-invoice must return 202 with the
    canonical async envelope shape.  Regression guard against
    accidental sync fallback."""
    pdf_bytes = (_PDF_DIR / "invoice_single_1item_digital.pdf").read_bytes()
    files = {"file": ("kickoff.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    r = requests.post(
        f"{API}/imports/pdf-invoice", headers=admin_h,
        files=files, timeout=15,
    )
    assert r.status_code == 202, r.text
    body = r.json()
    for key in ("batch_id", "status", "poll_hint_seconds",
                 "poll_url", "async"):
        assert key in body, f"missing key {key!r} in envelope: {body}"
    assert body["status"] == "queued"
    assert body["async"] is True
    assert body["poll_url"].endswith(body["batch_id"])
    assert 3 <= body["poll_hint_seconds"] <= 30
    # UUID shape check.
    uuid.UUID(body["batch_id"])
    # Cleanup — kill the batch row + any downstream fanout so
    # subsequent rate-limit tests start clean.
    dbc.import_batches.delete_one({"id": body["batch_id"]})


# ─────────────────────────────────────────────────────────────
# §2 · Kickoff latency (proves the vision calls are NOT blocking)
# ─────────────────────────────────────────────────────────────
def test_kickoff_latency_is_fast(admin_h, aquaterra_id, dbc):
    """Kickoff must return in < 2s even for a real-world 2-page
    invoice fixture.  If a future refactor accidentally makes
    the extractor block the kickoff, this test flags it before
    ingress does."""
    pdf_bytes = (_PDF_DIR / "invoice_single_1item_digital.pdf").read_bytes()
    files = {"file": ("kickoff.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    t0 = time.time()
    r = requests.post(
        f"{API}/imports/pdf-invoice", headers=admin_h,
        files=files, timeout=10,
    )
    dt = time.time() - t0
    assert r.status_code == 202, r.text
    assert dt < 2.0, (
        f"kickoff took {dt:.2f}s -- expected <2s; extractor may be "
        f"blocking the request path"
    )
    dbc.import_batches.delete_one({"id": r.json()["batch_id"]})


# ─────────────────────────────────────────────────────────────
# §3 · Poll endpoint · progress_pct + tenant isolation
# ─────────────────────────────────────────────────────────────
def test_poll_returns_progress_pct(admin_h, aquaterra_id, dbc):
    """Kickoff a batch, immediately poll, assert the poll payload
    includes a computed ``progress_pct`` field."""
    pdf_bytes = (_PDF_DIR / "invoice_single_1item_digital.pdf").read_bytes()
    files = {"file": ("poll.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    r = requests.post(
        f"{API}/imports/pdf-invoice", headers=admin_h,
        files=files, timeout=15,
    )
    assert r.status_code == 202
    batch_id = r.json()["batch_id"]
    try:
        pr = requests.get(
            f"{API}/imports/pdf-invoice/{batch_id}",
            headers=admin_h, timeout=10,
        )
        assert pr.status_code == 200, pr.text
        row = pr.json()
        assert "progress_pct" in row
        assert isinstance(row["progress_pct"], int)
        assert 0 <= row["progress_pct"] <= 100
        assert row["status"] in ("queued", "processing", "preview_complete")
    finally:
        dbc.import_batches.delete_one({"id": batch_id})


def test_poll_404_on_nonexistent_batch(admin_h):
    r = requests.get(
        f"{API}/imports/pdf-invoice/batch-that-does-not-exist-xxx",
        headers=admin_h, timeout=10,
    )
    assert r.status_code == 404, r.text
    detail = r.json().get("detail") or {}
    assert detail.get("error") == "batch_not_found"


def test_poll_404_on_cross_tenant_batch(admin_h, dbc):
    """Tenant-isolation posture: a batch that exists but belongs
    to another tenant MUST return 404 (not 403) so the poll
    surface cannot be used as a tenant-membership probe."""
    # Insert a fake batch row on a synthetic OTHER tenant.
    other_tenant = f"b2b-cross-tenant-{uuid.uuid4().hex[:8]}"
    fake_batch = str(uuid.uuid4())
    dbc.import_batches.insert_one({
        "id": fake_batch,
        "tenant_id": other_tenant,
        "status": "queued",
        "source_filename": "foreign.pdf",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.get(
            f"{API}/imports/pdf-invoice/{fake_batch}",
            headers=admin_h, timeout=10,
        )
        assert r.status_code == 404, r.text
        detail = r.json().get("detail") or {}
        assert detail.get("error") == "batch_not_found"
    finally:
        dbc.import_batches.delete_one({"id": fake_batch})


# ─────────────────────────────────────────────────────────────
# §4 · Status enum source-inspection guard
# ─────────────────────────────────────────────────────────────
def test_status_enum_includes_all_five():
    """Regression guard: the router MUST define all five status
    values so future H.4 cancel work doesn't require re-shipping
    the client-side status-badge switch statement."""
    from routers import imports as _imp

    assert _imp._STATUS_QUEUED == "queued"
    assert _imp._STATUS_PROCESSING == "processing"
    assert _imp._STATUS_PREVIEW_COMPLETE == "preview_complete"
    assert _imp._STATUS_FAILED == "failed"
    assert _imp._STATUS_CANCELLED == "cancelled"
    # Rate-limit set must cover BOTH queued and processing.
    assert set(_imp._IN_FLIGHT_STATUSES) == {"queued", "processing"}


# ─────────────────────────────────────────────────────────────
# §5 · progress_pct helper unit tests
# ─────────────────────────────────────────────────────────────
def test_compute_progress_pct_bands():
    from routers.imports import _compute_progress_pct as pct

    assert pct("queued", None) == 0
    assert pct("processing", "segmentation") == 0
    assert pct("processing", "extraction 0/10") == 5
    # 5% + (10/10 * 65%) = 70%
    assert pct("processing", "extraction 10/10") == 70
    # 70% + (5/10 * 15%) = 77%
    assert pct("processing", "mapping 5/10") == 77
    assert pct("processing", "persisting") == 85
    assert pct("preview_complete", "done") == 100
    # Failed rows preserve the derived pct from stage.
    assert pct("failed", "extraction 5/10") == 5 + int(65 * 0.5)
    # Unknown stage → 0 (defensive).
    assert pct("processing", "banana") == 0


# ─────────────────────────────────────────────────────────────
# §6 · Rate-limit guard still enforced
# ─────────────────────────────────────────────────────────────
def test_rate_limit_still_enforced_at_kickoff(admin_h, aquaterra_id, dbc):
    """Insert 3 fake ``queued`` rows for the tenant, then attempt
    a 4th kickoff — must be rejected with 429 ``import_in_flight``."""
    now = datetime.now(timezone.utc).isoformat()
    seeded = []
    try:
        for _ in range(3):
            bid = f"b2b-rate-limit-seed-{uuid.uuid4().hex[:8]}"
            dbc.import_batches.insert_one({
                "id": bid,
                "tenant_id": aquaterra_id,
                "status": "queued",
                "source_filename": "seed.pdf",
                "created_at": now,
            })
            seeded.append(bid)

        pdf_bytes = _synth_pdf("rate-limit probe")
        files = {"file": ("rl.pdf",
                           io.BytesIO(pdf_bytes), "application/pdf")}
        r = requests.post(
            f"{API}/imports/pdf-invoice", headers=admin_h,
            files=files, timeout=10,
        )
        assert r.status_code == 429, r.text
        detail = r.json().get("detail") or {}
        assert detail.get("error") == "import_in_flight"
    finally:
        for bid in seeded:
            dbc.import_batches.delete_one({"id": bid})


# ─────────────────────────────────────────────────────────────
# §7 · Partial-progress preservation on failure (unit)
# ─────────────────────────────────────────────────────────────
@pytest.mark.anyio
async def test_partial_progress_preserved_on_pipeline_failure(
    aquaterra_id, adb, monkeypatch,
):
    """When the extractor raises mid-processing, ``_run_pipeline``
    must transition the row to ``status=failed`` WITHOUT wiping
    the ``stage`` field or any partial-documents metadata the
    progress callback wrote before the exception.

    Simulates the failure by monkeypatching ``extract`` to write
    two partial-progress updates then raise.  Asserts the poll
    surface would show ``failed at extraction 2/10 -- <error>``.
    """
    from routers import imports as _imp

    batch_id = f"b2b-partial-fail-{uuid.uuid4().hex[:10]}"
    # Seed the queued row exactly as the kickoff endpoint does.
    await adb.import_batches.insert_one({
        "id": batch_id,
        "tenant_id": aquaterra_id,
        "status": "queued",
        "stage": None,
        "source_filename": "partial_fail.pdf",
        "page_count": 20,
        "source_byte_count": 12345,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "admin-1",
    })
    try:
        async def _fake_extract(*, batch_id, progress_callback, **_kwargs):
            # Two successful progress updates, then explode.
            await progress_callback(
                stage="extraction", current=1, total=10,
                partial_documents=[],
            )
            await progress_callback(
                stage="extraction", current=2, total=10,
                partial_documents=[],
            )
            raise RuntimeError("simulated vision RPC blew up")

        monkeypatch.setattr(_imp, "extract", _fake_extract)

        # Use the real motor client so the pipeline's Mongo
        # writes actually land — swap the module-level ``db``
        # inside the router for our test motor client.
        monkeypatch.setattr(_imp, "db", adb)

        await _imp._run_pipeline(
            batch_id=batch_id,
            tenant_id=aquaterra_id,
            source_filename="partial_fail.pdf",
            pdf_bytes=b"%PDF-1.4\n",
            hint_doc_kind=None,
            user_id="admin-1",
        )

        row = await adb.import_batches.find_one({"id": batch_id})
        assert row is not None
        assert row["status"] == "failed"
        assert "simulated vision RPC blew up" in row.get("error", "")
        # Stage preserved from the last successful progress update.
        assert row.get("stage") == "extraction 2/10", (
            f"expected preserved stage 'extraction 2/10', got {row.get('stage')!r}"
        )
        # Computed progress must reflect the failure point.
        pct = _imp._compute_progress_pct(row["status"], row.get("stage"))
        assert 5 < pct < 70, f"unexpected progress on failure: {pct}"
    finally:
        await adb.import_batches.delete_one({"id": batch_id})


# ─────────────────────────────────────────────────────────────
# §8 · Poll-hint heuristic bounds
# ─────────────────────────────────────────────────────────────
def test_poll_hint_seconds_heuristic():
    from routers.imports import _poll_hint_seconds

    assert _poll_hint_seconds(1) == 3          # min bound
    assert _poll_hint_seconds(2) == 3          # min bound
    assert _poll_hint_seconds(5) == 7          # int(5*1.5)
    assert _poll_hint_seconds(20) == 30        # max bound
    assert _poll_hint_seconds(200) == 30       # capped


# ─────────────────────────────────────────────────────────────
# §9 · Sanitizer strips Mongo internals
# ─────────────────────────────────────────────────────────────
def test_sanitize_row_strips_underscore_id_and_stamps_pct():
    from routers.imports import _sanitize_row

    raw = {
        "_id": "mongo-internal-oid",
        "id": "batch-1",
        "tenant_id": "t-1",
        "status": "processing",
        "stage": "extraction 3/48",
    }
    out = _sanitize_row(raw)
    assert "_id" not in out
    assert out["id"] == "batch-1"
    assert "progress_pct" in out
    # 5% + (3/48 * 65%) ≈ 9%
    assert 4 < out["progress_pct"] < 15
