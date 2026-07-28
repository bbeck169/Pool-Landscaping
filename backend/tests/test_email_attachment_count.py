"""Phase B1 · Feb 2026 — Email attachment-count copy tests.

The invoice/estimate email builders should render:

    "3 attachments included"    when N == 3
    "1 attachment included"     when N == 1
    (nothing at all)            when N == 0

The copy sits above the CTA button so recipients can see whether
inline attachments they've reviewed on the CRM are also on this
email — matches F2b product intent.
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from emailer import _reminder_html  # noqa: E402


BASE_INV = {
    "id": "inv-1",
    "title": "Test Invoice",
    "total": 100.0,
    "amount_paid": 0.0,
    "due_date": "2026-03-01",
    "tenant_id": "t-1",
}


def test_reminder_html_no_attachments_omits_line():
    html = _reminder_html(BASE_INV, "Brian", attachment_count=0)
    assert "attachment" not in html.lower(), \
        "Expected no attachment copy when N == 0"


def test_reminder_html_one_attachment_singular():
    html = _reminder_html(BASE_INV, "Brian", attachment_count=1)
    assert "1 attachment included" in html
    assert "1 attachments included" not in html  # no wrong plural


def test_reminder_html_multiple_attachments_plural():
    html = _reminder_html(BASE_INV, "Brian", attachment_count=3)
    assert "3 attachments included" in html


def test_reminder_html_default_kwarg_is_zero():
    """Callers that don't know about attachments still get a clean
    email (no attachment line). Belt-and-braces vs. legacy call sites."""
    html = _reminder_html(BASE_INV, "Brian")
    assert "attachment" not in html.lower()


def test_reminder_html_negative_treated_as_zero():
    html = _reminder_html(BASE_INV, "Brian", attachment_count=-2)
    assert "attachment" not in html.lower()
