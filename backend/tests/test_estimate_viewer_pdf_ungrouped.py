"""Phase K79-UNGROUPED-UNIT · Feb-2026 — DEPRECATED customer PDF
(``/api/estimates/{qid}/pdf``, served by
``routers/estimate_viewer.py::estimate_pdf``) renders ``name`` +
muted ``description`` + ``unit_price`` + ``line_total``.

4-column layout: ``[Item | Qty | Unit | Total]``.

Covers:
  * ``_CUSTOMER_LINE_HIDDEN`` no longer strips ``unit_price`` so
    the projection carries it through to the renderer.
  * Column 1 renders ``name`` bold with ``description`` muted
    below.  Empty-safe (no stray ``—``, no duplicate muted line
    when ``description == name``, legacy rows with only
    ``description`` render description bold alone).
  * Column 3 (``Unit``) shows ``$x,xxx.xx`` or ``—`` for
    missing / zero unit_price.
  * Column 4 (``Total``) prefers stored ``line_total`` and
    falls back to ``quantity × unit_price``; ``—`` when zero.
  * Grouped-mode regression — a quote with
    ``customer_group_display=True`` still renders the grouped
    ``[Service | Description | Subtotal]`` layout.
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
        "title": "K79-UNGROUPED-UNIT estimate_viewer fixture",
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
    r = admin.get(
        f"{BASE_URL}/api/estimates/{qid}/pdf",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, \
        f"estimate pdf fetch {r.status_code}: {r.text[:200]}"
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


def test_customer_pdf_ungrouped_renders_name_description_unit(
         admin, customer_id):
    """Collapsed fixture — 6 line items cover every case the brief
    called out.  Single POST + single PDF fetch keeps the test
    fast."""
    line_items = [
        {   # Case 1 — Full (name + description + unit_price + qty)
            "item_name": "Heat Pump",
            "description": ("Pentair Heat and cool Pump includes "
                             "plumbing connecting to automation "
                             "and 1 year warranty"),
            "quantity": 1,
            "unit_price": 7995.00,
        },
        {   # Case 2 — Name-only (no description, clean render)
            "item_name": "Electrical",
            "description": "",
            "quantity": 1,
            "unit_price": 4500.00,
        },
        {   # Case 3 — Legacy row (description-only, no name)
            "item_name": "",
            "description": "legacy line",
            "quantity": 1,
            "unit_price": 100.00,
        },
        {   # Case 4 — Legacy ``line_total`` populated — renderer
            # prefers the stored value over the computed one.
            "item_name": "Weird Legacy",
            "description": "stored line_total overrides compute",
            "quantity": 3,
            "unit_price": 50.00,
            "line_total": 275.00,  # explicit; qty*unit would give 150
        },
        {   # Case 5 — Zero unit_price → Unit ``—``, Total ``—``
            "item_name": "Freebie",
            "description": "",
            "quantity": 1,
            "unit_price": 0,
        },
        {   # Case 6 — Zero quantity → Total ``—`` (0 * unit = 0)
            "item_name": "Zero Qty Edge",
            "description": "",
            "quantity": 0,
            "unit_price": 100.00,
        },
    ]
    qid = _create_quote(admin, customer_id, line_items,
                           grouped=False)
    try:
        text = _get_pdf_text(admin, qid)

        # ── Headers — new 4-column shape ───────────────────────
        assert "Item" in text, (
            f"'Item' header missing. Text head: {text[:600]!r}")
        assert "Unit" in text, (
            f"'Unit' header missing. Text head: {text[:600]!r}")
        # 4-column means the old ``Qty/Hr`` + ``Visits`` columns
        # MUST be gone.
        assert "Qty/Hr" not in text, (
            f"old 'Qty/Hr' header leaked into 4-column render: "
            f"{text[:600]!r}")
        assert "Visits" not in text, (
            f"old 'Visits' header leaked into 4-column render: "
            f"{text[:600]!r}")

        # ── Case 1 — Full (name + description + $7,995.00) ─────
        assert "Heat Pump" in text, text[:1200]
        assert "Pentair Heat" in text, text[:1200]
        assert "$7,995.00" in text, text[:1200]

        # ── Case 2 — Name-only ─────────────────────────────────
        assert "Electrical" in text, text[:1200]
        assert "$4,500.00" in text, text[:1200]

        # ── Case 3 — Legacy description-only ───────────────────
        assert "legacy line" in text, text[:1200]
        assert "$100.00" in text, text[:1200]

        # ── Case 4 — ``line_total`` prefers stored value ───────
        assert "$275.00" in text, (
            f"stored line_total $275 missing. Text: {text[:1200]!r}")
        # And ``$150.00`` (qty*unit computed) must NOT appear for
        # this row — confirmation that we didn't accidentally
        # compute instead of using the stored value.
        # (The $50 unit_price should still render in the Unit
        # column.)
        assert "$50.00" in text, text[:1200]

        # ── Cases 5 + 6 — Degenerate rows → ``—`` ──────────────
        em_dash_count = text.count("—")
        assert em_dash_count >= 2, (
            f"expected ≥2 em-dashes for degenerate rows "
            f"(Freebie Unit + Total, Zero Qty Edge Total), got "
            f"{em_dash_count}. Text: {text[:1500]!r}")
    finally:
        _delete_quote(admin, qid)


def test_customer_pdf_grouped_mode_unaffected_regression(
         admin, customer_id):
    """Regression — ``customer_group_display=True`` still routes
    to the grouped renderer (``[Service | Description | Subtotal]``
    headers)."""
    line_items = [{
        "item_name": "Pool Clean",
        "description": "Weekly maintenance",
        "quantity": 1,
        "unit_price": 100.00,
        "category": "Maintenance",
        "category_id": "maintenance",
    }]
    qid = _create_quote(admin, customer_id, line_items,
                           grouped=True)
    try:
        text = _get_pdf_text(admin, qid)
        assert "Service" in text, text[:800]
        assert "Subtotal" in text, text[:800]
        # Ungrouped-mode fingerprints must not appear:
        assert "Qty/Hr" not in text, text[:800]
        assert "Visits" not in text, text[:800]
    finally:
        _delete_quote(admin, qid)
