"""Feb 2026 · Customer Merge · Phase 1 — backend pytest suite.

All tests HTTP-drive the live backend (same loop-safety pattern as
``test_custom_trigger_builder_e2e.py``): sync ``pymongo`` for seed +
assertion, sync ``httpx`` for the API surface. Direct-service calls
that hit Motor from a fresh event loop crash with a cross-loop bind
error — the HTTP path uses the server's persistent loop and is
therefore safe.

Coverage (16 flows):

  Detection endpoint
    01. Exact email match — case-insensitive
    02. Exact phone match — punctuation-insensitive
    03. Exact name + address match — case + whitespace insensitive
    04. Fuzzy name (positive)   — Jaro-Winkler ≥ 0.92
    05. Fuzzy name (negative)   — below threshold → no group
    06. Tenant-scoped — no cross-tenant leaks
    07. Skips already-merged and soft-deleted records
    08. Confidence tier — high vs low correctly assigned

  Merge endpoint
    09. Newest-wins reconciliation + empty fields filled
    10. Related records rewired — 6 buckets counts match
    11. Dry-run — no writes
    12. Audit row created with the correct shape

  Endpoint layer
    13. RBAC — technician gets 403 on all 3 endpoints
    14. 422 (primary in secondaries / empty) + 404 (unknown primary)
    15. GET /customers with include_merged=false/true parity
    16. Smoke — /detect-duplicates → /merge → /merge-audit chain
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List

import httpx
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)



BASE = "http://localhost:8001"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db() if (_MONGO_URL and _DB_NAME) else None
# ─── Sync fixture helpers ───────────────────────────────────────────
def _mk_tenant() -> str:
    tid = f"CM_tenant_{uuid.uuid4().hex}"
    _sync.tenants.insert_one({
        "id": tid, "slug": f"cm-{uuid.uuid4().hex[:8]}",
        "name": "CM Tenant", "active": True,
    })
    return tid


def _mk_customer(tid: str, **kw) -> str:
    cid = f"CM_cust_{uuid.uuid4().hex}"
    doc = {
        "id": cid, "tenant_id": tid,
        "name": kw.pop("name", "Test Customer"),
        "email": kw.pop("email", None),
        "phone": kw.pop("phone", None),
        "address": kw.pop("address", None),
        "created_at": kw.pop("created_at", "2026-02-01T00:00:00+00:00"),
        "updated_at": kw.pop("updated_at", "2026-02-01T00:00:00+00:00"),
        "is_active": True,
    }
    doc.update(kw)
    _sync.customers.insert_one(doc)
    return cid


def _mk_user(tid: str, role: str = "admin") -> str:
    from utils import hash_password
    email = f"cm-{role}-{uuid.uuid4().hex[:8]}@example.com"
    _sync.users.insert_one({
        "id": f"CM_user_{uuid.uuid4().hex}",
        "email": email, "role": role,
        "password_hash": hash_password("password123"),
        "tenant_id": tid, "name": f"CM {role}",
        "failed_login_attempts": 0, "active": True,
    })
    return email


def _token_for(email: str) -> str:
    r = httpx.post(f"{BASE}/api/auth/login", json={
        "email": email, "password": "password123",
    }, timeout=30)
    r.raise_for_status()
    b = r.json()
    return b.get("access_token") or b.get("token") or ""


def _hdrs_for_admin(tid: str) -> Dict[str, str]:
    tok = _token_for(_mk_user(tid, "admin"))
    return {"Authorization": f"Bearer {tok}"}


def _cleanup(tid: str):
    if _sync is None:
        return
    _sync.tenants.delete_many({"id": tid})
    for coll in (
        "customers", "users", "jobs", "quotes", "estimates",
        "payments", "service_reports", "leads",
        "customer_merge_audit",
    ):
        _sync[coll].delete_many({"tenant_id": tid})


def _detect(tid: str) -> Dict[str, Any]:
    r = httpx.post(f"{BASE}/api/customers/detect-duplicates",
                    headers=_hdrs_for_admin(tid), json={}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _merge(tid: str, primary: str, secondaries: List[str],
             hdrs: Dict[str, str], *, dry_run: bool = False,
             match_type: str = None, confidence: str = None,
             expect_status: int = 200) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "primary_id": primary, "secondary_ids": secondaries,
        "dry_run": dry_run,
    }
    if match_type: body["match_type"] = match_type
    if confidence: body["confidence"] = confidence
    r = httpx.post(f"{BASE}/api/customers/merge",
                    headers=hdrs, json=body, timeout=30)
    assert r.status_code == expect_status, (r.status_code, r.text)
    return r.json() if r.headers.get("content-type", "").startswith(
        "application/json") else {}


# ═════════════════════════════════════════════════════════════════════
# DETECTION
# ═════════════════════════════════════════════════════════════════════
def test_01_exact_email_case_insensitive():
    tid = _mk_tenant()
    try:
        _mk_customer(tid, email="Alice@Example.com")
        _mk_customer(tid, email="alice@example.com")
        _mk_customer(tid, email="bob@example.com")
        body = _detect(tid)
        emails = [g for g in body["duplicate_groups"]
                    if g["match_type"] == "exact_email"]
        assert len(emails) == 1, body
        g = emails[0]
        assert g["confidence"] == "high"
        assert g["match_field_values"]["email"] == "alice@example.com"
        assert len(g["customer_ids"]) == 2
    finally:
        _cleanup(tid)


def test_02_exact_phone_punct_insensitive():
    tid = _mk_tenant()
    try:
        _mk_customer(tid, phone="+1 (623) 555-0100")
        _mk_customer(tid, phone="6235550100")
        body = _detect(tid)
        phones = [g for g in body["duplicate_groups"]
                    if g["match_type"] == "exact_phone"]
        assert len(phones) == 1, body
        assert phones[0]["confidence"] == "high"
        assert phones[0]["match_field_values"]["phone"] == "6235550100"
    finally:
        _cleanup(tid)


def test_03_exact_name_and_address():
    tid = _mk_tenant()
    try:
        _mk_customer(tid, name="John Smith", address="1 Main St")
        _mk_customer(tid, name="  JOHN SMITH ", address="1 Main St")
        _mk_customer(tid, name="John Smith", address="99 Other St")
        body = _detect(tid)
        na = [g for g in body["duplicate_groups"]
                if g["match_type"] == "exact_name_address"]
        assert len(na) == 1, body
        assert na[0]["confidence"] == "low"
    finally:
        _cleanup(tid)


def test_04_fuzzy_name_positive():
    tid = _mk_tenant()
    try:
        _mk_customer(tid, name="Jonathon Smyth")
        _mk_customer(tid, name="Jonathan Smith")
        body = _detect(tid)
        fuzz = [g for g in body["duplicate_groups"]
                  if g["match_type"] == "fuzzy_name"]
        assert len(fuzz) == 1, body
        assert fuzz[0]["confidence"] == "low"
        assert fuzz[0]["score"] >= 0.92
    finally:
        _cleanup(tid)


def test_05_fuzzy_name_negative_below_threshold():
    tid = _mk_tenant()
    try:
        _mk_customer(tid, name="John Smith")
        _mk_customer(tid, name="Alice Cooper")
        body = _detect(tid)
        fuzz = [g for g in body["duplicate_groups"]
                  if g["match_type"] == "fuzzy_name"]
        assert fuzz == [], body
    finally:
        _cleanup(tid)


def test_06_tenant_scoped_no_cross_leak():
    tid_a = _mk_tenant(); tid_b = _mk_tenant()
    try:
        _mk_customer(tid_a, email="shared@example.com")
        _mk_customer(tid_b, email="shared@example.com")
        assert _detect(tid_a)["duplicate_groups"] == []
        assert _detect(tid_b)["duplicate_groups"] == []
    finally:
        _cleanup(tid_a); _cleanup(tid_b)


def test_07_skips_already_merged_and_soft_deleted():
    tid = _mk_tenant()
    try:
        alive = _mk_customer(tid, email="dup@example.com")
        _mk_customer(tid, email="dup@example.com", merged_into=alive)
        _mk_customer(tid, email="dup@example.com",
                       deleted_at="2026-02-15T00:00:00+00:00")
        _mk_customer(tid, email="unique@example.com")
        assert _detect(tid)["duplicate_groups"] == []
    finally:
        _cleanup(tid)


def test_08_confidence_tier_high_vs_low():
    tid = _mk_tenant()
    try:
        _mk_customer(tid, email="tier@example.com", name="A")
        _mk_customer(tid, email="tier@example.com", name="B")
        _mk_customer(tid, name="Same Person", address="Same Address")
        _mk_customer(tid, name="Same Person", address="Same Address")
        body = _detect(tid)
        by_type = {g["match_type"]: g["confidence"]
                    for g in body["duplicate_groups"]}
        assert by_type.get("exact_email") == "high", body
        assert by_type.get("exact_name_address") == "low", body
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# EXECUTOR (via /api/customers/merge)
# ═════════════════════════════════════════════════════════════════════
def test_09_newest_wins_and_empty_fields_filled():
    tid = _mk_tenant()
    try:
        primary = _mk_customer(
            tid, name="Old Name", email="p@example.com",
            phone=None, address="123 Main",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        secondary = _mk_customer(
            tid, name="New Name", email="s@example.com",
            phone="+1 555 111 2222", address="123 Main",
            updated_at="2026-02-15T00:00:00+00:00",
        )
        r = _merge(tid, primary, [secondary],
                     hdrs=_hdrs_for_admin(tid))
        assert r["fields_reconciled"]["name"] == "New Name", r
        assert r["empty_fields_filled"]["phone"] == "+1 555 111 2222", r
        pdoc = _sync.customers.find_one({"id": primary})
        assert pdoc["name"] == "New Name"
        assert pdoc["phone"] == "+1 555 111 2222"
        sdoc = _sync.customers.find_one({"id": secondary})
        assert sdoc["merged_into"] == primary
        assert sdoc.get("merged_at")
        assert sdoc.get("merged_by")
    finally:
        _cleanup(tid)


def test_10_related_records_rewired_all_six_buckets():
    tid = _mk_tenant()
    try:
        primary = _mk_customer(tid, name="P")
        secondary = _mk_customer(tid, name="S")
        for i in range(3):
            _sync.jobs.insert_one({
                "id": f"job_{i}_{uuid.uuid4().hex[:6]}",
                "tenant_id": tid, "customer_id": secondary,
            })
        for i in range(2):
            _sync.quotes.insert_one({
                "id": f"inv_{i}_{uuid.uuid4().hex[:6]}",
                "tenant_id": tid, "customer_id": secondary,
                "doc_type": "invoice",
            })
        _sync.quotes.insert_one({
            "id": f"qest_{uuid.uuid4().hex[:6]}",
            "tenant_id": tid, "customer_id": secondary,
            "doc_type": "estimate",
        })
        for i in range(2):
            _sync.estimates.insert_one({
                "id": f"est_{i}_{uuid.uuid4().hex[:6]}",
                "tenant_id": tid, "customer_id": secondary,
            })
        _sync.payments.insert_one({
            "id": f"pay_{uuid.uuid4().hex[:6]}",
            "tenant_id": tid, "customer_id": secondary,
        })
        for i in range(4):
            _sync.service_reports.insert_one({
                "id": f"sr_{i}_{uuid.uuid4().hex[:6]}",
                "tenant_id": tid, "customer_id": secondary,
            })
        for i in range(5):
            _sync.leads.insert_one({
                "id": f"ld_{i}_{uuid.uuid4().hex[:6]}",
                "tenant_id": tid, "customer_id": secondary,
            })
        r = _merge(tid, primary, [secondary],
                     hdrs=_hdrs_for_admin(tid))
        counts = r["related_records_rewired"]
        assert counts == {
            "jobs": 3, "invoices": 2, "payments": 1,
            "service_reports": 4, "estimates": 3, "leads": 5,
        }, counts
        # Verify jobs actually rewired to primary.
        assert _sync.jobs.count_documents(
            {"tenant_id": tid, "customer_id": secondary}) == 0
        assert _sync.jobs.count_documents(
            {"tenant_id": tid, "customer_id": primary}) == 3
    finally:
        _cleanup(tid)


def test_11_dry_run_writes_nothing():
    tid = _mk_tenant()
    try:
        primary = _mk_customer(tid, name="OldName", phone=None)
        secondary = _mk_customer(
            tid, name="NewName", phone="+1-555-333-4444",
            updated_at="2026-02-20T00:00:00+00:00",
        )
        job_id = f"dry_job_{uuid.uuid4().hex[:6]}"
        _sync.jobs.insert_one({
            "id": job_id, "tenant_id": tid, "customer_id": secondary,
        })
        r = _merge(tid, primary, [secondary],
                     hdrs=_hdrs_for_admin(tid), dry_run=True)
        assert r["dry_run"] is True
        assert r["audit_id"] is None
        pdoc = _sync.customers.find_one({"id": primary})
        assert pdoc["name"] == "OldName"
        assert not pdoc.get("phone")
        sdoc = _sync.customers.find_one({"id": secondary})
        assert not sdoc.get("merged_into")
        job = _sync.jobs.find_one({"id": job_id})
        assert job["customer_id"] == secondary
        # Counts + preview values still returned.
        assert r["related_records_rewired"]["jobs"] == 1
        assert r["fields_reconciled"]["name"] == "NewName"
    finally:
        _cleanup(tid)


def test_12_audit_row_shape():
    tid = _mk_tenant()
    try:
        primary = _mk_customer(tid, name="P", email="p@e.com")
        secondary = _mk_customer(
            tid, name="P", email="s@e.com",
            updated_at="2026-02-20T00:00:00+00:00",
        )
        r = _merge(tid, primary, [secondary],
                     hdrs=_hdrs_for_admin(tid),
                     match_type="exact_email", confidence="high")
        aid = r["audit_id"]
        assert aid and aid.startswith("audit_")
        row = _sync.customer_merge_audit.find_one({"id": aid})
        assert row is not None
        assert row["tenant_id"] == tid
        assert row["primary_id"] == primary
        assert row["secondary_ids"] == [secondary]
        assert row["match_type"] == "exact_email"
        assert row["confidence"] == "high"
        assert "fields_reconciled" in row
        assert "related_records_rewired" in row
        assert row["reversed_at"] is None
        assert row["reversed_by"] is None
        assert row["created_at"]
        # ``initiated_by`` is stamped from the caller's user id.
        assert row["initiated_by"] and row["initiated_by"] != "unknown"
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# ENDPOINT LAYER
# ═════════════════════════════════════════════════════════════════════
def test_13_endpoint_rbac_technician_403():
    tid = _mk_tenant()
    try:
        tech_email = _mk_user(tid, "technician")
        tok = _token_for(tech_email)
        hdrs = {"Authorization": f"Bearer {tok}"}
        for method, path, body in (
            ("POST", "/api/customers/detect-duplicates", {}),
            ("POST", "/api/customers/merge",
                {"primary_id": "x", "secondary_ids": ["y"]}),
            ("GET",  "/api/customers/merge-audit", None),
        ):
            if method == "POST":
                r = httpx.post(f"{BASE}{path}", headers=hdrs,
                                 json=body, timeout=30)
            else:
                r = httpx.get(f"{BASE}{path}", headers=hdrs, timeout=30)
            assert r.status_code == 403, (path, r.status_code, r.text)
    finally:
        _cleanup(tid)


def test_14_merge_endpoint_404_and_422_paths():
    tid = _mk_tenant()
    try:
        primary = _mk_customer(tid, name="P")
        hdrs = _hdrs_for_admin(tid)
        # 422 — primary in secondaries
        _merge(tid, primary, [primary], hdrs=hdrs, expect_status=422)
        # 422 — empty secondaries
        _merge(tid, primary, [], hdrs=hdrs, expect_status=422)
        # 404 — unknown primary
        _merge(tid, "nope-primary", ["nope-sec"],
                 hdrs=hdrs, expect_status=404)
    finally:
        _cleanup(tid)


def test_15_customer_list_hides_merged_by_default():
    tid = _mk_tenant()
    try:
        primary = _mk_customer(tid, name="Kept")
        secondary = _mk_customer(
            tid, name="Gone", merged_into=primary,
            merged_at="2026-02-20T00:00:00+00:00",
        )
        hdrs = _hdrs_for_admin(tid)
        # Default — merged row hidden.
        r = httpx.get(f"{BASE}/api/customers", headers=hdrs, timeout=30)
        assert r.status_code == 200, r.text
        rows = r.json()
        ids = {c["id"] for c in rows if isinstance(c, dict)}
        assert primary in ids
        assert secondary not in ids
        # include_merged=true — merged row surfaces.
        r = httpx.get(f"{BASE}/api/customers?include_merged=true",
                        headers=hdrs, timeout=30)
        assert r.status_code == 200, r.text
        ids = {c["id"] for c in r.json() if isinstance(c, dict)}
        assert primary in ids
        assert secondary in ids
    finally:
        _cleanup(tid)


def test_16_endpoint_smoke_detect_then_merge_then_audit():
    tid = _mk_tenant()
    try:
        a = _mk_customer(tid, name="John Smith",
                            email="smoke@example.com",
                            updated_at="2026-02-01T00:00:00+00:00")
        b = _mk_customer(tid, name="John Smith",
                            email="smoke@example.com",
                            phone="+1 555 000 1111",
                            updated_at="2026-02-20T00:00:00+00:00")
        hdrs = _hdrs_for_admin(tid)
        # Detect
        body = _detect(tid)
        assert body["count"] >= 1, body
        emails = [g for g in body["duplicate_groups"]
                    if g["match_type"] == "exact_email"]
        assert emails, body
        assert set(emails[0]["customer_ids"]) == {a, b}
        # Dry-run
        dry = _merge(tid, a, [b], hdrs=hdrs, dry_run=True,
                       match_type="exact_email", confidence="high")
        assert dry["dry_run"] is True
        assert dry["audit_id"] is None
        assert dry["empty_fields_filled"].get("phone") == "+1 555 000 1111"
        # Live merge
        live = _merge(tid, a, [b], hdrs=hdrs,
                        match_type="exact_email", confidence="high")
        assert live["dry_run"] is False
        assert live["audit_id"] and live["audit_id"].startswith("audit_")
        # Audit endpoint
        r = httpx.get(f"{BASE}/api/customers/merge-audit",
                        headers=hdrs, timeout=30)
        assert r.status_code == 200, r.text
        audit = r.json()
        assert audit["count"] >= 1
        # First entry (newest) should be our merge.
        first = audit["entries"][0]
        assert first["primary_id"] == a
        assert first["secondary_ids"] == [b]
        assert first["match_type"] == "exact_email"
    finally:
        _cleanup(tid)
