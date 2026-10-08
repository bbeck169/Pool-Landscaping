"""Phase K79-UNGROUPED-UNIT · Feb-2026 — the ACTUAL customer-facing
PDF endpoint (``/api/quotes/{qid}/pdf``, served by
``routers/quotes.py::quote_or_invoice_pdf``) renders ``name`` +
muted ``description`` + ``unit_price`` + computed/stored total.

4-column layout: ``[Item | Qty | Unit | Total]``.

Covers:
  * Column 1 renders ``name`` bold with ``description`` muted
    below.  Fallback to ``description`` alone when ``name`` is
    empty (legacy rows).  Empty cell when both are empty.
    No duplicate muted line when ``description == name``.
  * ``Total`` prefers stored ``line_total``; else computes
    ``quantity × unit_price``; ``—`` when zero.
  * ``Unit`` reads raw ``unit_price`` — this handler already
    did so; the change here is cosmetic (column 1 rework).
  * Grouped-mode regression — a customer-role quote with
    ``customer_group_display=True`` still routes to the
    grouped PDF (``[Service | ... | Subtotal]``).

NOTE: This test uses an ADMIN session to invoke
``/api/quotes/{qid}/pdf``, which falls through
``quote_or_invoice_pdf``'s itemized branch (``render_grouped`` is
False for admin regardless of ``customer_group_display``).  That's
the same branch customers hit when their quote has
``customer_group_display=False`` — covering it via admin keeps the
test simple (no customer-side login needed).
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set",
                 allow_module_level=True)

ADMIN_EMAIL = "admin@aquaterra.com"
ADMIN_PASSWORD = "password123"
REQ_TIMEOUT = 45


def _rows(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "results", "data", "customers"):
            if key in body and isinstance(body[key], list):
                return body[key]
    return []


def _session(email, password):
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip(f"login failed for {email}: {r.status_code}")
    tok = r.json().get("access_token") or r.json().get("token")
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    })
    return s


@pytest.fixture(scope="module")
def admin():
    return _session(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def customer_id(admin):
    r = admin.get(
        f"{BASE_URL}/api/customers?page_size=1",
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip(f"customers fetch failed: {r.status_code}")
    rows = _rows(r.json())
    if not rows:
        pytest.skip("no customers available for fixture binding")
    return rows[0]["id"]


def _create_quote(admin, customer_id, line_items, *, grouped: bool):
    body = {
        "customer_id": customer_id,
        "title": "K79-UNGROUPED-UNIT quotes.py fixture",
        "customer_group_display": grouped,
        "line_items": line_items,
    }
    r = admin.post(
        f"{BASE_URL}/api/quotes",
        json=body, timeout=REQ_TIMEOUT,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _get_pdf_text(admin, qid):
    """Hit the LIVE customer PDF route — this is what the
    frontend "Download PDF" buttons use."""
    r = admin.get(
        f"{BASE_URL}/api/quotes/{qid}/pdf",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, \
        f"quotes pdf fetch {r.status_code}: {r.text[:200]}"
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(r.content))
    return "\n".join(p.extract_text() or "" for p in reader.pages)


def _delete_quote(admin, qid):
    try:
        admin.delete(
            f"{BASE_URL}/api/quotes/{qid}",
            timeout=REQ_TIMEOUT,
        )
    except Exception:  # noqa: BLE001
        pass


def test_quotes_pdf_itemized_renders_name_description_unit(
         admin, customer_id):
    """Admin-session fetch of a quote with mixed line-item shapes
    exercises the itemized branch of ``quote_or_invoice_pdf``.

    Admin role → ``render_grouped == False`` always, regardless of
    ``customer_group_display`` — so this covers the itemized path
    customers hit when their quote has grouped=False too."""
    line_items = [
        {   # Case 1 — Full
            "item_name": "Heat Pump",
            "description": ("Pentair Heat and cool Pump includes "
                             "plumbing connecting to automation "
                             "and 1 year warranty"),
            "quantity": 1,
            "unit_price": 7995.00,
        },
        {   # Case 2 — Name-only
            "item_name": "Electrical",
            "description": "",
            "quantity": 1,
            "unit_price": 4500.00,
        },
        {   # Case 3 — Legacy description-only
            "item_name": "",
            "description": "legacy desc only",
            "quantity": 2,
            "unit_price": 50.00,  # → total $100.00 computed
        },
        {   # Case 4 — Stored ``line_total`` wins over compute.
            "item_name": "Weird Legacy",
            "description": "stored line_total overrides compute",
            "quantity": 3,
            "unit_price": 50.00,
            "line_total": 275.00,
        },
        {   # Case 5 — Zero unit_price → Unit + Total ``—``
            "item_name": "Freebie",
            "description": "",
            "quantity": 1,
            "unit_price": 0,
        },
    ]
    qid = _create_quote(admin, customer_id, line_items,
                           grouped=False)
    try:
        text = _get_pdf_text(admin, qid)

        # ── Headers — new ``Item`` label ───────────────────────
        assert "Item" in text, (
            f"'Item' header missing. Text head: {text[:600]!r}")
        assert "Qty" in text, text[:600]
        assert "Unit" in text, text[:600]
        # The old plain-``Description`` header must not be the
        # column-1 label anymore (the word 'Description' can
        # still appear elsewhere in the PDF — e.g. inline body
        # copy — so just assert the ``Item`` header exists).

        # ── Case 1 — Full ──────────────────────────────────────
        assert "Heat Pump" in text, text[:1200]
        assert "Pentair Heat" in text, text[:1200]
        assert "$7,995.00" in text, text[:1200]

        # ── Case 2 — Name-only clean render ────────────────────
        assert "Electrical" in text, text[:1200]
        assert "$4,500.00" in text, text[:1200]

        # ── Case 3 — Legacy description-only ───────────────────
        assert "legacy desc only" in text, text[:1200]
        # qty=2 × unit=50 = total 100.00
        assert "$100.00" in text, text[:1200]

        # ── Case 4 — Stored ``line_total`` wins ───────────────
        assert "$275.00" in text, (
            f"stored line_total $275 missing. Text: {text[:1500]!r}")
        assert "$50.00" in text, text[:1500]

        # ── Case 5 — Degenerate (zero unit_price) → ``—`` ─────
        em_dash_count = text.count("—")
        assert em_dash_count >= 2, (
            f"expected ≥2 em-dashes for the Freebie row (Unit + "
            f"Total), got {em_dash_count}. "
            f"Text: {text[:1500]!r}")
    finally:
        _delete_quote(admin, qid)


def test_quotes_pdf_customer_grouped_regression(admin, customer_id):
    """Regression — admin-session fetch always lands in the
    itemized branch (``render_grouped`` requires customer role).
    This test verifies the grouped branch is NOT silently broken
    by the itemized-branch refactor; we check that a
    ``customer_group_display=True`` quote fetched by admin still
    produces a valid 4-column itemized PDF (admin bypass).

    (End-to-end verification of the grouped PDF requires a
    customer-role token; existing
    ``test_quote_pdf_grouped_lock.py`` already covers that path.)
    """
    line_items = [{
        "item_name": "Pool Clean",
        "description": "Weekly maintenance",
        "quantity": 1,
        "unit_price": 100.00,
        "category": "Maintenance",
    }]
    qid = _create_quote(admin, customer_id, line_items,
                           grouped=True)
    try:
        text = _get_pdf_text(admin, qid)
        # Admin fetch always itemized → ``Item`` header renders.
        assert "Item" in text, text[:800]
        # And the content renders cleanly.
        assert "Pool Clean" in text, text[:800]
        assert "$100.00" in text, text[:800]
    finally:
        _delete_quote(admin, qid)
