"""Feb-2026 · P17-follow · Widget lead persistence parity + raw-
submission lazy-load endpoint.

Covers:
  1. ``_upsert_lead_from_submission`` now persists ``address`` +
     ``service_interest`` on the lead doc (parity with the legacy
     public-form path in ``routers/marketing.py::_lead_row_from_form_values``).
  2. New ``GET /api/leads/{lid}/raw-submission`` endpoint:
     * Tenant-scoped (submission from tenant B is NOT surfaced to a
       tenant A caller even if the submission id happens to collide).
     * Role-gated (403 for roles outside the leads allow-set).
     * 404 for legacy leads with no ``meta.submission_id``.
     * 404 for cross-tenant lookups.
     * Values normalised across all 3 upstream shapes
       (``answers`` / ``values`` / ``data``).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient, ASGITransport


def _run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════
# 1 · Widget path persists address + service_interest on the lead.
# ═══════════════════════════════════════════════════════════════════
def test_upsert_lead_from_submission_persists_address_and_service_interest():
    """Widget path parity — the lead doc now carries ``address``,
    ``service_address``, and ``service_interest`` alongside the
    existing ``name``/``email``/``phone``/``notes`` fields."""
    from routers import marketing_forms as _mod

    inserted: Dict[str, Any] = {}

    class _Leads:
        async def find_one(self, q, p=None):
            return None  # No existing lead — force insert branch.
        async def insert_one(self, doc):
            inserted.update(doc)

    class _DB:
        leads = _Leads()

    async def _go():
        with patch.object(_mod, "db", _DB()):
            lead_id = await _mod._upsert_lead_from_submission(
                tenant_id="t1",
                form={"id": "form-x", "slug": "slug-x"},
                submission_id="sub-1",
                name="Terry Gray",
                email="terry@example.com",
                phone="480-555-0100",
                notes="Free chlorine keeps dropping",
                page_url="https://pool.example.com/quote",
                address="1234 W Vistancia Blvd, Peoria, AZ 85383",
                service_interest="weekly_pool_service",
            )
            return lead_id

    lead_id = _run(_go())
    assert lead_id, "lead was not created"
    # New fields present + persisted.
    assert inserted["address"] == "1234 W Vistancia Blvd, Peoria, AZ 85383"
    assert inserted["service_address"] == "1234 W Vistancia Blvd, Peoria, AZ 85383"
    assert inserted["service_interest"] == "weekly_pool_service"
    # Pre-existing fields still present.
    assert inserted["name"] == "Terry Gray"
    assert inserted["email"] == "terry@example.com"
    assert inserted["phone"] == "480-555-0100"
    # Meta stamps the submission back-reference so the raw-submission
    # endpoint has a join key.
    assert inserted["meta"]["submission_id"] == "sub-1"


def test_upsert_lead_from_submission_omits_address_when_not_provided():
    """Backwards-compat — old callers that don't pass ``address`` /
    ``service_interest`` still work (both default to ``None``)."""
    from routers import marketing_forms as _mod

    inserted: Dict[str, Any] = {}

    class _Leads:
        async def find_one(self, q, p=None): return None
        async def insert_one(self, doc): inserted.update(doc)

    class _DB:
        leads = _Leads()

    async def _go():
        with patch.object(_mod, "db", _DB()):
            await _mod._upsert_lead_from_submission(
                tenant_id="t1",
                form={"id": "form-x", "slug": "slug-x"},
                submission_id="sub-1",
                name="Sam", email="sam@x.co", phone=None,
                notes=None, page_url=None,
            )

    _run(_go())
    # New fields land as empty defaults, never as ``None`` for the
    # address strings (leads schema treats them as strings).
    assert inserted["address"] == ""
    assert inserted["service_address"] == ""
    # ``service_interest`` is nullable in the schema — None is fine.
    assert inserted["service_interest"] is None


# ═══════════════════════════════════════════════════════════════════
# 2 · GET /api/leads/{lid}/raw-submission — happy path.
# ═══════════════════════════════════════════════════════════════════
def _build_leads_app(user, tenant, leads_rows, submissions_rows):
    """Minimal FastAPI harness for the leads router."""
    from fastapi import FastAPI
    from routers.leads import router as _r
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    class _Coll:
        def __init__(s, rows): s.rows = rows
        async def find_one(s, q, p=None):
            for r in s.rows:
                if all(r.get(k) == v for k, v in q.items()):
                    return dict(r)
            return None

    class _DB:
        leads = _Coll(leads_rows)
        form_submissions = _Coll(submissions_rows)

    app = FastAPI()
    app.include_router(_r, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    return app, _DB()


def test_raw_submission_endpoint_returns_values_for_admin():
    """Happy path — admin fetches a lead's linked submission and
    receives the normalised ``values`` block."""
    from routers import leads as _mod

    user = {"id": "u_admin", "role": "admin", "tenant_id": "t1"}
    tenant = {"id": "t1"}
    lead_id = "lead-1"
    sub_id = "sub-abc"
    leads_rows = [{
        "id": lead_id, "tenant_id": "t1",
        "meta": {"form_id": "f1", "submission_id": sub_id,
                  "page_url": "https://pool.example.com/quote"},
    }]
    submissions_rows = [{
        "id": sub_id, "tenant_id": "t1", "form_id": "f1",
        "created_at": "2026-08-25T10:00:00Z",
        "page_url": "https://pool.example.com/quote",
        # Widget shape → ``answers``.
        "answers": {"full_name": "Terry Gray",
                    "email_address": "terry@example.com",
                    "phone_number": "480-555-0100",
                    "pool_size": "20000 gal",
                    "notes": "Free chlorine keeps dropping"},
    }]
    app, db_stub = _build_leads_app(user, tenant,
                                     leads_rows, submissions_rows)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.get(f"/api/leads/{lead_id}/raw-submission")
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["submission_id"] == sub_id
    assert body["form_id"] == "f1"
    assert body["page_url"] == "https://pool.example.com/quote"
    # ``answers`` was normalised into ``values`` for the client.
    assert body["values"]["full_name"] == "Terry Gray"
    assert body["values"]["pool_size"] == "20000 gal"


def test_raw_submission_endpoint_normalises_legacy_values_key():
    """Legacy marketing.py path writes ``values`` (not ``answers``).
    The endpoint MUST normalise both into the response's ``values``
    key so the client is agnostic to the upstream shape."""
    from routers import leads as _mod

    user = {"id": "u_admin", "role": "admin", "tenant_id": "t1"}
    tenant = {"id": "t1"}
    lead_id, sub_id = "lead-2", "sub-legacy"
    leads_rows = [{"id": lead_id, "tenant_id": "t1",
                    "meta": {"submission_id": sub_id}}]
    submissions_rows = [{
        "id": sub_id, "tenant_id": "t1",
        "values": {"name": "Legacy Sam", "email": "sam@old.co"},
    }]
    app, db_stub = _build_leads_app(user, tenant,
                                     leads_rows, submissions_rows)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.get(f"/api/leads/{lead_id}/raw-submission")
    r = _run(_body())
    assert r.status_code == 200, r.text
    assert r.json()["values"]["name"] == "Legacy Sam"


# ═══════════════════════════════════════════════════════════════════
# 3 · 404 branches — legacy lead with no submission ref, missing sub.
# ═══════════════════════════════════════════════════════════════════
def test_raw_submission_endpoint_404s_on_legacy_lead_no_submission_id():
    """Pre-P17 leads have no ``meta.submission_id`` — endpoint MUST
    return 404 so the frontend hides the panel."""
    from routers import leads as _mod
    user = {"id": "u_admin", "role": "admin", "tenant_id": "t1"}
    tenant = {"id": "t1"}
    leads_rows = [{"id": "lead-legacy", "tenant_id": "t1",
                    "meta": None}]
    app, db_stub = _build_leads_app(user, tenant, leads_rows, [])

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.get("/api/leads/lead-legacy/raw-submission")
    r = _run(_body())
    assert r.status_code == 404


def test_raw_submission_endpoint_404s_when_submission_vanished():
    """Submission id present on the lead but the submission row was
    deleted (e.g. GDPR purge) — 404 so the panel hides cleanly."""
    from routers import leads as _mod
    user = {"id": "u_admin", "role": "admin", "tenant_id": "t1"}
    tenant = {"id": "t1"}
    leads_rows = [{"id": "lead-orphan", "tenant_id": "t1",
                    "meta": {"submission_id": "sub-gone"}}]
    app, db_stub = _build_leads_app(user, tenant, leads_rows, [])

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.get("/api/leads/lead-orphan/raw-submission")
    r = _run(_body())
    assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 4 · Tenant scope — submission from tenant B never leaks to A.
# ═══════════════════════════════════════════════════════════════════
def test_raw_submission_endpoint_scopes_by_tenant():
    """Same submission-id exists on tenant B but the caller is on
    tenant A. Endpoint MUST 404 rather than surface tenant B's data."""
    from routers import leads as _mod
    user_a = {"id": "u_admin_a", "role": "admin", "tenant_id": "tA"}
    tenant_a = {"id": "tA"}
    # Lead on tenant A references submission-id ``s-shared``.
    leads_rows = [{"id": "lead-a", "tenant_id": "tA",
                    "meta": {"submission_id": "s-shared"}}]
    # Submission with that id exists ONLY on tenant B — MUST NOT leak.
    submissions_rows = [{
        "id": "s-shared", "tenant_id": "tB",  # ← wrong tenant
        "values": {"name": "TENANT-B-LEAK"},
    }]
    app, db_stub = _build_leads_app(user_a, tenant_a,
                                     leads_rows, submissions_rows)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.get("/api/leads/lead-a/raw-submission")
    r = _run(_body())
    assert r.status_code == 404, r.text
    # And the leak string never appears anywhere in the body.
    assert "TENANT-B-LEAK" not in r.text


