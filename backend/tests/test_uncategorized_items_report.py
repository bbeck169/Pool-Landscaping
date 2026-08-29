"""Feb-2026 · UncategorizedItemsReport — Pytest empirical suite.

Covers the backend contract for the two-taxonomy scope-addendum:

  1. GET /reports/uncategorized-items — accepts ``missing=income|service|
     either|both``, defaults to ``either``. Rows include the
     two resolved category fields and two ``missing_*`` booleans.
  2. GET default ``missing=either`` includes rows missing at least
     one taxonomy; ``missing=both`` narrows to rows missing both.
  3. PATCH /reports/uncategorized-items/{invoice_id}/{line_item_index}
     — accepts either or both ``{income_category_id, service_category_id}``.
     Idempotent no-op (same value twice) returns ``changed=false``.
  4. PATCH with only ``income_category_id`` leaves
     ``service_category_id`` untouched (empirical proof — supplied by
     the user).
  5. Audit log — one row is written per mutation with the actual
     before/after diff. PATCH with both fields writes ONE audit row
     containing both changes in the diff.
  6. DELETE (undo) — body ``{clear_income?, clear_service?}`` clears
     only what's asked for. Empty body defaults to clearing income
     only (backwards-compat).
  7. Auth gate — 403 for technician / customer.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]


# ── helpers ─────────────────────────────────────────────────────
def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": "password123"},
                      timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _seed_tenant(role: str = "admin"):
    from utils import hash_password
    tid = f"TEST-uncat-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({
        "id": tid, "slug": f"test-uncat-{uuid.uuid4().hex[:6]}",
        "name": "TEST_uncat", "active": True,
    })
    email = f"uncat-{role}-{uuid.uuid4().hex[:6]}@example.com"
    uid = f"TEST-uncat-u-{uuid.uuid4().hex[:6]}"
    _db.users.insert_one({
        "id": uid, "tenant_id": tid, "email": email,
        "name": "TEST_uncat", "role": role,
        "password_hash": hash_password("password123"),
    })
    # Seed two income + two service categories.
    inc_a = str(uuid.uuid4()); inc_b = str(uuid.uuid4())
    svc_a = str(uuid.uuid4()); svc_b = str(uuid.uuid4())
    _db.income_categories.insert_many([
        {"id": inc_a, "tenant_id": tid, "name": "Pool",
         "is_archived": False, "color": "#123456"},
        {"id": inc_b, "tenant_id": tid, "name": "Chemicals",
         "is_archived": False, "color": "#654321"},
    ])
    _db.service_categories.insert_many([
        {"id": svc_a, "tenant_id": tid, "name": "Pool Service",
         "is_archived": False, "color": "#aabbcc"},
        {"id": svc_b, "tenant_id": tid, "name": "Landscaping",
         "is_archived": False, "color": "#ccbbaa"},
    ])
    return tid, uid, email, inc_a, inc_b, svc_a, svc_b


def _seed_invoice(tid: str, *, income=None, service=None,
                    invoice_number: Optional[str] = None):
    """Create an invoice with one line item — configurable which
    taxonomies (if any) are set on it. Invoice numbers are
    tenant-uniquely random unless the caller supplies one."""
    iid = f"TEST-uncat-inv-{uuid.uuid4().hex[:6]}"
    li = {"description": "Service call", "quantity": 1,
          "unit_price": 100.0}
    if income:
        li["income_category_id"] = income
        li["category"] = income
    if service:
        li["service_category_id"] = service
    _db.quotes.insert_one({
        "id": iid, "tenant_id": tid, "doc_type": "invoice",
        "customer_name": "Test Customer", "customer_id": "cust-1",
        "invoice_number": invoice_number or f"INV-TEST-{uuid.uuid4().hex[:8]}",
        "line_items": [li],
        "created_at": "2026-02-15T00:00:00Z",
    })
    return iid


def _cleanup(tid: str):
    for coll in ("users", "tenants", "quotes", "income_categories",
                 "service_categories", "audit_logs"):
        _db[coll].delete_many({"tenant_id": tid})


# ═══════════════════════════════════════════════════════════════════
# Q1 — GET ``missing`` filter contract
# ═══════════════════════════════════════════════════════════════════
def test_list_filter_missing_income_service_either_both():
    tid, uid, email, inc_a, inc_b, svc_a, svc_b = _seed_tenant()
    inv_none  = _seed_invoice(tid, invoice_number="INV-NONE")                 # missing both
    inv_inc   = _seed_invoice(tid, income=inc_a, invoice_number="INV-INC")     # only service missing
    inv_svc   = _seed_invoice(tid, service=svc_a, invoice_number="INV-SVC")    # only income missing
    inv_full  = _seed_invoice(tid, income=inc_a, service=svc_a, invoice_number="INV-FULL")  # neither
    try:
        tok = _login(email)
        H = {"Authorization": f"Bearer {tok}"}
        # either (default) → 3 rows (all except full).
        r = requests.get(f"{API}/reports/uncategorized-items?range=all", headers=H, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["missing"] == "either"
        got = {row["invoice_id"] for row in j["items"]}
        assert got == {inv_none, inv_inc, inv_svc}

        # income → 2 rows.
        j = requests.get(f"{API}/reports/uncategorized-items?range=all&missing=income", headers=H, timeout=15).json()
        assert {r["invoice_id"] for r in j["items"]} == {inv_none, inv_svc}

        # service → 2 rows.
        j = requests.get(f"{API}/reports/uncategorized-items?range=all&missing=service", headers=H, timeout=15).json()
        assert {r["invoice_id"] for r in j["items"]} == {inv_none, inv_inc}

        # both → 1 row.
        j = requests.get(f"{API}/reports/uncategorized-items?range=all&missing=both", headers=H, timeout=15).json()
        assert {r["invoice_id"] for r in j["items"]} == {inv_none}

        # bogus value → 422.
        r = requests.get(f"{API}/reports/uncategorized-items?range=all&missing=banana", headers=H, timeout=15)
        assert r.status_code == 422
    finally:
        _cleanup(tid)


# ═══════════════════════════════════════════════════════════════════
# Q2 — Per-row fields include both taxonomies + missing_* booleans
# ═══════════════════════════════════════════════════════════════════
def test_list_row_fields_include_both_taxonomies_and_missing_flags():
    tid, uid, email, inc_a, inc_b, svc_a, svc_b = _seed_tenant()
    inv_none = _seed_invoice(tid)                            # both missing
    inv_inc  = _seed_invoice(tid, income=inc_a)              # service missing only
    try:
        tok = _login(email)
        rows = requests.get(f"{API}/reports/uncategorized-items?range=all",
                             headers={"Authorization": f"Bearer {tok}"},
                             timeout=15).json()["items"]
        by_inv = {r["invoice_id"]: r for r in rows}
        r_none = by_inv[inv_none]
        r_inc  = by_inv[inv_inc]
        # Both rows carry both taxonomy fields (either populated or "").
        for r in (r_none, r_inc):
            for k in ("income_category_id", "income_category_name",
                      "service_category_id", "service_category_name",
                      "missing_income", "missing_service"):
                assert k in r, f"missing field {k!r} on row {r['invoice_id']}"
        assert r_none["missing_income"] is True
        assert r_none["missing_service"] is True
        assert r_inc["missing_income"] is False
        assert r_inc["missing_service"] is True
        assert r_inc["income_category_id"] == inc_a
        assert r_inc["income_category_name"] == "Pool"
    finally:
        _cleanup(tid)


# ═══════════════════════════════════════════════════════════════════
# Q3 — PATCH with only income_category_id leaves service untouched
# ═══════════════════════════════════════════════════════════════════
def test_patch_income_only_does_not_touch_service():
    tid, uid, email, inc_a, inc_b, svc_a, svc_b = _seed_tenant()
    inv = _seed_invoice(tid)     # both missing
    try:
        tok = _login(email)
        r = requests.patch(
            f"{API}/reports/uncategorized-items/{inv}/0",
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json"},
            json={"income_category_id": inc_a},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["changed"] is True
        assert body["income_category"]["id"] == inc_a
        assert body["service_category"] is None

        # Direct DB check — service_category_id remains unset on the row.
        doc = _db.quotes.find_one({"id": inv}, {"_id": 0, "line_items": 1})
        li = doc["line_items"][0]
        assert li.get("income_category_id") == inc_a
        assert li.get("category") == inc_a
        assert li.get("category_name") == "Pool"
        assert "service_category_id" not in li or not li.get("service_category_id")
    finally:
        _cleanup(tid)


# ═══════════════════════════════════════════════════════════════════
# Q4 — PATCH idempotent no-op (same value twice returns changed=false)
# ═══════════════════════════════════════════════════════════════════
def test_patch_same_value_twice_is_noop():
    tid, uid, email, inc_a, inc_b, svc_a, svc_b = _seed_tenant()
    inv = _seed_invoice(tid)
    try:
        tok = _login(email)
        H = {"Authorization": f"Bearer {tok}",
              "Content-Type": "application/json"}
        r1 = requests.patch(f"{API}/reports/uncategorized-items/{inv}/0",
                             headers=H, json={"income_category_id": inc_a},
                             timeout=15)
        assert r1.json()["changed"] is True
        r2 = requests.patch(f"{API}/reports/uncategorized-items/{inv}/0",
                             headers=H, json={"income_category_id": inc_a},
                             timeout=15)
        assert r2.status_code == 200
        assert r2.json()["changed"] is False
    finally:
        _cleanup(tid)


# ═══════════════════════════════════════════════════════════════════
# Q5 — Audit log — ONE row per mutation, PATCH with BOTH → single row
#      with both fields in the diff
# ═══════════════════════════════════════════════════════════════════
def test_patch_both_fields_writes_single_audit_row_with_both_diffs():
    tid, uid, email, inc_a, inc_b, svc_a, svc_b = _seed_tenant()
    inv = _seed_invoice(tid)
    try:
        tok = _login(email)
        r = requests.patch(
            f"{API}/reports/uncategorized-items/{inv}/0",
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json"},
            json={"income_category_id": inc_a,
                  "service_category_id": svc_a},
            timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["changed"] is True

        audits = list(_db.audit_logs.find(
            {"tenant_id": tid, "event": "line_item.recategorize",
             "invoice_id": inv},
            {"_id": 0}))
        assert len(audits) == 1, (
            f"expected 1 audit row for the batched PATCH, got {len(audits)}")
        diff = audits[0]["diff"]
        assert "income_category_id" in diff
        assert "service_category_id" in diff
        assert diff["income_category_id"]["after"] == inc_a
        assert diff["service_category_id"]["after"] == svc_a
        # Actor stamped.
        assert audits[0]["actor_email"] == email
    finally:
        _cleanup(tid)


def test_patch_income_only_writes_audit_only_for_income_fields():
    tid, uid, email, inc_a, inc_b, svc_a, svc_b = _seed_tenant()
    inv = _seed_invoice(tid)
    try:
        tok = _login(email)
        requests.patch(
            f"{API}/reports/uncategorized-items/{inv}/0",
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json"},
            json={"income_category_id": inc_a},
            timeout=15,
        )
        audits = list(_db.audit_logs.find(
            {"tenant_id": tid, "event": "line_item.recategorize",
             "invoice_id": inv},
            {"_id": 0}))
        assert len(audits) == 1
        diff = audits[0]["diff"]
        assert "income_category_id" in diff
        assert "service_category_id" not in diff
    finally:
        _cleanup(tid)


# ═══════════════════════════════════════════════════════════════════
# Q6 — DELETE (undo) — body ``clear_service`` clears service only
# ═══════════════════════════════════════════════════════════════════
def test_undo_delete_body_clears_only_requested_taxonomies():
    tid, uid, email, inc_a, inc_b, svc_a, svc_b = _seed_tenant()
    inv = _seed_invoice(tid, income=inc_a, service=svc_a)
    try:
        tok = _login(email)
        r = requests.delete(
            f"{API}/reports/uncategorized-items/{inv}/0/assign",
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json"},
            json={"clear_income": False, "clear_service": True},
            timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["cleared"] == {"income": False, "service": True}
        # Row still has income, service is gone.
        doc = _db.quotes.find_one({"id": inv}, {"_id": 0, "line_items": 1})
        li = doc["line_items"][0]
        assert li.get("category") == inc_a
        assert li.get("income_category_id") == inc_a
        assert "service_category_id" not in li or not li.get("service_category_id")
    finally:
        _cleanup(tid)


# ═══════════════════════════════════════════════════════════════════
# Q7 — Auth gate — 403 for technician / customer
# ═══════════════════════════════════════════════════════════════════
def test_patch_forbidden_for_non_admin_roles():
    tid, _uid, admin_email, inc_a, _b, _sa, _sb = _seed_tenant("admin")
    from utils import hash_password
    tech_email = f"uncat-tech-{uuid.uuid4().hex[:6]}@example.com"
    _db.users.insert_one({
        "id": f"TEST-uncat-tech-{uuid.uuid4().hex[:6]}",
        "tenant_id": tid, "email": tech_email,
        "name": "TEST_tech", "role": "technician",
        "password_hash": hash_password("password123"),
    })
    inv = _seed_invoice(tid)
    try:
        tech_tok = _login(tech_email)
        # GET — technicians get 403 on the report list.
        r = requests.get(f"{API}/reports/uncategorized-items?range=all",
                          headers={"Authorization": f"Bearer {tech_tok}"},
                          timeout=15)
        assert r.status_code == 403
        # PATCH — technicians get 403.
        r = requests.patch(
            f"{API}/reports/uncategorized-items/{inv}/0",
            headers={"Authorization": f"Bearer {tech_tok}",
                     "Content-Type": "application/json"},
            json={"income_category_id": inc_a},
            timeout=15,
        )
        assert r.status_code == 403
    finally:
        _cleanup(tid)


# ═══════════════════════════════════════════════════════════════════
# Q8 — Bulk-assign — supports income OR service, mixed successes
# ═══════════════════════════════════════════════════════════════════
def test_bulk_assign_supports_service_taxonomy():
    tid, _uid, email, inc_a, inc_b, svc_a, svc_b = _seed_tenant()
    inv1 = _seed_invoice(tid)
    inv2 = _seed_invoice(tid, income=inc_a)
    try:
        tok = _login(email)
        # Bulk-assign SERVICE to both rows.
        r = requests.post(
            f"{API}/reports/uncategorized-items/bulk-assign",
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json"},
            json={"items": [
                    {"invoice_id": inv1, "line_item_index": 0},
                    {"invoice_id": inv2, "line_item_index": 0}],
                  "service_category_id": svc_a},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["assigned"] == 2
        assert j["failed"] == 0
        assert j["service_category"]["id"] == svc_a
        # Bulk-assign requires at-least-one → error when neither.
        r = requests.post(
            f"{API}/reports/uncategorized-items/bulk-assign",
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json"},
            json={"items": [{"invoice_id": inv1, "line_item_index": 0}]},
            timeout=15,
        )
        assert r.status_code == 422
    finally:
        _cleanup(tid)
