"""Feb-2026 · P36 — customer_tags manager (archive / restore / merge).

Pins the new admin contract:

  * DELETE now soft-archives (``is_active=False``, ``archived_at/by``
    stamped) and does NOT strip ``customers.tags`` snapshots.
  * POST ``/{id}/restore`` flips ``is_active=True``.
  * PATCH accepts ``is_active`` as an alternate archive/restore path.
  * GET hides archived by default; ``?include_inactive=true`` shows them.
  * POST ``/merge`` collapses N victim tags into a canonical tag:
    rewrites ``customers.tags`` (dedup, case-insensitive), archives
    victims, audit-logs, is idempotent on re-run.
  * P29b parity — P33 auto-persist MUST NOT reactivate an archived
    tag when a customer is created carrying that label.
  * RBAC — tech 403 on writes; open GET.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture
def admin_h():
    return _hdrs("admin@aquaterra.com")


@pytest.fixture
def tech_h():
    return _hdrs("mike@aquaterra.com")


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"})["tenant_id"]


def _seed_tag(tid: str, name: str, *, is_active: bool = True,
               is_system: bool = False) -> str:
    tag_id = f"TEST_p36_t_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": tag_id, "tenant_id": tid,
        "name": name, "name_lower": name.lower(),
        "color": "#0EA5E9", "is_system": is_system,
        "created_by": "seed", "created_at": "2026-02-01T00:00:00+00:00",
        "usage_count": 0, "is_active": is_active, "sort_order": 0,
    }
    _sync.customer_tags.insert_one(doc)
    return tag_id


def _seed_customer(tid: str, tags: list[str]) -> str:
    cid = f"TEST_p36_c_{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": f"TEST P36 {uuid.uuid4().hex[:6]}",
        "email": f"{cid}@example.com", "phone": "6235550100",
        "address": "1 Test St", "tags": list(tags),
        "created_at": "2026-06-01T09:00:00+00:00",
    })
    return cid


def _cleanup_tags(ids: list[str]):
    if ids:
        _sync.customer_tags.delete_many({"id": {"$in": ids}})


def _cleanup_customers(ids: list[str]):
    if ids:
        _sync.customers.delete_many({"id": {"$in": ids}})


# ─── 1. openapi lists the new routes ─────────────────────────────────

def test_openapi_lists_new_routes():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200
    paths = r.json().get("paths") or {}
    assert "/api/customer-tags/merge" in paths
    assert "/api/customer-tags/{tag_id}/restore" in paths


# ─── 2. DELETE soft-archives + preserves customers.tags ──────────────

def test_delete_is_soft_archive_and_leaves_customers_tags_intact(
    admin_h, aquaterra_tid,
):
    label = f"Archived P36 {uuid.uuid4().hex[:6]}"
    tag_id = _seed_tag(aquaterra_tid, label)
    cid = _seed_customer(aquaterra_tid, [label, "Other tag"])
    try:
        r = requests.delete(f"{API}/customer-tags/{tag_id}",
                                headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("archived") is True

        # Tag row flipped to inactive.
        row = _sync.customer_tags.find_one({"id": tag_id})
        assert row["is_active"] is False
        assert row.get("archived_at")
        assert row.get("archived_by")

        # Customer snapshot UNCHANGED.
        cust = _sync.customers.find_one({"id": cid})
        assert label in (cust.get("tags") or [])
    finally:
        _cleanup_tags([tag_id])
        _cleanup_customers([cid])


# ─── 3. GET default hides archived; ?include_inactive shows them ─────

def test_get_default_hides_archived(admin_h, aquaterra_tid):
    active_id = _seed_tag(aquaterra_tid, f"Active {uuid.uuid4().hex[:4]}")
    archived_id = _seed_tag(aquaterra_tid, f"Archived {uuid.uuid4().hex[:4]}",
                                 is_active=False)
    try:
        r_default = requests.get(f"{API}/customer-tags",
                                      headers=admin_h, timeout=15)
        assert r_default.status_code == 200
        ids = {t["id"] for t in r_default.json()["items"]}
        assert active_id in ids
        assert archived_id not in ids

        r_incl = requests.get(f"{API}/customer-tags?include_inactive=true",
                                   headers=admin_h, timeout=15)
        assert r_incl.status_code == 200
        ids2 = {t["id"] for t in r_incl.json()["items"]}
        assert active_id in ids2
        assert archived_id in ids2
    finally:
        _cleanup_tags([active_id, archived_id])


# ─── 4. POST /restore reactivates ────────────────────────────────────

def test_restore_reactivates_archived_tag(admin_h, aquaterra_tid):
    tag_id = _seed_tag(aquaterra_tid, f"Toggle {uuid.uuid4().hex[:4]}",
                            is_active=False)
    try:
        r = requests.post(f"{API}/customer-tags/{tag_id}/restore",
                             headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        row = _sync.customer_tags.find_one({"id": tag_id})
        assert row["is_active"] is True
        assert row.get("archived_at") is None
    finally:
        _cleanup_tags([tag_id])


# ─── 5. PATCH is_active alternates as archive/restore alias ──────────

def test_patch_is_active_false_archives(admin_h, aquaterra_tid):
    tag_id = _seed_tag(aquaterra_tid, f"Patched {uuid.uuid4().hex[:4]}")
    try:
        r = requests.patch(f"{API}/customer-tags/{tag_id}",
                              headers=admin_h,
                              json={"is_active": False}, timeout=15)
        assert r.status_code == 200, r.text
        row = _sync.customer_tags.find_one({"id": tag_id})
        assert row["is_active"] is False
        assert row.get("archived_at")
    finally:
        _cleanup_tags([tag_id])


# ─── 6. P29b parity — auto-persist does NOT reactivate archived rows ─

def test_auto_persist_does_not_reactivate_archived_row(
    admin_h, aquaterra_tid,
):
    """A customer created with a tag string whose ``name_lower``
    matches an ARCHIVED row must NOT silently reactivate the row."""
    label = f"DormantP36 {uuid.uuid4().hex[:6]}"
    tag_id = _seed_tag(aquaterra_tid, label, is_active=False)
    created_cid = None
    try:
        payload = {
            "name": f"TEST P36 auto {uuid.uuid4().hex[:6]}",
            "email": f"auto-{uuid.uuid4().hex[:6]}@example.com",
            "phone": "6235550100", "address": "1 Test St",
            "tags": [label],
        }
        r = requests.post(f"{API}/customers", headers=admin_h,
                             json=payload, timeout=15)
        assert r.status_code in (200, 201), r.text
        created_cid = r.json()["id"]

        # Row still archived.
        row = _sync.customer_tags.find_one({"id": tag_id})
        assert row["is_active"] is False, row

        # No duplicate row was inserted for the same label_norm.
        n = _sync.customer_tags.count_documents({
            "tenant_id": aquaterra_tid, "name_lower": label.lower(),
        })
        assert n == 1, f"expected 1 catalog row for archived label, got {n}"

        # Customer snapshot still stored.
        cust = _sync.customers.find_one({"id": created_cid})
        assert label in (cust.get("tags") or [])
    finally:
        _cleanup_tags([tag_id])
        _cleanup_customers([created_cid] if created_cid else [])


# ─── 7. Merge — canonical + N victims across referencing customers ───

def test_merge_collapses_victims_into_canonical(admin_h, aquaterra_tid):
    canonical_label = f"Canonical {uuid.uuid4().hex[:4]}"
    v1_label = f"lower-variant {uuid.uuid4().hex[:4]}"
    v2_label = f"Variant-plural {uuid.uuid4().hex[:4]}"
    canonical_id = _seed_tag(aquaterra_tid, canonical_label)
    v1_id = _seed_tag(aquaterra_tid, v1_label)
    v2_id = _seed_tag(aquaterra_tid, v2_label)

    c_a = _seed_customer(aquaterra_tid, [v1_label, "Untouched"])
    c_b = _seed_customer(aquaterra_tid, [v2_label])
    c_c = _seed_customer(aquaterra_tid, [v1_label, canonical_label])
    c_d = _seed_customer(aquaterra_tid, ["Untouched"])
    try:
        r = requests.post(
            f"{API}/customer-tags/merge", headers=admin_h,
            json={"canonical_id": canonical_id,
                    "victim_ids": [v1_id, v2_id]}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["merged_victims"] == 2
        assert body["customers_updated"] == 3  # a, b, c
        assert body["canonical_label"] == canonical_label

        # a: v1 → canonical (Untouched preserved)
        a = _sync.customers.find_one({"id": c_a})
        assert canonical_label in a["tags"]
        assert v1_label not in a["tags"]
        assert "Untouched" in a["tags"]

        # b: v2 → canonical
        b = _sync.customers.find_one({"id": c_b})
        assert b["tags"] == [canonical_label]

        # c: v1 stripped, canonical stays exactly once (dedup)
        c = _sync.customers.find_one({"id": c_c})
        assert c["tags"].count(canonical_label) == 1
        assert v1_label not in c["tags"]

        # d: untouched
        d = _sync.customers.find_one({"id": c_d})
        assert d["tags"] == ["Untouched"]

        # Victims archived; canonical still active.
        assert _sync.customer_tags.find_one({"id": v1_id})["is_active"] is False
        assert _sync.customer_tags.find_one({"id": v2_id})["is_active"] is False
        assert _sync.customer_tags.find_one({"id": canonical_id})["is_active"] is True

        # Audit log written.
        audit = _sync.audit_logs.find_one(
            {"tenant_id": aquaterra_tid, "event": "customer_tag_merge",
              "payload.canonical_id": canonical_id},
            sort=[("at", -1)],
        )
        assert audit is not None
        assert set(audit["payload"]["victim_ids"]) == {v1_id, v2_id}
    finally:
        _cleanup_tags([canonical_id, v1_id, v2_id])
        _cleanup_customers([c_a, c_b, c_c, c_d])
        _sync.audit_logs.delete_many({
            "tenant_id": aquaterra_tid,
            "payload.canonical_id": canonical_id,
        })


def test_merge_is_idempotent_on_rerun(admin_h, aquaterra_tid):
    canonical_id = _seed_tag(aquaterra_tid, f"Canon {uuid.uuid4().hex[:4]}")
    v1_id = _seed_tag(aquaterra_tid, f"Vic {uuid.uuid4().hex[:4]}",
                          is_active=False)
    try:
        r = requests.post(
            f"{API}/customer-tags/merge", headers=admin_h,
            json={"canonical_id": canonical_id,
                    "victim_ids": [v1_id]}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["customers_updated"] == 0
        assert body["victims_archived_now"] == 0  # already archived
    finally:
        _cleanup_tags([canonical_id, v1_id])
        _sync.audit_logs.delete_many({
            "tenant_id": aquaterra_tid,
            "payload.canonical_id": canonical_id,
        })


def test_merge_rejects_canonical_as_victim(admin_h, aquaterra_tid):
    tag_id = _seed_tag(aquaterra_tid, f"Self {uuid.uuid4().hex[:4]}")
    try:
        r = requests.post(
            f"{API}/customer-tags/merge", headers=admin_h,
            json={"canonical_id": tag_id, "victim_ids": [tag_id]}, timeout=15,
        )
        assert r.status_code == 400, r.text
    finally:
        _cleanup_tags([tag_id])


def test_merge_forbidden_for_technician(tech_h, admin_h, aquaterra_tid):
    canonical_id = _seed_tag(aquaterra_tid, f"Canon {uuid.uuid4().hex[:4]}")
    v1_id = _seed_tag(aquaterra_tid, f"Vic {uuid.uuid4().hex[:4]}")
    try:
        r = requests.post(
            f"{API}/customer-tags/merge", headers=tech_h,
            json={"canonical_id": canonical_id,
                    "victim_ids": [v1_id]}, timeout=15,
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup_tags([canonical_id, v1_id])


def test_merge_rejects_system_victim(admin_h, aquaterra_tid):
    """System tags (Active/Inactive) can't be victims of a merge."""
    from routers.customer_tags import SYSTEM_TAG_ACTIVE
    sys_row = _sync.customer_tags.find_one(
        {"tenant_id": aquaterra_tid, "name": SYSTEM_TAG_ACTIVE,
          "is_system": True},
    )
    if not sys_row:
        pytest.skip("System tag scaffolding not seeded on this tenant")
    canonical_id = _seed_tag(aquaterra_tid, f"Canon {uuid.uuid4().hex[:4]}")
    try:
        r = requests.post(
            f"{API}/customer-tags/merge", headers=admin_h,
            json={"canonical_id": canonical_id,
                    "victim_ids": [sys_row["id"]]}, timeout=15,
        )
        assert r.status_code == 400, r.text
    finally:
        _cleanup_tags([canonical_id])


# ─── 8. Restore RBAC — tech 403 ──────────────────────────────────────

def test_restore_forbidden_for_technician(tech_h, aquaterra_tid):
    tag_id = _seed_tag(aquaterra_tid, f"NoRestore {uuid.uuid4().hex[:4]}",
                            is_active=False)
    try:
        r = requests.post(f"{API}/customer-tags/{tag_id}/restore",
                             headers=tech_h, timeout=15)
        assert r.status_code == 403, r.text
    finally:
        _cleanup_tags([tag_id])
