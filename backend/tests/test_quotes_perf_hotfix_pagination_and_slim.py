"""P1 PERF-HOTFIX · Feb-2026 — ``GET /quotes`` default limits +
Shape-A pagination envelope + ``slim=1`` opt-in projection.

Pins three contracts on ``routers.quotes.list_quotes``:

  1. **Backward-compat invariant** — when ``limit`` is absent the
     response is the historical bare array capped at 1000 rows
     with the full ``{_id: 0}`` projection. Every existing caller
     (external tooling, mobile, the broader admin UI) is
     unchanged.
  2. **Shape-A envelope** — when ``limit`` is passed the response
     becomes ``{rows, limit, offset, has_more, total_count}``.
     ``has_more`` is True iff more docs exist beyond the window;
     ``total_count`` is the exact unfiltered-by-pagination count
     for "Showing X of N" UI labels.
  3. **``slim=1`` projection** — drops the four heaviest fields
     (``line_items``, ``pdf_cache``, ``pdf_url_cache``,
     ``legacy_payload``) from every row. All other fields
     (``id``, ``invoice_number``, ``status``, ``payment_status``,
     ``total``, ``customer_name``, ``customer_id``,
     ``created_at``, ``doc_type`` …) are preserved so the
     RecentDocsSection list-row rendering stays feature-complete.

Hermetic — direct handler call with monkey-patched ``db`` against
the preview Mongo. Mirrors the pattern used in
``test_fin_parity_b_list_quotes_payment_status_filter.py``.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(MONGO_URL, io_loop=_LOOP)
_DB = _MC[DB_NAME]

PFX = "TESTpph_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


TENANT = f"{PFX}tenant"
CUSTOMER = f"{PFX}cust_focused"


async def _seed(
    *,
    tenant_id: str = TENANT,
    customer_id: str = CUSTOMER,
    doc_type: str = "invoice",
    extras: Optional[Dict[str, Any]] = None,
    created_at: Optional[str] = None,
) -> str:
    inv_id = f"{PFX}inv_{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": inv_id,
        "tenant_id": tenant_id,
        "doc_type": doc_type,
        "status": "sent",
        "payment_status": "unpaid",
        "total": 100.0,
        "subtotal": 95.0,
        "tax": 5.0,
        "customer_id": customer_id,
        "customer_name": "Test Customer",
        "invoice_number": uuid.uuid4().hex[:6].upper(),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "line_items": [
            {"description": "a", "quantity": 1, "unit_price": 50.0},
            {"description": "b", "quantity": 1, "unit_price": 45.0},
        ],
        "pdf_cache": "SOMEBASE64BODY",
        "pdf_url_cache": "https://example.com/signed-url-cache",
        "legacy_payload": {"source": "import-2024"},
    }
    if extras:
        doc.update(extras)
    await _DB.quotes.insert_one(doc)
    return inv_id


async def _wipe():
    await _DB.quotes.delete_many({"id": {"$regex": f"^{PFX}"}})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


def _call(**overrides):
    """Direct call to list_quotes with reasonable defaults for
    everything the audit test doesn't itself exercise."""
    from routers import quotes as quotes_mod
    orig_db = quotes_mod.db
    quotes_mod.db = _DB
    try:
        kwargs = dict(
            user={"id": "u", "role": "admin", "tenant_id": TENANT},
            tenant={"id": TENANT},
            doc_type="invoice",
            include_deleted=False,
            category=None,
            card_on_file=None,
            customer_id=CUSTOMER,
            payment_status=None,
            view=None,
            limit=None,
            offset=0,
            slim=False,
        )
        kwargs.update(overrides)
        return _run(quotes_mod.list_quotes(**kwargs))
    finally:
        quotes_mod.db = orig_db


# ═════════════════════════════════════════════════════════════════
# §1 · Backward-compat invariant — bare array when limit is absent
# ═════════════════════════════════════════════════════════════════

def test_omit_limit_returns_bare_array_unchanged_shape():
    """When ``limit`` is absent, response is a plain list of docs
    with the full ``{_id: 0}`` projection and the historical
    ``to_list(1000)`` ceiling — zero contract change."""
    for _ in range(3):
        _run(_seed())
    rows = _call()
    assert isinstance(rows, list), (
        "legacy callers (external tooling, mobile, admin UI) "
        "depend on the bare-array response shape when the ``limit`` "
        "query param is absent"
    )
    assert len(rows) == 3
    # Full doc shape preserved (heavy fields still included
    # because ``slim`` defaults to False).
    first = rows[0]
    assert "line_items" in first
    assert "pdf_cache" in first
    assert "pdf_url_cache" in first
    assert "legacy_payload" in first
    # _id is still stripped (historical behaviour).
    assert "_id" not in first


