"""Feb-2026 · Pricebook × Profit-Reporting Phase 3.

Coverage:
  1. Effective-value math — overrides win over snapshots.
  2. Partial-invoice proration on revenue; costs untouched.
  3. Tax exclusion (subtotal-only math).
  4. Uncategorized bucket for null-snapshot lines.
  5. Response envelope shape (from/to/group_by/rows/currency/assumptions).
  6. CSV headers + row parity with JSON.
  7. Admin-only guard.
  8. ``/reports/pricebook-health`` math.
"""
from __future__ import annotations

import csv
import io
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]
_CACHE: dict = {}


def _login(email: str = "admin@aquaterra.com") -> str:
    if _CACHE.get(email):
        return _CACHE[email]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"},
        timeout=30,
    )
    r.raise_for_status()
    _CACHE[email] = r.json()["access_token"]
    return _CACHE[email]


def _hdr(email: str = "admin@aquaterra.com") -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


def _tenant_of(email: str) -> str:
    u = _db.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1})
    assert u, f"seed user {email} missing"
    return u["tenant_id"]


_TID = _tenant_of("admin@aquaterra.com")


@pytest.fixture(scope="module")
def seed():
    """Seed:
      * 2 service cats (Svc_A, Svc_B) + 1 income cat (Inc_A)
      * 2 items, each bound to Svc_A
      * inv_paid  — 2 lines, both snapshots present, bound to Svc_A
      * inv_partial — 1 line, snapshots present, bound to Svc_B;
                       amount_paid = total/2 → 50% prorate
      * inv_override — 1 line, override wholesale=99, override
                        labor=11 (should win over snapshots 10/2)
      * inv_legacy — 1 line, NO snapshots → Uncategorized (svc dim)
      * inv_taxy — 1 line, has tax on invoice total; only pre-tax
                    subtotal contributes to revenue.
      * inv_sent (should be EXCLUDED — status not in {paid,partial})
    """
    now = datetime.now(timezone.utc).isoformat()
    svc_a = f"pb3-svc-a-{uuid.uuid4()}"
    svc_b = f"pb3-svc-b-{uuid.uuid4()}"
    inc_a = f"pb3-inc-a-{uuid.uuid4()}"
    item_1 = f"pb3-item-1-{uuid.uuid4()}"
    item_2 = f"pb3-item-2-{uuid.uuid4()}"
    _db.service_categories.insert_many([
        {"id": svc_a, "tenant_id": _TID, "name": "PB3 Svc A", "is_archived": False},
        {"id": svc_b, "tenant_id": _TID, "name": "PB3 Svc B", "is_archived": False},
    ])
    _db.income_categories.insert_one(
        {"id": inc_a, "tenant_id": _TID, "name": "PB3 Inc A", "is_archived": False},
    )
    _db.items.insert_many([
        {"id": item_1, "tenant_id": _TID, "name": "PB3 Item 1",
          "service_category_id": svc_a, "active": True, "unit_price": 100},
        {"id": item_2, "tenant_id": _TID, "name": "PB3 Item 2",
          "service_category_id": svc_a, "active": True, "unit_price": 50},
    ])
    invs = {
        "inv_paid": f"pb3-inv-paid-{uuid.uuid4()}",
        "inv_partial": f"pb3-inv-partial-{uuid.uuid4()}",
        "inv_override": f"pb3-inv-override-{uuid.uuid4()}",
        "inv_legacy": f"pb3-inv-legacy-{uuid.uuid4()}",
        "inv_taxy": f"pb3-inv-taxy-{uuid.uuid4()}",
        "inv_sent": f"pb3-inv-sent-{uuid.uuid4()}",
    }
    _db.quotes.insert_many([
        # inv_paid — Svc_A × 2 lines
        {"id": invs["inv_paid"], "tenant_id": _TID, "doc_type": "invoice",
          "status": "paid", "amount_paid": 300, "customer_id": "c",
          "created_at": now, "total": 300, "subtotal": 300, "tax": 0,
          "line_items": [
              {"description": "L1", "quantity": 2, "unit_price": 100,
               "item_id": item_1, "retail_price_snapshot": 100,
               "wholesale_price_snapshot": 20, "labor_cost_snapshot": 10,
               "income_category_id": inc_a},
              {"description": "L2", "quantity": 1, "unit_price": 100,
               "item_id": item_2, "retail_price_snapshot": 100,
               "wholesale_price_snapshot": 30, "labor_cost_snapshot": 5,
               "income_category_id": inc_a},
          ]},
        # inv_partial — Svc_B, 50% paid → 50% revenue proration
        {"id": invs["inv_partial"], "tenant_id": _TID, "doc_type": "invoice",
          "status": "partial", "amount_paid": 100, "customer_id": "c",
          "created_at": now, "total": 200, "subtotal": 200, "tax": 0,
          "line_items": [
              {"description": "PP", "quantity": 1, "unit_price": 200,
               "service_category_id": svc_b,
               "retail_price_snapshot": 200,
               "wholesale_price_snapshot": 40, "labor_cost_snapshot": 20,
               "income_category_id": inc_a},
          ]},
        # inv_override — override wholesale (99) + labor (11)
        {"id": invs["inv_override"], "tenant_id": _TID, "doc_type": "invoice",
          "status": "paid", "amount_paid": 100, "customer_id": "c",
          "created_at": now, "total": 100, "subtotal": 100, "tax": 0,
          "line_items": [
              {"description": "OV", "quantity": 1, "unit_price": 100,
               "service_category_id": svc_a,
               "retail_price_snapshot": 100,
               "wholesale_price_snapshot": 10, "labor_cost_snapshot": 2,
               "wholesale_cost_override": 99.0,
               "labor_cost_override": 11.0,
               "income_category_id": inc_a},
          ]},
        # inv_legacy — no snapshots + no service cat → Uncategorized
        {"id": invs["inv_legacy"], "tenant_id": _TID, "doc_type": "invoice",
          "status": "paid", "amount_paid": 100, "customer_id": "c",
          "created_at": now, "total": 100, "subtotal": 100, "tax": 0,
          "line_items": [
              {"description": "LEGACY", "quantity": 1, "unit_price": 100},
          ]},
        # inv_taxy — has tax on invoice but line-level pre-tax retail = 50
        {"id": invs["inv_taxy"], "tenant_id": _TID, "doc_type": "invoice",
          "status": "paid", "amount_paid": 55, "customer_id": "c",
          "created_at": now, "total": 55, "subtotal": 50, "tax": 5,
          "tax_rate": 0.10,
          "line_items": [
              {"description": "TX", "quantity": 1, "unit_price": 50,
               "service_category_id": svc_a,
               "retail_price_snapshot": 50,
               "wholesale_price_snapshot": 10, "labor_cost_snapshot": 5,
               "income_category_id": inc_a},
          ]},
        # inv_sent — must be EXCLUDED (status not in {paid, partial})
        {"id": invs["inv_sent"], "tenant_id": _TID, "doc_type": "invoice",
          "status": "sent", "customer_id": "c",
          "created_at": now, "total": 999, "subtotal": 999,
          "line_items": [
              {"description": "SENT-only", "quantity": 1, "unit_price": 999,
               "service_category_id": svc_a,
               "retail_price_snapshot": 999,
               "wholesale_price_snapshot": 100, "labor_cost_snapshot": 50,
               "income_category_id": inc_a},
          ]},
    ])
    yield {
        "svc_a": svc_a, "svc_b": svc_b, "inc_a": inc_a,
        "item_1": item_1, "item_2": item_2, "invs": invs,
    }
    _db.quotes.delete_many({"id": {"$in": list(invs.values())}})
    _db.items.delete_many({"id": {"$in": [item_1, item_2]}})
    _db.service_categories.delete_many({"id": {"$in": [svc_a, svc_b]}})
    _db.income_categories.delete_one({"id": inc_a})


