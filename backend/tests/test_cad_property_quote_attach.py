"""TD-cad-phase1 · Oct-2026 — pytest for property_id + quote_id attach
fields + role widening to require_admin_or_manager on the /designs CRUD
endpoints.

Covers:
  §1 property_id / quote_id round-trip (create → GET → PUT → DELETE).
  §2 List-filter by property_id + quote_id returns only matching docs.
  §3 Cross-tenant property reference → 404.
  §4 Cross-tenant quote reference → 404.
  §5 Role widening — manager CRUDs; technician + customer are 403.
  §6 Legacy designs with no property_id/quote_id serialise unchanged
     (backward-compat lock).
  §7 Vendor-cleanup narrowing (GAP-C correction) — ``cad.py`` carries
     the inline comment documenting the Google vs Mapbox split and
     explicitly stating that ``MAPBOX_ACCESS_TOKEN`` must NOT be
     removed (would break 5 other surfaces).

Pattern mirrors test_cad_marco_generate_endpoint.py (TestClient +
monkeypatched DB) so the existing 2014-LOC designs pytest baseline
stays byte-identical.
"""
from __future__ import annotations

import os
import sys
import uuid
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from server import app  # noqa: E402

client = TestClient(app)

TENANT_A = "tenant-A"
TENANT_B = "tenant-B"
PFX = f"td_cad_p1_{uuid.uuid4().hex[:6]}_"


