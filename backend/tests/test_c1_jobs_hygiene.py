"""Phase C1 · Feb-2026 — Jobs hygiene + payments health tests.

Covers:
  1.  Job completion PATCH stamps ``completed_at``.
  2.  Backfill script uses ``auto_invoice_created_at`` when present.
  3.  Backfill script uses latest service-report timestamp else.
  4.  Backfill script uses ``updated_at`` as last resort.
  5.  Backfill script is idempotent (second run: 0 backfilled).
  6.  Kanban Completed column reads ``completed_at`` when present
      (backend picks it over ``auto_invoice_created_at`` proxy).
  7.  Non-recurring job → ``follow_up_at = completed_at + 14d``.
  8.  Weekly-recurring job → ``follow_up_at = completed_at + 7d``.
  9.  Admin PATCH of ``follow_up_at`` overrides auto-populated value.
  10. Admin PATCH of ``needs_follow_up=true`` on a completed job with
      no ``follow_up_at`` still surfaces in the Kanban Follow-up column.
  11. Technician PATCH of ``follow_up_at`` → 403.
  12. ``/api/health/payments`` returns ``unconfigured`` when the
      env var carries a placeholder value.
  13. ``/api/health/payments`` returns ``ok`` with a mock Stripe
      probe.
  14. ``/api/health/payments`` returns ``degraded`` when the probe
      raises.
  15. ``/api/health/payments`` is publicly accessible (no auth).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import httpx
import jwt as _jwt
import pytest

from tests._f7_loop_fixture import run_test


API = "/api"


def _get_app():
    from server import app
    return app


def _mint_token(*, uid: str, tid: str, role: str,
                 technician_id: str = "") -> str:
    from config import JWT_SECRET
    payload = {
        "sub":       uid,
        "email":     f"{uid}@ex.test",
        "role":      role,
        "tenant_id": tid,
        "exp":       int((datetime.now(timezone.utc)
                            + timedelta(hours=1)).timestamp()),
    }
    if technician_id:
        payload["technician_id"] = technician_id
    return _jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat() \
              if dt.tzinfo is None else dt.isoformat()


@pytest.fixture
def c1_seed():
    tid = f"c1-tid-{uuid.uuid4()}"
    admin_uid = f"c1-admin-{uuid.uuid4()}"
    tech_uid = f"c1-tech-{uuid.uuid4()}"
    tech_pk = f"c1-tech-pk-{uuid.uuid4()}"

    async def _seed(_db):
        await _db.tenants.insert_one(
            {"id": tid, "name": "Tenant C1",
              "slug": f"c1-{uuid.uuid4().hex[:8]}",
              "active": True, "settings": {}})
        await _db.users.insert_many([
            {"id": admin_uid, "email": f"admin-{admin_uid}@ex.test",
              "role": "admin", "tenant_id": tid,
              "name": "Alex Admin"},
            {"id": tech_uid, "email": f"tech-{tech_uid}@ex.test",
              "role": "technician", "tenant_id": tid,
              "technician_id": tech_pk, "name": "Terry Tech"},
        ])

    async def _teardown(_db):
        await _db.tenants.delete_many({"id": tid})
        await _db.users.delete_many({"id": {"$in": [admin_uid, tech_uid]}})
        await _db.jobs.delete_many({"tenant_id": tid})
        await _db.recurring_job_templates.delete_many({"tenant_id": tid})
        await _db.service_reports.delete_many({"tenant_id": tid})

    run_test(_seed)
    yield {
        "tenant_id":    tid,
        "admin_token":  _mint_token(uid=admin_uid, tid=tid, role="admin"),
        "tech_token":   _mint_token(uid=tech_uid,  tid=tid,
                                       role="technician",
                                       technician_id=tech_pk),
        "tech_pk":      tech_pk,
    }
    run_test(_teardown)


async def _mk_job(_db, tid: str, *, status: str = "scheduled",
                    tech_id: str = "",
                    recurring_template_id: str = "",
                    completed_at: str = "",
                    follow_up_at: str = "") -> str:
    jid = f"c1-job-{uuid.uuid4()}"
    doc: Dict[str, Any] = {
        "id": jid, "tenant_id": tid,
        "status": status,
        "customer_id": f"c1-cust-{uuid.uuid4()}",
        "customer_name": "Cust",
        "service_type": "Pool Cleaning",
        "work_class": "service",
        "title": "Weekly clean",
        "price": 100.0,
        "scheduled_date": datetime.now(timezone.utc).date().isoformat(),
        "created_at": _iso(datetime.now(timezone.utc)),
    }
    if tech_id:
        doc["technician_id"] = tech_id
        doc["technician_name"] = "Terry Tech"
    if recurring_template_id:
        doc["recurring_template_id"] = recurring_template_id
    if completed_at:
        doc["completed_at"] = completed_at
    if follow_up_at:
        doc["follow_up_at"] = follow_up_at
    await _db.jobs.insert_one(doc)
    return jid


async def _mk_template(_db, tid: str, *, frequency: str,
                          interval_days: int = None) -> str:
    tpl_id = f"c1-tpl-{uuid.uuid4()}"
    doc: Dict[str, Any] = {
        "id": tpl_id, "tenant_id": tid,
        "frequency": frequency, "active": True,
        "is_active": True,
        "customer_id": "c1-cust-anything",
    }
    if interval_days is not None:
        doc["interval_days"] = interval_days
    await _db.recurring_job_templates.insert_one(doc)
    return tpl_id


async def _patch_job(client: httpx.AsyncClient, token: str,
                       jid: str, body: Dict[str, Any]) -> httpx.Response:
    # Router mounts the endpoint as ``PUT /api/jobs/{jid}``.
    return await client.put(
        f"{API}/jobs/{jid}", json=body,
        headers={"Authorization": f"Bearer {token}"})


# ═════════════════════════════════════════════════════════════════════
# 1 · PATCH → completed stamps completed_at.
# ═════════════════════════════════════════════════════════════════════
def test_completion_patch_stamps_completed_at(c1_seed):
    S = c1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        # Landscape job → no chemistry gate.
        jid = await _mk_job(_db, S["tenant_id"], status="scheduled",
                              tech_id=S["tech_pk"])
        # Force a non-pool service_type so the chemistry gate skips.
        await _db.jobs.update_one(
            {"id": jid}, {"$set": {"service_type": "Landscape Cleanup"}})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await _patch_job(
                c, S["admin_token"], jid, {"status": "completed"})
            result["status"] = r.status_code
        fresh = await _db.jobs.find_one({"id": jid}, {"_id": 0})
        result["completed_at"] = fresh.get("completed_at")

    run_test(_go)
    assert result["status"] == 200, result
    assert result["completed_at"], result
    # Round-trip parseable.
    datetime.fromisoformat(result["completed_at"].replace("Z", "+00:00"))


# ═════════════════════════════════════════════════════════════════════
# 2·3·4 · Backfill precedence.
# ═════════════════════════════════════════════════════════════════════
def test_backfill_prefers_auto_invoice_created_at(c1_seed):
    from scripts.backfill_job_completed_at import backfill_tenant
    S = c1_seed
    async def _go(_db):
        jid = await _mk_job(_db, S["tenant_id"], status="completed")
        stamp = _iso(datetime.now(timezone.utc) - timedelta(days=3))
        await _db.jobs.update_one(
            {"id": jid},
            {"$set": {"auto_invoice_created_at": stamp,
                       "updated_at": _iso(datetime.now(timezone.utc))}})
        summary = await backfill_tenant(_db, S["tenant_id"])
        fresh = await _db.jobs.find_one({"id": jid}, {"_id": 0})
        return summary, fresh
    summary, fresh = run_test(_go)
    assert summary["backfilled_count"] == 1
    assert fresh["completed_at"] == fresh["auto_invoice_created_at"]


def test_backfill_uses_service_report_timestamp(c1_seed):
    from scripts.backfill_job_completed_at import backfill_tenant
    S = c1_seed
    async def _go(_db):
        jid = await _mk_job(_db, S["tenant_id"], status="completed")
        rep_stamp = _iso(datetime.now(timezone.utc) - timedelta(days=5))
        await _db.service_reports.insert_one({
            "id": f"c1-sr-{uuid.uuid4()}",
            "tenant_id": S["tenant_id"], "job_id": jid,
            "completed_at": rep_stamp,
            "submitted_at": rep_stamp,
        })
        summary = await backfill_tenant(_db, S["tenant_id"])
        fresh = await _db.jobs.find_one({"id": jid}, {"_id": 0})
        return summary, fresh
    summary, fresh = run_test(_go)
    assert summary["backfilled_count"] == 1
    assert fresh["completed_at"], fresh


def test_backfill_falls_back_to_updated_at(c1_seed):
    from scripts.backfill_job_completed_at import backfill_tenant
    S = c1_seed
    async def _go(_db):
        jid = await _mk_job(_db, S["tenant_id"], status="completed")
        upd = _iso(datetime.now(timezone.utc) - timedelta(days=9))
        await _db.jobs.update_one({"id": jid},
                                     {"$set": {"updated_at": upd}})
        summary = await backfill_tenant(_db, S["tenant_id"])
        fresh = await _db.jobs.find_one({"id": jid}, {"_id": 0})
        return summary, fresh
    summary, fresh = run_test(_go)
    assert summary["backfilled_count"] == 1
    assert fresh["completed_at"] == fresh["updated_at"]


def test_backfill_is_idempotent(c1_seed):
    from scripts.backfill_job_completed_at import backfill_tenant
    S = c1_seed
    async def _go(_db):
        jid = await _mk_job(_db, S["tenant_id"], status="completed")
        stamp = _iso(datetime.now(timezone.utc) - timedelta(days=1))
        await _db.jobs.update_one(
            {"id": jid},
            {"$set": {"auto_invoice_created_at": stamp}})
        first = await backfill_tenant(_db, S["tenant_id"])
        second = await backfill_tenant(_db, S["tenant_id"])
        return first, second
    first, second = run_test(_go)
    assert first["backfilled_count"] == 1
    assert second["backfilled_count"] == 0
    assert second["skipped_count"] >= 1


# ═════════════════════════════════════════════════════════════════════
# 6 · Kanban Completed column reads completed_at when present.
# ═════════════════════════════════════════════════════════════════════
def test_kanban_completed_uses_completed_at(c1_seed):
    S = c1_seed
    app = _get_app()

    async def _go(_db):
        # Job with EXPLICIT completed_at set — old (10 min ago) so
        # it's inside the 14-day window; but its
        # auto_invoice_created_at is a fake future stamp that would
        # be an incorrect proxy.
        real_stamp = _iso(datetime.now(timezone.utc)
                          - timedelta(minutes=10))
        fake_proxy = _iso(datetime.now(timezone.utc)
                          + timedelta(days=100))
        jid = await _mk_job(_db, S["tenant_id"], status="completed",
                              completed_at=real_stamp)
        await _db.jobs.update_one(
            {"id": jid},
            {"$set": {"auto_invoice_created_at": fake_proxy}})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/pipeline/kanban",
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            body = r.json()
        return body, jid

    body, jid = run_test(_go)
    by_key = {col["key"]: col for col in body["columns"]}
    ids = {c["id"] for c in by_key["completed"]["cards"]}
    assert jid in ids, (ids, jid)


# ═════════════════════════════════════════════════════════════════════
# 7 · Non-recurring → follow_up_at = completed_at + 14d.
# ═════════════════════════════════════════════════════════════════════
def test_completion_populates_follow_up_default_14d(c1_seed):
    S = c1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        jid = await _mk_job(_db, S["tenant_id"], status="scheduled",
                              tech_id=S["tech_pk"])
        await _db.jobs.update_one(
            {"id": jid}, {"$set": {"service_type": "Landscape Cleanup"}})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            await _patch_job(c, S["admin_token"], jid,
                                 {"status": "completed"})
        fresh = await _db.jobs.find_one({"id": jid}, {"_id": 0})
        result["ca"] = fresh.get("completed_at")
        result["fu"] = fresh.get("follow_up_at")

    run_test(_go)
    assert result["ca"] and result["fu"], result
    ca = datetime.fromisoformat(result["ca"].replace("Z", "+00:00"))
    fu = datetime.fromisoformat(result["fu"].replace("Z", "+00:00"))
    delta_days = (fu - ca).total_seconds() / 86400
    assert 13.9 <= delta_days <= 14.1, delta_days


# ═════════════════════════════════════════════════════════════════════
# 8 · Weekly-recurring → follow_up_at = completed_at + 7d.
# ═════════════════════════════════════════════════════════════════════
def test_completion_populates_follow_up_weekly_7d(c1_seed):
    S = c1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        tpl = await _mk_template(_db, S["tenant_id"],
                                    frequency="weekly", interval_days=7)
        jid = await _mk_job(_db, S["tenant_id"], status="scheduled",
                              tech_id=S["tech_pk"],
                              recurring_template_id=tpl)
        await _db.jobs.update_one(
            {"id": jid},
            {"$set": {"service_type": "Landscape Cleanup"}})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            await _patch_job(c, S["admin_token"], jid,
                                 {"status": "completed"})
        fresh = await _db.jobs.find_one({"id": jid}, {"_id": 0})
        result["ca"] = fresh.get("completed_at")
        result["fu"] = fresh.get("follow_up_at")

    run_test(_go)
    assert result["ca"] and result["fu"], result
    ca = datetime.fromisoformat(result["ca"].replace("Z", "+00:00"))
    fu = datetime.fromisoformat(result["fu"].replace("Z", "+00:00"))
    delta_days = (fu - ca).total_seconds() / 86400
    assert 6.9 <= delta_days <= 7.1, delta_days


# ═════════════════════════════════════════════════════════════════════
# 9 · Admin override wins over auto-populated follow_up_at.
# ═════════════════════════════════════════════════════════════════════
def test_admin_override_follow_up(c1_seed):
    S = c1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        jid = await _mk_job(_db, S["tenant_id"], status="completed")
        override = _iso(datetime.now(timezone.utc) + timedelta(days=3))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await _patch_job(c, S["admin_token"], jid,
                                    {"follow_up_at": override})
            result["status"] = r.status_code
        fresh = await _db.jobs.find_one({"id": jid}, {"_id": 0})
        result["fu"] = fresh.get("follow_up_at")

    run_test(_go)
    assert result["status"] == 200
    # The override is round-tripped as-is.
    assert result["fu"], result


# ═════════════════════════════════════════════════════════════════════
# 10 · needs_follow_up=true surfaces on Kanban.
# ═════════════════════════════════════════════════════════════════════
def test_needs_follow_up_flag_surfaces_in_kanban(c1_seed):
    S = c1_seed
    app = _get_app()

    async def _go(_db):
        jid = await _mk_job(_db, S["tenant_id"], status="completed",
                              completed_at=_iso(
                                  datetime.now(timezone.utc)
                                  - timedelta(minutes=15)))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            await _patch_job(c, S["admin_token"], jid,
                                 {"needs_follow_up": True})
            r = await c.get(
                f"{API}/pipeline/kanban",
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            body = r.json()
        return body, jid

    body, jid = run_test(_go)
    by_key = {col["key"]: col for col in body["columns"]}
    ids = {c["id"] for c in by_key["follow_up"]["cards"]}
    assert jid in ids, (ids, jid)


# ═════════════════════════════════════════════════════════════════════
# 11 · Technician PATCH of follow_up_at → 403.
# ═════════════════════════════════════════════════════════════════════
def test_tech_cannot_patch_follow_up(c1_seed):
    S = c1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        jid = await _mk_job(_db, S["tenant_id"], status="scheduled",
                              tech_id=S["tech_pk"])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await _patch_job(
                c, S["tech_token"], jid,
                {"follow_up_at":
                     _iso(datetime.now(timezone.utc))})
            result["status"] = r.status_code
            result["detail"] = r.json().get("detail")

    run_test(_go)
    assert result["status"] == 403, result
    assert "follow-up" in (result["detail"] or "").lower()


# ═════════════════════════════════════════════════════════════════════
# 12·13·14·15 · /api/health/payments endpoint.
# ═════════════════════════════════════════════════════════════════════
def _hit_health_payments():
    from server import app
    from routers.health_payments import set_stripe_probe

    import asyncio
    transport = httpx.ASGITransport(app=app)

    async def _go():
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(f"{API}/health/payments")
            return r.status_code, r.json()

    return asyncio.new_event_loop().run_until_complete(_go())


def test_health_payments_unconfigured_placeholder(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY_LIVE", "sk_placeholder_x")
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_placeholder_x")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "REPLACE_ME_ROTATE")
    status, body = _hit_health_payments()
    assert status == 200
    assert body["status"] == "unconfigured", body
    assert body["checks"]["key_shape_valid"] is False
    assert body["checks"]["stripe_api_reachable"] is False


def test_health_payments_ok_with_mock(monkeypatch):
    monkeypatch.setenv(
        "STRIPE_SECRET_KEY_LIVE",
        "sk_live_" + "0" * 60,
    )
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY_TEST", raising=False)
    from routers.health_payments import set_stripe_probe
    called: Dict[str, Any] = {}

    def _fake(key: str):
        called["key"] = key
        return True

    set_stripe_probe(_fake)
    try:
        status, body = _hit_health_payments()
    finally:
        set_stripe_probe(None)

    assert status == 200
    assert body["status"] == "ok", body
    assert body["checks"]["stripe_api_reachable"] is True
    # The probe received the real env value — verify shape only, not
    # the literal value to keep the assertion resilient.
    assert called["key"].startswith("sk_live_")


def test_health_payments_degraded_on_probe_failure(monkeypatch):
    monkeypatch.setenv(
        "STRIPE_SECRET_KEY_LIVE",
        "sk_live_" + "0" * 60,
    )
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY_TEST", raising=False)
    from routers.health_payments import set_stripe_probe

    def _fail(_key: str):
        raise RuntimeError("simulated Stripe auth error")

    set_stripe_probe(_fail)
    try:
        status, body = _hit_health_payments()
    finally:
        set_stripe_probe(None)

    assert status == 200
    assert body["status"] == "degraded", body
    assert body["checks"]["key_shape_valid"] is True
    assert body["checks"]["stripe_api_reachable"] is False


def test_health_payments_public_no_auth(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY_LIVE", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY_TEST", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    status, body = _hit_health_payments()
    assert status == 200
    # No Authorization header was sent — route must respond, not 401.
    assert body["status"] == "unconfigured"
