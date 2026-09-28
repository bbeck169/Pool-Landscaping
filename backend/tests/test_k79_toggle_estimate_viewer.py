"""K79-TOGGLE · Feb-2026 — customer PDF alias branches on
``customer_group_display``.

The deprecated ``/api/estimates/{qid}/pdf`` alias
(``routers.estimate_viewer.estimate_pdf``) must obey the same
un-lock rule as the primary ``/api/quotes/{qid}/pdf`` handler:

  * ``customer_group_display=True``   → grouped customer PDF
  * ``customer_group_display=False``  → itemized customer PDF
  * field absent / None               → grouped (legacy default)
  * ``?internal=1`` (admin only)      → itemized admin PDF
                                         regardless of toggle

Uses the same live HTTP integration harness as
``test_quote_pdf_grouped_lock.py`` + ``test_k79_customer_view_endpoint.py``
— that is the repo's convention for PDF handler tests and side-
steps the "attached to a different loop" trap that in-process
async calls hit when modules cross-import each other's ``db``
binding.
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
    """Resolve the customer's ``customer_id`` via ``/auth/me`` so the
    seeded quote's ``customer_id`` matches what the PDF handler
    enforces on the customer role."""
    r = customer_sess.get(f"{BASE_URL}/api/auth/me", timeout=REQ_TIMEOUT)
    if r.status_code != 200:
        pytest.skip(f"/auth/me failed: {r.status_code}")
    body = r.json()
    cid = (body.get("user") or body).get("customer_id")
    if not cid:
        pytest.skip("customer session has no linked customer_id")
    return cid


@pytest.fixture(scope="module")
def svc_cats(admin_sess):
    r = admin_sess.get(
        f"{BASE_URL}/api/service-categories", timeout=REQ_TIMEOUT,
    )
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert len(rows) >= 2
    return rows[:2]


@pytest.fixture(scope="module")
def inc_cat(admin_sess):
    r = admin_sess.get(
        f"{BASE_URL}/api/income-categories", timeout=REQ_TIMEOUT,
    )
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert rows
    return rows[0]


_CREATED: list[str] = []


@pytest.fixture(scope="module", autouse=True)
def _teardown(admin_sess):
    yield
    for qid in _CREATED:
        try:
            admin_sess.delete(
                f"{BASE_URL}/api/quotes/{qid}", timeout=REQ_TIMEOUT,
            )
        except Exception:
            pass


def _make_quote(
    admin_sess, customer_id, svc_cats, inc_cat, *,
    customer_group_display=None,
):
    """Seed a quote via ``POST /api/quotes``. When
    ``customer_group_display`` is ``None`` the field is omitted so
    the doc mimics a legacy quote (server default backfills to
    ``True`` on create — but the read path still handles missing
    docs, exercised via §3 below with a direct write)."""
    a, b = svc_cats
    body = {
        "customer_id": customer_id,
        "title": "K79-TOGGLE alias PDF probe",
        "doc_type": "quote",
        "line_items": [
            {"description": "Pool cleaning", "quantity": 4,
             "unit_price": 40, "service_category_id": a["id"],
             "income_category_id": inc_cat["id"]},
            {"description": "Grout resealing", "quantity": 1,
             "unit_price": 200, "service_category_id": b["id"],
             "income_category_id": inc_cat["id"]},
        ],
        "customer_group_descriptions": {
            a["id"]: "Weekly service package.",
            b["id"]: "One-time grout job.",
        },
    }
    if customer_group_display is not None:
        body["customer_group_display"] = customer_group_display
    r = admin_sess.post(
        f"{BASE_URL}/api/quotes", json=body, timeout=REQ_TIMEOUT,
    )
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


# ═══════════════════════════════════════════════════════════════════
# §1 · Toggle ON → grouped customer PDF
# ═══════════════════════════════════════════════════════════════════
def test_alias_pdf_renders_grouped_when_toggle_on(
    admin_sess, customer_sess, customer_id, svc_cats, inc_cat,
):
    doc = _make_quote(
        admin_sess, customer_id, svc_cats, inc_cat,
        customer_group_display=True,
    )
    r = customer_sess.get(
        f"{BASE_URL}/api/estimates/{doc['id']}/pdf",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text[:500]
    assert r.content[:4] == b"%PDF"
    text = _pdf_text(r.content)
    # Grouped header row includes ``Service`` + ``Subtotal``.
    assert "Service" in text, "alias PDF missing grouped 'Service' header"
    assert "Subtotal" in text
    # Itemized customer header ``Qty/Hr`` must not appear.
    assert "Qty/Hr" not in text, (
        "alias PDF fell to itemized branch when toggle=True"
    )


# ═══════════════════════════════════════════════════════════════════
# §2 · Toggle OFF → itemized customer PDF
# ═══════════════════════════════════════════════════════════════════
def test_alias_pdf_renders_itemized_when_toggle_off(
    admin_sess, customer_sess, customer_id, svc_cats, inc_cat,
):
    doc = _make_quote(
        admin_sess, customer_id, svc_cats, inc_cat,
        customer_group_display=False,
    )
    r = customer_sess.get(
        f"{BASE_URL}/api/estimates/{doc['id']}/pdf",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text[:500]
    assert r.content[:4] == b"%PDF"
    text = _pdf_text(r.content)
    # Itemized customer PDF header row includes ``Qty/Hr``.
    assert "Qty/Hr" in text, (
        "toggle=False must render itemized customer PDF with "
        "'Qty/Hr' header column"
    )
    # Raw line-item descriptions appear (not category rollups).
    assert "Pool cleaning" in text
    assert "Grout resealing" in text


# ═══════════════════════════════════════════════════════════════════
# §3 · Field absent → grouped (legacy backward-compat)
# ═══════════════════════════════════════════════════════════════════
def test_alias_pdf_renders_grouped_when_field_absent_legacy_default(
    admin_sess, customer_sess, customer_id, svc_cats, inc_cat,
):
    """Legacy quotes with no ``customer_group_display`` field must
    render grouped, matching the prior lock-on behaviour so
    historicals never regress. The create endpoint backfills the
    field to ``True`` on POST, so we scrub it via a direct PUT
    ``$unset`` to reproduce the legacy shape."""
    doc = _make_quote(admin_sess, customer_id, svc_cats, inc_cat)
    # Reset the field to None via PUT so the doc looks like a legacy
    # record that predates K79.
    r = admin_sess.put(
        f"{BASE_URL}/api/quotes/{doc['id']}",
        json={"customer_group_display": None},
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    r = customer_sess.get(
        f"{BASE_URL}/api/estimates/{doc['id']}/pdf",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text[:500]
    text = _pdf_text(r.content)
    assert "Service" in text
    assert "Subtotal" in text
    assert "Qty/Hr" not in text


# ═══════════════════════════════════════════════════════════════════
# §4 · Admin ?internal=1 stays itemized regardless of toggle
# ═══════════════════════════════════════════════════════════════════
def test_alias_pdf_admin_internal_is_itemized_regardless_of_toggle(
    admin_sess, customer_id, svc_cats, inc_cat,
):
    """The ``?internal=1`` admin escape hatch always renders the
    full itemized 6-column admin PDF, no matter what the customer
    toggle says."""
    for toggle in (True, False):
        doc = _make_quote(
            admin_sess, customer_id, svc_cats, inc_cat,
            customer_group_display=toggle,
        )
        r = admin_sess.get(
            f"{BASE_URL}/api/estimates/{doc['id']}/pdf?internal=1",
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 200, r.text[:500]
        assert r.content[:4] == b"%PDF"
        text = _pdf_text(r.content)
        # Admin PDF header row includes ``Cost/Rate`` + ``Margin %``.
        assert "Cost/Rate" in text, (
            f"admin ?internal=1 PDF (toggle={toggle!r}) must show "
            f"'Cost/Rate' header"
        )
        assert "Margin %" in text
        # Raw line-item descriptions appear.
        assert "Pool cleaning" in text
        assert "Grout resealing" in text


# ═══════════════════════════════════════════════════════════════════
# §5 · Auth guard — anonymous fetch is rejected
# ═══════════════════════════════════════════════════════════════════
def test_alias_pdf_requires_auth(
    admin_sess, customer_id, svc_cats, inc_cat,
):
    doc = _make_quote(
        admin_sess, customer_id, svc_cats, inc_cat,
        customer_group_display=True,
    )
    r = requests.get(
        f"{BASE_URL}/api/estimates/{doc['id']}/pdf",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code in (401, 403), (r.status_code, r.text[:200])
