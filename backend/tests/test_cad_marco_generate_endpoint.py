"""Phase CAD-2 · Feb-2026 — MARCO shape-generation endpoint.

Locks the ``POST /api/cad/generate`` contract:

  * Happy path returns validated + clamped shapes with a
    ``generation_id`` + ``reasoning`` + ``warnings`` array.
  * Invalid JSON from the LLM retries ONCE then 502.
  * Coords outside ``[0..1]`` are clamped in-place with a warning.
  * Missing ``design_id`` AND missing ``context.canvas_w_ft`` → 400.
  * Tenant-scoped design lookup + admin-only auth guard.
  * ``EMERGENT_LLM_KEY`` empty → 424.
  * All outbound LLM calls are patched via
    ``routers.cad.dispatch_ai_completion``. No real Emergent calls.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

TENANT_A = "test-cad2-marco-tenant-a"
TENANT_B = "test-cad2-marco-tenant-b"


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _reset_fixtures():
    db = _sync_db()
    db.tenants.delete_many({"id": {"$in": [TENANT_A, TENANT_B]}})
    db.designs.delete_many(
        {"tenant_id": {"$in": [TENANT_A, TENANT_B]}},
    )
    db.tenants.insert_one({"id": TENANT_A, "name": "Tenant A"})
    db.tenants.insert_one({"id": TENANT_B, "name": "Tenant B"})


def _seed_design(did: str, *, tenant_id: str = TENANT_A):
    _sync_db().designs.insert_one({
        "id": did, "tenant_id": tenant_id,
        "name": "Marco Test", "canvas_w_ft": 60, "canvas_h_ft": 40,
        "boundary": [], "elements": [],
        "feet_per_pixel": 0.5,
    })


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
        async def _go(db):
            from server import app
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                await coro_factory(ac, db)
        run_test(_go)
    finally:
        clear()


class _FakeAIResult:
    def __init__(self, content: str):
        self.content = content


def _install_llm_mock(monkeypatch, *, responses):
    """Patch ``routers.cad.dispatch_ai_completion`` to return the
    provided response strings in order. Each call consumes one
    response — extra calls raise a fail-loud AssertionError so an
    unexpected retry surfaces in the test."""
    import routers.cad as cad_mod
    from services.ai import dispatch_ai_completion as _real_import  # noqa: F401
    # Force the lazy import inside the handler to resolve to our
    # module attribute by installing it directly on the module.
    calls = {"count": 0}
    it = iter(responses)

    async def _fake(**_kw):
        calls["count"] += 1
        try:
            content = next(it)
        except StopIteration:
            raise AssertionError(
                f"dispatch_ai_completion called {calls['count']} "
                f"times; only {len(responses)} response(s) queued",
            )
        return _FakeAIResult(content)

    # ``routers.cad.cad_generate`` does a lazy
    # ``from services.ai import dispatch_ai_completion`` inside the
    # function body — patch the source module attribute so both
    # ``services.ai`` and ``routers.cad`` (if it had cached one)
    # see the mock.
    import services.ai as _sa
    monkeypatch.setattr(_sa, "dispatch_ai_completion", _fake)
    # Also install on ``routers.cad`` in case a future refactor
    # promotes the import to module level.
    monkeypatch.setattr(
        cad_mod, "dispatch_ai_completion", _fake, raising=False,
    )
    return calls


# ═══════════════════════════════════════════════════════════════════
# §1 · Happy path — valid shapes returned + generation_id present
# ═══════════════════════════════════════════════════════════════════
def test_cad_generate_happy_path(monkeypatch):
    _reset_fixtures()
    _seed_design("d-happy")
    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-emergent-fake")
    _install_llm_mock(monkeypatch, responses=[json.dumps({
        "shapes": [
            {"type": "pool",
             "coords": [{"x": 0.2, "y": 0.3}, {"x": 0.5, "y": 0.3},
                        {"x": 0.5, "y": 0.6}, {"x": 0.2, "y": 0.6}],
             "dims_ft": {"w": 15, "h": 30},
             "label": "Pool 15x30"},
            {"type": "icon", "icon": "tree",
             "coords": [{"x": 0.1, "y": 0.1}],
             "dims_ft": None, "label": None},
        ],
        "reasoning": "Placed a pool on the sunny south side and a "
                     "shade tree on the north.",
    })])

    async def _t(ac, _db):
        r = await ac.post(
            "/api/cad/generate",
            json={"design_id": "d-happy",
                  "prompt": "add a pool + a shade tree"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["generation_id"]
        assert len(body["shapes"]) == 2
        pool = body["shapes"][0]
        assert pool["type"] == "pool"
        assert len(pool["coords"]) == 4
        tree = body["shapes"][1]
        assert tree["type"] == "icon"
        assert tree["icon"] == "tree"
        assert "shade tree" in body["reasoning"]
        assert body["warnings"] == []

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §2 · Invalid JSON triggers retry then 502
# ═══════════════════════════════════════════════════════════════════
def test_cad_generate_invalid_json_retries_then_502(monkeypatch):
    _reset_fixtures()
    _seed_design("d-badjson")
    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-emergent-fake")
    calls = _install_llm_mock(monkeypatch, responses=[
        "not json at all", "still not json",
    ])

    async def _t(ac, _db):
        r = await ac.post(
            "/api/cad/generate",
            json={"design_id": "d-badjson", "prompt": "chaos please"},
        )
        assert r.status_code == 502, r.text
        assert r.json()["detail"]["error_code"] == "marco_invalid_shape_json"
        # Two attempts fired — initial + one retry.
        assert calls["count"] == 2

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §3 · Boundary-out-of-range coords get clamped + warning
# ═══════════════════════════════════════════════════════════════════
def test_cad_generate_out_of_range_coords_clamped(monkeypatch):
    _reset_fixtures()
    _seed_design("d-clamp")
    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-emergent-fake")
    _install_llm_mock(monkeypatch, responses=[json.dumps({
        "shapes": [
            {"type": "paver",
             "coords": [{"x": -0.2, "y": 0.1}, {"x": 1.5, "y": 0.1},
                        {"x": 1.5, "y": 1.4}, {"x": -0.2, "y": 1.4}],
             "dims_ft": None, "label": "Overhang deck"},
        ],
        "reasoning": "Paver deck.",
    })])

    async def _t(ac, _db):
        r = await ac.post(
            "/api/cad/generate",
            json={"design_id": "d-clamp", "prompt": "deck it out"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["shapes"]) == 1
        clamped = body["shapes"][0]["coords"]
        # Every clamped coord landed within [0, 1].
        for p in clamped:
            assert 0.0 <= p["x"] <= 1.0
            assert 0.0 <= p["y"] <= 1.0
        # A warning surfaced for the clamp.
        assert any("clamped" in w for w in body["warnings"])

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §4 · Missing design_id AND missing context.canvas_w_ft → 400
# ═══════════════════════════════════════════════════════════════════
def test_cad_generate_missing_canvas_context_400(monkeypatch):
    _reset_fixtures()
    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-emergent-fake")
    # No LLM mock — the endpoint must short-circuit before dispatch.
    async def _t(ac, _db):
        r = await ac.post(
            "/api/cad/generate",
            json={"prompt": "design something"},
        )
        assert r.status_code == 400, r.text
        assert r.json()["detail"]["error_code"] == "missing_canvas_context"

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §5 · Tenant scoping — design in Tenant A invisible from Tenant B
# ═══════════════════════════════════════════════════════════════════
def test_cad_generate_tenant_isolation(monkeypatch):
    _reset_fixtures()
    _seed_design("d-crosstenant", tenant_id=TENANT_A)
    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-emergent-fake")

    async def _t(ac, _db):
        r = await ac.post(
            "/api/cad/generate",
            json={"design_id": "d-crosstenant", "prompt": "hi"},
        )
        assert r.status_code == 404, r.text
        assert r.json()["detail"]["error_code"] == "design_not_found"

    _run(_t, tenant_id=TENANT_B)


# ═══════════════════════════════════════════════════════════════════
# §6 · Non-admin → 403
# ═══════════════════════════════════════════════════════════════════
def test_cad_generate_non_admin_403(monkeypatch):
    _reset_fixtures()
    _seed_design("d-role")
    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-emergent-fake")

    async def _t(ac, _db):
        r = await ac.post(
            "/api/cad/generate",
            json={"design_id": "d-role", "prompt": "hi"},
        )
        assert r.status_code == 403, r.text

    _run(_t, role="technician")


# ═══════════════════════════════════════════════════════════════════
# §7 · Missing EMERGENT_LLM_KEY → 424
# ═══════════════════════════════════════════════════════════════════
def test_cad_generate_missing_emergent_key_424(monkeypatch):
    _reset_fixtures()
    _seed_design("d-nokey")
    monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)

    async def _t(ac, _db):
        r = await ac.post(
            "/api/cad/generate",
            json={"design_id": "d-nokey", "prompt": "hi"},
        )
        assert r.status_code == 424, r.text
        assert r.json()["detail"]["error_code"] == "emergent_llm_key_missing"

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §8 · Body-only context (no design_id) works
# ═══════════════════════════════════════════════════════════════════
def test_cad_generate_body_only_context(monkeypatch):
    _reset_fixtures()
    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-emergent-fake")
    _install_llm_mock(monkeypatch, responses=[json.dumps({
        "shapes": [
            {"type": "spa",
             "coords": [{"x": 0.4, "y": 0.4}, {"x": 0.6, "y": 0.4},
                        {"x": 0.6, "y": 0.5}, {"x": 0.4, "y": 0.5}],
             "dims_ft": {"w": 8, "h": 6}, "label": "Spa"},
        ],
        "reasoning": "Standalone spa preview.",
    })])

    async def _t(ac, _db):
        r = await ac.post(
            "/api/cad/generate",
            json={
                "prompt": "spa please",
                "context": {"canvas_w_ft": 40, "canvas_h_ft": 30},
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["shapes"][0]["type"] == "spa"

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §9 · Fenced ```json parses successfully
# ═══════════════════════════════════════════════════════════════════
def test_cad_generate_accepts_fenced_json(monkeypatch):
    _reset_fixtures()
    _seed_design("d-fenced")
    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-emergent-fake")
    payload = json.dumps({
        "shapes": [{"type": "wall",
                    "coords": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}],
                    "dims_ft": {"length_ft": 48}, "label": None}],
        "reasoning": "Retaining wall along the fence.",
    })
    fenced = f"```json\n{payload}\n```"
    _install_llm_mock(monkeypatch, responses=[fenced])

    async def _t(ac, _db):
        r = await ac.post(
            "/api/cad/generate",
            json={"design_id": "d-fenced", "prompt": "wall it up"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["shapes"][0]["type"] == "wall"

    _run(_t)
