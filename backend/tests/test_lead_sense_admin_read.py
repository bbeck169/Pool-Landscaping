"""LSP-1 · Feb-2026 — Lead-Sense admin read surface tests.

Locks the fifteen invariants of the LSP-1 track:

    (1)  Intents list: unfiltered returns all tenant rows, paginated.
    (2)  Intents list: filter by ``session_id`` (exact match).
    (3)  Intents list: ``converted=true`` returns only converted rows.
    (4)  Intents list: ``converted=false`` returns only unconverted.
    (5)  Intents list: ``since`` / ``until`` range filter.
    (6)  Intents list: ``since >= until`` on summary → 400.
    (7)  Intents list: sort asc vs desc.
    (8)  Intents list: non-admin caller → 403.
    (9)  Intents list: cross-tenant isolation.
    (10) Intents list: page_size capped at 200.
    (11) Summary: happy path — counts + top_pages + top_referrers +
         top_utm_sources ordering.
    (12) Summary: empty window → 0 counts, empty arrays, 0.0%.
    (13) Summary: tenant isolation.
    (14) Pixel: valid ls_id + sid → 1×1 GIF + row w/ ``capture_mode``.
    (15) Pixel: invalid ls_id → GIF but NO write; mismatched Origin
         → GIF but NO write.

Test-loop convention mirrors ``test_lead_sense_intake.py`` — real
Motor client bound per-test to the caller's asyncio loop (via
httpx.AsyncClient) with the shared ``config.db`` swapped in-place.
Auth is stubbed via FastAPI ``dependency_overrides`` (see
``test_lead_communications_send_sms.py`` for the origin of the
pattern).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pytest
from dotenv import dotenv_values
from fastapi import FastAPI
from pymongo import MongoClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "LSP1_"
BASE = "/api/lead-sense"


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    seeded_tenant_ids: List[str] = []
    yield seeded_tenant_ids
    if seeded_tenant_ids:
        dbc.tenants.delete_many({"id": {"$in": seeded_tenant_ids}})
        dbc.visitor_intent.delete_many(
            {"tenant_id": {"$in": seeded_tenant_ids}},
        )


def _fresh(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_tenant(dbc, *, ls_id: Optional[str] = None,
                 allowed_origins: Optional[List[str]] = None) -> str:
    tid = _fresh("TEN")
    dbc.tenants.insert_one({
        "id": tid,
        "name": f"LSP1 seed tenant {tid[-8:]}",
        "marco_lead_sense_id": ls_id or f"lsp1_{uuid.uuid4().hex[:10]}",
        "lead_sense_allowed_origins": allowed_origins or [],
        "active": True,
        "created_at": "2026-02-15T00:00:00Z",
    })
    return tid


def _seed_intents(dbc, *, tenant_id: str, rows: List[Dict[str, Any]]) -> None:
    for r in rows:
        base = {
            "id":            _fresh("INT"),
            "tenant_id":     tenant_id,
            "session_id":    r.get("session_id") or f"sess-{uuid.uuid4().hex[:12]}",
            "current_url":   r.get("current_url") or "https://example.com/",
            "referrer":      r.get("referrer"),
            "ip":            r.get("ip") or "1.2.3.4",
            "company":       None,
            "user_agent":    r.get("user_agent") or "test-ua",
            "page_title":    r.get("page_title") or "Page",
            "viewport":      r.get("viewport"),
            "occurred_at":   r.get("occurred_at") or "2026-02-15T10:00:00+00:00",
            "source_channel": "MARCO Lead-Sense",
        }
        if "converted_at" in r:
            base["converted_at"] = r["converted_at"]
        if "converted_lead_id" in r:
            base["converted_lead_id"] = r["converted_lead_id"]
        if "capture_mode" in r:
            base["capture_mode"] = r["capture_mode"]
        dbc.visitor_intent.insert_one(base)


def _build_app(*, user: Dict[str, Any], tenant: Dict[str, Any]) -> FastAPI:
    """Mount only the lead_sense router + inject auth stubs.

    ``get_current_user`` is the sub-dep of ``require_admin`` — when
    overridden, ``require_admin`` runs its role check against the
    injected dict. Non-admin role → 403 via ``require_admin`` itself.
    """
    from routers import lead_sense as _ls
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    app = FastAPI()
    app.include_router(_ls.router)
    app.dependency_overrides[get_current_user]   = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant

    # SlowAPI wiring — mirrors _client_and_app in test_lead_sense_intake.
    try:
        from slowapi.errors import RateLimitExceeded
        from slowapi import _rate_limit_exceeded_handler
        if _ls._shared_limiter is not None:
            app.state.limiter = _ls._shared_limiter
            app.add_exception_handler(
                RateLimitExceeded, _rate_limit_exceeded_handler,
            )
    except Exception:
        pass

    return app


def _run(app: FastAPI, method: str, path: str, *,
         params: Optional[Dict[str, Any]] = None,
         headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    """Execute one request via httpx.AsyncClient with a fresh
    Motor client bound to the coroutine's event loop (avoids the
    motor-cross-loop RuntimeError under TestClient)."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from routers import lead_sense as _ls

    async def _hit():
        loop_client = AsyncIOMotorClient(MONGO_URL)
        try:
            _ls.db = loop_client[DB_NAME]
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver",
            ) as client:
                return await client.request(
                    method, path,
                    params=params, headers=headers or {},
                )
        finally:
            try: loop_client.close()
            except Exception: pass
    return asyncio.run(_hit())


