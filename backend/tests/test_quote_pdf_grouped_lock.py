"""Feb-2026 · Quote customer-view grouped-lock — PDF contract test.

Locks the invariant that the customer-facing PDF ALWAYS renders the
grouped layout regardless of the ``customer_group_display`` field's
value on the quote doc. Admin PDF stays itemized (regression guard).

Strategy: hit the live HTTP endpoint (matches the pattern used by
``test_k79_customer_view_endpoint.py``), then use ``pypdf`` to
extract text and check for the grouped-mode markers vs. the
itemized-mode markers.

Both PDF handlers exist:
    * ``routers/quotes.py::quote_or_invoice_pdf`` — resolves the
      ``/api/quotes/{qid}/pdf`` route first (registered before
      ``estimate_viewer``). Post-ship this handler branches to
      grouped for customer role.
    * ``routers/estimate_viewer.py::estimate_pdf`` — the deprecated
      ``/api/estimates/{qid}/pdf`` alias. Also grouped-locked
      post-ship but not the route this test targets.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)

ADMIN_EMAIL = "admin@aquaterra.com"
ADMIN_PASSWORD = "password123"
CUSTOMER_EMAIL = "customer@aquaterra.com"
CUSTOMER_PASSWORD = "password123"
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
def admin_sess():
    return _session(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def customer_sess():
    return _session(CUSTOMER_EMAIL, CUSTOMER_PASSWORD)


@pytest.fixture(scope="module")
def customer_id(customer_sess):
    """Resolve the customer_id via ``GET /api/auth/me`` on the
    customer session — the PDF handler enforces
    ``doc.customer_id == user.customer_id`` for the customer role,
    so the seeded quote's customer_id must match this value.
    """
    r = customer_sess.get(f"{BASE_URL}/api/auth/me", timeout=REQ_TIMEOUT)
    if r.status_code != 200:
        pytest.skip(f"/auth/me failed for customer session: {r.status_code}")
    body = r.json()
    cid = (body.get("user") or body).get("customer_id")
    if not cid:
        pytest.skip("customer session has no linked customer_id")
    return cid


@pytest.fixture(scope="module")
def svc_cats(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/service-categories",
                        timeout=REQ_TIMEOUT)
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert len(rows) >= 2
    return rows[:2]


@pytest.fixture(scope="module")
def inc_cat(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/income-categories",
                        timeout=REQ_TIMEOUT)
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert rows
    return rows[0]


_CREATED: list[str] = []


@pytest.fixture(scope="module", autouse=True)
def _teardown(admin_sess):
    yield
    for qid in _CREATED:
        try:
            admin_sess.delete(f"{BASE_URL}/api/quotes/{qid}",
                                timeout=REQ_TIMEOUT)
        except Exception:
            pass


def _make_quote(admin_sess, customer_id, svc_cats, inc_cat,
                customer_group_display):
    a, b = svc_cats
    body = {
        "customer_id": customer_id,
        "title": "PDF grouped-lock probe",
        "doc_type": "quote",
        "customer_group_display": customer_group_display,
        "customer_group_descriptions": {
            a["id"]: "Weekly service package.",
            b["id"]: "One-time grout job.",
        },
        "line_items": [
            {"description": "Pool cleaning", "quantity": 4,
             "unit_price": 40, "service_category_id": a["id"],
             "income_category_id": inc_cat["id"]},
            {"description": "Grout resealing", "quantity": 1,
             "unit_price": 200, "service_category_id": b["id"],
             "income_category_id": inc_cat["id"]},
        ],
    }
    r = admin_sess.post(f"{BASE_URL}/api/quotes", json=body,
                        timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    doc = r.json()
    _CREATED.append(doc["id"])
    return doc


def _pdf_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader
    from io import BytesIO
    reader = PdfReader(BytesIO(pdf_bytes))
    text = []
    for page in reader.pages:
        try:
            text.append(page.extract_text() or "")
        except Exception:
            pass
    return "\n".join(text)


# ═════════════════════════════════════════════════════════════════════
# Grouped-lock invariants
# ═════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("toggle_value", [True, False])
def test_customer_pdf_always_uses_grouped_layout(
    admin_sess, customer_sess, customer_id, svc_cats, inc_cat, toggle_value,
):
    doc = _make_quote(admin_sess, customer_id, svc_cats, inc_cat,
                       customer_group_display=toggle_value)
    r = customer_sess.get(
        f"{BASE_URL}/api/quotes/{doc['id']}/pdf", timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text[:500]
    assert r.content[:4] == b"%PDF"

    text = _pdf_text(r.content)
    # Grouped-mode marker: the "Service" header + "Subtotal" column
    # + at least one of the service-category labels from svc_cats.
    assert "Service" in text, (
        f"customer PDF missing grouped 'Service' header (toggle={toggle_value})"
    )
    assert "Subtotal" in text
    # Should NOT still show the raw line-item description of "Pool cleaning"
    # in itemized rows (grouped shows the category name + description
    # instead). The category NAME may or may not literally equal
    # "Pool cleaning"; the important guardrail is the header switched.
    assert "Qty" not in text or text.count("Qty") == 0, (
        f"customer PDF fell to itemized branch (toggle={toggle_value}) "
        f"— found 'Qty' header"
    )


def test_admin_pdf_stays_itemized(
    admin_sess, customer_id, svc_cats, inc_cat,
):
    """Regression guard: admin PDF (role != customer) still renders
    the full itemized 4-column table with the raw line items.
    """
    doc = _make_quote(admin_sess, customer_id, svc_cats, inc_cat,
                       customer_group_display=True)
    r = admin_sess.get(
        f"{BASE_URL}/api/quotes/{doc['id']}/pdf", timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"

    text = _pdf_text(r.content)
    # Admin PDF has the itemized header row.
    assert "Description" in text
    assert "Qty" in text, (
        "admin PDF missing 'Qty' header — accidentally rendered grouped"
    )
    # Raw line-item descriptions appear.
    assert "Pool cleaning" in text
    assert "Grout resealing" in text
