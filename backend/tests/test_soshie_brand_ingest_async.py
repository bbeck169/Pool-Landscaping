"""Phase I4 · Feb-2026 — Soshie brand-brain async ingest tests.

Exercises the three new endpoints + the worker + the stale-job
sweep. Every test rebinds the DB through the F7 loop fixture so
Motor collection affinity stays honest.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from tests._f7_loop_fixture import run_test


POST_URL = "/api/soshie/brand-brain/ingest"


def _get_app():
    from server import app
    return app


async def _make_role_token(db, role, email, tenant_id="aquaterra"):
    from utils import create_token, new_id
    from datetime import datetime, timezone
    existing = await db.users.find_one({"email": email})
    if existing:
        if existing.get("role") != role:
            await db.users.update_one({"email": email},
                                          {"$set": {"role": role}})
            existing["role"] = role
        return create_token(existing)
    user = {
        "id": new_id(),
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(user)
    return create_token(user)


async def _ensure_tenant(db, tenant_id="aquaterra"):
    from utils import now_iso
    existing = await db.tenants.find_one({"id": tenant_id})
    if existing:
        # Ensure active flag is set for get_current_tenant lookups.
        if not existing.get("active"):
            await db.tenants.update_one(
                {"id": tenant_id}, {"$set": {"active": True}},
            )
        return existing
    row = {"id": tenant_id, "slug": tenant_id, "name": tenant_id,
              "active": True, "created_at": now_iso()}
    await db.tenants.insert_one(dict(row))
    return row


def _wait_for(coro_fn, timeout_s=5.0, poll_s=0.05):
    """Await ``coro_fn()`` repeatedly until it returns truthy or
    the timeout elapses. Returns the last observation."""
    async def _loop():
        deadline = asyncio.get_event_loop().time() + timeout_s
        last = None
        while asyncio.get_event_loop().time() < deadline:
            last = await coro_fn()
            if last:
                return last
            await asyncio.sleep(poll_s)
        return last
    return _loop()


# ═══════════════════════════════════════════════════════════════════
# 1. POST returns 202 immediately with a job_id
# ═══════════════════════════════════════════════════════════════════
def test_i4_post_returns_202_with_job_id():
    async def _go(db):
        await _ensure_tenant(db)
        token = await _make_role_token(db, "admin", "i4admin@aquaterra.com")
        # Patch the worker to a no-op so the test doesn't hit the
        # network. The POST assertion only cares about the sync
        # response shape.
        import services.soshie.brand_ingest_jobs as jobs
        orig = jobs.spawn_ingest_job
        jobs.spawn_ingest_job = lambda _jid: None
        try:
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.post(
                    POST_URL,
                    headers={"Authorization": f"Bearer {token}"},
                    json={"website_url": "https://example.com"},
                )
                assert r.status_code == 202, r.text
                body = r.json()
                assert body["status"] == "queued"
                assert body["url"] == "https://example.com"
                assert body["progress"]["paths_total"] == 1
                job_id = body["id"]
                assert isinstance(job_id, str) and len(job_id) >= 8
                loc = r.headers.get("location") or r.headers.get("Location")
                assert loc == f"/api/soshie/brand-brain/ingest/{job_id}"
        finally:
            jobs.spawn_ingest_job = orig

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 2. GET status endpoint returns the row + progress
# ═══════════════════════════════════════════════════════════════════
def test_i4_get_status_returns_progress():
    async def _go(db):
        await _ensure_tenant(db)
        token = await _make_role_token(db, "admin", "i4admin@aquaterra.com")
        from services.soshie.brand_ingest_jobs import create_ingest_job
        row = await create_ingest_job(
            "aquaterra", "https://example.com", ["/services"],
            user_id="user1",
        )
        await db.soshie_ingest_jobs.update_one(
            {"id": row["id"]},
            {"$set": {"status": "running",
                        "progress.current_step": "crawling_and_parsing",
                        "progress.paths_crawled": 1,
                        "progress.paths_total": 2}},
        )
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.get(
                f"{POST_URL}/{row['id']}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["id"] == row["id"]
            assert body["status"] == "running"
            assert body["progress"]["paths_crawled"] == 1
            assert body["progress"]["paths_total"] == 2

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 3. Job records error on failure without crashing
# ═══════════════════════════════════════════════════════════════════
def test_i4_worker_records_error_on_failure():
    async def _go(db):
        await _ensure_tenant(db)
        import services.soshie.brand_ingest_jobs as jobs
        # Monkeypatch the inner ingest to raise so we exercise the
        # exception-encoding branch.
        orig = jobs._do_ingest
        async def _boom(job_id):
            raise RuntimeError("simulated_failure_xyz")
        jobs._do_ingest = _boom
        try:
            row = await jobs.create_ingest_job(
                "aquaterra", "https://example.com", [],
            )
            await jobs._run_ingest_worker(row["id"])
            after = await db.soshie_ingest_jobs.find_one({"id": row["id"]})
            assert after["status"] == "failed"
            assert "simulated_failure_xyz" in after["error"]
            assert after["finished_at"]
        finally:
            jobs._do_ingest = orig

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 4. LLM/inner timeout scenario → status=failed, error=timeout
# ═══════════════════════════════════════════════════════════════════
def test_i4_worker_records_timeout_error():
    async def _go(db):
        await _ensure_tenant(db)
        import services.soshie.brand_ingest_jobs as jobs
        # Force a timeout by shrinking the ceiling + making the
        # inner coroutine wait past it.
        orig_do = jobs._do_ingest
        orig_ceiling = jobs._TOTAL_JOB_TIMEOUT_S
        async def _slow(job_id):
            await asyncio.sleep(1.0)
            return {}
        jobs._do_ingest = _slow
        jobs._TOTAL_JOB_TIMEOUT_S = 0.05  # 50ms
        try:
            row = await jobs.create_ingest_job(
                "aquaterra", "https://example.com", [],
            )
            await jobs._run_ingest_worker(row["id"])
            after = await db.soshie_ingest_jobs.find_one({"id": row["id"]})
            assert after["status"] == "failed"
            assert after["error"] == "timeout"
        finally:
            jobs._do_ingest = orig_do
            jobs._TOTAL_JOB_TIMEOUT_S = orig_ceiling

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 5. Stale-job cleanup marks 15-min-old running jobs as failed
# ═══════════════════════════════════════════════════════════════════
def test_i4_stale_job_cleanup_marks_failed():
    async def _go(db):
        await _ensure_tenant(db)
        from utils import new_id
        stale_started = (datetime.now(timezone.utc)
                             - timedelta(minutes=20)).isoformat()
        fresh_started = (datetime.now(timezone.utc)
                             - timedelta(minutes=5)).isoformat()
        stale = {"id": new_id(), "tenant_id": "aquaterra",
                    "url": "https://a.example.com",
                    "extra_paths": [], "status": "running",
                    "started_at": stale_started,
                    "finished_at": None, "error": None,
                    "progress": {"paths_crawled": 0, "paths_total": 1,
                                    "current_step": "queued"},
                    "result_summary": None}
        fresh = {"id": new_id(), "tenant_id": "aquaterra",
                    "url": "https://b.example.com",
                    "extra_paths": [], "status": "running",
                    "started_at": fresh_started,
                    "finished_at": None, "error": None,
                    "progress": {"paths_crawled": 0, "paths_total": 1,
                                    "current_step": "queued"},
                    "result_summary": None}
        await db.soshie_ingest_jobs.insert_many([stale, fresh])
        try:
            from services.soshie.brand_ingest_jobs import (
                cleanup_stale_ingest_jobs,
            )
            result = await cleanup_stale_ingest_jobs()
            assert result["swept"] >= 1
            after_stale = await db.soshie_ingest_jobs.find_one(
                {"id": stale["id"]},
            )
            after_fresh = await db.soshie_ingest_jobs.find_one(
                {"id": fresh["id"]},
            )
            assert after_stale["status"] == "failed"
            assert after_stale["error"] == "timeout_stale"
            assert after_stale["finished_at"]
            # Fresh job untouched.
            assert after_fresh["status"] == "running"
            assert after_fresh["error"] is None
        finally:
            await db.soshie_ingest_jobs.delete_many(
                {"id": {"$in": [stale["id"], fresh["id"]]}},
            )

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 6. >5 total paths → 400 at the API layer
# ═══════════════════════════════════════════════════════════════════
def test_i4_too_many_paths_returns_400():
    async def _go(db):
        await _ensure_tenant(db)
        token = await _make_role_token(db, "admin", "i4admin@aquaterra.com")
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.post(
                POST_URL,
                headers={"Authorization": f"Bearer {token}"},
                json={"website_url": "https://example.com",
                        "extra_paths": ["/a", "/b", "/c", "/d", "/e"]},
            )
            # 5 extras + home = 6 pages → over cap.
            assert r.status_code == 400, r.text
            detail = r.json().get("detail", "")
            assert "too_many_paths" in detail

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 7. RBAC — admin+ only
# ═══════════════════════════════════════════════════════════════════
def test_i4_rbac_tech_gets_403():
    async def _go(db):
        await _ensure_tenant(db)
        token = await _make_role_token(db, "tech", "i4tech@aquaterra.com")
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.post(
                POST_URL,
                headers={"Authorization": f"Bearer {token}"},
                json={"website_url": "https://example.com"},
            )
            assert r.status_code == 403, r.text

    run_test(_go)


def test_i4_rbac_unauth_gets_401_or_403():
    async def _go(_db):
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.post(
                POST_URL,
                json={"website_url": "https://example.com"},
            )
            assert r.status_code in (401, 403), r.text

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 8. Latest endpoint returns most recent tenant job
# ═══════════════════════════════════════════════════════════════════
def test_i4_latest_returns_most_recent_tenant_job():
    async def _go(db):
        await _ensure_tenant(db)
        token = await _make_role_token(db, "admin", "i4admin@aquaterra.com")
        from services.soshie.brand_ingest_jobs import create_ingest_job
        older = await create_ingest_job(
            "aquaterra", "https://older.example.com", [],
        )
        await asyncio.sleep(0.01)
        newer = await create_ingest_job(
            "aquaterra", "https://newer.example.com", [],
        )
        # Cross-tenant row that must NOT surface.
        other = await create_ingest_job(
            "other-tenant", "https://other.example.com", [],
        )
        try:
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.get(
                    f"{POST_URL}/latest",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["job"] is not None
                assert body["job"]["id"] == newer["id"]
                assert body["job"]["url"] == "https://newer.example.com"
                # Cross-tenant leakage guard.
                assert body["job"]["tenant_id"] == "aquaterra"
        finally:
            await db.soshie_ingest_jobs.delete_many(
                {"id": {"$in": [older["id"], newer["id"], other["id"]]}},
            )

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 9. GET latest returns {job: null} when tenant has no jobs
# ═══════════════════════════════════════════════════════════════════
def test_i4_latest_empty_tenant_returns_null():
    async def _go(db):
        # Isolate a tenant with no jobs.
        await _ensure_tenant(db, "empty-i4-tenant")
        await db.soshie_ingest_jobs.delete_many(
            {"tenant_id": "empty-i4-tenant"},
        )
        token = await _make_role_token(
            db, "admin", "i4empty@empty-i4-tenant.com", "empty-i4-tenant",
        )
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.get(
                f"{POST_URL}/latest",
                headers={"Authorization": f"Bearer {token}",
                            "X-Tenant-Slug": "empty-i4-tenant"},
            )
            assert r.status_code == 200
            assert r.json()["job"] is None

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 10. Worker writes brand_brain fields on success
# ═══════════════════════════════════════════════════════════════════
def test_i4_worker_writes_brand_brain_on_success():
    async def _go(db):
        await _ensure_tenant(db)
        import services.soshie.brand_ingest_jobs as jobs
        orig = jobs._do_ingest
        # Simulate a successful crawl that would have merged
        # bullets. The result dict is what the worker writes as
        # result_summary.
        async def _fake_success(job_id):
            # Represent a successful merge into brand_brain.
            await db.brand_brain.update_one(
                {"tenant_id": "aquaterra"},
                {"$set": {"tenant_id": "aquaterra",
                            "talking_points": ["We serve Phoenix pools."]}},
                upsert=True,
            )
            return {"pages_fetched": 1, "bullets_added": 1,
                        "urls": ["https://example.com"]}
        jobs._do_ingest = _fake_success
        try:
            row = await jobs.create_ingest_job(
                "aquaterra", "https://example.com", [],
            )
            await jobs._run_ingest_worker(row["id"])
            after = await db.soshie_ingest_jobs.find_one({"id": row["id"]})
            assert after["status"] == "succeeded"
            assert after["result_summary"]["pages_fetched"] == 1
            assert after["result_summary"]["bullets_added"] == 1
            bb = await db.brand_brain.find_one({"tenant_id": "aquaterra"})
            assert "We serve Phoenix pools." in (bb.get("talking_points")
                                                       or [])
        finally:
            jobs._do_ingest = orig

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 11. Legacy /soshie/ingest-website shims to async job (202-shape)
# ═══════════════════════════════════════════════════════════════════
def test_i4_legacy_endpoint_shims_to_async():
    async def _go(db):
        await _ensure_tenant(db)
        token = await _make_role_token(db, "admin", "i4admin@aquaterra.com")
        # No-op worker to avoid the network hit.
        import services.soshie.brand_ingest_jobs as jobs
        orig = jobs.spawn_ingest_job
        jobs.spawn_ingest_job = lambda _jid: None
        try:
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.post(
                    "/api/soshie/ingest-website",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"website_url": "https://example.com"},
                )
                assert r.status_code == 200, r.text
                body = r.json()
                assert body.get("async_job") is True
                assert body.get("job_id")
                assert body["poll_url"].startswith(
                    "/api/soshie/brand-brain/ingest/",
                )
                # Historical shape preserved so old clients that
                # inspect these keys don't crash.
                assert "pages_fetched" in body
                assert "bullets_added" in body
                assert "urls" in body
        finally:
            jobs.spawn_ingest_job = orig

    run_test(_go)
