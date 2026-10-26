"""Ticket II · Feb-2026 — Auto-Billing New Plan modal pricebook link.

Covers the backend contract introduced by Commit A:

  * ``POST /billing-plans`` with ``pricebook_item_id`` → the plan doc
    persists the id alongside the snapshot ``service`` / ``amount``
    (which the FE copies from the catalogue entry on selection).
  * Backward compat: ``POST /billing-plans`` WITHOUT the field still
    succeeds (existing free-text fallback path on the modal) and the
    plan doc simply omits ``pricebook_item_id`` or stores ``null``.
  * Snapshot pattern verification — the plan carries the free-text
    ``service`` value the FE sent at create time, independent of
    whatever the referenced pricebook item currently says.  (The
    plan→invoice generator continues to use ``plan.service`` as the
    line_items[0].description source; a separate pytest already
    locks the generator path — this file only covers persistence.)
  * No new endpoint, no new validation, no generator change.  The
    field is a traceability pointer only.
"""
import os
import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": email, "password": password}, timeout=45)
    r.raise_for_status()
    return r.json()["access_token"]


def _pick_customer_id(admin_tok: str) -> str:
    r = requests.get(f"{BASE}/api/customers?is_active=true",
                     headers={"Authorization": f"Bearer {admin_tok}"},
                     timeout=45)
    r.raise_for_status()
    rows = r.json()
    assert isinstance(rows, list) and rows, "need at least one customer"
    return rows[0]["id"]


def _cleanup(admin_tok: str, pid: str) -> None:
    # Best-effort — the DD test suite already covers delete semantics.
    try:
        requests.post(f"{BASE}/api/billing-plans/bulk-delete",
                      headers={"Authorization": f"Bearer {admin_tok}"},
                      json={"ids": [pid]}, timeout=30)
    except Exception:
        pass


def test_ii_plan_persists_pricebook_item_id() -> None:
    admin = _login("admin@aquaterra.com")
    cid = _pick_customer_id(admin)
    fake_item_id = f"ii-item-{uuid.uuid4().hex[:8]}"
    body = {
        "customer_id": cid,
        "service": "Weekly Pool Cleaning",
        "frequency": "weekly",
        "amount": 120.0,
        "next_run": "2026-03-02",
        "run_schedule": "first_of_month",
        "pricebook_item_id": fake_item_id,
    }
    r = requests.post(f"{BASE}/api/billing-plans",
                      headers={"Authorization": f"Bearer {admin}"},
                      json=body, timeout=45)
    r.raise_for_status()
    plan = r.json()
    try:
        # Snapshot fields echo back verbatim.
        assert plan["service"] == "Weekly Pool Cleaning"
        assert plan["amount"] == 120.0
        # The pricebook pointer round-trips.
        assert plan.get("pricebook_item_id") == fake_item_id, plan
    finally:
        _cleanup(admin, plan["id"])


def test_ii_plan_without_pricebook_item_id_still_creates() -> None:
    """Backward-compat: the free-text fallback path on the modal."""
    admin = _login("admin@aquaterra.com")
    cid = _pick_customer_id(admin)
    body = {
        "customer_id": cid,
        "service": "Ad-hoc Service",
        "frequency": "monthly",
        "amount": 99.0,
        "run_schedule": "first_of_month",
    }
    r = requests.post(f"{BASE}/api/billing-plans",
                      headers={"Authorization": f"Bearer {admin}"},
                      json=body, timeout=45)
    r.raise_for_status()
    plan = r.json()
    try:
        assert plan["service"] == "Ad-hoc Service"
        # No id persisted (either absent or None).
        assert plan.get("pricebook_item_id") in (None, "")
    finally:
        _cleanup(admin, plan["id"])


def test_ii_plan_run_generates_invoice_with_snapshot_service() -> None:
    """Snapshot pattern: ``plan.service`` remains the authoritative
    line_items[0].description source on generated invoices even
    though the FE sourced it from a pricebook catalogue entry."""
    admin = _login("admin@aquaterra.com")
    cid = _pick_customer_id(admin)
    body = {
        "customer_id": cid,
        "service": "Snapshot Service Label",
        "frequency": "monthly",
        "amount": 55.0,
        "next_run": "2026-03-02",
        "run_schedule": "first_of_month",
        "pricebook_item_id": "ii-snapshot-item",
    }
    r = requests.post(f"{BASE}/api/billing-plans",
                      headers={"Authorization": f"Bearer {admin}"},
                      json=body, timeout=45)
    r.raise_for_status()
    plan = r.json()
    try:
        rr = requests.post(f"{BASE}/api/billing-plans/{plan['id']}/run",
                           headers={"Authorization": f"Bearer {admin}"},
                           timeout=45)
        rr.raise_for_status()
        gen = rr.json()
        invoice_id = gen.get("invoice_id")
        assert invoice_id, gen
        # Fetch the generated invoice via the quotes router (invoices
        # share the quotes collection).
        inv_r = requests.get(f"{BASE}/api/quotes/{invoice_id}",
                             headers={"Authorization": f"Bearer {admin}"},
                             timeout=45)
        inv_r.raise_for_status()
        inv = inv_r.json()
        line_items = inv.get("line_items") or []
        assert line_items, inv
        assert line_items[0]["description"] == "Snapshot Service Label"
    finally:
        _cleanup(admin, plan["id"])