# ═════════════════════════════════════════════════════════════════════
# (1) Intents list — unfiltered + pagination
# ═════════════════════════════════════════════════════════════════════
def test_1_intents_list_unfiltered_and_paginated(dbc, cleanup):
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    # Seed 3 rows.
    _seed_intents(dbc, tenant_id=tid, rows=[
        {"session_id": "s1", "current_url": "https://a.example/p1"},
        {"session_id": "s2", "current_url": "https://a.example/p2"},
        {"session_id": "s3", "current_url": "https://a.example/p3"},
    ])
    app = _build_app(
        user={"id": "u-adm", "role": "admin"},
        tenant={"id": tid},
    )
    resp = _run(app, "GET", f"{BASE}/intents")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert body["total_pages"] == 1
    assert len(body["items"]) == 3
    for it in body["items"]:
        assert it["tenant_id"] == tid
        assert "has_converted" in it
        assert it["source_channel"] == "MARCO Lead-Sense"

    # Page 2 with page_size=2 → 1 row remaining.
    resp2 = _run(app, "GET", f"{BASE}/intents",
                 params={"page": 2, "page_size": 2})
    body2 = resp2.json()
    assert body2["total"] == 3
    assert body2["page_size"] == 2
    assert body2["total_pages"] == 2
    assert len(body2["items"]) == 1


# ═════════════════════════════════════════════════════════════════════
# (2) Filter by session_id
# ═════════════════════════════════════════════════════════════════════
def test_2_filter_by_session_id(dbc, cleanup):
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    _seed_intents(dbc, tenant_id=tid, rows=[
        {"session_id": "target-session-42", "current_url": "https://a/x"},
        {"session_id": "other-session",     "current_url": "https://a/y"},
    ])
    app = _build_app(
        user={"id": "u-adm", "role": "admin"}, tenant={"id": tid},
    )
    resp = _run(app, "GET", f"{BASE}/intents",
                params={"session_id": "target-session-42"})
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["session_id"] == "target-session-42"


# ═════════════════════════════════════════════════════════════════════
# (3) Filter converted=true
# ═════════════════════════════════════════════════════════════════════
def test_3_filter_converted_true(dbc, cleanup):
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    _seed_intents(dbc, tenant_id=tid, rows=[
        {"session_id": "s1", "converted_at": "2026-02-16T00:00:00+00:00",
         "converted_lead_id": "lead-abc"},
        {"session_id": "s2"},
        {"session_id": "s3"},
    ])
    app = _build_app(
        user={"id": "u-adm", "role": "admin"}, tenant={"id": tid},
    )
    resp = _run(app, "GET", f"{BASE}/intents", params={"converted": "true"})
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["has_converted"] is True
    assert body["items"][0]["converted_lead_id"] == "lead-abc"


