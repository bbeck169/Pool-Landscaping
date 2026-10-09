"""Phase 7A · Feb-2026 — Form Templates contract tests.

Locks the Phase 7A scaffold:

  * Lazy-init on GET creates a v1 seed per form_type.
  * GET per form_type returns the ``is_current`` row.
  * PUT bumps ``version`` and flips ``is_current``.
  * Validation on PUT rejects width_cols=13, invalid hex, duplicate
    field_id, unknown field_id (add), and missing field_id (delete).
  * ``POST /revert/{version}`` flips ``is_current`` back to the
    specified historical version.
  * Role gates: tech + customer + manager cannot PUT (403); tech +
    customer + manager cannot GET versions (403); admin can do both.
  * Tenant isolation: tenant A cannot read or mutate tenant B's
    templates — a GET from tenant A lazily seeds tenant A's own v1
    rather than returning tenant B's doc.
  * All 8 default seed templates are generated (one param case
    per ``form_type``).
"""
from __future__ import annotations

import copy
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values

from tests._shared_mongo import shared_db as _shared_db


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = "HS256"


# ──────────────────────────────────────────────────────────────────
#  Minting helpers
# ──────────────────────────────────────────────────────────────────

def _tok(uid: str, email: str, tid: str, role: str) -> str:
    return jwt.encode(
        {"sub": uid, "email": email, "role": role, "tenant_id": tid,
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _seed_tenant() -> str:
    tid = f"p7a-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one(
        {"id": tid, "name": "P7A form-tpl smoke", "slug": tid, "active": True}
    )
    return tid


def _seed_user(tenant_id: str, role: str) -> dict:
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@p7a.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"P7A {role}", "email": email,
    })
    return {
        "id": uid, "email": email, "tenant_id": tenant_id, "role": role,
        "token": _tok(uid, email, tenant_id, role),
    }


# ──────────────────────────────────────────────────────────────────
#  Fixtures
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tenant_id():
    tid = _seed_tenant()
    yield tid
    for col in ("tenants", "users", "form_templates"):
        _sync[col].delete_many({"tenant_id": tid})


@pytest.fixture
def admin(tenant_id):
    return _seed_user(tenant_id, "admin")


@pytest.fixture
def manager(tenant_id):
    return _seed_user(tenant_id, "manager")


@pytest.fixture
def tech(tenant_id):
    return _seed_user(tenant_id, "technician")


@pytest.fixture
def customer(tenant_id):
    return _seed_user(tenant_id, "customer")


# ──────────────────────────────────────────────────────────────────
#  Seed-builder import (direct, in-process)
# ──────────────────────────────────────────────────────────────────

from routers.form_templates import (                           # noqa: E402
    FORM_TYPES,
    build_default_form_template,
)


# ──────────────────────────────────────────────────────────────────
#  Tests
# ──────────────────────────────────────────────────────────────────

# ── 1 ─ GET returns a lazily-created v1 template per form_type ────
def test_get_list_creates_lazy_v1_per_form_type(admin, tenant_id):
    r = requests.get(f"{API}/form-templates", headers=_auth(admin["token"]),
                     timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["templates"].keys()) == set(FORM_TYPES)
    for ft, doc in body["templates"].items():
        assert doc["version"] == 1
        assert doc["is_current"] is True
        assert doc["tenant_id"] == tenant_id
        assert doc["form_type"] == ft
        assert len(doc["fields"]) > 0


# ── 2 ─ GET per form_type returns the current version ────────────
def test_get_single_form_type_returns_current(admin, tenant_id):
    r = requests.get(f"{API}/form-templates/pool_service_report",
                     headers=_auth(admin["token"]), timeout=20)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["form_type"] == "pool_service_report"
    assert doc["is_current"] is True
    assert doc["version"] == 1
    # Field order on the seed is monotonic 0..N-1.
    orders = [f["order"] for f in doc["fields"]]
    assert orders == list(range(len(orders)))