# ═════════════════════════════════════════════════════════════════
# §2 · Shape-A envelope when limit is passed
# ═════════════════════════════════════════════════════════════════

def test_limit_returns_envelope_shape_with_rows_and_pagination_fields():
    """``limit=5`` with 7 seeded rows → envelope with
    ``rows=5 limit=5 offset=0 has_more=True total_count=7``."""
    for i in range(7):
        _run(_seed(created_at=f"2026-01-{i+1:02d}T12:00:00+00:00"))
    out = _call(limit=5)
    assert isinstance(out, dict), (
        "envelope shape required when ``limit`` is passed"
    )
    assert set(out.keys()) == {
        "rows", "limit", "offset", "has_more", "total_count",
    }
    assert out["limit"] == 5
    assert out["offset"] == 0
    assert len(out["rows"]) == 5
    assert out["has_more"] is True
    assert out["total_count"] == 7


def test_limit_returns_has_more_false_when_exactly_at_tail():
    """When the window exactly fits the remaining rows,
    ``has_more`` must be False and the envelope still populated."""
    for _ in range(3):
        _run(_seed())
    out = _call(limit=5)
    assert out["has_more"] is False
    assert len(out["rows"]) == 3
    assert out["total_count"] == 3


def test_offset_pagination_advances_window_correctly():
    """``limit=2 offset=2`` on 5 rows → rows 3 + 4 (0-indexed 2+3).
    Verifies the compound sort + skip math."""
    created = [f"2026-01-{i+1:02d}T12:00:00+00:00" for i in range(5)]
    for ts in created:
        _run(_seed(created_at=ts))
    # Sort is created_at DESC, so the first page returns rows
    # with created_at = 2026-01-05, 04. Second page (offset=2) is
    # 03, 02. Third page (offset=4) is 01, then stops.
    out_p1 = _call(limit=2, offset=0)
    out_p2 = _call(limit=2, offset=2)
    out_p3 = _call(limit=2, offset=4)
    assert [r["created_at"] for r in out_p1["rows"]] == \
           ["2026-01-05T12:00:00+00:00", "2026-01-04T12:00:00+00:00"]
    assert [r["created_at"] for r in out_p2["rows"]] == \
           ["2026-01-03T12:00:00+00:00", "2026-01-02T12:00:00+00:00"]
    assert [r["created_at"] for r in out_p3["rows"]] == \
           ["2026-01-01T12:00:00+00:00"]
    assert out_p1["has_more"] is True
    assert out_p2["has_more"] is True
    assert out_p3["has_more"] is False
    assert out_p1["total_count"] == 5
    assert out_p3["total_count"] == 5


# ═════════════════════════════════════════════════════════════════
# §3 · slim=1 projection
# ═════════════════════════════════════════════════════════════════

_HEAVY_FIELDS = {
    "line_items", "pdf_cache", "pdf_url_cache", "legacy_payload",
}


def test_slim_drops_the_four_heavy_fields_on_bare_array():
    """``slim=1`` with no ``limit`` → bare array, every row missing
    the 4 heavy fields but every other field preserved."""
    _run(_seed())
    rows = _call(slim=True)
    assert isinstance(rows, list)
    row = rows[0]
    for f in _HEAVY_FIELDS:
        assert f not in row, (
            f"``slim=1`` must drop {f!r} — payload hot path"
        )
    # Core list-rendering fields preserved.
    for f in ("id", "invoice_number", "status", "payment_status",
              "total", "subtotal", "tax", "customer_id",
              "customer_name", "created_at", "doc_type"):
        assert f in row, (
            f"``slim=1`` must preserve {f!r} — needed by "
            f"RecentDocsSection list rendering"
        )


def test_slim_drops_heavy_fields_on_envelope_shape_too():
    """``slim=1`` composes with ``limit=X`` — the envelope's
    ``rows`` entries also drop the 4 heavy fields."""
    for _ in range(3):
        _run(_seed())
    out = _call(slim=True, limit=5)
    assert isinstance(out, dict)
    assert "rows" in out
    for row in out["rows"]:
        for f in _HEAVY_FIELDS:
            assert f not in row
        # Core fields still present.
        assert "id" in row
        assert "customer_name" in row
        assert "created_at" in row


def test_slim_absent_default_still_returns_heavy_fields():
    """Backward-compat — if a caller never passes ``slim``, the
    full doc (including the 4 heavy fields) continues to ship.
    This is the invariant that keeps every pre-PERF-HOTFIX caller
    unchanged."""
    _run(_seed())
    rows = _call()  # defaults
    row = rows[0]
    for f in _HEAVY_FIELDS:
        assert f in row, (
            f"regression — ``{f}`` must still be in the response "
            f"by default; ``slim=1`` is strictly opt-in"
        )
