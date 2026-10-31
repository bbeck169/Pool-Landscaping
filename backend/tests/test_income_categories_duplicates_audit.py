"""Feb-2026 · TD-income-category-dupes-audit · Phase 1 pytest.

Covers ``GET /api/admin/income-categories/duplicates`` — the
read-only audit endpoint feeding the Phase 2 migration script.

End-to-end HTTP against the running backend; isolated TEST-
tenant per test so the shared aquaterra seed never influences
the fixtures (and vice-versa).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv(Path(__file__).resolve().parent.parent / ".env")
API = "http://localhost:8001/api"
_db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password},
                        timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def _seed_tenant_and_admin() -> tuple[str, str]:
    from utils import hash_password
    tid = f"TEST-icdup-tenant-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({"id": tid, "slug": tid, "name": tid,
                              "active": True})
    uid = f"TEST-icdup-u-{uuid.uuid4().hex[:6]}"
    email = f"icdup-{uuid.uuid4().hex[:6]}@example.com"
    _db.users.insert_one({
        "id": uid, "tenant_id": tid, "email": email,
        "role": "admin", "name": "T",
        "password_hash": hash_password("password123"),
    })
    return tid, _login(email)


def _seed_tenant_and_tech() -> tuple[str, str]:
    """Secondary context for the 403 check — role != admin."""
    from utils import hash_password
    tid = f"TEST-icdup-tenant-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({"id": tid, "slug": tid, "name": tid,
                              "active": True})
    uid = f"TEST-icdup-u-{uuid.uuid4().hex[:6]}"
    email = f"icdup-tech-{uuid.uuid4().hex[:6]}@example.com"
    _db.users.insert_one({
        "id": uid, "tenant_id": tid, "email": email,
        "role": "technician", "name": "T",
        "password_hash": hash_password("password123"),
    })
    return tid, _login(email)


def _seed_cat(tid: str, name: str, archived: bool = False) -> str:
    cid = f"TEST-icdup-ic-{uuid.uuid4().hex[:8]}"
    _db.income_categories.insert_one({
        "id": cid, "tenant_id": tid, "name": name,
        "is_archived": archived,
    })
    return cid


def _seed_invoice(tid: str, lines: list[dict]) -> str:
    iid = f"TEST-icdup-inv-{uuid.uuid4().hex[:8]}"
    _db.quotes.insert_one({
        "id": iid, "tenant_id": tid, "doc_type": "invoice",
        "invoice_number": iid,
        "status": "paid", "payment_status": "paid",
        "line_items": lines,
    })
    return iid


def _cleanup(tid: str):
    _db.quotes.delete_many({"tenant_id": tid})
    _db.income_categories.delete_many({"tenant_id": tid})
    _db.users.delete_many({"tenant_id": tid})
    _db.tenants.delete_one({"id": tid})


# ═══════════════════════════════════════════════════════════════════
# 1. Two duplicate sets → endpoint returns 2 sets, canonical by
#    MAX ref_count with lex tiebreak.
# ═══════════════════════════════════════════════════════════════════
def test_two_duplicate_sets_canonical_by_ref_count():
    tid, tok = _seed_tenant_and_admin()
    hdr = {"Authorization": f"Bearer {tok}"}
    try:
        # Set 1: case-drift dupes — "Landscaping" vs "landscaping"
        # (SAME normalized name) → ref_count 1 vs 3, canonical =
        # the ref_count=3 row.
        lsc = _seed_cat(tid, "Landscaping")
        lsg = _seed_cat(tid, "landscaping")
        # Set 2: whitespace + case drift — "Pool" vs "pool" (SAME
        # normalized name 'pool') → ref_count 2 vs 2, lex tiebreak
        # on raw name: "Pool" < "pool" in ASCII so "Pool" wins.
        p1 = _seed_cat(tid, "Pool")
        p2 = _seed_cat(tid, "pool")
        _seed_invoice(tid, [
            {"description": "L", "quantity": 1, "unit_price": 10,
             "income_category_id": lsc},
            {"description": "L", "quantity": 1, "unit_price": 10,
             "income_category_id": lsg},
            {"description": "L", "quantity": 1, "unit_price": 10,
             "income_category_id": lsg},
            {"description": "L", "quantity": 1, "unit_price": 10,
             "income_category_id": lsg},
            {"description": "P", "quantity": 1, "unit_price": 10,
             "income_category_id": p1},
            {"description": "P", "quantity": 1, "unit_price": 10,
             "income_category_id": p1},
            {"description": "P", "quantity": 1, "unit_price": 10,
             "income_category_id": p2},
            {"description": "P", "quantity": 1, "unit_price": 10,
             "income_category_id": p2},
        ])
        r = requests.get(f"{API}/admin/income-categories/duplicates",
                            headers=hdr, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        sets_by_norm = {s["canonical_name_normalized"]: s
                        for s in body["duplicate_sets"]}
        assert "landscaping" in sets_by_norm
        assert "pool" in sets_by_norm
        assert len(body["duplicate_sets"]) == 2

        # Landscaping set — ref_count 3 wins over 1.
        lsc_set = sets_by_norm["landscaping"]
        rows = {r_["id"]: r_ for r_ in lsc_set["rows"]}
        assert rows[lsg]["ref_count"] == 3
        assert rows[lsc]["ref_count"] == 1
        assert rows[lsg]["would_be_canonical"] is True
        assert rows[lsc]["would_be_canonical"] is False

        # Pool set — tie on 2/2, lex tiebreak on raw name:
        # "Pool" < "pool" in ASCII, so "Pool" wins.
        pool_set = sets_by_norm["pool"]
        rows_p = {r_["id"]: r_ for r_ in pool_set["rows"]}
        assert rows_p[p1]["ref_count"] == 2
        assert rows_p[p2]["ref_count"] == 2
        assert rows_p[p1]["would_be_canonical"] is True
        assert rows_p[p2]["would_be_canonical"] is False
    finally:
        _cleanup(tid)


# ═══════════════════════════════════════════════════════════════════
# 2. No duplicates → empty duplicate_sets array.
# ═══════════════════════════════════════════════════════════════════
def test_no_duplicates_returns_empty_sets():
    tid, tok = _seed_tenant_and_admin()
    hdr = {"Authorization": f"Bearer {tok}"}
    try:
        _seed_cat(tid, "Pool")
        _seed_cat(tid, "Chemicals")
        r = requests.get(f"{API}/admin/income-categories/duplicates",
                            headers=hdr, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["duplicate_sets"] == []
    finally:
        _cleanup(tid)


# ═══════════════════════════════════════════════════════════════════
# 3. Cross-tenant isolation — tenant A does not see tenant B dupes.
# ═══════════════════════════════════════════════════════════════════
def test_cross_tenant_isolation():
    tid_a, tok_a = _seed_tenant_and_admin()
    tid_b, _tok_b = _seed_tenant_and_admin()
    hdr = {"Authorization": f"Bearer {tok_a}"}
    try:
        # Dupes in tenant B.
        b1 = _seed_cat(tid_b, "Landscape")
        b2 = _seed_cat(tid_b, "Landscaping")
        _seed_invoice(tid_b, [
            {"description": "x", "quantity": 1, "unit_price": 10,
             "income_category_id": b1},
            {"description": "x", "quantity": 1, "unit_price": 10,
             "income_category_id": b2},
        ])
        r = requests.get(f"{API}/admin/income-categories/duplicates",
                            headers=hdr, timeout=15)
        body = r.json()
        assert body["tenant_id"] == tid_a
        assert body["duplicate_sets"] == []
    finally:
        _cleanup(tid_a)
        _cleanup(tid_b)


# ═══════════════════════════════════════════════════════════════════
# 4. Non-admin → 403.
# ═══════════════════════════════════════════════════════════════════
def test_non_admin_403():
    tid, tok = _seed_tenant_and_tech()
    hdr = {"Authorization": f"Bearer {tok}"}
    try:
        r = requests.get(f"{API}/admin/income-categories/duplicates",
                            headers=hdr, timeout=15)
        assert r.status_code == 403, r.text
    finally:
        _cleanup(tid)


# ═══════════════════════════════════════════════════════════════════
# 5. Inline-string-only line items counted; resolves_to_fk_id null
#    when no matching category exists post-dedupe.
# ═══════════════════════════════════════════════════════════════════
def test_inline_string_only_line_items_counted():
    tid, tok = _seed_tenant_and_admin()
    hdr = {"Authorization": f"Bearer {tok}"}
    try:
        pool_id = _seed_cat(tid, "Pool")
        _seed_invoice(tid, [
            # Inline-string "Pool" resolves to pool_id canonical.
            {"description": "A", "quantity": 1, "unit_price": 10,
             "category": "Pool"},
            {"description": "B", "quantity": 1, "unit_price": 10,
             "category": "pool"},
            # Inline-string "LegacyUnknown" has no matching
            # income_categories row — resolves_to_fk_id null.
            {"description": "C", "quantity": 1, "unit_price": 10,
             "category": "LegacyUnknown"},
            # FK-rooted line items are NOT counted in the inline
            # tally — must not inflate the count.
            {"description": "D", "quantity": 1, "unit_price": 10,
             "income_category_id": pool_id, "category": "Pool"},
        ])
        r = requests.get(f"{API}/admin/income-categories/duplicates",
                            headers=hdr, timeout=15)
        body = r.json()
        inline = body["inline_string_only_line_items"]
        # 3 inline-only lines (A, B, C) — D is excluded because it
        # has an FK.
        assert inline["total"] == 3
        by_name = {row["normalized"]: row
                   for row in inline["by_normalized_name"]}
        assert "pool" in by_name
        assert by_name["pool"]["count"] == 2
        assert by_name["pool"]["resolves_to_fk_id"] == pool_id
        assert "legacyunknown" in by_name
        assert by_name["legacyunknown"]["count"] == 1
        assert by_name["legacyunknown"]["resolves_to_fk_id"] is None
    finally:
        _cleanup(tid)