# ═════════════════════════════════════════════════════════════════════
# (4) Filter converted=false
# ═════════════════════════════════════════════════════════════════════
def test_4_filter_converted_false(dbc, cleanup):
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    _seed_intents(dbc, tenant_id=tid, rows=[
        {"session_id": "s1", "converted_at": "2026-02-16T00:00:00+00:00"},
        {"session_id": "s2"},
        {"session_id": "s3"},
    ])
    app = _build_app(
        user={"id": "u-adm", "role": "admin"}, tenant={"id": tid},
    )
    resp = _run(app, "GET", f"{BASE}/intents", params={"converted": "false"})
    body = resp.json()
    assert body["total"] == 2
    for it in body["items"]:
        assert it["has_converted"] is False


# ═════════════════════════════════════════════════════════════════════
# (5) since / until range filter + 400 on invalid ISO
# ═════════════════════════════════════════════════════════════════════
def test_5_range_filter_and_400_on_bad_iso(dbc, cleanup):
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    _seed_intents(dbc, tenant_id=tid, rows=[
        {"session_id": "s1", "occurred_at": "2026-01-01T00:00:00+00:00"},
        {"session_id": "s2", "occurred_at": "2026-02-01T00:00:00+00:00"},
        {"session_id": "s3", "occurred_at": "2026-03-01T00:00:00+00:00"},
    ])
    app = _build_app(
        user={"id": "u-adm", "role": "admin"}, tenant={"id": tid},
    )
    resp = _run(app, "GET", f"{BASE}/intents", params={
        "since": "2026-01-15T00:00:00Z",
        "until": "2026-02-15T00:00:00Z",
    })
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["session_id"] == "s2"

    # 400 on garbage ISO.
    bad = _run(app, "GET", f"{BASE}/intents", params={"since": "not-an-iso"})
    assert bad.status_code == 400, bad.text


# ═════════════════════════════════════════════════════════════════════
# (6) Summary: since >= until → 400
# ═════════════════════════════════════════════════════════════════════
def test_6_summary_since_ge_until_returns_400(dbc, cleanup):
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    app = _build_app(
        user={"id": "u-adm", "role": "admin"}, tenant={"id": tid},
    )
    resp = _run(app, "GET", f"{BASE}/intents/summary", params={
        "since": "2026-03-01T00:00:00Z",
        "until": "2026-02-01T00:00:00Z",
    })
    assert resp.status_code == 400, resp.text


# ═════════════════════════════════════════════════════════════════════
# (7) Sort asc vs desc
# ═════════════════════════════════════════════════════════════════════
def test_7_sort_asc_vs_desc(dbc, cleanup):
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    _seed_intents(dbc, tenant_id=tid, rows=[
        {"session_id": "s-a", "occurred_at": "2026-01-01T00:00:00+00:00"},
        {"session_id": "s-b", "occurred_at": "2026-02-01T00:00:00+00:00"},
        {"session_id": "s-c", "occurred_at": "2026-03-01T00:00:00+00:00"},
    ])
    app = _build_app(
        user={"id": "u-adm", "role": "admin"}, tenant={"id": tid},
    )
    desc = _run(app, "GET", f"{BASE}/intents",
                params={"sort": "created_at_desc"}).json()
    asc  = _run(app, "GET", f"{BASE}/intents",
                params={"sort": "created_at_asc"}).json()
    assert desc["items"][0]["session_id"] == "s-c"
    assert asc["items"][0]["session_id"]  == "s-a"

    # Invalid sort value → 400.
    bad = _run(app, "GET", f"{BASE}/intents", params={"sort": "wat"})
    assert bad.status_code == 400, bad.text


