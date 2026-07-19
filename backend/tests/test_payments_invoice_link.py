"""Payments Page · Invoice Link (Feb 2026) — verifies GET /api/payments/list
and GET /api/payments both project the new `invoice_id` + `invoice_number`
fields alongside their existing shape.

The invoice_number field is stored on ``db.quotes`` (e.g. ``INV-2026-000021``)
and is exposed unchanged. Rows without an invoice_number render as
``None`` in the response — the frontend renders `—` for those.
"""
from __future__ import annotations
import os
import requests

from tests.conftest import demo_pw

BACKEND = os.environ.get("REACT_APP_BACKEND_URL") \
    or "https://poolscape-audit.preview.emergentagent.com"
API = f"{BACKEND}/api"
T = 20


def _login(email, pw):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=T)
    r.raise_for_status()
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def test_payments_list_projects_invoice_id_and_invoice_number():
    tok = _login("admin@aquaterra.com", demo_pw("admin@aquaterra.com"))
    r = requests.get(f"{API}/payments/list?page_size=100",
                      headers=_h(tok), timeout=T)
    assert r.status_code == 200
    payload = r.json()
    rows = payload.get("rows") or []
    assert isinstance(rows, list)
    # Every row must carry both keys (values may be None on rows without a
    # populated invoice_number, but the keys must exist so the frontend
    # can safely check them).
    for row in rows:
        assert "invoice_id" in row, f"missing invoice_id on row: {row!r}"
        assert "invoice_number" in row, f"missing invoice_number on row: {row!r}"
        assert row["invoice_id"] == row["id"], \
            "invoice_id must alias id for backward compat"


def test_payments_endpoint_projects_invoice_id_and_invoice_number():
    tok = _login("admin@aquaterra.com", demo_pw("admin@aquaterra.com"))
    r = requests.get(f"{API}/payments", headers=_h(tok), timeout=T)
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    for row in rows:
        assert "invoice_id" in row
        assert "invoice_number" in row
        assert row["invoice_id"] == row["id"]


def test_at_least_one_row_has_a_populated_invoice_number():
    """At least one paid quote in the seeded aquaterra tenant carries an
    ``invoice_number`` — proves the projection actually reaches real data."""
    tok = _login("admin@aquaterra.com", demo_pw("admin@aquaterra.com"))
    r = requests.get(f"{API}/payments/list?page_size=500",
                      headers=_h(tok), timeout=T)
    assert r.status_code == 200
    rows = r.json().get("rows") or []
    populated = [row for row in rows if row.get("invoice_number")]
    assert populated, (
        "expected at least one paid-invoice row with a populated "
        "invoice_number in the seeded aquaterra tenant")
    # Format sanity — invoice numbers in this tenant follow INV-YYYY-######.
    assert populated[0]["invoice_number"].startswith("INV-"), \
        f"unexpected invoice_number shape: {populated[0]['invoice_number']!r}"