# ─── Fake async Mongo collections (chainable; just enough) ──────────
class _Cursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def sort(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    async def to_list(self, _n):
        return list(self._rows)


class _Coll:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []

    async def find_one(self, filt, projection=None):
        for d in self.docs:
            if _m(d, filt):
                return dict(d)
        return None

    def find(self, filt, projection=None):
        return _Cursor([d for d in self.docs if _m(d, filt)])

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return type("R", (), {"inserted_id": "x"})

    async def update_one(self, filt, update, upsert=False):
        for d in self.docs:
            if _m(d, filt):
                d.update(update.get("$set", {}))
                return type("R", (), {"matched_count": 1, "modified_count": 1})
        return type("R", (), {"matched_count": 0, "modified_count": 0})

    async def delete_one(self, filt):
        before = len(self.docs)
        self.docs[:] = [d for d in self.docs if not _m(d, filt)]
        return type("R", (), {"deleted_count": before - len(self.docs)})


def _m(doc, filt):
    for k, v in filt.items():
        if doc.get(k) != v:
            return False
    return True


class _FakeDB:
    def __init__(self):
        self.designs = _Coll()
        self.design_media = _Coll()
        self.properties = _Coll()
        self.quotes = _Coll()


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    fake = _FakeDB()
    from routers import cad as _cad_mod
    monkeypatch.setattr(_cad_mod, "db", fake, raising=False)
    yield fake
    app.dependency_overrides.clear()


def _as(role: str, tenant_id: str = TENANT_A, user_id: str = "user-1"):
    from utils import get_current_user
    from routers.tenants import get_current_tenant
    user = {"id": user_id, "tenant_id": tenant_id,
              "role": role, "email": f"{role}@e.com", "name": role}
    tenant = {"id": tenant_id, "name": "T"}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    return user


def _seed_property(fake, pid, tenant_id=TENANT_A):
    fake.properties.docs.append(
        {"id": pid, "tenant_id": tenant_id, "name": f"prop {pid}"})


def _seed_quote(fake, qid, tenant_id=TENANT_A):
    fake.quotes.docs.append(
        {"id": qid, "tenant_id": tenant_id, "number": "Q-1"})


# ═══════════════ §1 · property_id/quote_id round-trip ═══════════════
def test_property_id_create_get_update_delete_roundtrip(_wire):
    _as("admin")
    _seed_property(_wire, "prop-1")
    r = client.post("/api/designs", json={
        "name": "P-design", "property_id": "prop-1",
    })
    assert r.status_code == 200, r.text
    did = r.json()["id"]
    assert r.json()["property_id"] == "prop-1"
    # GET single
    r2 = client.get(f"/api/designs/{did}")
    assert r2.status_code == 200
    assert r2.json()["property_id"] == "prop-1"
    # PUT update (also seed a new property)
    _seed_property(_wire, "prop-2")
    r3 = client.put(f"/api/designs/{did}", json={
        "name": "P-design", "property_id": "prop-2",
    })
    assert r3.status_code == 200
    assert r3.json()["property_id"] == "prop-2"
    # DELETE
    r4 = client.delete(f"/api/designs/{did}")
    assert r4.status_code == 200
    assert r4.json() == {"ok": True}


def test_quote_id_create_roundtrip(_wire):
    _as("admin")
    _seed_quote(_wire, "quote-1")
    r = client.post("/api/designs", json={
        "name": "Q-design", "quote_id": "quote-1",
    })
    assert r.status_code == 200, r.text
    assert r.json()["quote_id"] == "quote-1"


# ═══════════════ §2 · Filter by property_id / quote_id ═══════════════
def test_list_filter_by_property_id(_wire):
    _as("admin")
    _seed_property(_wire, "prop-1")
    _seed_property(_wire, "prop-2")
    for name, pid in [("d1", "prop-1"), ("d2", "prop-1"), ("d3", "prop-2")]:
        client.post("/api/designs", json={"name": name, "property_id": pid})
    r = client.get("/api/designs?property_id=prop-1")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert all(d["property_id"] == "prop-1" for d in rows)


def test_list_filter_by_quote_id(_wire):
    _as("admin")
    _seed_quote(_wire, "q-A")
    _seed_quote(_wire, "q-B")
    for name, qid in [("d1", "q-A"), ("d2", "q-B"), ("d3", "q-A")]:
        client.post("/api/designs", json={"name": name, "quote_id": qid})
    r = client.get("/api/designs?quote_id=q-A")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert all(d["quote_id"] == "q-A" for d in rows)


# ═══════════════ §3+§4 · Cross-tenant 404 ════════════════════════════
def test_cross_tenant_property_reference_404(_wire):
    _as("admin", tenant_id=TENANT_A)
    _seed_property(_wire, "cross-prop", tenant_id=TENANT_B)
    r = client.post("/api/designs", json={
        "name": "x", "property_id": "cross-prop",
    })
    assert r.status_code == 404, r.text


def test_cross_tenant_quote_reference_404(_wire):
    _as("admin", tenant_id=TENANT_A)
    _seed_quote(_wire, "cross-quote", tenant_id=TENANT_B)
    r = client.post("/api/designs", json={
        "name": "x", "quote_id": "cross-quote",
    })
    assert r.status_code == 404, r.text


def test_nonexistent_property_reference_404(_wire):
    _as("admin")
    r = client.post("/api/designs", json={
        "name": "x", "property_id": "nope",
    })
    assert r.status_code == 404


# ═══════════════ §5 · Role widening ══════════════════════════════════
@pytest.mark.parametrize("role", ["admin", "super_admin", "owner", "manager"])
def test_role_widening_allows_cad_crud(_wire, role):
    _as(role)
    r = client.post("/api/designs", json={"name": "r-test"})
    assert r.status_code == 200, (role, r.text)
    did = r.json()["id"]
    assert client.get(f"/api/designs/{did}").status_code == 200
    assert client.put(f"/api/designs/{did}",
                       json={"name": "r-test-2"}).status_code == 200
    assert client.delete(f"/api/designs/{did}").status_code == 200
    assert client.get("/api/designs").status_code == 200


@pytest.mark.parametrize("role", ["technician", "customer"])
def test_role_widening_still_blocks_below_tier(_wire, role):
    _as(role)
    assert client.get("/api/designs").status_code == 403
    assert client.post("/api/designs", json={"name": "x"}).status_code == 403


# ═══════════════ §6 · Legacy design backward-compat ══════════════════
def test_legacy_design_without_fk_fields_still_serialises(_wire):
    _as("admin")
    r = client.post("/api/designs", json={"name": "legacy"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["property_id"] is None
    assert body["quote_id"] is None
    assert body["customer_id"] is None
    assert body["lead_id"] is None


# ═══════════════ §7 · GAP-C vendor-cleanup narrowing lock ════════════
def test_gap_c_vendor_split_comment_present_in_cad_source():
    """Phase 1 narrowed GAP-C to an inline comment because
    MAPBOX_ACCESS_TOKEN is NOT dead config (5 other surfaces consume
    it: property.py + gps_route.py + maps/dispatcher.py +
    reverse_geocoder.py + gps_stops_batch.py). Lock the comment so a
    future refactor can't remove it without seeing the test fail."""
    cad_src = os.path.join(_BACKEND, "routers", "cad.py")
    with open(cad_src, "r", encoding="utf-8") as fh:
        source = fh.read()
    # The vendor-split comment MUST remain in place.
    assert "MAPBOX_ACCESS_TOKEN" in source
    assert "Google Static Maps" in source
    assert "property.py" in source or "routers.property" in source  # the comment names the dependent surfaces
    assert "reverse_geocoder" in source
