"""Feb-2026 · P1 · Roster Cleanup admin endpoints.

Covers:
  * ``GET  /api/admin/migrations/roster`` — tenant-scoped list of
    tech-adjacent users w/ live active-jobs count.
  * ``POST /api/admin/migrations/deactivate-users`` — soft-deactivate
    batch. Role gate, tenant scope, active-job guard, idempotency,
    dry-run.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import patch

from httpx import AsyncClient, ASGITransport


def _run(coro):
    return asyncio.run(coro)


class _AsyncCursor:
    def __init__(self, rows): self._rows = list(rows)
    def sort(self, *_a, **_k): return self
    async def to_list(self, _n): return list(self._rows)
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
        return _AsyncCursor([dict(r) for r in self.rows if _match(r, q)])

    async def count_documents(self, q):
        return sum(1 for r in self.rows if _match(r, q))

    async def update_one(self, q, upd):
        for r in self.rows:
            if _match(r, q):
                r.update(upd.get("$set", {}))
                self.updates.append({"q": dict(q), "set": upd["$set"]})
                return


def _match(row, query):
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
            if "$in" in v and rv not in v["$in"]:
                return False
            if "$ne" in v and rv == v["$ne"]:
                return False
            if "$exists" in v and (k in row) != v["$exists"]:
                return False
        else:
            if rv != v:
                return False
    return True


class _DB:
    def __init__(self, users, jobs, tenants):
        self.users = _Coll(users)
        self.jobs = _Coll(jobs)
        self.tenants = _Coll(tenants)


def _build_app(user, tenant):
    from fastapi import FastAPI
    from routers.admin_migrations import router as _r
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    app = FastAPI()
    app.include_router(_r, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    return app


def _seed_db():
    users = [
        {"id": "u_active", "tenant_id": "tA", "email": "active@a.co",
         "name": "Active Tech", "role": "technician", "active": True,
         "created_at": "2026-01-01"},
        {"id": "u_inactive", "tenant_id": "tA", "email": "inact@a.co",
         "name": "Already Inactive", "role": "technician", "active": False,
         "created_at": "2026-01-02"},
        {"id": "u_with_jobs", "tenant_id": "tA", "email": "busy@a.co",
         "name": "Busy Tech", "role": "technician", "active": True,
         "created_at": "2026-01-03"},
        # Non-tech role — endpoint must refuse.
        {"id": "u_admin", "tenant_id": "tA", "email": "admin@a.co",
         "name": "Alex Admin", "role": "admin", "active": True,
         "created_at": "2026-01-04"},
        # Cross-tenant user — endpoint MUST refuse to touch.
        {"id": "u_tenant_b", "tenant_id": "tB", "email": "b@b.co",
         "name": "Tenant B Tech", "role": "technician", "active": True,
         "created_at": "2026-01-05"},
    ]
    jobs = [
        # Busy tech has an in-progress job — guard should refuse.
        {"id": "j1", "tenant_id": "tA", "technician_id": "u_with_jobs",
         "status": "in_progress"},
        # Completed job on the active tech — should NOT count.
        {"id": "j2", "tenant_id": "tA", "technician_id": "u_active",
         "status": "completed"},
    ]
    tenants = [{"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}]
    return _DB(users, jobs, tenants)


# ═══════════════════════════════════════════════════════════════════
# 1 · super_admin only — every other role gets 403.
# ═══════════════════════════════════════════════════════════════════
def test_deactivate_users_super_admin_only():
    from routers import admin_migrations as _mod

    for role in ("admin", "manager", "technician", "customer"):
        db_stub = _seed_db()
        user = {"id": "u_x", "role": role, "tenant_id": "tA"}
        tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
        app = _build_app(user, tenant)

        async def _body():
            with patch.object(_mod, "db", db_stub):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport,
                                        base_url="http://t") as ac:
                    return await ac.post(
                        "/api/admin/migrations/deactivate-users",
                        json={"user_ids": ["u_active"], "dry_run": False},
                    )
        r = _run(_body())
        assert r.status_code == 403, (role, r.text)
        # No DB writes on 403.
        assert db_stub.users.updates == [], role


# ═══════════════════════════════════════════════════════════════════
# 2 · dry_run=true reports but writes nothing.
# ═══════════════════════════════════════════════════════════════════
def test_deactivate_users_dry_run_leaves_db_untouched():
    from routers import admin_migrations as _mod
    db_stub = _seed_db()
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.post(
                    "/api/admin/migrations/deactivate-users",
                    json={"user_ids": ["u_active"], "dry_run": True},
                )
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["deactivated_count"] == 1
    assert body["deactivated"] == ["u_active"]
    # DB untouched on dry-run.
    assert db_stub.users.updates == []
    # Row still has active=True.
    row = next(u for u in db_stub.users.rows if u["id"] == "u_active")
    assert row["active"] is True


# ═══════════════════════════════════════════════════════════════════
# 3 · Active-job guard — refuses to deactivate a tech with a job.
# ═══════════════════════════════════════════════════════════════════
def test_deactivate_users_refuses_when_active_jobs_exist():
    from routers import admin_migrations as _mod
    db_stub = _seed_db()
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.post(
                    "/api/admin/migrations/deactivate-users",
                    json={"user_ids": ["u_with_jobs"], "dry_run": False},
                )
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deactivated_count"] == 0
    assert body["skipped_count"] == 1
    skip = body["skipped"][0]
    assert skip["user_id"] == "u_with_jobs"
    assert skip["reason"] == "has_active_jobs"
    assert skip["active_jobs"] == 1
    # DB untouched — busy tech's ``active`` is still True.
    row = next(u for u in db_stub.users.rows if u["id"] == "u_with_jobs")
    assert row["active"] is True


# ═══════════════════════════════════════════════════════════════════
# 4 · Idempotency — already-inactive users are a no-op.
# ═══════════════════════════════════════════════════════════════════
def test_deactivate_users_idempotent_on_already_inactive():
    from routers import admin_migrations as _mod
    db_stub = _seed_db()
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.post(
                    "/api/admin/migrations/deactivate-users",
                    json={"user_ids": ["u_inactive"], "dry_run": False},
                )
    r = _run(_body())
    body = r.json()
    assert body["deactivated_count"] == 0
    assert body["skipped"][0]["reason"] == "already_inactive"


# ═══════════════════════════════════════════════════════════════════
# 5 · Tenant scope — caller on tenant A can NEVER touch tenant B user.
# ═══════════════════════════════════════════════════════════════════
def test_deactivate_users_tenant_scope_strict():
    from routers import admin_migrations as _mod
    db_stub = _seed_db()
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.post(
                    "/api/admin/migrations/deactivate-users",
                    json={"user_ids": ["u_tenant_b"], "dry_run": False},
                )
    r = _run(_body())
    body = r.json()
    # Response collapses "wrong tenant" + "not found" into ``not_found``
    # to avoid leaking cross-tenant user existence.
    assert body["skipped"][0]["reason"] == "not_found"
    # Tenant B user unchanged.
    row = next(u for u in db_stub.users.rows if u["id"] == "u_tenant_b")
    assert row["active"] is True


# ═══════════════════════════════════════════════════════════════════
# 6 · Non-tech-adjacent role (admin) can't be touched via this endpoint.
# ═══════════════════════════════════════════════════════════════════
def test_deactivate_users_refuses_non_tech_adjacent_roles():
    from routers import admin_migrations as _mod
    db_stub = _seed_db()
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.post(
                    "/api/admin/migrations/deactivate-users",
                    json={"user_ids": ["u_admin"], "dry_run": False},
                )
    r = _run(_body())
    body = r.json()
    assert body["skipped"][0]["reason"] == "not_tech_adjacent"


# ═══════════════════════════════════════════════════════════════════
# 7 · Commit path — writes active=false + deactivated_at + _by.
# ═══════════════════════════════════════════════════════════════════
def test_deactivate_users_commit_writes_soft_delete_fields():
    from routers import admin_migrations as _mod
    db_stub = _seed_db()
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA",
            "email": "sa@a.co"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.post(
                    "/api/admin/migrations/deactivate-users",
                    json={"user_ids": ["u_active"], "dry_run": False},
                )
    r = _run(_body())
    body = r.json()
    assert body["deactivated_count"] == 1
    assert body["deactivated"] == ["u_active"]
    # Row was soft-deactivated with audit stamps.
    row = next(u for u in db_stub.users.rows if u["id"] == "u_active")
    assert row["active"] is False
    assert row["deactivated_by"] == "u_sa"
    assert row["deactivated_at"]  # ISO string
    # 2nd call is idempotent.
    r2 = _run(_body())
    b2 = r2.json()
    assert b2["deactivated_count"] == 0
    assert b2["skipped"][0]["reason"] == "already_inactive"


# ═══════════════════════════════════════════════════════════════════
# 8 · Roster GET — only tech-adjacent users, includes active_jobs.
# ═══════════════════════════════════════════════════════════════════
def test_list_roster_returns_tech_adjacent_with_active_jobs():
    from routers import admin_migrations as _mod
    db_stub = _seed_db()
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.get("/api/admin/migrations/roster")
    r = _run(_body())
    assert r.status_code == 200, r.text
    rows = r.json()
    # Admin (u_admin) + tenant B user (u_tenant_b) NEVER surface.
    ids = {row["id"] for row in rows}
    assert "u_admin" not in ids
    assert "u_tenant_b" not in ids
    # Active-jobs count computed per row.
    busy = next(row for row in rows if row["id"] == "u_with_jobs")
    assert busy["active_jobs"] == 1
    active = next(row for row in rows if row["id"] == "u_active")
    assert active["active_jobs"] == 0
    # is_deactivated flag matches.
    inactive = next(row for row in rows if row["id"] == "u_inactive")
    assert inactive["is_deactivated"] is True
    assert active["is_deactivated"] is False


# ═══════════════════════════════════════════════════════════════════
# 9 · Feb 2026 · Auto-resolve branch — empty ``user_ids`` on dry_run
#     expands to the tenant's full tech-adjacent roster, filters out
#     already-inactive + busy techs via the standard skip reasons,
#     writes NOTHING, and returns rich ``deactivated_details`` rows.
# ═══════════════════════════════════════════════════════════════════
def test_deactivate_users_auto_resolve_dry_run_returns_details():
    from routers import admin_migrations as _mod
    db_stub = _seed_db()
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                # user_ids omitted entirely → auto-resolve branch.
                return await ac.post(
                    "/api/admin/migrations/deactivate-users",
                    json={"dry_run": True},
                )
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["resolved_from"] == "auto"
    # ``u_active`` is the only tenant-A tech that's active + free —
    # ``u_inactive`` is already inactive, ``u_with_jobs`` has an
    # active job, ``u_admin`` isn't tech-adjacent, ``u_tenant_b`` is
    # a different tenant.
    assert body["deactivated_count"] == 1
    assert body["deactivated"] == ["u_active"]
    detail = body["deactivated_details"][0]
    assert detail["id"] == "u_active"
    assert detail["email"] == "active@a.co"
    assert detail["role"] == "technician"
    # Busy tech + already-inactive tech surface as skipped rows.
    skip_reasons = {s["reason"] for s in body["skipped"]}
    assert "has_active_jobs" in skip_reasons
    assert "already_inactive" in skip_reasons
    # DB untouched — dry-run.
    assert db_stub.users.updates == []


# ═══════════════════════════════════════════════════════════════════
# 10 · Auto-resolve commit path — writes soft-delete on every
#      cleanable row, leaves busy + already-inactive alone.
# ═══════════════════════════════════════════════════════════════════
def test_deactivate_users_auto_resolve_commit_writes_only_cleanable():
    from routers import admin_migrations as _mod
    db_stub = _seed_db()
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA",
            "email": "sa@a.co"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant)

    async def _body(json_body):
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.post(
                    "/api/admin/migrations/deactivate-users",
                    json=json_body,
                )
    # Auto-resolve commit — no ``user_ids`` in payload.
    r = _run(_body({"dry_run": False}))
    body = r.json()
    assert body["resolved_from"] == "auto"
    assert body["deactivated"] == ["u_active"]
    # Only u_active was written to.
    updated_ids = [u["q"].get("id") for u in db_stub.users.updates]
    assert updated_ids == ["u_active"]
    # Row confirms soft-delete stamps.
    row = next(u for u in db_stub.users.rows if u["id"] == "u_active")
    assert row["active"] is False
    assert row["deactivated_by"] == "u_sa"
    # Busy tech untouched.
    busy = next(u for u in db_stub.users.rows if u["id"] == "u_with_jobs")
    assert busy["active"] is True
    # 2nd auto-commit call is idempotent — nothing left to
    # deactivate, everything either already-inactive or has jobs.
    r2 = _run(_body({"dry_run": False}))
    b2 = r2.json()
    assert b2["deactivated_count"] == 0
    reasons = {s["reason"] for s in b2["skipped"]}
    assert "already_inactive" in reasons
    assert "has_active_jobs" in reasons


# ═══════════════════════════════════════════════════════════════════
# 11 · Auto-resolve never crosses tenant boundaries.
# ═══════════════════════════════════════════════════════════════════
def test_deactivate_users_auto_resolve_is_tenant_scoped():
    from routers import admin_migrations as _mod
    db_stub = _seed_db()
    user = {"id": "u_sa_b", "role": "super_admin", "tenant_id": "tB"}
    # Caller sits on tenant B — the auto-resolve MUST only sweep
    # tenant-B users. Seed only had ``u_tenant_b`` on tenant B and
    # it has no active jobs, so it should be the only candidate.
    tenant = {"id": "tB", "slug": "bravo", "name": "Bravo"}
    app = _build_app(user, tenant)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.post(
                    "/api/admin/migrations/deactivate-users",
                    json={"dry_run": True},
                )
    r = _run(_body())
    body = r.json()
    assert body["resolved_from"] == "auto"
    assert body["deactivated"] == ["u_tenant_b"]
    # Tenant-A rows never surface even though they'd be cleanable.
    detail_ids = {d["id"] for d in body["deactivated_details"]}
    assert "u_active" not in detail_ids


# ═══════════════════════════════════════════════════════════════════
# 12 · Explicit ``user_ids`` still routes through the legacy path
#      (backwards compatibility — response labels ``resolved_from``
#      as ``"explicit"``).
# ═══════════════════════════════════════════════════════════════════
def test_deactivate_users_explicit_path_still_works():
    from routers import admin_migrations as _mod
    db_stub = _seed_db()
    user = {"id": "u_sa", "role": "super_admin", "tenant_id": "tA"}
    tenant = {"id": "tA", "slug": "aquaterra", "name": "AquaTerra"}
    app = _build_app(user, tenant)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport,
                                    base_url="http://t") as ac:
                return await ac.post(
                    "/api/admin/migrations/deactivate-users",
                    json={"user_ids": ["u_active"], "dry_run": True},
                )
    r = _run(_body())
    body = r.json()
    assert body["resolved_from"] == "explicit"
    assert body["deactivated"] == ["u_active"]
    # Enriched details on the explicit path too.
    assert body["deactivated_details"][0]["email"] == "active@a.co"
