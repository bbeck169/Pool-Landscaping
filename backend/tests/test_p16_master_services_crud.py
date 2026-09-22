"""Phase P16 · Feb-2026 — Master Services (Pricebook) CRUD contract.

Locks in the wire contract for ``/api/master-services``:

  1. Create as admin → 200, doc has expected shape.
  2. Create as manager → 200 (widened RBAC for CRUD).
  3. Create as technician → 403.
  4. Soft delete as admin → 200, ``is_active=False``, row survives.
  5. Soft delete as manager → 403 (delete stays admin-only).
  6. Hard delete as admin with body ``{confirm:"DELETE"}`` → 200,
     row removed, ``deletion_audit`` row written with
     ``resource_type="master_service"``.
  7. Hard delete without confirm → 400.
  8. Duplicate name (case-insensitive) → 409.
  9. Tenant isolation — a tenant-B row never surfaces on the
     tenant-A list, PATCH, or DELETE.
  10. Counts aggregate returns correct active / inactive / total.
  11. ``?include_inactive=false`` (default) hides soft-deleted rows;
      ``?include_inactive=true`` includes them.
  12. ``?q=`` name substring filter is case-insensitive.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_h() -> dict:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def manager_h() -> dict:
    return {"Authorization": f"Bearer {_login('manager@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def admin_tid(dbc) -> str:
    u = dbc.users.find_one({"email": "admin@aquaterra.com"},
                            {"_id": 0, "tenant_id": 1})
    assert u and u.get("tenant_id"), "seed admin missing tenant_id"
    return u["tenant_id"]


@pytest.fixture(scope="module")
def tech_h(dbc) -> dict:
    """Seed a throwaway technician user tied to the same tenant so
    RBAC 403 assertions have a clean caller.  Cleans up on
    teardown."""
    from bcrypt import hashpw, gensalt
    email = f"p16-tech-{uuid.uuid4().hex[:8]}@example.com"
    admin = dbc.users.find_one({"email": "admin@aquaterra.com"},
                                 {"_id": 0, "tenant_id": 1})
    tid = admin["tenant_id"]
    dbc.users.insert_one({
        "id": f"TEST-p16-tech-{uuid.uuid4().hex[:8]}",
        "email": email,
        "role": "technician",
        "password_hash": hashpw(b"password123", gensalt()).decode(),
        "tenant_id": tid,
        "name": "P16 Test Tech",
        "technician_id": f"TEST-p16-{uuid.uuid4().hex[:8]}",
        "active": True,
        "failed_login_attempts": 0,
    })
    try:
        tok = _login(email)["access_token"]
        yield {"Authorization": f"Bearer {tok}"}
    finally:
        dbc.users.delete_many({"email": email})


@pytest.fixture(scope="module")
def known_category(dbc, admin_tid) -> str:
    """Return an existing non-archived service-category name for
    the current tenant so create/patch calls pass validation."""
    row = dbc.service_categories.find_one(
        {"tenant_id": admin_tid, "is_archived": False}, {"_id": 0, "name": 1},
    )
    assert row and row.get("name"), "seed tenant missing service categories"
    return row["name"]


# ─────────────────────────────────────────────────────────────────────
# Helpers — every seeded / created row is prefixed so teardown can
# scrub without touching production data even on a shared DB.
# ─────────────────────────────────────────────────────────────────────
def _name(suffix: str = "") -> str:
    return f"TEST-P16 {suffix or uuid.uuid4().hex[:8]}"


def _create_svc(headers: dict, name: str, category: str,
                default_price: float = 199.00) -> requests.Response:
    return requests.post(
        f"{API}/master-services",
        headers=headers,
        json={"name": name, "default_price": default_price,
                "category": category},
        timeout=15,
    )


@pytest.fixture(autouse=True)
def _scrub(dbc, admin_tid):
    """Auto-scrub any TEST-P16 rows before + after each test so the
    counts assertions are deterministic even if a prior test
    aborted mid-way."""
    dbc.pricebook.delete_many({"tenant_id": admin_tid,
                                 "name": {"$regex": "^TEST-P16 "}})
    yield
    dbc.pricebook.delete_many({"tenant_id": admin_tid,
                                 "name": {"$regex": "^TEST-P16 "}})


# ═════════════════════════════════════════════════════════════════════
# Acceptance 1 · Create as admin — 200 + expected doc shape
# ═════════════════════════════════════════════════════════════════════
def test_create_master_service_as_admin_returns_200_with_shape(
    admin_h, known_category,
):
    name = _name("admin-create")
    r = _create_svc(admin_h, name, known_category, 249.50)
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("id", "tenant_id", "name", "default_price", "category",
                "is_active", "created_at", "updated_at",
                "created_by", "updated_by"):
        assert k in body, (k, body)
    assert body["name"] == name
    assert body["default_price"] == 249.50
    assert body["category"] == known_category
    assert body["is_active"] is True


# ═════════════════════════════════════════════════════════════════════
# Acceptance 2 · Create as manager — 200 (widened RBAC for CRUD)
# ═════════════════════════════════════════════════════════════════════
def test_create_master_service_as_manager_returns_200(
    manager_h, known_category,
):
    name = _name("mgr-create")
    r = _create_svc(manager_h, name, known_category)
    assert r.status_code == 200, r.text


# ═════════════════════════════════════════════════════════════════════
# Acceptance 3 · Create as technician — 403
# ═════════════════════════════════════════════════════════════════════
def test_create_master_service_as_technician_returns_403(
    tech_h, known_category,
):
    r = _create_svc(tech_h, _name("tech-create"), known_category)
    assert r.status_code == 403, r.text


# ═════════════════════════════════════════════════════════════════════
# Acceptance 4 · Soft delete as admin flips is_active=False
# ═════════════════════════════════════════════════════════════════════
def test_soft_delete_as_admin_flips_is_active_false(
    admin_h, admin_tid, dbc, known_category,
):
    body = _create_svc(admin_h, _name("soft-del"), known_category).json()
    r = requests.delete(f"{API}/master-services/{body['id']}",
                          headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    resp = r.json()
    assert resp["hard_deleted"] is False
    assert resp["master_service"]["is_active"] is False
    # Row still exists in Mongo.
    row = dbc.pricebook.find_one({"id": body["id"]})
    assert row and row["is_active"] is False


# ═════════════════════════════════════════════════════════════════════
# Acceptance 5 · Soft delete as manager → 403 (admin-only)
# ═════════════════════════════════════════════════════════════════════
def test_soft_delete_as_manager_returns_403(
    admin_h, manager_h, known_category,
):
    body = _create_svc(admin_h, _name("mgr-del-blocked"),
                        known_category).json()
    r = requests.delete(f"{API}/master-services/{body['id']}",
                          headers=manager_h, timeout=15)
    assert r.status_code == 403, r.text


# ═════════════════════════════════════════════════════════════════════
# Acceptance 6 · Hard delete as admin with confirm=DELETE writes
# ``deletion_audit`` row.
# ═════════════════════════════════════════════════════════════════════
def test_hard_delete_as_admin_removes_row_and_writes_audit(
    admin_h, admin_tid, dbc, known_category,
):
    body = _create_svc(admin_h, _name("hard-del"), known_category).json()
    svc_id = body["id"]
    try:
        r = requests.delete(
            f"{API}/master-services/{svc_id}?hard=true",
            headers=admin_h,
            json={"confirm": "DELETE"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        resp = r.json()
        assert resp["hard_deleted"] is True
        assert resp["deleted_count"] == 1
        # Row is gone.
        assert dbc.pricebook.find_one({"id": svc_id}) is None
        # Audit row exists with the right shape.
        audit = dbc.deletion_audit.find_one({"resource_id": svc_id,
                                                "resource_type": "master_service"})
        assert audit is not None, "audit row not written"
        assert audit["tenant_id"] == admin_tid
        assert audit["deletion_reason"] == "master_service.hard_delete"
        assert (audit.get("snapshot") or {}).get("name") == body["name"]
    finally:
        dbc.deletion_audit.delete_many({"resource_id": svc_id})


# ═════════════════════════════════════════════════════════════════════
# Acceptance 7 · Hard delete WITHOUT confirm body → 400
# ═════════════════════════════════════════════════════════════════════
def test_hard_delete_without_confirm_returns_400(admin_h, known_category):
    body = _create_svc(admin_h, _name("hard-noconfirm"), known_category).json()
    r = requests.delete(f"{API}/master-services/{body['id']}?hard=true",
                          headers=admin_h, timeout=15)
    assert r.status_code == 400, r.text
    # Body carries a stable error code the FE can key on.
    assert "confirm_required" in r.text


# ═════════════════════════════════════════════════════════════════════
# Acceptance 8 · Duplicate name (case-insensitive) → 409
# ═════════════════════════════════════════════════════════════════════
def test_duplicate_name_case_insensitive_returns_409(
    admin_h, known_category,
):
    n = _name("dupe")
    r1 = _create_svc(admin_h, n, known_category)
    assert r1.status_code == 200, r1.text
    r2 = _create_svc(admin_h, n.upper(), known_category)
    assert r2.status_code == 409, r2.text
    assert "duplicate_name" in r2.text


# ═════════════════════════════════════════════════════════════════════
# Acceptance 9 · Tenant isolation — a tenant-B row never surfaces on
# tenant-A's list.
# ═════════════════════════════════════════════════════════════════════
def test_tenant_isolation_prevents_cross_tenant_read(
    admin_h, admin_tid, dbc,
):
    # Seed a foreign-tenant row directly (no API call — no cross-
    # tenant admin session available).
    other_tid = f"TEST-p16-other-{uuid.uuid4().hex[:8]}"
    foreign_id = f"TEST-p16-foreign-{uuid.uuid4().hex[:8]}"
    dbc.tenants.insert_one({"id": other_tid, "name": "P16 · Other Tenant",
                              "slug": f"p16-other-{other_tid}",
                              "active": True})
    dbc.pricebook.insert_one({
        "id": foreign_id,
        "tenant_id": other_tid,
        "name": "TEST-P16 foreign leak",
        "default_price": 999.0,
        "category": "Pool",
        "is_active": True,
        "created_at": "2026-02-01T00:00:00+00:00",
        "updated_at": "2026-02-01T00:00:00+00:00",
    })
    try:
        r = requests.get(f"{API}/master-services",
                           headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        ids = [row["id"] for row in r.json()["items"]]
        assert foreign_id not in ids
        # PATCH on foreign id → 404.
        r_patch = requests.patch(f"{API}/master-services/{foreign_id}",
                                   headers=admin_h,
                                   json={"default_price": 1.0}, timeout=15)
        assert r_patch.status_code == 404, r_patch.text
        # DELETE on foreign id → 404.
        r_del = requests.delete(f"{API}/master-services/{foreign_id}",
                                  headers=admin_h, timeout=15)
        assert r_del.status_code == 404, r_del.text
    finally:
        dbc.pricebook.delete_one({"id": foreign_id})
        dbc.tenants.delete_one({"id": other_tid})


# ═════════════════════════════════════════════════════════════════════
# Acceptance 10 · Counts aggregate returns correct totals.
# ═════════════════════════════════════════════════════════════════════
def test_counts_aggregate_returns_active_inactive_total(
    admin_h, admin_tid, dbc, known_category,
):
    # Seed 3 active + 2 inactive under the TEST-P16 prefix so we can
    # assert the delta the scrub-fixture guarantees is exactly ours.
    active_ids = []
    inactive_ids = []
    for i in range(3):
        active_ids.append(_create_svc(admin_h, _name(f"count-a{i}"),
                                        known_category).json()["id"])
    for i in range(2):
        sid = _create_svc(admin_h, _name(f"count-i{i}"),
                            known_category).json()["id"]
        # Soft-delete via API to flip is_active.
        requests.delete(f"{API}/master-services/{sid}",
                          headers=admin_h, timeout=15)
        inactive_ids.append(sid)

    r = requests.get(f"{API}/master-services?include_inactive=true",
                       headers=admin_h, timeout=15)
    body = r.json()
    counts = body["counts"]

    # Recompute expected from Mongo (tenant-wide) so a co-existing
    # non-test row doesn't skew the assertion.
    expected_total = dbc.pricebook.count_documents({"tenant_id": admin_tid})
    expected_active = dbc.pricebook.count_documents(
        {"tenant_id": admin_tid, "is_active": True},
    )
    expected_inactive = expected_total - expected_active
    assert counts["total"] == expected_total
    assert counts["active"] == expected_active
    assert counts["inactive"] == expected_inactive


# ═════════════════════════════════════════════════════════════════════
# Acceptance 11 · include_inactive gate on the items[] side.
# ═════════════════════════════════════════════════════════════════════
def test_include_inactive_false_hides_soft_deleted(admin_h, known_category):
    active = _create_svc(admin_h, _name("ii-a"), known_category).json()["id"]
    inactive = _create_svc(admin_h, _name("ii-i"), known_category).json()["id"]
    requests.delete(f"{API}/master-services/{inactive}",
                      headers=admin_h, timeout=15)

    default = requests.get(f"{API}/master-services",
                             headers=admin_h, timeout=15).json()
    default_ids = [x["id"] for x in default["items"]]
    assert active in default_ids
    assert inactive not in default_ids

    with_inactive = requests.get(
        f"{API}/master-services?include_inactive=true",
        headers=admin_h, timeout=15,
    ).json()
    with_ids = [x["id"] for x in with_inactive["items"]]
    assert active in with_ids
    assert inactive in with_ids


# ═════════════════════════════════════════════════════════════════════
# Acceptance 12 · ?q= substring is case-insensitive.
# ═════════════════════════════════════════════════════════════════════
def test_q_filter_is_case_insensitive_substring(admin_h, known_category):
    marker = uuid.uuid4().hex[:8].upper()
    name_a = f"TEST-P16 {marker} pool-shock"
    name_b = f"TEST-P16 {marker} pool-service"
    other = f"TEST-P16 zz-unrelated-{marker}"
    for n in (name_a, name_b, other):
        _create_svc(admin_h, n, known_category)

    r = requests.get(
        f"{API}/master-services?q={marker.lower()}",
        headers=admin_h, timeout=15,
    ).json()
    ids_by_name = {row["name"] for row in r["items"]}
    assert name_a in ids_by_name and name_b in ids_by_name
    assert other in ids_by_name  # 'other' also carries the marker

    r2 = requests.get(
        f"{API}/master-services?q=SHOCK",
        headers=admin_h, timeout=15,
    ).json()
    names = {row["name"] for row in r2["items"]}
    assert name_a in names
    assert name_b not in names