# ═══════════════════════════════════════════════════════════════════
# 5 · Role gate — customer/portal roles get 403.
# ═══════════════════════════════════════════════════════════════════
def test_raw_submission_endpoint_403s_for_non_admin_roles():
    """The endpoint reuses ``_require_leads_role`` (same as
    ``/leads/{lid}``) — a customer role must never reach the DB."""
    from routers import leads as _mod
    user = {"id": "u_cust", "role": "customer", "tenant_id": "t1"}
    tenant = {"id": "t1"}
    leads_rows = [{"id": "lead-1", "tenant_id": "t1",
                    "meta": {"submission_id": "sub-1"}}]
    submissions_rows = [{"id": "sub-1", "tenant_id": "t1",
                           "values": {"name": "leaked"}}]
    app, db_stub = _build_leads_app(user, tenant,
                                     leads_rows, submissions_rows)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.get("/api/leads/lead-1/raw-submission")
    r = _run(_body())
    assert r.status_code == 403, r.text
    assert "leaked" not in r.text


# ═══════════════════════════════════════════════════════════════════
# 6 · Manager role — mid-tier admin also has access (matches
#     ``_INBOUND_MANAGER_ROLES`` on the leads router).
# ═══════════════════════════════════════════════════════════════════
def test_raw_submission_endpoint_allows_manager_role():
    from routers import leads as _mod
    user = {"id": "u_mgr", "role": "manager", "tenant_id": "t1"}
    tenant = {"id": "t1"}
    leads_rows = [{"id": "lead-m", "tenant_id": "t1",
                    "meta": {"submission_id": "sub-m"}}]
    submissions_rows = [{"id": "sub-m", "tenant_id": "t1",
                           "answers": {"n": 1}}]
    app, db_stub = _build_leads_app(user, tenant,
                                     leads_rows, submissions_rows)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.get("/api/leads/lead-m/raw-submission")
    r = _run(_body())
    assert r.status_code == 200, r.text
