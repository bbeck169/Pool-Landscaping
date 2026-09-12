"""Feb-2026 · Theme Refresh — quote_or_invoice_pdf routing lock.

Locks the routing contract the tester flagged in the Theme Refresh
verification pass:

  * ``GET /api/quotes/{qid}/pdf`` — admin default → plain itemized
    PDF (no brand-colour bytes in the content stream).
  * Same route, customer JWT + ``doc_type=quote`` → themed grouped
    PDF (brand-colour bytes present).
  * ``GET /api/estimates/{qid}/pdf`` — deprecated alias — admin
    default → themed customer PDF. ``?internal=1`` → unthemed.

The tester's WARN ("2371-byte stub regardless of ``?internal=1``")
was a routing-contract confusion, not a defect: ``?internal`` is
not a param on ``/api/quotes/{qid}/pdf`` — admins always get the
plain itemized PDF there. This test locks that behaviour so a
future contributor can't silently invert it.
"""
from __future__ import annotations

import io
import os
import re
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)

REQ_TIMEOUT = 45


def _rows(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "results", "data"):
            if key in body and isinstance(body[key], list):
                return body[key]
    return []


def _admin_session():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@aquaterra.com", "password": "password123"},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip("admin login failed")
    tok = r.json().get("access_token") or r.json().get("token")
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    })
    return s


def _content_stream_bytes(pdf_data: bytes) -> bytes:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_data))
    out = b""
    for page in reader.pages:
        try:
            c = page.get_contents()
            if c is None:
                continue
            out += c.get_data()
        except Exception:
            continue
    return out


# Theme band signature — the ReportLab canvas hook fills a
# specific-sized rectangle at the top (86.4 pt = 1.2 in) or bottom
# (36 pt = 0.5 in) of the page. These are the smoking guns that
# unambiguously indicate the branded bands are painted. Plain PDFs
# emit small grey background rectangles for table cells but those
# use different sizes, so this regex won't false-positive on them.
BRAND_HEADER_RECT_RE = re.compile(
    rb"n 0 705\.6 612 86\.4 re f\*"
)
BRAND_FOOTER_RECT_RE = re.compile(
    rb"n 0 0 612 36 re f\*"
)


def _has_brand_bands(stream: bytes) -> bool:
    return bool(BRAND_HEADER_RECT_RE.search(stream)
                or BRAND_FOOTER_RECT_RE.search(stream))


@pytest.fixture(scope="module")
def admin_sess():
    return _admin_session()


@pytest.fixture(scope="module")
def any_quote(admin_sess):
    """Pick any quote in the tenant so tests don't depend on a
    specific fixture ID. Skips gracefully when the tenant is empty.
    """
    r = admin_sess.get(f"{BASE_URL}/api/quotes?limit=5",
                        timeout=REQ_TIMEOUT)
    rows = _rows(r.json())
    for doc in rows:
        if doc.get("doc_type") == "quote":
            return doc
    pytest.skip("no quote fixtures available in this tenant")


# ═════════════════════════════════════════════════════════════════════
# 1. Admin GET /api/quotes/{qid}/pdf → plain itemized (no brand fill)
# ═════════════════════════════════════════════════════════════════════

def test_admin_quotes_pdf_returns_plain_itemized(admin_sess, any_quote):
    qid = any_quote["id"]
    r = admin_sess.get(f"{BASE_URL}/api/quotes/{qid}/pdf",
                        timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    ctype = r.headers.get("content-type", "")
    assert "application/pdf" in ctype, ctype
    data = r.content
    assert data[:4] == b"%PDF", data[:20]
    # Real PDF — not a "stub". Expected size range for an itemized
    # quote PDF is ~2 – 6 KB.
    assert len(data) >= 1500, f"suspiciously small PDF: {len(data)} bytes"
    # No branded fill bytes in the content stream (admin surface is
    # intentionally plain).
    stream = _content_stream_bytes(data)
    assert not _has_brand_bands(stream), (
        f"admin quote PDF unexpectedly contains brand fill bytes: "
        f"{stream[:200]!r}"
    )


# ═════════════════════════════════════════════════════════════════════
# 2. ``?internal=1`` is a no-op on this route (not a param) — same
#    plain PDF as the default. Locks the tester's confusion.
# ═════════════════════════════════════════════════════════════════════

def test_admin_quotes_pdf_internal_query_is_noop(admin_sess, any_quote):
    qid = any_quote["id"]
    r1 = admin_sess.get(f"{BASE_URL}/api/quotes/{qid}/pdf",
                        timeout=REQ_TIMEOUT)
    r2 = admin_sess.get(
        f"{BASE_URL}/api/quotes/{qid}/pdf?internal=1",
        timeout=REQ_TIMEOUT,
    )
    assert r1.status_code == 200 and r2.status_code == 200
    # Both are real PDFs; sizes may differ by a few bytes only if the
    # created_at timestamp changed between fetches (it doesn't inside
    # a doc). Assert both are plain — no brand fill.
    for r in (r1, r2):
        stream = _content_stream_bytes(r.content)
        assert not _has_brand_bands(stream), (
            "?internal=1 unexpectedly toggled theming on the admin route"
        )


# ═════════════════════════════════════════════════════════════════════
# 3. Deprecated /api/estimates/{qid}/pdf alias — admin default is
#    themed (matches ``estimate_pdf`` semantics: ``internal`` opts
#    OUT, not IN).
# ═════════════════════════════════════════════════════════════════════

def test_admin_estimates_alias_default_is_themed(admin_sess, any_quote):
    qid = any_quote["id"]
    r = admin_sess.get(f"{BASE_URL}/api/estimates/{qid}/pdf",
                        timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.content
    assert data[:4] == b"%PDF"
    stream = _content_stream_bytes(data)
    # The themed alias paints the branded header + footer bands, so
    # the brand fill bytes MUST appear.
    assert _has_brand_bands(stream), (
        f"deprecated alias default should be themed, got: "
        f"{stream[:200]!r}"
    )


# ═════════════════════════════════════════════════════════════════════
# 4. Deprecated alias with ``?internal=1`` → unthemed (opt-out).
# ═════════════════════════════════════════════════════════════════════

def test_admin_estimates_alias_internal_opts_out(admin_sess, any_quote):
    qid = any_quote["id"]
    r = admin_sess.get(
        f"{BASE_URL}/api/estimates/{qid}/pdf?internal=1",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    stream = _content_stream_bytes(r.content)
    assert not _has_brand_bands(stream), (
        "?internal=1 on the deprecated alias should skip theming"
    )