# ═════════════════════════════════════════════════════════════════════
# (8) Non-admin caller → 403
# ═════════════════════════════════════════════════════════════════════
def test_8_non_admin_returns_403(dbc, cleanup):
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    app = _build_app(
        user={"id": "u-tech", "role": "technician"}, tenant={"id": tid},
    )
    resp = _run(app, "GET", f"{BASE}/intents")
    assert resp.status_code == 403, resp.text

    resp2 = _run(app, "GET", f"{BASE}/intents/summary")
    assert resp2.status_code == 403, resp2.text


# ═════════════════════════════════════════════════════════════════════
# (9) Cross-tenant isolation
# ═════════════════════════════════════════════════════════════════════
def test_9_cross_tenant_isolation(dbc, cleanup):
    tid_a = _seed_tenant(dbc)
    tid_b = _seed_tenant(dbc)
    cleanup.extend([tid_a, tid_b])
    _seed_intents(dbc, tenant_id=tid_a, rows=[{"session_id": "a1"}])
    _seed_intents(dbc, tenant_id=tid_b, rows=[
        {"session_id": "b1"}, {"session_id": "b2"},
    ])
    # Admin scoped to tenant A sees only A's row.
    app_a = _build_app(
        user={"id": "u-adm", "role": "admin"}, tenant={"id": tid_a},
    )
    body_a = _run(app_a, "GET", f"{BASE}/intents").json()
    assert body_a["total"] == 1
    assert body_a["items"][0]["tenant_id"] == tid_a

    # Admin scoped to tenant B sees only B's rows.
    app_b = _build_app(
        user={"id": "u-adm", "role": "admin"}, tenant={"id": tid_b},
    )
    body_b = _run(app_b, "GET", f"{BASE}/intents").json()
    assert body_b["total"] == 2
    for it in body_b["items"]:
        assert it["tenant_id"] == tid_b


# ═════════════════════════════════════════════════════════════════════
# (10) page_size capped at 200
# ═════════════════════════════════════════════════════════════════════
def test_10_page_size_capped_at_200(dbc, cleanup):
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    app = _build_app(
        user={"id": "u-adm", "role": "admin"}, tenant={"id": tid},
    )
    resp = _run(app, "GET", f"{BASE}/intents", params={"page_size": 500})
    body = resp.json()
    assert body["page_size"] == 200


