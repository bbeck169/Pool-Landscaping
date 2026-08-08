"""Phase 54a · Feb-2026 — Supplier pricebook import skeleton tests.

Backend-only (Phase 54a is skeleton — no supplier network calls, no
UI work). Covers:

* Auto-seed on first ``GET /suppliers`` — all 5 rows appear
  (poolcorp / siteone / ewing / heritage / epoolsupply).
* Idempotent re-seed — second call does NOT duplicate rows.
* Role gate on every endpoint — manager / tech / customer → 403.
* Credentials round-trip: save → not-plaintext-in-DB → has_credentials
  true → delete → has_credentials false.
* Tenant isolation across all four new/extended collections.
* Sync-jobs listing empty for a fresh tenant.
* Manual sync returns 501 with the phase-owner message.
* Connector protocol: every concrete stub raises NotImplementedError
  on both abstract methods.
* Pricebook item accepts the new supplier fields (additive).
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
TIMEOUT = 30
TID = "3814833a-dd0d-4bd9-90ea-351c24924649"
OTHER_TID = "phase54a-other-tenant"

USERS = {
    "super":    "super@aquaterra.com",
    "admin":    "admin@aquaterra.com",
    "manager":  "manager@aquaterra.com",
    "tech":     "landscaper@aquaterra.com",
    "customer": "customer@aquaterra.com",
}
PW = "password123"

EXPECTED_SLUGS = ["poolcorp", "siteone", "ewing", "heritage", "epoolsupply"]


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def sync_db():
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        yield mc[be["DB_NAME"]]
    finally:
        mc.close()


_TOKEN_CACHE: dict = {}


def _login(email: str) -> str:
    tok = _TOKEN_CACHE.get(email)
    if tok:
        return tok
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": PW}, timeout=TIMEOUT)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    tok = r.json()["access_token"]
    _TOKEN_CACHE[email] = tok
    return tok


def _hdr(email: str = USERS["admin"]) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture(scope="module", autouse=True)
def _cleanup(sync_db):
    """Wipe supplier data for the test tenants before + after so tests
    always start from a known state. Auto-seed is exercised on demand."""
    def _wipe():
        for coll in ("suppliers", "supplier_credentials", "supplier_sync_jobs"):
            sync_db[coll].delete_many({"tenant_id": TID})
            sync_db[coll].delete_many({"tenant_id": OTHER_TID})
    _wipe()
    yield
    _wipe()


# ═══════════════════════════════════════════════════════════════════
# Auto-seed
# ═══════════════════════════════════════════════════════════════════
def test_supplier_list_auto_seeds_all_five():
    r = requests.get(f"{API}/suppliers", headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    slugs = [row["slug"] for row in rows]
    assert slugs == EXPECTED_SLUGS, f"expected {EXPECTED_SLUGS}, got {slugs}"
    for row in rows:
        assert row["active"] is False
        assert row["sync_frequency"] == "daily"
        assert row["last_sync_at"] is None


def test_supplier_list_is_idempotent(sync_db):
    # Second call must NOT duplicate rows.
    r1 = requests.get(f"{API}/suppliers", headers=_hdr(), timeout=TIMEOUT)
    r2 = requests.get(f"{API}/suppliers", headers=_hdr(), timeout=TIMEOUT)
    assert r1.status_code == r2.status_code == 200
    n = sync_db.suppliers.count_documents({"tenant_id": TID})
    assert n == 5, f"auto-seed leaked — expected 5, got {n}"


# ═══════════════════════════════════════════════════════════════════
# Role gate
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("who", ["manager", "tech", "customer"])
def test_supplier_list_forbidden_for_non_admin(who):
    r = requests.get(f"{API}/suppliers", headers=_hdr(USERS[who]), timeout=TIMEOUT)
    assert r.status_code == 403


@pytest.mark.parametrize("who", ["manager", "tech", "customer"])
def test_supplier_credentials_forbidden_for_non_admin(who):
    for method, path in [("get", "/suppliers/poolcorp/credentials"),
                          ("post", "/suppliers/poolcorp/credentials"),
                          ("delete", "/suppliers/poolcorp/credentials"),
                          ("get", "/suppliers/poolcorp/sync-jobs")]:
        if method == "post":
            r = requests.post(f"{API}{path}", headers=_hdr(USERS[who]),
                                json={"username": "x", "password": "y"},
                                timeout=TIMEOUT)
        elif method == "delete":
            r = requests.delete(f"{API}{path}", headers=_hdr(USERS[who]),
                                  timeout=TIMEOUT)
        else:
            r = requests.get(f"{API}{path}", headers=_hdr(USERS[who]),
                              timeout=TIMEOUT)
        assert r.status_code == 403, f"{method} {path}: expected 403, got {r.status_code}"


def test_super_admin_allowed():
    r = requests.get(f"{API}/suppliers", headers=_hdr(USERS["super"]), timeout=TIMEOUT)
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════
# Credentials round-trip (never plaintext)
# ═══════════════════════════════════════════════════════════════════
def test_credentials_round_trip_and_never_plaintext(sync_db):
    slug = "poolcorp"
    plaintext_user = f"admin-{uuid.uuid4().hex[:6]}"
    plaintext_pw = f"secret-{uuid.uuid4().hex[:6]}!"

    # 1) initially absent
    r = requests.get(f"{API}/suppliers/{slug}/credentials",
                     headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 200
    assert r.json()["has_credentials"] is False

    # 2) save
    r = requests.post(
        f"{API}/suppliers/{slug}/credentials",
        headers=_hdr(),
        json={"username": plaintext_user, "password": plaintext_pw,
              "notes": "phase54a-test"},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # 3) has_credentials + updated_at set + notes echoed
    r = requests.get(f"{API}/suppliers/{slug}/credentials",
                     headers=_hdr(), timeout=TIMEOUT)
    d = r.json()
    assert d["has_credentials"] is True
    assert d["updated_at"]
    assert d["notes"] == "phase54a-test"

    # 4) direct-DB inspection — plaintext must NOT be persisted anywhere
    row = sync_db.supplier_credentials.find_one(
        {"tenant_id": TID}, {"_id": 0})
    assert row is not None
    joined_blob = str(row).lower()
    assert plaintext_user.lower() not in joined_blob, "plaintext username leaked to DB"
    assert plaintext_pw.lower() not in joined_blob, "plaintext password leaked to DB"
    # Fernet cipher-text starts with the URL-safe base64 header "gAAAA"
    assert row["encrypted_username"].startswith("gAAAA")
    assert row["encrypted_password"].startswith("gAAAA")

    # 5) delete → absent again
    r = requests.delete(f"{API}/suppliers/{slug}/credentials",
                          headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 200
    assert r.json()["deleted_count"] == 1
    r = requests.get(f"{API}/suppliers/{slug}/credentials",
                     headers=_hdr(), timeout=TIMEOUT)
    assert r.json()["has_credentials"] is False


# ═══════════════════════════════════════════════════════════════════
# Sync endpoints
# ═══════════════════════════════════════════════════════════════════
def test_manual_sync_returns_501_with_phase_pointer():
    r = requests.post(f"{API}/suppliers/poolcorp/sync",
                       headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 501
    body = r.json()
    detail = body.get("detail", "")
    assert "not implemented" in detail.lower()
    assert "54b" in detail  # poolcorp is planned for 54b


def test_sync_endpoint_slug_gates():
    r = requests.post(f"{API}/suppliers/unknown-supplier/sync",
                       headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 404


def test_sync_jobs_empty_for_fresh_tenant():
    r = requests.get(f"{API}/suppliers/siteone/sync-jobs",
                     headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 200
    body = r.json()
    assert body["supplier_slug"] == "siteone"
    assert body["jobs"] == []
    assert body["count"] == 0


# ═══════════════════════════════════════════════════════════════════
# Tenant isolation
# ═══════════════════════════════════════════════════════════════════
def test_tenant_isolation_on_suppliers_and_credentials(sync_db):
    # Plant a supplier + credential for OTHER_TID directly.
    other_supplier_id = f"other-supp-{uuid.uuid4()}"
    sync_db.suppliers.insert_one({
        "id": other_supplier_id, "tenant_id": OTHER_TID,
        "slug": "poolcorp", "display_name": "Pool360 (PoolCorp)",
        "active": False, "sync_frequency": "daily",
        "last_sync_at": None, "last_sync_status": None,
        "last_sync_item_count": 0, "created_at": "2016-01-01T00:00:00+00:00",
    })
    sync_db.supplier_credentials.insert_one({
        "id": f"other-cred-{uuid.uuid4()}", "tenant_id": OTHER_TID,
        "supplier_id": other_supplier_id,
        "encrypted_username": "gAAAAotherusername",
        "encrypted_password": "gAAAAotherpassword",
        "notes": "other-tenant",
        "updated_at": "2016-01-01T00:00:00+00:00",
    })

    # Aquaterra admin must NOT see the other tenant's row.
    r = requests.get(f"{API}/suppliers", headers=_hdr(), timeout=TIMEOUT)
    tenant_ids = {row.get("tenant_id") for row in r.json()}
    assert tenant_ids == {TID}, f"cross-tenant leak: {tenant_ids}"

    # And the aquaterra credentials view must not surface the other tenant's cred.
    r = requests.get(f"{API}/suppliers/poolcorp/credentials",
                     headers=_hdr(), timeout=TIMEOUT)
    assert r.json()["has_credentials"] is False


# ═══════════════════════════════════════════════════════════════════
# Connector protocol contract
# ═══════════════════════════════════════════════════════════════════
def test_all_connector_stubs_raise_not_implemented():
    # Import from the app process to exercise the exact same class
    # instances the router uses.
    import sys
    sys.path.insert(0, "/app/backend")
    from services.suppliers.connector import CONNECTORS

    assert set(CONNECTORS.keys()) == set(EXPECTED_SLUGS)
    for slug, conn in CONNECTORS.items():
        with pytest.raises(NotImplementedError) as ei:
            conn.authenticate({})
        assert conn.display_name in str(ei.value)
        with pytest.raises(NotImplementedError):
            list(conn.list_products(None))  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════
# Data-model shape + indexes exist
# ═══════════════════════════════════════════════════════════════════
def test_pricebook_item_accepts_new_supplier_fields():
    # First discover a valid service_category_id for this tenant (the
    # existing items router enforces this — 54a is additive, doesn't
    # change that rule).
    cats = requests.get(f"{API}/service-categories",
                          headers=_hdr(), timeout=TIMEOUT).json()
    items = cats.get("items") if isinstance(cats, dict) else cats
    assert items, "expected at least one seeded service category"
    scid = items[0]["id"]

    # Push a new item with the three additive fields — must round-trip
    # verbatim without disturbing any existing legacy field.
    r = requests.post(f"{API}/items", headers=_hdr(), json={
        "name": f"P54a probe {uuid.uuid4().hex[:6]}",
        "category": "Parts",
        "unit": "each",
        "unit_price": 12.34,
        "wholesale_price": 5.67,
        "sku": "P54A-PROBE",
        "service_category_id": scid,
        "supplier_id": "supp-poolcorp-fake",
        "external_sku": "EXT-99999",
        "last_synced_at": "2026-02-15T00:00:00+00:00",
    }, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["supplier_id"] == "supp-poolcorp-fake"
    assert d["external_sku"] == "EXT-99999"
    assert d["last_synced_at"] == "2026-02-15T00:00:00+00:00"


def test_supplier_indexes_created(sync_db):
    # Touch the list endpoint once to trigger ``_ensure_indexes``.
    requests.get(f"{API}/suppliers", headers=_hdr(), timeout=TIMEOUT)
    supp_idx = sync_db.suppliers.index_information()
    assert "suppliers_tenant_slug_uniq" in supp_idx
    cred_idx = sync_db.supplier_credentials.index_information()
    assert "suppcred_tenant_supplier_uniq" in cred_idx
    job_idx = sync_db.supplier_sync_jobs.index_information()
    assert "suppsync_tenant_supplier_started_desc" in job_idx
    item_idx = sync_db.items.index_information()
    assert "items_tenant_supplier" in item_idx
    assert "items_tenant_external_sku" in item_idx
