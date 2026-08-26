"""Feb-2026 · POST /api/admin/migrations/backfill-website-visitor-leads

Contract:
  * super_admin only (403 for admin / manager / customer / tech).
  * ``dry_run=true`` (default) → matches + diffs, no DB write.
  * ``dry_run=false`` → writes; second call is idempotent (0 additional
    enrichments).
  * Response envelope: ``tenant_id``, ``tenant_slug``, ``tenant_name``,
    ``dry_run``, ``matched_leads``, ``enriched_leads``,
    ``skipped_no_match``, ``skipped_no_new_data``, ``enrichments``,
    ``warnings``.
  * Tenant scope: no cross-tenant fan-out unless ``tenant_slug`` is
    explicitly passed; passing it targets a different tenant (super_admin
    only) and logs at WARN.

Uses an in-memory Motor-shaped stub so we don't touch preview Mongo.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import patch

from httpx import AsyncClient, ASGITransport


def _run(coro):
    return asyncio.run(coro)


# ── Motor-shaped in-memory stub ─────────────────────────────────────
class _AsyncCursor:
    def __init__(self, rows): self._rows = list(rows)
    def __aiter__(self): self._i = 0; return self
    async def __anext__(self):
        if self._i >= len(self._rows): raise StopAsyncIteration
        r = self._rows[self._i]; self._i += 1; return r


class _Coll:
    def __init__(self, rows): self.rows = list(rows); self.updates: List = []

    async def find_one(self, q, p=None):
        for r in self.rows:
            if _match(r, q):
                return dict(r)
        return None

    def find(self, q, p=None):
        return _AsyncCursor([r for r in self.rows if _match(r, q)])

    async def update_one(self, q, upd):
        for r in self.rows:
            if _match(r, q):
                r.update(upd.get("$set", {}))
                self.updates.append({"q": q, "set": upd["$set"]})
                return


def _match(row, query):
    """Recursive Motor-shaped query matcher — supports the subset the
    P19 migration uses: eq, $and, $or, $exists, $gte/$lte ISO strings."""
    for k, v in query.items():
        if k == "$and":
            if not all(_match(row, sub) for sub in v):
                return False
            continue
        if k == "$or":
            if not any(_match(row, sub) for sub in v):
                return False
            continue
        rv = row.get(k)
        if isinstance(v, dict):
            if "$exists" in v:
                if (k in row) != v["$exists"]:
                    return False
            if "$gte" in v:
                if rv is None or not (v["$gte"] <= rv <= v["$lte"]):
                    return False
        else:
            if rv != v:
                return False
    return True


class _DB:
    def __init__(self, leads, submissions, tenants):
        self.leads = _Coll(leads)
        self.form_submissions = _Coll(submissions)
        self.tenants = _Coll(tenants)


def _build_app(user, tenant, db_stub):
    from fastapi import FastAPI
    from routers.admin_migrations import router as _r
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    app = FastAPI()
    app.include_router(_r, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    return app


def _seed():
    """One tenant-A lead is a candidate (contact empty, submission match
    within ±5min); one tenant-A lead already populated (skipped-no-new);
    one tenant-B lead is a candidate but different tenant (never touched
    unless caller explicitly targets it)."""
    leads = [
        # Candidate: tenant A, empty contact, name = "Website Visitor".
        {"id": "lead-a1", "tenant_id": "tA",
         "name": "Website Visitor",
         "phone": "", "email": "", "address": "",
         "source": "Web Form",
         "created_at": "2026-08-21T14:00:00+00:00"},
        # Already populated — should skip (no new data).
        {"id": "lead-a2", "tenant_id": "tA",
         "name": "Terry Gray",
         "phone": "480-555-0100", "email": "terry@example.com",
         "created_at": "2026-08-21T14:05:00+00:00"},
        # Tenant B candidate — must NEVER surface to tenant A.
        {"id": "lead-b1", "tenant_id": "tB",
         "name": "Website Visitor",
         "phone": "", "email": "",
         "created_at": "2026-08-21T14:00:00+00:00"},
    ]
    submissions = [
        # Matches lead-a1 by ±5min window.
        {"id": "sub-a1", "tenant_id": "tA", "form_id": "f1",
         "created_at": "2026-08-21T14:00:03+00:00",
         "values": {"full_name": "Marshall Cuoco",
                     "email_address": "marshall@example.com",
                     "phone_number": "480-555-0200",
                     "address": "742 Evergreen Terrace"}},
        # Matches lead-b1 too — cross-tenant test relies on this NOT
        # being returned to a tenant-A caller.
        {"id": "sub-b1", "tenant_id": "tB", "form_id": "f1",
         "created_at": "2026-08-21T14:00:03+00:00",
         "values": {"full_name": "TENANT-B-LEAK"}},
    ]
    tenants = [
        {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"},
        {"id": "tB", "slug": "bravo", "name": "Bravo"},
    ]
    return _DB(leads, submissions, tenants)


# ═══════════════════════════════════════════════════════════════════
# 1 · super_admin can invoke; admin gets 403.
# ═══════════════════════════════════════════════════════════════════
def test_backfill_endpoint_super_admin_only():
    """Admin / manager / customer / tech all get 403; only super_admin
    reaches the migration."""
    from routers import admin_migrations as _mod
    from migrations import task_p19_backfill_empty_website_visitor_leads as _p19

    for role in ("admin", "manager", "technician", "customer"):
        db_stub = _seed()
        user = {"id": f"u_{role}", "role": role, "tenant_id": "tA"}
        tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
        app = _build_app(user, tenant, db_stub)

        async def _body():
            with patch.object(_mod, "db", db_stub), \
                 patch.object(_p19, "db", db_stub):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport,
                                        base_url="http://t") as ac:
                    return await ac.post(
                        "/api/admin/migrations/backfill-website-visitor-leads",
                    )
        r = _run(_body())
        assert r.status_code == 403, (role, r.text)
        # No DB write attempted.
        assert db_stub.leads.updates == [], role


# ═══════════════════════════════════════════════════════════════════
# 2 · dry_run=true returns diff, DB unchanged.
# ═══════════════════════════════════════════════════════════════════
def test_backfill_endpoint_dry_run_default_leaves_db_untouched():
    from routers import admin_migrations as _mod
    from migrations import task_p19_backfill_empty_website_visitor_leads as _p19

    db_stub = _seed()
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant, db_stub)

    async def _body():
        with patch.object(_mod, "db", db_stub), \
             patch.object(_p19, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.post(
                    "/api/admin/migrations/backfill-website-visitor-leads",
                )
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["tenant_id"] == "tA"
    assert body["tenant_slug"] == "aquaterra"
    assert body["matched_leads"] == 1  # Only lead-a1 matches on tenant A.
    assert body["enriched_leads"] == 0  # Dry-run — nothing written.
    assert len(body["enrichments"]) == 1
    e = body["enrichments"][0]
    assert e["lead_id"] == "lead-a1"
    assert e["after"]["name"] == "Marshall Cuoco"
    assert e["after"]["email"] == "marshall@example.com"
    assert e["after"]["phone"] == "480-555-0200"
    # Response envelope contract — all documented fields present.
    for k in ("tenant_id", "tenant_slug", "tenant_name", "dry_run",
              "matched_leads", "enriched_leads", "skipped_no_match",
              "skipped_no_new_data", "enrichments", "warnings"):
        assert k in body, f"missing key {k}"
    # DB untouched.
    assert db_stub.leads.updates == []


# ═══════════════════════════════════════════════════════════════════
# 3 · dry_run=false writes; 2nd call idempotent (0 additional).
# ═══════════════════════════════════════════════════════════════════
def test_backfill_endpoint_commit_writes_and_is_idempotent():
    from routers import admin_migrations as _mod
    from migrations import task_p19_backfill_empty_website_visitor_leads as _p19

    db_stub = _seed()
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant, db_stub)

    async def _hit(dry):
        with patch.object(_mod, "db", db_stub), \
             patch.object(_p19, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.post(
                    "/api/admin/migrations/backfill-website-visitor-leads"
                    f"?dry_run={'true' if dry else 'false'}",
                )

    # First real run — writes.
    r1 = _run(_hit(False))
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["dry_run"] is False
    assert b1["enriched_leads"] == 1
    assert len(db_stub.leads.updates) == 1
    # DB row was patched in place.
    lead_a1 = next(r for r in db_stub.leads.rows if r["id"] == "lead-a1")
    assert lead_a1["name"] == "Marshall Cuoco"
    assert lead_a1["email"] == "marshall@example.com"

    # Second run — idempotent: candidate filter (name=="Website Visitor")
    # no longer matches because the name was patched in the first pass.
    r2 = _run(_hit(False))
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["matched_leads"] == 0
    assert b2["enriched_leads"] == 0
    # No additional updates.
    assert len(db_stub.leads.updates) == 1


# ═══════════════════════════════════════════════════════════════════
# 4 · Tenant scope — default target is caller's tenant, tenant B
#     leads NEVER surface without explicit slug.
# ═══════════════════════════════════════════════════════════════════
def test_backfill_endpoint_never_leaks_other_tenants_leads_by_default():
    from routers import admin_migrations as _mod
    from migrations import task_p19_backfill_empty_website_visitor_leads as _p19

    db_stub = _seed()
    # Super_admin caller lives on tenant A. Even though tenant B has a
    # candidate lead, the default invocation MUST target tenant A only.
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant, db_stub)

    async def _body():
        with patch.object(_mod, "db", db_stub), \
             patch.object(_p19, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.post(
                    "/api/admin/migrations/backfill-website-visitor-leads",
                )
    r = _run(_body())
    body = r.json()
    # Only 1 match (tenant A), tenant B lead never surfaces.
    assert body["matched_leads"] == 1
    ids = [e["lead_id"] for e in body["enrichments"]]
    assert "lead-b1" not in ids
    # And the tenant-B leak string is not in the body.
    assert "TENANT-B-LEAK" not in r.text


# ═══════════════════════════════════════════════════════════════════
# 5 · Explicit tenant_slug targets a different tenant (super_admin).
# ═══════════════════════════════════════════════════════════════════
def test_backfill_endpoint_targets_other_tenant_when_slug_passed():
    from routers import admin_migrations as _mod
    from migrations import task_p19_backfill_empty_website_visitor_leads as _p19

    db_stub = _seed()
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant, db_stub)

    async def _body():
        with patch.object(_mod, "db", db_stub), \
             patch.object(_p19, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.post(
                    "/api/admin/migrations/backfill-website-visitor-leads"
                    "?tenant_slug=bravo",
                )
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "tB"
    assert body["tenant_slug"] == "bravo"
    # Tenant B has 1 candidate.
    assert body["matched_leads"] == 1


# ═══════════════════════════════════════════════════════════════════
# 6 · Unknown tenant_slug → 404 (never silently falls back).
# ═══════════════════════════════════════════════════════════════════
def test_backfill_endpoint_404s_on_unknown_tenant_slug():
    from routers import admin_migrations as _mod
    from migrations import task_p19_backfill_empty_website_visitor_leads as _p19

    db_stub = _seed()
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant, db_stub)

    async def _body():
        with patch.object(_mod, "db", db_stub), \
             patch.object(_p19, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.post(
                    "/api/admin/migrations/backfill-website-visitor-leads"
                    "?tenant_slug=nonexistent",
                )
    r = _run(_body())
    assert r.status_code == 404, r.text
    assert "tenant_not_found" in r.text