# ═════════════════════════════════════════════════════════════════════
# (11) Summary happy path
# ═════════════════════════════════════════════════════════════════════
def test_11_summary_happy_path(dbc, cleanup):
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    _seed_intents(dbc, tenant_id=tid, rows=[
        # 2 sessions hitting /pricing (one converted), 1 hitting /home.
        {"session_id": "s1", "current_url": "https://ex.com/pricing?utm_source=google",
         "referrer": "https://google.com/search?q=pool",
         "occurred_at": "2026-02-15T10:00:00+00:00",
         "converted_at": "2026-02-15T10:05:00+00:00",
         "converted_lead_id": "L1"},
        {"session_id": "s1", "current_url": "https://ex.com/pricing?utm_source=google",
         "referrer": "https://google.com/search?q=pool",
         "occurred_at": "2026-02-15T10:01:00+00:00",
         "converted_at": "2026-02-15T10:05:00+00:00",
         "converted_lead_id": "L1"},
        {"session_id": "s2", "current_url": "https://ex.com/pricing?utm_source=facebook",
         "referrer": "https://facebook.com/ad/123",
         "occurred_at": "2026-02-15T11:00:00+00:00"},
        {"session_id": "s3", "current_url": "https://ex.com/home",
         "referrer": "https://bing.com/",
         "occurred_at": "2026-02-15T12:00:00+00:00"},
    ])
    app = _build_app(
        user={"id": "u-adm", "role": "admin"}, tenant={"id": tid},
    )
    resp = _run(app, "GET", f"{BASE}/intents/summary", params={
        "since": "2026-02-01T00:00:00Z",
        "until": "2026-03-01T00:00:00Z",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_intents"]      == 4
    assert body["total_sessions"]     == 3
    assert body["converted_sessions"] == 1
    # 1 converted / 3 total = 33.33%.
    assert body["conversion_rate_pct"] == 33.33
    # Top page: /pricing (3 hits) > /home (1 hit).
    assert body["top_pages"][0]["page"].endswith("/pricing?utm_source=google")
    # Top referrers grouped by host.
    ref_hosts = [x["referrer"] for x in body["top_referrers"]]
    assert "google.com" in ref_hosts
    assert "facebook.com" in ref_hosts
    assert "bing.com" in ref_hosts
    # Google is top (2 hits).
    assert body["top_referrers"][0]["referrer"] == "google.com"
    # Top utm_sources.
    utms = [x["utm_source"] for x in body["top_utm_sources"]]
    assert "google" in utms
    assert "facebook" in utms
    assert body["top_utm_sources"][0]["utm_source"] == "google"


# ═════════════════════════════════════════════════════════════════════
# (12) Summary empty window
# ═════════════════════════════════════════════════════════════════════
def test_12_summary_empty_window(dbc, cleanup):
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    # No intents at all.
    app = _build_app(
        user={"id": "u-adm", "role": "admin"}, tenant={"id": tid},
    )
    resp = _run(app, "GET", f"{BASE}/intents/summary")
    body = resp.json()
    assert body["total_intents"] == 0
    assert body["total_sessions"] == 0
    assert body["converted_sessions"] == 0
    assert body["conversion_rate_pct"] == 0.0
    assert body["top_pages"] == []
    assert body["top_referrers"] == []
    assert body["top_utm_sources"] == []


# ═════════════════════════════════════════════════════════════════════
# (13) Summary tenant isolation
# ═════════════════════════════════════════════════════════════════════
def test_13_summary_tenant_isolation(dbc, cleanup):
    tid_a = _seed_tenant(dbc)
    tid_b = _seed_tenant(dbc)
    cleanup.extend([tid_a, tid_b])
    _seed_intents(dbc, tenant_id=tid_a, rows=[
        {"session_id": "a1", "current_url": "https://a.com/",
         "occurred_at": "2026-02-15T00:00:00+00:00"},
    ])
    _seed_intents(dbc, tenant_id=tid_b, rows=[
        {"session_id": "b1", "current_url": "https://b.com/",
         "occurred_at": "2026-02-15T00:00:00+00:00"},
        {"session_id": "b2", "current_url": "https://b.com/x",
         "occurred_at": "2026-02-15T00:00:00+00:00"},
    ])
    app_a = _build_app(
        user={"id": "u-adm", "role": "admin"}, tenant={"id": tid_a},
    )
    body_a = _run(app_a, "GET", f"{BASE}/intents/summary", params={
        "since": "2026-02-01T00:00:00Z",
        "until": "2026-03-01T00:00:00Z",
    }).json()
    assert body_a["total_intents"] == 1
    assert body_a["total_sessions"] == 1

    app_b = _build_app(
        user={"id": "u-adm", "role": "admin"}, tenant={"id": tid_b},
    )
    body_b = _run(app_b, "GET", f"{BASE}/intents/summary", params={
        "since": "2026-02-01T00:00:00Z",
        "until": "2026-03-01T00:00:00Z",
    }).json()
    assert body_b["total_intents"] == 2
    assert body_b["total_sessions"] == 2


# ═════════════════════════════════════════════════════════════════════
# (14) Pixel: happy path → GIF + row w/ capture_mode
# ═════════════════════════════════════════════════════════════════════
def test_14_pixel_happy_path_writes_row_and_returns_gif(dbc, cleanup):
    ls_id = f"lsp1p_{uuid.uuid4().hex[:10]}"
    tid = _seed_tenant(dbc, ls_id=ls_id, allowed_origins=[
        "https://example.com",
    ])
    cleanup.append(tid)
    # Pixel is public — build the app WITHOUT dependency overrides so
    # the endpoint's silent-fail semantics run against real code.
    from routers import lead_sense as _ls
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _hit():
        loop_client = AsyncIOMotorClient(MONGO_URL)
        try:
            _ls.db = loop_client[DB_NAME]
            app = FastAPI()
            app.include_router(_ls.router)
            try:
                from slowapi.errors import RateLimitExceeded
                from slowapi import _rate_limit_exceeded_handler
                if _ls._shared_limiter is not None:
                    app.state.limiter = _ls._shared_limiter
                    app.add_exception_handler(
                        RateLimitExceeded, _rate_limit_exceeded_handler,
                    )
            except Exception:
                pass
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver",
            ) as client:
                return await client.get(
                    f"{BASE}/pixel",
                    params={
                        "ls_id": ls_id,
                        "sid": f"sess-{uuid.uuid4().hex[:12]}",
                        "p": "https://example.com/pricing",
                        "r": "https://google.com/search",
                    },
                    headers={"Origin": "https://example.com"},
                )
        finally:
            try: loop_client.close()
            except Exception: pass
    resp = asyncio.run(_hit())
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-type", "").startswith("image/gif")
    assert resp.headers.get("cache-control", "").startswith("no-store")
    # Body is exactly a 1×1 GIF (42-43 bytes).
    assert resp.content.startswith(b"GIF89a")

    # Row was written with capture_mode="pixel".
    rows = list(dbc.visitor_intent.find({"tenant_id": tid}))
    assert len(rows) == 1
    assert rows[0].get("capture_mode") == "pixel"
    assert rows[0].get("source_channel") == "MARCO Lead-Sense"


# ═════════════════════════════════════════════════════════════════════
# (15) Pixel silent-fail on invalid ls_id + mismatched origin
# ═════════════════════════════════════════════════════════════════════
def test_15_pixel_silent_fail_on_invalid_ls_id_and_bad_origin(dbc, cleanup):
    ls_id = f"lsp1p_{uuid.uuid4().hex[:10]}"
    tid = _seed_tenant(dbc, ls_id=ls_id, allowed_origins=[
        "https://example.com",
    ])
    cleanup.append(tid)
    from routers import lead_sense as _ls
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _hit(params: Dict[str, Any], headers: Dict[str, str]):
        loop_client = AsyncIOMotorClient(MONGO_URL)
        try:
            _ls.db = loop_client[DB_NAME]
            app = FastAPI()
            app.include_router(_ls.router)
            try:
                from slowapi.errors import RateLimitExceeded
                from slowapi import _rate_limit_exceeded_handler
                if _ls._shared_limiter is not None:
                    app.state.limiter = _ls._shared_limiter
                    app.add_exception_handler(
                        RateLimitExceeded, _rate_limit_exceeded_handler,
                    )
            except Exception:
                pass
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver",
            ) as client:
                return await client.get(f"{BASE}/pixel",
                    params=params, headers=headers)
        finally:
            try: loop_client.close()
            except Exception: pass

    # (a) Invalid ls_id → still GIF, no write.
    r1 = asyncio.run(_hit(
        {"ls_id": f"unknown_{uuid.uuid4().hex[:6]}",
         "sid": f"sess-{uuid.uuid4().hex[:12]}"},
        {"Origin": "https://example.com"},
    ))
    assert r1.status_code == 200
    assert r1.headers.get("content-type", "").startswith("image/gif")
    assert r1.content.startswith(b"GIF89a")

    # (b) Mismatched Origin on a real ls_id → still GIF, no write.
    r2 = asyncio.run(_hit(
        {"ls_id": ls_id, "sid": f"sess-{uuid.uuid4().hex[:12]}"},
        {"Origin": "https://evil.attacker.tld"},
    ))
    assert r2.status_code == 200
    assert r2.headers.get("content-type", "").startswith("image/gif")

    # Neither case wrote a row.
    assert dbc.visitor_intent.count_documents({"tenant_id": tid}) == 0