def _q(seed_ids, dim="service_category", **extra):
    params = {"group_by": dim, "range": "ytd", **extra}
    r = requests.get(f"{API}/reports/profit",
                     headers=_hdr(), params=params, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


# ─── 1. Envelope shape ─────────────────────────────────────────
def test_envelope_shape(seed):
    payload = _q(seed)
    for key in ("from", "to", "group_by", "currency", "rows",
                "totals", "assumptions"):
        assert key in payload, f"envelope missing key: {key}"
    assert payload["currency"] == "USD"
    assert payload["group_by"] == "service_category"
    # rows === breakdown (canonical alias)
    assert payload["rows"] == payload["breakdown"]
    assumptions = payload["assumptions"]
    assert "partial_invoices" in assumptions
    assert "tax" in assumptions
    assert "null_snapshots" in assumptions
    assert "override_precedence" in assumptions


# ─── 2. Overrides win over snapshots ───────────────────────────
def test_overrides_win_over_snapshots(seed):
    payload = _q(seed)
    svc_a_row = next(
        (r for r in payload["rows"] if r["category_id"] == seed["svc_a"]),
        None,
    )
    assert svc_a_row, "expected Svc_A row"
    # Svc_A carries inv_paid (2 lines) + inv_override (1 line) + inv_taxy (1 line).
    # inv_override line: revenue=100, cogs=99 (override), labor=11 (override).
    # inv_paid lines: revenue=200+100=300, cogs=40+30=70, labor=20+5=25.
    # inv_taxy line: revenue=50, cogs=10, labor=5.
    # Expected Svc_A totals:
    #   revenue = 100 + 300 + 50 = 450
    #   cogs    = 99  + 70  + 10 = 179
    #   labor   = 11  + 25  + 5  = 41
    #   profit  = 450 - 179 - 41 = 230
    assert svc_a_row["revenue"] == 450.0
    assert svc_a_row["cogs"] == 179.0
    assert svc_a_row["labor"] == 41.0
    assert svc_a_row["profit"] == 230.0


# ─── 3. Partial-invoice proration ──────────────────────────────
def test_partial_invoice_proration(seed):
    payload = _q(seed)
    svc_b_row = next(
        (r for r in payload["rows"] if r["category_id"] == seed["svc_b"]),
        None,
    )
    assert svc_b_row, "expected Svc_B row"
    # inv_partial: 200 revenue at 50% prorate → 100.
    # Costs (40 wholesale + 20 labor) NOT prorated per assumption.
    assert svc_b_row["revenue"] == 100.0
    assert svc_b_row["cogs"] == 40.0
    assert svc_b_row["labor"] == 20.0
    assert svc_b_row["profit"] == 40.0


# ─── 4. Tax exclusion ──────────────────────────────────────────
def test_tax_excluded_from_revenue(seed):
    """The taxy invoice has total=55 (50 subtotal + 5 tax). Only the
    pre-tax line retail (50) should contribute to revenue.

    We already assert ``svc_a_row["revenue"] == 450`` in
    ``test_overrides_win_over_snapshots``. If the aggregator wrongly
    included the 5-unit tax, that would be 455. This test locks in
    the specific taxy invoice's line-level revenue contribution."""
    payload = _q(seed)
    svc_a_row = next(
        (r for r in payload["rows"] if r["category_id"] == seed["svc_a"]),
        None,
    )
    assert svc_a_row, "expected Svc_A row"
    # inv_paid=300 + inv_override=100 + inv_taxy=50 → 450 (pre-tax).
    # If tax leaked, this becomes 455. Assert the exact pre-tax figure.
    assert svc_a_row["revenue"] == 450.0
    # And revenue matches subtotal-only math (no + tax) — locked.
    assert svc_a_row["revenue"] not in (455.0, 460.0)


# ─── 5. Uncategorized bucket for null-snapshot lines ───────────
def test_uncategorized_bucket_svc_dim(seed):
    payload = _q(seed)
    uncat = next(
        (r for r in payload["rows"] if r["category_id"] == "__uncategorized__"),
        None,
    )
    assert uncat, "expected Uncategorized row"
    # inv_legacy contributes revenue=100, cogs=0, labor=0. Tenant may
    # carry other legacy Uncategorized lines from prior fixtures; assert
    # by presence + inv_legacy's contribution being included.
    assert uncat["revenue"] >= 100.0
    assert uncat["line_count"] >= 1


# ─── 6. inv_sent EXCLUDED (status filter) ──────────────────────
def test_sent_status_is_excluded(seed):
    payload = _q(seed)
    # inv_sent has revenue 999 which we know is NOT present in totals.
    assert payload["totals"]["revenue"] < 999.0


# ─── 7. CSV parity with JSON ───────────────────────────────────
def test_csv_headers_and_row_parity(seed):
    payload = _q(seed)
    r = requests.get(
        f"{API}/reports/profit.csv",
        headers=_hdr(),
        params={"group_by": "service_category", "range": "ytd"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    disp = r.headers["content-disposition"]
    assert "profit_report_" in disp and ".csv" in disp
    rows = list(csv.DictReader(io.StringIO(r.text)))
    # Header row
    assert rows[0]["category_id"] == "__totals__"
    assert float(rows[0]["revenue"]) == payload["totals"]["revenue"]
    # Same count as JSON breakdown (+1 for the totals row).
    assert len(rows) == 1 + len(payload["rows"])
    # Row parity — every JSON row ID appears in CSV.
    csv_ids = {r["category_id"] for r in rows}
    for jrow in payload["rows"]:
        assert jrow["category_id"] in csv_ids


# ─── 8. Admin-only guard ───────────────────────────────────────
def test_admin_only_guard(seed):
    """Non-admin (manager) must be rejected."""
    r = requests.get(
        f"{API}/reports/profit",
        headers=_hdr("manager@aquaterra.com"),
        params={"group_by": "service_category", "range": "ytd"},
        timeout=30,
    )
    assert r.status_code == 403, r.text
    r_csv = requests.get(
        f"{API}/reports/profit.csv",
        headers=_hdr("manager@aquaterra.com"),
        params={"group_by": "service_category", "range": "ytd"},
        timeout=30,
    )
    assert r_csv.status_code == 403


# ─── 9. Pricebook-health endpoint math ─────────────────────────
def test_pricebook_health_math(seed):
    r = requests.get(
        f"{API}/reports/pricebook-health",
        headers=_hdr(), params={"window_days": 47}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("window_days", "as_of", "lines_total",
                "lines_with_wholesale_snapshot",
                "lines_with_labor_snapshot",
                "lines_with_any_snapshot", "coverage_pct"):
        assert key in body, f"health envelope missing: {key}"
    assert body["window_days"] == 47
    # Fixture-only counts: 5 lines with wholesale snapshot
    # (inv_paid×2, inv_partial, inv_override, inv_taxy),
    # 5 lines with labor snapshot (same set),
    # 1 legacy line WITHOUT snapshots, and inv_sent EXCLUDED (status).
    # Tenant may carry other paid invoices; assert lower bounds.
    assert body["lines_total"] >= 6
    assert body["lines_with_wholesale_snapshot"] >= 5
    assert body["lines_with_labor_snapshot"] >= 5
    # Non-zero coverage percentages
    assert body["coverage_pct"]["wholesale"] > 0
    assert body["coverage_pct"]["labor"] > 0
    assert body["coverage_pct"]["any"] > 0


def test_pricebook_health_admin_only(seed):
    r = requests.get(
        f"{API}/reports/pricebook-health",
        headers=_hdr("manager@aquaterra.com"),
        timeout=30,
    )
    assert r.status_code == 403


# ─── 10. Explicit from/to shape works ──────────────────────────
def test_explicit_from_to_shape(seed):
    """The Phase 3 canonical query shape (``from=YYYY-MM-DD&to=YYYY-MM-DD``
    with no preset ``range`` param) must succeed."""
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    r = requests.get(
        f"{API}/reports/profit",
        headers=_hdr(),
        params={"group_by": "service_category",
                "from": yesterday, "to": today},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["from"] == yesterday
    assert payload["to"] == today



# ---------------------------------------------------------------------------
# Feb-2026 · Batch-verify follow-up · 401 vs 403 auth-guard contract
# ---------------------------------------------------------------------------
# ``HTTPBearer(auto_error=False)`` + explicit ``creds is None`` gate in
# ``utils.get_current_user`` mean the three admin report endpoints now
# distinguish:
#   * No / malformed ``Authorization`` header → 401 (RFC 7235
#     "credentials required").
#   * Authenticated but wrong role                → 403 (Forbidden).
#   * Admin                                        → 200.
# ---------------------------------------------------------------------------

_REPORT_ROUTES = [
    "/reports/profit",
    "/reports/profit.csv",
    "/reports/pricebook-health",
]


@pytest.mark.parametrize("path", _REPORT_ROUTES)
def test_report_endpoints_return_401_without_token(path):
    """No ``Authorization`` header → 401, never 403."""
    r = requests.get(f"{API}{path}", timeout=15)
    assert r.status_code == 401, (
        f"{path} returned {r.status_code} for unauthenticated request; "
        f"expected 401. body={r.text[:200]!r}"
    )


@pytest.mark.parametrize("path", _REPORT_ROUTES)
def test_report_endpoints_return_401_for_malformed_token(path):
    """Bogus bearer token → 401 (invalid), never 403."""
    r = requests.get(
        f"{API}{path}",
        headers={"Authorization": "Bearer not-a-real-jwt"},
        timeout=15,
    )
    assert r.status_code == 401, (
        f"{path} returned {r.status_code} for malformed token; expected 401."
    )


@pytest.mark.parametrize("path", _REPORT_ROUTES)
def test_report_endpoints_return_403_for_manager(path):
    """Authenticated ``role='manager'`` → 403 (insufficient role)."""
    r = requests.get(
        f"{API}{path}", headers=_hdr("manager@aquaterra.com"), timeout=15,
    )
    assert r.status_code == 403, (
        f"{path} returned {r.status_code} for manager; expected 403."
    )


@pytest.mark.parametrize("path", _REPORT_ROUTES)
def test_report_endpoints_return_200_for_admin(path):
    """``role='admin'`` → 200 (baseline sanity)."""
    # Profit endpoints require ``group_by`` + a date range — pass
    # both so the 200-sanity check exercises the auth-guard path,
    # not query validation. ``pricebook-health`` has no required
    # params.
    params = (
        {"group_by": "service_category", "range": "ytd"}
        if path.startswith("/reports/profit")
        else None
    )
    r = requests.get(f"{API}{path}", headers=_hdr(), params=params, timeout=30)
    assert r.status_code == 200, (
        f"{path} returned {r.status_code} for admin; expected 200. "
        f"body={r.text[:200]!r}"
    )
