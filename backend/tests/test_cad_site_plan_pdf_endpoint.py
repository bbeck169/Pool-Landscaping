"""Phase CAD-3 · Feb-2026 — Site Plan PDF endpoint.

Locks the ``POST /api/cad/designs/{did}/site-plan-pdf`` contract.

Outbound Google Static Maps calls are patched via
``routers.cad._fetch_static_map_bytes`` — no real HTTP is issued.

Page-1 render-context assertions run against the pure helper
``services.cad.site_plan_pdf.build_render_context`` so we don't
have to parse PDF binaries to verify placeholder degradation.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

TENANT_A = "test-cad3-tenant-a"
TENANT_B = "test-cad3-tenant-b"

# The two-byte PNG stub is enough for ReportLab ``drawImage`` to
# recognise the format without needing a real image (we exercise
# the failure path branch when the stub is invalid too).
_PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
    b"\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx"
    b"\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\xc4\x00\x00\x00\x00"
    b"IEND\xaeB`\x82"
)


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _reset_fixtures():
    db = _sync_db()
    db.tenants.delete_many({"id": {"$in": [TENANT_A, TENANT_B]}})
    db.customers.delete_many(
        {"tenant_id": {"$in": [TENANT_A, TENANT_B]}},
    )
    db.designs.delete_many(
        {"tenant_id": {"$in": [TENANT_A, TENANT_B]}},
    )
    db.design_media.delete_many(
        {"tenant_id": {"$in": [TENANT_A, TENANT_B]}},
    )
    db.tenants.insert_one({"id": TENANT_A, "name": "Tenant A"})
    db.tenants.insert_one({"id": TENANT_B, "name": "Tenant B"})


def _seed_customer(cid: str, *, tenant_id: str = TENANT_A,
                   address: str = "123 Main St, Miami FL 33101",
                   name: str = "Robert Blake"):
    _sync_db().customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": name, "address": address,
        "phone": "555-0100", "email": "robert@example.com",
    })


def _seed_design(did: str, *,
                 tenant_id: str = TENANT_A,
                 customer_id: str = "cust-marco",
                 elements: list | None = None,
                 boundary: list | None = None,
                 map_meta: bool = True):
    doc = {
        "id": did, "tenant_id": tenant_id,
        "customer_id": customer_id,
        "name": "Backyard plan",
        "canvas_w_ft": 60.0, "canvas_h_ft": 40.0,
        "feet_per_pixel": 0.5,
        "elements": elements or [],
        "boundary": boundary or [],
    }
    if map_meta:
        doc.update({
            "map_center_lat": 25.7617,
            "map_center_lng": -80.1918,
            "map_zoom": 19,
            "map_size_px": {"w": 800, "h": 500},
        })
    _sync_db().designs.insert_one(doc)


def _install_overrides(*, role="admin", tenant_id=TENANT_A):
    from server import app
    from utils import get_current_user, require_admin
    from routers.tenants import get_current_tenant

    async def _u():
        return {"id": "u_admin", "role": role, "email": "a@x",
                "tenant_id": tenant_id}

    async def _t():
        d = _sync_db().tenants.find_one({"id": tenant_id}) or {}
        d.pop("_id", None)
        return d

    async def _require_admin_dep():
        if role in ("admin", "super_admin"):
            return await _u()
        from fastapi import HTTPException
        raise HTTPException(403, "admin only")

    app.dependency_overrides[get_current_user] = _u
    app.dependency_overrides[get_current_tenant] = _t
    app.dependency_overrides[require_admin] = _require_admin_dep

    def _clear():
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_tenant, None)
        app.dependency_overrides.pop(require_admin, None)
    return _clear


def _run(coro_factory, *, role="admin", tenant_id=TENANT_A):
    clear = _install_overrides(role=role, tenant_id=tenant_id)
    try:
        async def _go(_db):
            from server import app
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                await coro_factory(ac, _db)
        run_test(_go)
    finally:
        clear()


def _install_map_mock(monkeypatch, *, png: bytes = _PNG_1x1):
    """Patch ``_fetch_static_map_bytes`` on the CAD router."""
    import routers.cad as cad_mod

    async def _fake(**_kw):
        return png

    monkeypatch.setattr(cad_mod, "_fetch_static_map_bytes", _fake)


# ═══════════════════════════════════════════════════════════════════
# §1 · Happy path
# ═══════════════════════════════════════════════════════════════════
def test_site_plan_pdf_happy_path(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-1")
    _seed_design("d-1", customer_id="cust-1", elements=[
        {"id": "el-pool", "type": "pool",
         "coords": [{"x": 0.2, "y": 0.3}, {"x": 0.5, "y": 0.3},
                    {"x": 0.5, "y": 0.6}, {"x": 0.2, "y": 0.6}]},
        {"id": "el-paver", "type": "paver",
         "coords": [{"x": 0.1, "y": 0.7}, {"x": 0.4, "y": 0.7},
                    {"x": 0.4, "y": 0.9}, {"x": 0.1, "y": 0.9}]},
        {"id": "el-wall", "type": "wall",
         "coords": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}]},
        {"id": "el-tree", "type": "icon",
         "coords": [{"x": 0.5, "y": 0.05}],
         "props": {"icon": "tree"}},
    ])
    _install_map_mock(monkeypatch)

    async def _t(ac, _db):
        r = await ac.post("/api/cad/designs/d-1/site-plan-pdf")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pages"] == 2
        assert body["media_id"]
        assert body["media_url"].startswith("/api/uploads/design_pdfs/")
        assert body["media_url"].endswith(".pdf")
        assert body["size_bytes"] > 500
        assert body["filename"].startswith("site-plan-")
        # Bytes exist on disk.
        pod_path = Path(body["media_url"].replace(
            "/api/uploads/", "/app/backend/uploads/"))
        assert pod_path.exists()
        assert pod_path.stat().st_size == body["size_bytes"]
        # PDF magic marker.
        assert pod_path.read_bytes()[:4] == b"%PDF"
        # design_media row created.
        rows = list(_sync_db().design_media.find(
            {"design_id": "d-1"}, {"_id": 0},
        ))
        assert len(rows) == 1
        assert rows[0]["kind"] == "site_plan_pdf"

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §2 · Design without customer_id → 400
# ═══════════════════════════════════════════════════════════════════
def test_site_plan_pdf_missing_customer_id_400(monkeypatch):
    _reset_fixtures()
    _seed_design("d-nc", customer_id=None)
    _sync_db().designs.update_one(
        {"id": "d-nc"}, {"$set": {"customer_id": None}},
    )
    _install_map_mock(monkeypatch)

    async def _t(ac, _db):
        r = await ac.post("/api/cad/designs/d-nc/site-plan-pdf")
        assert r.status_code == 400, r.text
        assert r.json()["detail"]["error_code"] == "design_customer_missing"

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §3 · Empty-address customer → 200, render context has placeholders
# ═══════════════════════════════════════════════════════════════════
def test_site_plan_pdf_empty_address_render_context(monkeypatch):
    from services.cad.site_plan_pdf import build_render_context
    design = {
        "id": "d-3", "tenant_id": TENANT_A,
        "customer_id": "cust-noaddr", "name": "X",
        "canvas_w_ft": 60, "canvas_h_ft": 40,
        "feet_per_pixel": 0.5,
        "map_center_lat": 25.76, "map_center_lng": -80.19,
        "map_zoom": 19, "elements": [], "boundary": [],
    }
    customer = {
        "id": "cust-noaddr", "tenant_id": TENANT_A,
        "name": "Anonymous", "address": "",  # ← empty
        "phone": "", "email": "",
    }
    tenant = {"id": TENANT_A, "name": "T"}
    ctx = build_render_context(
        design=design, customer=customer, tenant=tenant,
        map_bytes=_PNG_1x1, generated_by="u1",
    )
    # Address / phone / email collapse to "—".
    assert ctx["customer"]["address"] == "—"
    assert ctx["customer"]["phone"] == "—"
    assert ctx["customer"]["email"] == "—"
    # Name is present because we seeded it.
    assert ctx["customer"]["name"] == "Anonymous"
    # No warnings — this is degrade, not fail.
    assert ctx["map_state"] == "available"


# ═══════════════════════════════════════════════════════════════════
# §4 · Legacy design (only pool + boundary, no CAD-2 types) renders
# ═══════════════════════════════════════════════════════════════════
def test_site_plan_pdf_legacy_only(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-legacy")
    _sync_db().designs.insert_one({
        "id": "d-legacy", "tenant_id": TENANT_A,
        "customer_id": "cust-legacy",
        "name": "Legacy design",
        "canvas_w_ft": 60.0, "canvas_h_ft": 40.0,
        # Legacy x/y/w/h element shape.
        "elements": [
            {"id": "e-old-pool", "type": "pool",
             "x": 0.2, "y": 0.3, "w": 0.3, "h": 0.3},
        ],
        "boundary": [
            {"x": 0.05, "y": 0.05}, {"x": 0.95, "y": 0.05},
            {"x": 0.95, "y": 0.95}, {"x": 0.05, "y": 0.95},
        ],
        "map_center_lat": 25.7617, "map_center_lng": -80.1918,
        "map_zoom": 19,
    })
    _install_map_mock(monkeypatch)

    async def _t(ac, _db):
        r = await ac.post("/api/cad/designs/d-legacy/site-plan-pdf")
        assert r.status_code == 200, r.text
        # Row created.
        rows = list(_sync_db().design_media.find(
            {"design_id": "d-legacy"}, {"_id": 0},
        ))
        assert len(rows) == 1

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §5 · Missing map metadata → renders with blank white backdrop
# ═══════════════════════════════════════════════════════════════════
def test_site_plan_pdf_missing_map_metadata(monkeypatch):
    from services.cad.site_plan_pdf import build_render_context
    design = {
        "id": "d-5", "tenant_id": TENANT_A,
        "customer_id": "c5", "name": "Nomap",
        "canvas_w_ft": 60, "canvas_h_ft": 40,
        "feet_per_pixel": None,
        # No map_center_lat/lng.
        "map_center_lat": None, "map_center_lng": None,
        "map_zoom": None, "elements": [], "boundary": [],
    }
    customer = {"id": "c5", "name": "C5", "address": "123 X",
                "phone": "", "email": ""}
    tenant = {"id": TENANT_A, "name": "T"}
    ctx = build_render_context(
        design=design, customer=customer, tenant=tenant,
        map_bytes=None, generated_by="u1",
    )
    assert ctx["map_state"] == "unavailable"
    assert ctx["map_caption"] == "No satellite backdrop available"
    # Endpoint round-trip renders successfully with no map.
    _reset_fixtures()
    _seed_customer("c5")
    _sync_db().designs.insert_one({
        "id": "d-5", "tenant_id": TENANT_A,
        "customer_id": "c5", "name": "Nomap",
        "canvas_w_ft": 60.0, "canvas_h_ft": 40.0,
        "elements": [], "boundary": [],
    })
    _install_map_mock(monkeypatch)

    async def _t(ac, _db):
        r = await ac.post("/api/cad/designs/d-5/site-plan-pdf")
        assert r.status_code == 200, r.text

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §6 · Non-admin → 403
# ═══════════════════════════════════════════════════════════════════
def test_site_plan_pdf_non_admin_403(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-6")
    _seed_design("d-6", customer_id="cust-6")
    _install_map_mock(monkeypatch)

    async def _t(ac, _db):
        r = await ac.post("/api/cad/designs/d-6/site-plan-pdf")
        assert r.status_code == 403, r.text

    _run(_t, role="technician")


# ═══════════════════════════════════════════════════════════════════
# §7 · Cross-tenant → 404
# ═══════════════════════════════════════════════════════════════════
def test_site_plan_pdf_cross_tenant_404(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-7", tenant_id=TENANT_A)
    _seed_design("d-7", tenant_id=TENANT_A, customer_id="cust-7")
    _install_map_mock(monkeypatch)

    async def _t(ac, _db):
        r = await ac.post("/api/cad/designs/d-7/site-plan-pdf")
        assert r.status_code == 404, r.text
        assert r.json()["detail"]["error_code"] == "design_not_found"

    _run(_t, tenant_id=TENANT_B)


# ═══════════════════════════════════════════════════════════════════
# §8 · Media attachment surfaces on GET /designs/{did}
# ═══════════════════════════════════════════════════════════════════
def test_site_plan_pdf_appears_on_design_get(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-8")
    _seed_design("d-8", customer_id="cust-8")
    _install_map_mock(monkeypatch)

    async def _t(ac, _db):
        r0 = await ac.get("/api/designs/d-8")
        assert r0.status_code == 200
        assert r0.json().get("media_attachments") == []
        # Generate.
        r1 = await ac.post("/api/cad/designs/d-8/site-plan-pdf")
        assert r1.status_code == 200
        media_id = r1.json()["media_id"]
        # Re-fetch design.
        r2 = await ac.get("/api/designs/d-8")
        assert r2.status_code == 200
        atts = r2.json().get("media_attachments") or []
        assert len(atts) == 1
        assert atts[0]["id"] == media_id
        assert atts[0]["kind"] == "site_plan_pdf"

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §9 · Repeat generation adds versions, does not overwrite
# ═══════════════════════════════════════════════════════════════════
def test_site_plan_pdf_versioning(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-9")
    _seed_design("d-9", customer_id="cust-9")
    _install_map_mock(monkeypatch)

    async def _t(ac, _db):
        r1 = await ac.post("/api/cad/designs/d-9/site-plan-pdf")
        r2 = await ac.post("/api/cad/designs/d-9/site-plan-pdf")
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["media_id"] != r2.json()["media_id"]
        rows = list(_sync_db().design_media.find(
            {"design_id": "d-9"}, {"_id": 0},
        ))
        assert len(rows) == 2

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §10 · Response ``pages`` value is 2
# ═══════════════════════════════════════════════════════════════════
def test_site_plan_pdf_pages_is_two(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-10")
    _seed_design("d-10", customer_id="cust-10")
    _install_map_mock(monkeypatch)

    async def _t(ac, _db):
        r = await ac.post("/api/cad/designs/d-10/site-plan-pdf")
        assert r.status_code == 200
        assert r.json()["pages"] == 2

    _run(_t)
