"""PROFIT-REPORT-EBIT-ALIGN · Feb-2026 — pytest regression cover.

The user reported the Profit Report tiles rendering ``$0`` beside
the EBIT panel's correct value on the SAME page.  Root cause: the
Profit Report query filtered on the wrong field — ``status ∈
{paid, partial}`` — while production fully-paid invoices stamp
``status: "accepted"`` + ``payment_status: "paid"`` (see
``routers/quotes.py:2148``).  EBIT used ``payment_status`` so it
worked; Profit Report never matched any docs so it rendered $0.

The fix adds a ``?revenue_basis=cash|accrual`` query param
(default ``cash``) and makes each branch mirror
``services.finance.ebit._load_invoices`` byte-for-byte:

* **cash**     — ``payment_status = "paid"`` filtered on ``paid_at``
* **accrual**  — ``status ∈ {paid, partial, sent, overdue}``
                   filtered on ``created_at``

Partial-invoice proration (``amount_paid/total``) now reads
``payment_status`` for the partial detection branch so partials
actually prorate (the pre-fix code read ``status`` and never
matched).

Assertions covered here:

1. ``_compute`` branch selection — cash shape vs accrual shape.
2. Partial detection reads ``payment_status`` not ``status``.
3. Default revenue basis is ``cash`` (matches EBIT panel default).
4. Invalid ``revenue_basis`` → 422 with ``allowed`` list.
5. Response envelope echoes the resolved basis so the frontend
   can label tiles and so cross-report parity tests can anchor on
   the resolved value.
6. HTTP-level parity: ``/reports/profit?revenue_basis=cash`` and
   ``/ebit/compute?revenue_basis=cash`` return the SAME revenue
   number for the same tenant + range (within a 1¢ rounding
   tolerance to absorb float rounding differences between the
   per-line and header-total paths).

The HTTP parity assertions require a running backend on
``:8001`` and the shared ``admin@aquaterra.com`` seed.  They are
guarded by the ``requests``-based reachability probe used by the
sibling ``test_profit_report.py`` suite so they are a no-op on a
boot where the service hasn't come up yet.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests
from dotenv import dotenv_values


# ─── Backend path shim (matches sibling test_profit_report.py) ───
_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"


# ─── 1. Unit — _compute branch selection ─────────────────────────
class _FakeCursor:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self._docs = docs

    async def to_list(self, _n: int) -> List[Dict[str, Any]]:
        return self._docs


class _QuoteCapture:
    """Capture quotes.find() calls into a dedicated slot so the
    assertion isn't trampled by subsequent category-lookup calls
    on sibling collections (``items`` / ``service_categories``)
    inside ``_compute``."""

    def __init__(self, invoices: List[Dict[str, Any]] | None = None) -> None:
        self.query: Dict[str, Any] | None = None
        self.proj: Dict[str, Any] | None = None
        self._invoices = invoices or []

    def find(self, q: Dict[str, Any], proj: Dict[str, Any]):
        # Only capture the FIRST call (which is the invoice
        # query); subsequent calls would be unexpected on this
        # collection.
        if self.query is None:
            self.query = q
            self.proj = proj
        return _FakeCursor(self._invoices)


class _EmptyColl:
    def find(self, _q: Dict[str, Any], _proj: Dict[str, Any]):
        return _FakeCursor([])


def _build_fake_db(invoices: List[Dict[str, Any]] | None = None):
    """Return (fake_db, quotes_capture) so a test can assert on
    the EXACT query shape built by ``_compute`` without worrying
    about which collection was hit last."""
    class _FakeDB:
        pass
    cap = _QuoteCapture(invoices)
    _FakeDB.quotes = cap
    _FakeDB.service_categories = _EmptyColl()
    _FakeDB.income_categories = _EmptyColl()
    _FakeDB.items = _EmptyColl()
    return _FakeDB(), cap


def test_cash_branch_builds_payment_status_paid_at_query(
    monkeypatch,
) -> None:
    """``revenue_basis='cash'`` must build a query with
    ``payment_status: 'paid'`` + ``paid_at`` boundary, matching
    EBIT cash exactly.  No ``status`` field, no ``created_at``
    filter on the invoice query itself."""
    from routers import profit_report as pr

    fake_db, cap = _build_fake_db()
    monkeypatch.setattr(pr, "db", fake_db)

    import asyncio
    bounds = {"from": "2026-10-01", "to": "2026-10-31",
               "label": "This Month"}
    asyncio.get_event_loop().run_until_complete(
        pr._compute("tenant-x", bounds, "service_category", "cash"),
    )

    q = cap.query
    assert q is not None, "_compute never queried db.quotes"
    assert q["tenant_id"] == "tenant-x"
    assert q["doc_type"] == "invoice"
    assert q["payment_status"] == "paid", (
        "cash branch must filter payment_status='paid' "
        "(mirrors EBIT cash)")
    assert "status" not in q, (
        "cash branch must NOT filter on the ``status`` field — "
        "that was the pre-fix bug")
    assert "paid_at" in q, (
        "cash branch must bucket on paid_at (not created_at)")
    assert "created_at" not in q
    # Projection must pull both payment_status + paid_at so
    # downstream math has what it needs regardless of branch.
    assert cap.proj.get("payment_status") == 1
    assert cap.proj.get("paid_at") == 1


def test_accrual_branch_builds_status_created_at_query(
    monkeypatch,
) -> None:
    """``revenue_basis='accrual'`` must mirror EBIT accrual —
    ``status ∈ {paid, partial, sent, overdue}`` filtered on
    ``created_at``."""
    from routers import profit_report as pr

    fake_db, cap = _build_fake_db()
    monkeypatch.setattr(pr, "db", fake_db)

    import asyncio
    bounds = {"from": "2026-10-01", "to": "2026-10-31",
               "label": "This Month"}
    asyncio.get_event_loop().run_until_complete(
        pr._compute("tenant-x", bounds, "service_category", "accrual"),
    )

    q = cap.query
    assert q is not None, "_compute never queried db.quotes"
    assert set(q["status"]["$in"]) == {
        "paid", "partial", "sent", "overdue",
    }, "accrual branch must mirror EBIT _ELIGIBLE_ACCRUAL_STATUSES"
    assert "created_at" in q
    assert "paid_at" not in q
    assert "payment_status" not in q


# ─── 2. Unit — partial-invoice detection uses payment_status ─────
def test_partial_proration_reads_payment_status_not_status(
    monkeypatch,
) -> None:
    """Pre-fix: ``_compute`` read ``inv.get('status')`` to detect
    partial invoices.  Production doesn't put the ``partial``
    literal in that field, so partials never prorated — they got
    full retail credit which overstated revenue vs cash received.

    After the fix the partial-detection branch reads
    ``payment_status``, which is the actual payment-state field.
    """
    from routers import profit_report as pr

    # One invoice:
    #   • payment_status == "partial"   (new, correct field)
    #   • status == "accepted"          (what production actually
    #                                     stamps — pre-fix code
    #                                     saw this and skipped the
    #                                     partial branch)
    #   • amount_paid = 50, total = 100  → prorate = 0.5
    #   • line_item: qty=1, retail=100  → revenue should be $50
    partial_invoice = {
        "id": "inv-partial-1",
        "doc_type": "invoice",
        "status": "accepted",
        "payment_status": "partial",
        "amount_paid": 50.0,
        "total": 100.0,
        "created_at": "2026-10-15T12:00:00+00:00",
        "paid_at": "2026-10-15T12:00:00+00:00",
        "line_items": [{
            "item_id": "item-1",
            "quantity": 1,
            "retail_price_snapshot": 100,
            "wholesale_price_snapshot": 0,
            "labor_cost_snapshot": 0,
            "service_category_id": "svc-x",
        }],
    }

    fake_db, _ = _build_fake_db([partial_invoice])
    monkeypatch.setattr(pr, "db", fake_db)

    import asyncio
    bounds = {"from": "2026-10-01", "to": "2026-10-31",
               "label": "This Month"}
    out = asyncio.get_event_loop().run_until_complete(
        pr._compute("tenant-x", bounds, "service_category", "accrual"),
    )

    # Pre-fix: $100 (full retail — partial branch skipped).
    # Post-fix: $50 (prorated by amount_paid/total = 0.5).
    assert out["totals"]["revenue"] == 50.0, (
        f"partial-invoice revenue must prorate; got "
        f"{out['totals']['revenue']} (expected 50.0 — if 100.0 "
        f"then the partial detection reverted to reading "
        f"``status`` instead of ``payment_status``)")


# ─── 3. Unit — defaults + validation ─────────────────────────────
def test_revenue_basis_defaults_to_cash() -> None:
    from routers import profit_report as pr
    assert pr._validate_revenue_basis(None) == "cash"
    assert pr._validate_revenue_basis("") == "cash"


def test_revenue_basis_accepts_cash_and_accrual() -> None:
    from routers import profit_report as pr
    assert pr._validate_revenue_basis("cash") == "cash"
    assert pr._validate_revenue_basis("accrual") == "accrual"
    assert pr._validate_revenue_basis("CASH") == "cash"


def test_revenue_basis_422s_on_unknown_value() -> None:
    from fastapi import HTTPException
    from routers import profit_report as pr
    with pytest.raises(HTTPException) as excinfo:
        pr._validate_revenue_basis("fiscal")
    assert excinfo.value.status_code == 422
    detail = excinfo.value.detail
    assert detail.get("error") == "invalid_revenue_basis"
    assert "cash" in detail.get("allowed", [])
    assert "accrual" in detail.get("allowed", [])


def test_response_envelope_echoes_resolved_basis(monkeypatch) -> None:
    """The response must carry back the resolved basis so the
    frontend can label tiles and parity assertions can anchor on
    the server-side value."""
    from routers import profit_report as pr

    fake_db, _ = _build_fake_db()
    monkeypatch.setattr(pr, "db", fake_db)

    import asyncio
    bounds = {"from": "2026-10-01", "to": "2026-10-31",
               "label": "This Month"}
    for basis in ("cash", "accrual"):
        # Re-mount a fresh fake db each loop so the quotes-find
        # capture isn't contaminated by the prior iteration.
        fake_db, _ = _build_fake_db()
        monkeypatch.setattr(pr, "db", fake_db)
        out = asyncio.get_event_loop().run_until_complete(
            pr._compute("tenant-x", bounds, "service_category", basis),
        )
        assert out["revenue_basis"] == basis


# ─── 4. HTTP — Profit vs EBIT parity (guarded) ───────────────────
def _server_up() -> bool:
    try:
        # Backend exposes ``/api/health`` (singular, no "z" suffix).
        # The endpoint runs a schema-migrations status check that
        # can take ~5s on a cold boot, so widen the probe timeout.
        r = requests.get(f"{API}/health", timeout=10)
        return r.status_code < 500
    except requests.RequestException:
        return False


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.mark.skipif(not _server_up(),
                     reason="backend not reachable on :8001 — "
                             "parity assertions are HTTP-based")
@pytest.mark.parametrize("basis", ["cash", "accrual"])
def test_profit_vs_ebit_revenue_parity(basis: str) -> None:
    """The two reports MUST return the same ``revenue`` number for
    the same tenant + range + basis.  This is the user-reported
    bug's end-state regression guard.

    Allows a 1¢ absolute tolerance to absorb float-rounding
    differences between EBIT's ``inv.total``-first path and
    Profit Report's per-line sum path (both end up at the same
    value for well-formed invoices).
    """
    hdr = _admin_headers()
    profit = requests.get(
        f"{API}/reports/profit",
        headers=hdr,
        params={"dimension": "service_category",
                 "range": "this_month",
                 "revenue_basis": basis},
        timeout=20,
    )
    assert profit.status_code == 200, profit.text
    profit_json = profit.json()
    assert profit_json["revenue_basis"] == basis
    profit_revenue = float(profit_json["totals"]["revenue"])

    ebit = requests.get(
        f"{API}/ebit/compute",
        headers=hdr,
        params={"range": "this_month", "revenue_basis": basis},
        timeout=20,
    )
    assert ebit.status_code == 200, ebit.text
    ebit_revenue = float(ebit.json()["revenue"])

    delta = abs(profit_revenue - ebit_revenue)
    assert delta <= 0.01, (
        f"Profit Report ({basis}) revenue={profit_revenue} but "
        f"EBIT ({basis}) revenue={ebit_revenue} — the two reports "
        f"are supposed to be byte-for-byte aligned on invoice "
        f"filters.  Delta={delta}.  If this reappears, re-check "
        f"the query shapes in ``profit_report._compute`` against "
        f"``services.finance.ebit._load_invoices``.")


@pytest.mark.skipif(not _server_up(),
                     reason="backend not reachable on :8001")
def test_profit_default_basis_is_cash() -> None:
    """Omitting ``?revenue_basis=`` must default to cash so the
    page's initial render matches the EBIT panel's initial
    render (cash is EBIT's default too)."""
    hdr = _admin_headers()
    r = requests.get(
        f"{API}/reports/profit",
        headers=hdr,
        params={"dimension": "service_category",
                 "range": "this_month"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    assert r.json()["revenue_basis"] == "cash"


@pytest.mark.skipif(not _server_up(),
                     reason="backend not reachable on :8001")
def test_profit_invalid_basis_returns_422() -> None:
    hdr = _admin_headers()
    r = requests.get(
        f"{API}/reports/profit",
        headers=hdr,
        params={"dimension": "service_category",
                 "range": "this_month",
                 "revenue_basis": "fiscal"},
        timeout=20,
    )
    assert r.status_code == 422, r.text
    body = r.json()
    err = body.get("detail", {})
    assert err.get("error") == "invalid_revenue_basis"
    assert "cash" in err.get("allowed", [])
    assert "accrual" in err.get("allowed", [])