# ── 3 ─ PUT bumps version + flips is_current ─────────────────────
def test_put_creates_new_version_and_flips_is_current(admin, tenant_id):
    seed = requests.get(
        f"{API}/form-templates/landscape_service_report",
        headers=_auth(admin["token"]), timeout=20,
    ).json()
    # Round-trip the seed with a tiny style tweak so no field_id
    # changes, satisfying the reorder-and-restyle-only validator.
    new_fields = copy.deepcopy(seed["fields"])
    new_fields[0]["style"]["padding_y"] = 4

    r = requests.put(
        f"{API}/form-templates/landscape_service_report",
        headers=_auth(admin["token"]),
        json={"fields": new_fields},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["version"] == 2
    assert updated["is_current"] is True

    # The old v1 should now be flagged ``is_current=False``.
    v1 = _sync.form_templates.find_one(
        {"tenant_id": tenant_id,
         "form_type": "landscape_service_report",
         "version": 1},
        {"_id": 0},
    )
    assert v1 is not None
    assert v1["is_current"] is False


# ── 4 ─ Invalid width_cols=13 → 400 ───────────────────────────────
def test_put_rejects_width_cols_out_of_range(admin):
    seed = requests.get(
        f"{API}/form-templates/estimate",
        headers=_auth(admin["token"]), timeout=20,
    ).json()
    bad = copy.deepcopy(seed["fields"])
    bad[0]["style"]["width_cols"] = 13
    r = requests.put(
        f"{API}/form-templates/estimate",
        headers=_auth(admin["token"]),
        json={"fields": bad}, timeout=20,
    )
    assert r.status_code == 400, r.text
    assert "width_cols" in r.text


# ── 5 ─ Invalid hex color → 400 ───────────────────────────────────
def test_put_rejects_invalid_hex_color(admin):
    seed = requests.get(
        f"{API}/form-templates/estimate",
        headers=_auth(admin["token"]), timeout=20,
    ).json()
    bad = copy.deepcopy(seed["fields"])
    bad[0]["style"]["bg_color"] = "fff"            # missing hash, 3-char
    r = requests.put(
        f"{API}/form-templates/estimate",
        headers=_auth(admin["token"]),
        json={"fields": bad}, timeout=20,
    )
    assert r.status_code == 400, r.text
    assert "bg_color" in r.text or "#RRGGBB" in r.text


# ── 6 ─ PUT that tries to add a new field_id → 400 ────────────────
def test_put_rejects_new_field_id(admin):
    seed = requests.get(
        f"{API}/form-templates/invoice",
        headers=_auth(admin["token"]), timeout=20,
    ).json()
    bad = copy.deepcopy(seed["fields"])
    bad.append({
        "field_id": "surprise_field_from_hostile_caller",
        "label": "Surprise!",
        "field_type": "text",
        "order": 99,
        "locked_reorder": False,
        "style": {
            "bg_color": "#FFFFFF", "bg_alpha": 1.0,
            "text_color": "#111827", "border_color": "#E5E7EB",
            "width_cols": 12, "padding_y": 2,
        },
    })
    r = requests.put(
        f"{API}/form-templates/invoice",
        headers=_auth(admin["token"]),
        json={"fields": bad}, timeout=20,
    )
    assert r.status_code == 400, r.text
    assert "unknown field_id" in r.text


# ── 7 ─ PUT that tries to drop a field → 400 ──────────────────────
def test_put_rejects_dropped_field(admin):
    seed = requests.get(
        f"{API}/form-templates/invoice",
        headers=_auth(admin["token"]), timeout=20,
    ).json()
    bad = copy.deepcopy(seed["fields"])
    bad.pop()  # drop the last seed field
    r = requests.put(
        f"{API}/form-templates/invoice",
        headers=_auth(admin["token"]),
        json={"fields": bad}, timeout=20,
    )
    assert r.status_code == 400, r.text
    assert "missing field_id" in r.text


# ── 7b ─ PUT that duplicates a field_id → 400 ─────────────────────
def test_put_rejects_duplicate_field_id(admin):
    seed = requests.get(
        f"{API}/form-templates/invoice",
        headers=_auth(admin["token"]), timeout=20,
    ).json()
    bad = copy.deepcopy(seed["fields"])
    bad.append(copy.deepcopy(bad[0]))  # duplicate the first field
    r = requests.put(
        f"{API}/form-templates/invoice",
        headers=_auth(admin["token"]),
        json={"fields": bad}, timeout=20,
    )
    assert r.status_code == 400, r.text
    assert "duplicate" in r.text


# ── 8 ─ Revert flips is_current back to an older version ──────────
def test_revert_flips_is_current(admin, tenant_id):
    seed = requests.get(
        f"{API}/form-templates/pool_service_report",
        headers=_auth(admin["token"]), timeout=20,
    ).json()
    # Push a v2.
    new_fields = copy.deepcopy(seed["fields"])
    new_fields[0]["style"]["padding_y"] = 3
    v2 = requests.put(
        f"{API}/form-templates/pool_service_report",
        headers=_auth(admin["token"]),
        json={"fields": new_fields}, timeout=20,
    ).json()
    assert v2["version"] == 2

    # Revert to v1.
    r = requests.post(
        f"{API}/form-templates/pool_service_report/revert/1",
        headers=_auth(admin["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    reverted = r.json()
    assert reverted["version"] == 1
    assert reverted["is_current"] is True

    # v2 should now be ``is_current=False``.
    v2_doc = _sync.form_templates.find_one(
        {"tenant_id": tenant_id,
         "form_type": "pool_service_report",
         "version": 2},
        {"_id": 0},
    )
    assert v2_doc["is_current"] is False


# ── 9 ─ Role gate on PUT (tech + manager + customer 403, admin OK)─
def test_put_role_gate(admin, manager, tech, customer):
    seed = requests.get(
        f"{API}/form-templates/estimate",
        headers=_auth(admin["token"]), timeout=20,
    ).json()
    body = {"fields": seed["fields"]}

    for actor, label in (
        (tech,     "technician"),
        (customer, "customer"),
        (manager,  "manager"),
    ):
        r = requests.put(
            f"{API}/form-templates/estimate",
            headers=_auth(actor["token"]),
            json=body, timeout=20,
        )
        assert r.status_code == 403, f"{label}: {r.status_code} {r.text}"

    # Admin succeeds (bumps to v2).
    ok = requests.put(
        f"{API}/form-templates/estimate",
        headers=_auth(admin["token"]),
        json=body, timeout=20,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["version"] == 2


# ── 10 ─ Role gate on GET versions (tech + manager + customer 403)
def test_versions_role_gate(admin, manager, tech, customer):
    for actor, label in (
        (tech,     "technician"),
        (customer, "customer"),
        (manager,  "manager"),
    ):
        r = requests.get(
            f"{API}/form-templates/estimate/versions",
            headers=_auth(actor["token"]), timeout=20,
        )
        assert r.status_code == 403, f"{label}: {r.status_code} {r.text}"

    r = requests.get(
        f"{API}/form-templates/estimate/versions",
        headers=_auth(admin["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    rows = r.json()["versions"]
    # Lazy-init in the admin GET means at least v1 is present.
    assert len(rows) >= 1
    assert rows[0]["version"] >= 1


# ── 11 ─ Tenant isolation: A can't see or mutate B's templates ────
def test_tenant_isolation(admin):
    # Spin up a second tenant with its own admin and PUT a bespoke
    # v2 so there is a tenant-B-specific style delta to look for.
    tid_b = _seed_tenant()
    admin_b = _seed_user(tid_b, "admin")
    try:
        seed_b = requests.get(
            f"{API}/form-templates/estimate",
            headers=_auth(admin_b["token"]), timeout=20,
        ).json()
        fields_b = copy.deepcopy(seed_b["fields"])
        # Distinctive marker only present on tenant B's v2.
        fields_b[0]["style"]["padding_y"] = 7
        v2_b = requests.put(
            f"{API}/form-templates/estimate",
            headers=_auth(admin_b["token"]),
            json={"fields": fields_b}, timeout=20,
        ).json()
        assert v2_b["version"] == 2

        # Tenant A's GET must return A's doc (lazy v1), not B's v2.
        r_a = requests.get(
            f"{API}/form-templates/estimate",
            headers=_auth(admin["token"]), timeout=20,
        )
        assert r_a.status_code == 200, r_a.text
        doc_a = r_a.json()
        assert doc_a["tenant_id"] == admin["tenant_id"]
        assert doc_a["tenant_id"] != tid_b
        # Marker from B must NOT be in A's response.
        assert doc_a["fields"][0]["style"]["padding_y"] != 7

        # Tenant A's version-history GET must not expose tenant B's rows.
        r_vers = requests.get(
            f"{API}/form-templates/estimate/versions",
            headers=_auth(admin["token"]), timeout=20,
        )
        assert r_vers.status_code == 200, r_vers.text
        rows = r_vers.json()["versions"]
        for row in rows:
            assert row["tenant_id"] == admin["tenant_id"]
            assert row["tenant_id"] != tid_b

        # Revert of a version that does NOT belong to tenant A must 404.
        bogus = requests.post(
            f"{API}/form-templates/estimate/revert/999",
            headers=_auth(admin["token"]), timeout=20,
        )
        assert bogus.status_code == 404
    finally:
        for col in ("tenants", "users", "form_templates"):
            _sync[col].delete_many({"tenant_id": tid_b})


# ── 12 ─ All 8 seed templates generate cleanly ────────────────────
@pytest.mark.parametrize("form_type", list(FORM_TYPES))
def test_seed_builder_covers_every_form_type(form_type):
    tpl = build_default_form_template(form_type)
    assert "fields" in tpl
    assert len(tpl["fields"]) > 0
    seen_ids: set = set()
    for i, f in enumerate(tpl["fields"]):
        assert f["order"] == i, f"{form_type} field {i} order mismatch"
        assert f["field_id"] not in seen_ids, f"{form_type} dup field_id"
        seen_ids.add(f["field_id"])
        assert f["locked_reorder"] in (True, False)
        s = f["style"]
        assert 1 <= s["width_cols"] <= 12
        assert 1 <= s["padding_y"] <= 8
        assert 0.0 <= s["bg_alpha"] <= 1.0


# ── 12b ─ OpenAPI confirmation: endpoints are routed ──────────────
def test_openapi_lists_form_templates_endpoints():
    r = requests.get(f"{API}/openapi.json", timeout=20)
    assert r.status_code == 200, r.text
    paths = r.json().get("paths", {})
    assert "/api/form-templates" in paths
    assert "/api/form-templates/{form_type}" in paths
    assert "/api/form-templates/{form_type}/versions" in paths
    assert "/api/form-templates/{form_type}/revert/{version}" in paths
