"""Feb-2026 · Repair Calculator — pytest math + endpoint smoke."""
from __future__ import annotations

import os
import uuid
import requests
import pytest
from pathlib import Path
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db()
_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else "http://localhost:8001/api"
)


def _login(email, pw="password123"):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": pw},
                          timeout=15).json()["access_token"]


def _admin():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


def _tech():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


# ── Pure math (mirror the extracted xlsx) ─────────────────────────────
def test_compute_quote_matches_xlsx_example():
    """xlsx cells E3..E26 with 100/100/47 parts and 1.5 hours."""
    from routers.repair_calculator import compute_quote, DEFAULT_CONFIG
    q = compute_quote(
        [{"cost": 100}, {"cost": 100}, {"cost": 47}], 1.5, DEFAULT_CONFIG,
    )
    assert q["parts_subtotal"] == 247.0
    assert q["sales_tax"] == 17.29
    assert q["parts_total"] == 264.29
    assert q["markup"] == 123.5
    assert q["labor"] == 262.5
    assert abs(q["merchant_fees"] - 19.5087) < 0.001
    assert abs(q["estimate_total"] - 669.7987) < 0.001
    assert abs(q["company_cost"] - 396.2987) < 0.001
    assert abs(q["profit_margin_pct"] - 40.83) < 0.01
    assert q["profit_margin_tier"] == "green"


def test_compute_quote_yellow_tier_between_20_and_30():
    """Markup ~20% lands in the yellow band."""
    from routers.repair_calculator import compute_quote, DEFAULT_CONFIG
    cfg = {**DEFAULT_CONFIG, "parts_markup_pct": 0.20}
    q = compute_quote([{"cost": 500}], 0.5, cfg)
    assert 20 <= q["profit_margin_pct"] < 30
    assert q["profit_margin_tier"] == "yellow"


def test_compute_quote_red_tier_when_margin_under_20():
    from routers.repair_calculator import compute_quote, DEFAULT_CONFIG
    cfg = {**DEFAULT_CONFIG, "parts_markup_pct": 0.0,
             "customer_labor_rate": 76.0}
    q = compute_quote([{"cost": 100}], 1.0, cfg)
    assert q["profit_margin_pct"] < 20
    assert q["profit_margin_tier"] == "red"


def test_compute_quote_zero_input_no_divide_by_zero():
    from routers.repair_calculator import compute_quote, DEFAULT_CONFIG
    q = compute_quote([], 0, DEFAULT_CONFIG)
    assert q["estimate_total"] == 0
    assert q["profit_margin"] == 0


# ── Endpoints ────────────────────────────────────────────────────────
def test_quote_endpoint_returns_expected_totals():
    r = requests.post(f"{API}/ops/repair-calculator/quote",
                       headers=_admin(),
                       json={"parts": [{"cost": 100}, {"cost": 100}, {"cost": 47}],
                              "labor_hours": 1.5}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parts_subtotal"] == 247
    assert body["profit_margin_tier"] == "green"


def test_quote_requires_admin():
    r = requests.post(f"{API}/ops/repair-calculator/quote",
                       headers=_tech(),
                       json={"parts": [], "labor_hours": 0}, timeout=15)
    assert r.status_code == 403


def test_config_get_returns_spreadsheet_defaults_when_untouched():
    tid_email = "admin@aquaterra.com"
    tenant_id = _sync.users.find_one({"email": tid_email},
                                        {"_id": 0, "tenant_id": 1})["tenant_id"]
    # Wipe any persisted config so we read the code defaults.
    _sync.tenants.update_one(
        {"id": tenant_id},
        {"$unset": {"settings.repair_calculator_defaults": ""}},
    )
    r = requests.get(f"{API}/ops/repair-calculator/config",
                      headers=_admin(), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["merchant_fees_pct"] == 0.03
    assert body["customer_labor_rate"] == 175.0
    assert body["internal_labor_rate"] == 75.0
    assert body["sales_tax_pct"] == 0.07


def test_config_patch_persists_and_bounds_check():
    r = requests.patch(f"{API}/ops/repair-calculator/config",
                        headers=_admin(),
                        json={"merchant_fees_pct": 0.025}, timeout=15)
    assert r.status_code == 200
    assert r.json()["merchant_fees_pct"] == 0.025
    # Bound-check.
    bad = requests.patch(f"{API}/ops/repair-calculator/config",
                          headers=_admin(),
                          json={"customer_labor_rate": -5}, timeout=15)
    assert bad.status_code == 422
    # Restore.
    requests.patch(f"{API}/ops/repair-calculator/config",
                    headers=_admin(),
                    json={"merchant_fees_pct": 0.03}, timeout=15).raise_for_status()


def test_email_endpoint_requires_recipient():
    r = requests.post(f"{API}/ops/repair-calculator/email",
                       headers=_admin(),
                       json={"subject": "x", "quote_snapshot": {"estimate_total": 100}},
                       timeout=15)
    assert r.status_code == 422


def test_email_endpoint_writes_communications_log_and_quote_row():
    tid = _sync.users.find_one({"email": "admin@aquaterra.com"},
                                  {"_id": 0, "tenant_id": 1})["tenant_id"]
    unique = f"pytest-{uuid.uuid4().hex[:6]}@example.com"
    quote = {
        "line_items": [{"name": "Filter", "cost": 100}],
        "parts_subtotal": 100, "sales_tax": 7, "parts_total": 107,
        "markup": 50, "labor": 175, "merchant_fees": 9.96,
        "estimate_total": 341.96, "company_cost": 191.96,
        "profit_margin": 0.44, "profit_margin_pct": 43.86,
        "profit_margin_tier": "green",
    }
    r = requests.post(f"{API}/ops/repair-calculator/email",
                       headers=_admin(),
                       json={"ad_hoc_email": unique, "subject": "Pytest quote",
                              "quote_snapshot": quote}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["quote_id"]
    assert body["communications_log_id"]

    # Rows exist.
    cl = _sync.communications_log.find_one({"id": body["communications_log_id"]},
                                              {"_id": 0})
    assert cl is not None
    assert cl["trigger_entity"]["kind"] == "repair_quote"
    assert cl["to"] == unique
    assert cl["template"] == "repair_quote_email"

    qrow = _sync.repair_calculator_quotes.find_one({"id": body["quote_id"]},
                                                       {"_id": 0})
    assert qrow is not None
    assert qrow["recipient"] == unique
    assert qrow["quote_snapshot"]["estimate_total"] == 341.96

    # Cleanup.
    _sync.communications_log.delete_one({"id": body["communications_log_id"]})
    _sync.repair_calculator_quotes.delete_one({"id": body["quote_id"]})
