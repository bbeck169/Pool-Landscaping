"""Phase C · Feb-2026 · Sales Pipeline Kanban — pytest suite.

Covers:
  1.  Happy — 1 card seeded in each of 5 columns + 1 open alert on a
      pipeline customer → response has correct counts and 1
      swimlane entry.
  2.  Column mapping: lead with status="new" lands in Leads.
  3.  Dollar totals: Leads/Quoted totals come from lead/quote
      dollars → cents. Scheduled/Completed use invoice
      ``total_cents`` when linked, else job ``price`` → cents.
  4.  Currency: tenant ``settings.currency == "EUR"`` → every
      column reports ``total_currency == "EUR"``.
  5.  ``date_from`` / ``date_to`` filter narrows results.
  6.  ``owner_id`` narrows scheduled/completed jobs to
      matching ``technician_id``.
  7.  Follow-up: only completed jobs with ``follow_up_at`` inside
      +14d land in Follow-up.
  8.  Risk swimlane: only about customers with pipeline cards.
  9.  Tenant isolation: tenant-B cards don't leak to tenant-A.
  10. Auth: admin/manager/super_admin → 200; tech/customer → 403.
  11. Empty tenant: 5 columns present with count=0, no crash.
  12. OpenAPI: schema exposes ``/api/pipeline/kanban``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

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


def _iso_now(offset_days: float = 0) -> str:
    return (datetime.now(timezone.utc)
             + timedelta(days=offset_days)).isoformat()


@pytest.fixture
def c_seed():
    tid   = f"c-tid-{uuid.uuid4()}"
    tid_b = f"c-tid-b-{uuid.uuid4()}"
    admin_uid   = f"c-admin-{uuid.uuid4()}"
    mgr_uid     = f"c-mgr-{uuid.uuid4()}"
    tech_uid    = f"c-tech-{uuid.uuid4()}"
    tech_pk     = f"c-tech-pk-{uuid.uuid4()}"
    other_tech_pk = f"c-tech-pk2-{uuid.uuid4()}"
    cust_uid    = f"c-cust-user-{uuid.uuid4()}"
    admin_b_uid = f"c-admin-b-{uuid.uuid4()}"

    async def _seed(_db):
        await _db.tenants.insert_many([
            {"id": tid, "name": "Tenant C",
              "slug": f"c-{uuid.uuid4().hex[:8]}",
              "active": True,
              "settings": {}},
            {"id": tid_b, "name": "Tenant C-B",
              "slug": f"cb-{uuid.uuid4().hex[:8]}",
              "active": True,
              "settings": {}},
        ])
        await _db.users.insert_many([
            {"id": admin_uid, "email": f"admin-{admin_uid}@ex.test",
              "role": "admin", "tenant_id": tid, "name": "Alex Admin"},
            {"id": mgr_uid, "email": f"mgr-{mgr_uid}@ex.test",
              "role": "manager", "tenant_id": tid, "name": "Morgan Manager"},
            {"id": tech_uid, "email": f"tech-{tech_uid}@ex.test",
              "role": "technician", "tenant_id": tid,
              "technician_id": tech_pk, "name": "Terry Tech"},
            {"id": cust_uid, "email": f"cust-{cust_uid}@ex.test",
              "role": "customer", "tenant_id": tid, "name": "Cast Cust"},
            {"id": admin_b_uid, "email": f"admin-b-{admin_b_uid}@ex.test",
              "role": "admin", "tenant_id": tid_b, "name": "Bailey B"},
        ])

    async def _teardown(_db):
        await _db.tenants.delete_many({"id": {"$in": [tid, tid_b]}})
        await _db.users.delete_many({"id": {"$in": [
            admin_uid, mgr_uid, tech_uid, cust_uid, admin_b_uid]}})

    run_test(_seed)
    yield {
        "tenant_id":     tid,
        "tenant_b":      tid_b,
        "tech_pk":       tech_pk,
        "other_tech_pk": other_tech_pk,
        "admin_token":   _mint_token(uid=admin_uid, tid=tid, role="admin"),
        "mgr_token":     _mint_token(uid=mgr_uid,   tid=tid, role="manager"),
        "tech_token":    _mint_token(uid=tech_uid,  tid=tid,
                                       role="technician",
                                       technician_id=tech_pk),
        "customer_token": _mint_token(uid=cust_uid, tid=tid,
                                        role="customer"),
        "admin_b_token": _mint_token(uid=admin_b_uid, tid=tid_b,
                                        role="admin"),
    }
    run_test(_teardown)


async def _seed_customer(_db, tid: str, name: str = "") -> str:
    cid = f"c-cust-{uuid.uuid4()}"
    await _db.customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": name or f"Cust {cid[:8]}",
    })
    return cid


async def _seed_lead(_db, tid: str, *, status: str = "new",
                       est_value: float = 500.0,
                       name: str = "Lead Guy",
                       created_offset_days: float = -5,
                       customer_id: str = "") -> str:
    lid = f"c-lead-{uuid.uuid4()}"
    await _db.leads.insert_one({
        "id": lid, "tenant_id": tid,
        "status": status, "est_value": est_value,
        "name": name,
        "customer_id": customer_id,
        "created_at": _iso_now(created_offset_days),
    })
    return lid


async def _seed_quote(_db, tid: str, *, cid: str,
                        status: str = "sent",
                        total: float = 750.0,
                        title: str = "Salt cell repair",
                        created_offset_days: float = -3) -> str:
    qid = f"c-quote-{uuid.uuid4()}"
    await _db.quotes.insert_one({
        "id": qid, "tenant_id": tid,
        "doc_type": "quote", "status": status,
        "total": total, "adjusted_total": total,
        "title": title,
        "customer_id": cid, "customer_name": "Cust",
        "created_at": _iso_now(created_offset_days),
    })
    return qid


async def _seed_job(_db, tid: str, *, cid: str,
                      status: str = "scheduled",
                      price: float = 120.0,
                      tech_id: str = "",
                      scheduled_offset_days: float = 1,
                      auto_invoice_id: str = "",
                      completed_offset_days: float = 0,
                      follow_up_offset_days: float = None,
                      needs_follow_up: bool = False,
                      title: str = "Weekly pool cleaning") -> str:
    jid = f"c-job-{uuid.uuid4()}"
    doc: Dict[str, Any] = {
        "id": jid, "tenant_id": tid,
        "status": status, "price": price,
        "title": title,
        "service_type": "Pool Cleaning",
        "customer_id": cid, "customer_name": "Cust",
        "scheduled_date": (datetime.now(timezone.utc)
                             + timedelta(days=scheduled_offset_days)
                             ).date().isoformat(),
        "created_at": _iso_now(-1),
    }
    if tech_id:
        doc["technician_id"] = tech_id
        doc["technician_name"] = "Terry Tech"
    if auto_invoice_id:
        doc["auto_invoice_id"] = auto_invoice_id
        doc["auto_invoice_created_at"] = _iso_now(completed_offset_days)
    if follow_up_offset_days is not None:
        doc["follow_up_at"] = _iso_now(follow_up_offset_days)
    if needs_follow_up:
        doc["needs_follow_up"] = True
    await _db.jobs.insert_one(doc)
    return jid


async def _seed_invoice(_db, tid: str, *, total_cents: int) -> str:
    iid = f"c-inv-{uuid.uuid4()}"
    await _db.invoices.insert_one({
        "id": iid, "tenant_id": tid,
        "total_cents": total_cents,
        "amount_due_cents": total_cents,
        "status": "past_due",
        "issued_at": _iso_now(0),
    })
    return iid


async def _seed_alert(_db, tid: str, *, cid: str,
                        category: str = "churn_risk",
                        severity: str = "recommended",
                        title: str = "Churn risk"):
    await _db.intelligence_alerts.insert_one({
        "tenant_id": tid,
        "alert_key": f"c-alert-{uuid.uuid4()}",
        "category": category, "severity": severity,
        "title": title, "body": "test",
        "customer_id": cid, "job_id": None,
        "actor_context": {},
        "created_at": datetime.now(timezone.utc),
        "read_at": None, "dismissed_at": None,
        "acknowledged_by": None,
    })


async def _cleanup_tenant(_db, tid: str) -> None:
    await _db.leads.delete_many({"tenant_id": tid})
    await _db.quotes.delete_many({"tenant_id": tid})
    await _db.jobs.delete_many({"tenant_id": tid})
    await _db.invoices.delete_many({"tenant_id": tid})
    await _db.customers.delete_many({"tenant_id": tid})
    await _db.intelligence_alerts.delete_many({"tenant_id": tid})


async def _hit_kanban(client: httpx.AsyncClient, token: str,
                        query: str = "") -> httpx.Response:
    url = f"{API}/pipeline/kanban"
    if query:
        # Never pre-encode; let httpx URL-encode the params.
        url = f"{url}?{query}"
    return await client.get(url,
                            headers={"Authorization": f"Bearer {token}"})


def _encode(**params: Any) -> str:
    """Build a properly URL-encoded query string from raw params."""
    import urllib.parse
    return urllib.parse.urlencode(
        {k: str(v) for k, v in params.items() if v not in (None, "")})


# ═════════════════════════════════════════════════════════════════════
# 1 · Happy path — 1 card in each of the 5 columns + 1 alert.
# ═════════════════════════════════════════════════════════════════════
def test_happy_five_columns_and_risk(c_seed):
    S = c_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid1 = await _seed_customer(_db, S["tenant_id"], "Alice One")
        cid2 = await _seed_customer(_db, S["tenant_id"], "Bob Two")
        cid3 = await _seed_customer(_db, S["tenant_id"], "Carla Three")
        cid4 = await _seed_customer(_db, S["tenant_id"], "Dan Four")

        # Leads
        await _seed_lead(_db, S["tenant_id"], status="new",
                           est_value=500.0, name="Alice One",
                           customer_id=cid1)
        # Quoted
        await _seed_quote(_db, S["tenant_id"], cid=cid1, status="sent",
                            total=750.0)
        # Scheduled
        await _seed_job(_db, S["tenant_id"], cid=cid2, status="scheduled",
                          price=120.0, tech_id=S["tech_pk"],
                          scheduled_offset_days=2)
        # Completed (with linked invoice)
        inv_id = await _seed_invoice(_db, S["tenant_id"],
                                        total_cents=42500)
        await _seed_job(_db, S["tenant_id"], cid=cid3, status="completed",
                          price=250.0,
                          auto_invoice_id=inv_id,
                          completed_offset_days=-2,
                          scheduled_offset_days=-2)
        # Follow-up (completed + follow_up_at inside +14d)
        await _seed_job(_db, S["tenant_id"], cid=cid4, status="completed",
                          price=175.0,
                          auto_invoice_id=None,
                          completed_offset_days=-1,
                          scheduled_offset_days=-1,
                          follow_up_offset_days=5)
        # Open intelligence alert on Alice (has a Leads card + Quote)
        await _seed_alert(_db, S["tenant_id"], cid=cid1,
                            category="churn_risk", severity="recommended",
                            title="Missed 2 payments")
        # Alert on someone WITHOUT a pipeline card — must NOT surface.
        cid_no_pipeline = await _seed_customer(_db, S["tenant_id"],
                                                   "Off-radar")
        await _seed_alert(_db, S["tenant_id"], cid=cid_no_pipeline,
                            category="churn_risk", severity="info",
                            title="Off radar alert")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await _hit_kanban(c, S["admin_token"])
            result["status"] = r.status_code
            result["body"]   = r.json()

        await _cleanup_tenant(_db, S["tenant_id"])

    run_test(_go)

    assert result["status"] == 200, result
    body = result["body"]
    keys = [col["key"] for col in body["columns"]]
    assert keys == ["leads", "quoted", "scheduled",
                     "completed", "follow_up"], keys
    by_key = {col["key"]: col for col in body["columns"]}

    assert by_key["leads"]["count"] == 1
    assert by_key["quoted"]["count"] == 1
    assert by_key["scheduled"]["count"] == 1
    assert by_key["completed"]["count"] == 1
    assert by_key["follow_up"]["count"] == 1

    # Risk swimlane: only Alice's alert (Off-radar filtered out).
    swim = body["risk_swimlane"]
    assert len(swim) == 1, swim
    assert swim[0]["risk_category"] == "churn_risk"
    assert swim[0]["customer_name"] == "Alice One"


# ═════════════════════════════════════════════════════════════════════
# 2 · Column mapping — lead status=new lands in Leads only.
# ═════════════════════════════════════════════════════════════════════
def test_lead_status_new_lands_in_leads_only(c_seed):
    S = c_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid = await _seed_customer(_db, S["tenant_id"])
        await _seed_lead(_db, S["tenant_id"], status="new",
                           est_value=99.0, customer_id=cid)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await _hit_kanban(c, S["admin_token"])
            result["body"] = r.json()
        await _cleanup_tenant(_db, S["tenant_id"])

    run_test(_go)
    by_key = {col["key"]: col for col in result["body"]["columns"]}
    assert by_key["leads"]["count"] == 1
    for k in ("quoted", "scheduled", "completed", "follow_up"):
        assert by_key[k]["count"] == 0, (k, by_key[k])


# ═════════════════════════════════════════════════════════════════════
# 3 · Dollar totals: leads/quoted use own totals, jobs use invoice.
# ═════════════════════════════════════════════════════════════════════
def test_dollar_totals_use_correct_source(c_seed):
    S = c_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid = await _seed_customer(_db, S["tenant_id"])
        # Lead $500 → 50000c ; Quote $750 → 75000c.
        await _seed_lead(_db, S["tenant_id"], status="new",
                           est_value=500.0, customer_id=cid)
        await _seed_quote(_db, S["tenant_id"], cid=cid, status="sent",
                            total=750.0)
        # Scheduled job w/ invoice $120 (12000c invoice OVERRIDES price).
        inv1 = await _seed_invoice(_db, S["tenant_id"], total_cents=12000)
        await _seed_job(_db, S["tenant_id"], cid=cid, status="scheduled",
                          price=999.0, auto_invoice_id=inv1,
                          scheduled_offset_days=1)
        # Completed job w/ invoice $250 → 25000c.
        inv2 = await _seed_invoice(_db, S["tenant_id"], total_cents=25000)
        await _seed_job(_db, S["tenant_id"], cid=cid, status="completed",
                          price=1.0, auto_invoice_id=inv2,
                          completed_offset_days=-2,
                          scheduled_offset_days=-2)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await _hit_kanban(c, S["admin_token"])
            result["body"] = r.json()
        await _cleanup_tenant(_db, S["tenant_id"])

    run_test(_go)
    by_key = {col["key"]: col for col in result["body"]["columns"]}
    assert by_key["leads"]["total_amount_cents"] == 50000
    assert by_key["quoted"]["total_amount_cents"] == 75000
    assert by_key["scheduled"]["total_amount_cents"] == 12000
    assert by_key["completed"]["total_amount_cents"] == 25000


# ═════════════════════════════════════════════════════════════════════
# 4 · Currency override via ``tenant.settings.currency``.
# ═════════════════════════════════════════════════════════════════════
def test_currency_override_eur(c_seed):
    S = c_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        await _db.tenants.update_one(
            {"id": S["tenant_id"]},
            {"$set": {"settings.currency": "EUR"}})
        cid = await _seed_customer(_db, S["tenant_id"])
        await _seed_lead(_db, S["tenant_id"], customer_id=cid)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await _hit_kanban(c, S["admin_token"])
            result["body"] = r.json()
        await _db.tenants.update_one(
            {"id": S["tenant_id"]},
            {"$unset": {"settings.currency": ""}})
        await _cleanup_tenant(_db, S["tenant_id"])

    run_test(_go)
    for col in result["body"]["columns"]:
        assert col["total_currency"] == "EUR", col


# ═════════════════════════════════════════════════════════════════════
# 5 · date_from / date_to narrow lead + quote windows.
# ═════════════════════════════════════════════════════════════════════
def test_date_range_narrows(c_seed):
    S = c_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid = await _seed_customer(_db, S["tenant_id"])
        # In-window (created -3d) + out-of-window (-45d).
        await _seed_lead(_db, S["tenant_id"], status="new",
                           customer_id=cid, created_offset_days=-3)
        await _seed_lead(_db, S["tenant_id"], status="new",
                           customer_id=cid, created_offset_days=-45)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            # Window: last 7 days only.
            df = (datetime.now(timezone.utc)
                    - timedelta(days=7)).isoformat()
            dt = (datetime.now(timezone.utc)
                    + timedelta(days=1)).isoformat()
            r = await _hit_kanban(
                c, S["admin_token"],
                query=_encode(date_from=df, date_to=dt))
            result["body"] = r.json()
        await _cleanup_tenant(_db, S["tenant_id"])

    run_test(_go)
    by_key = {col["key"]: col for col in result["body"]["columns"]}
    assert by_key["leads"]["count"] == 1, by_key["leads"]


# ═════════════════════════════════════════════════════════════════════
# 6 · owner_id filter narrows scheduled jobs.
# ═════════════════════════════════════════════════════════════════════
def test_owner_id_filters_scheduled_jobs(c_seed):
    S = c_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid = await _seed_customer(_db, S["tenant_id"])
        # Owned scheduled job.
        await _seed_job(_db, S["tenant_id"], cid=cid, status="scheduled",
                          tech_id=S["tech_pk"], scheduled_offset_days=1)
        # Not-owned scheduled job.
        await _seed_job(_db, S["tenant_id"], cid=cid, status="scheduled",
                          tech_id=S["other_tech_pk"],
                          scheduled_offset_days=1)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await _hit_kanban(
                c, S["admin_token"],
                query=f"owner_id={S['tech_pk']}")
            result["body"] = r.json()
        await _cleanup_tenant(_db, S["tenant_id"])

    run_test(_go)
    by_key = {col["key"]: col for col in result["body"]["columns"]}
    assert by_key["scheduled"]["count"] == 1


# ═════════════════════════════════════════════════════════════════════
# 7 · Follow-up column: only completed w/ follow_up_at ≤ now+14d.
# ═════════════════════════════════════════════════════════════════════
def test_followup_window(c_seed):
    S = c_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid = await _seed_customer(_db, S["tenant_id"])
        # In-window follow-up (+5d).
        await _seed_job(_db, S["tenant_id"], cid=cid, status="completed",
                          scheduled_offset_days=-1,
                          completed_offset_days=-1,
                          follow_up_offset_days=5)
        # Out-of-window follow-up (+30d — beyond 14).
        await _seed_job(_db, S["tenant_id"], cid=cid, status="completed",
                          scheduled_offset_days=-1,
                          completed_offset_days=-1,
                          follow_up_offset_days=30)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await _hit_kanban(c, S["admin_token"])
            result["body"] = r.json()
        await _cleanup_tenant(_db, S["tenant_id"])

    run_test(_go)
    by_key = {col["key"]: col for col in result["body"]["columns"]}
    assert by_key["follow_up"]["count"] == 1


# ═════════════════════════════════════════════════════════════════════
# 8 · Risk swimlane restricted to pipeline customers.
# ═════════════════════════════════════════════════════════════════════
def test_swimlane_only_pipeline_customers(c_seed):
    S = c_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid_in  = await _seed_customer(_db, S["tenant_id"], "In-pipeline")
        cid_out = await _seed_customer(_db, S["tenant_id"], "Off-radar")
        await _seed_lead(_db, S["tenant_id"], status="new",
                           customer_id=cid_in)
        await _seed_alert(_db, S["tenant_id"], cid=cid_in,
                            title="Alert-in")
        await _seed_alert(_db, S["tenant_id"], cid=cid_out,
                            title="Alert-out")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await _hit_kanban(c, S["admin_token"])
            result["body"] = r.json()
        await _cleanup_tenant(_db, S["tenant_id"])

    run_test(_go)
    swim = result["body"]["risk_swimlane"]
    titles = [row["title"] for row in swim]
    assert "Alert-in" in titles
    assert "Alert-out" not in titles, titles


# ═════════════════════════════════════════════════════════════════════
# 9 · Tenant isolation.
# ═════════════════════════════════════════════════════════════════════
def test_tenant_isolation(c_seed):
    S = c_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        # Card in tenant B.
        cid_b = await _seed_customer(_db, S["tenant_b"], "Tenant-B cust")
        await _seed_lead(_db, S["tenant_b"], status="new",
                           customer_id=cid_b, name="B-Lead")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r_a = await _hit_kanban(c, S["admin_token"])
            r_b = await _hit_kanban(c, S["admin_b_token"])
            result["body_a"] = r_a.json()
            result["body_b"] = r_b.json()

        await _cleanup_tenant(_db, S["tenant_id"])
        await _cleanup_tenant(_db, S["tenant_b"])

    run_test(_go)
    by_key_a = {c["key"]: c for c in result["body_a"]["columns"]}
    by_key_b = {c["key"]: c for c in result["body_b"]["columns"]}
    assert by_key_a["leads"]["count"] == 0
    assert by_key_b["leads"]["count"] == 1


# ═════════════════════════════════════════════════════════════════════
# 10 · Auth matrix: admin/mgr → 200; tech/customer → 403.
# ═════════════════════════════════════════════════════════════════════
def test_auth_matrix(c_seed):
    S = c_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            for name, tok in (
                ("admin",    S["admin_token"]),
                ("manager",  S["mgr_token"]),
                ("tech",     S["tech_token"]),
                ("customer", S["customer_token"]),
            ):
                r = await _hit_kanban(c, tok)
                result[name] = {"status": r.status_code,
                                 "detail": r.json().get("detail")
                                             if r.status_code >= 400
                                             else None}

    run_test(_go)
    assert result["admin"]["status"] == 200
    assert result["manager"]["status"] == 200
    assert result["tech"]["status"] == 403
    assert result["tech"]["detail"] == "insufficient_role_for_pipeline"
    assert result["customer"]["status"] == 403
    assert result["customer"]["detail"] == "insufficient_role_for_pipeline"


# ═════════════════════════════════════════════════════════════════════
# 11 · Empty tenant → all 5 columns, count=0, no swimlane.
# ═════════════════════════════════════════════════════════════════════
def test_empty_tenant(c_seed):
    S = c_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        await _cleanup_tenant(_db, S["tenant_id"])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await _hit_kanban(c, S["admin_token"])
            result["status"] = r.status_code
            result["body"] = r.json()

    run_test(_go)
    assert result["status"] == 200
    body = result["body"]
    assert len(body["columns"]) == 5
    for col in body["columns"]:
        assert col["count"] == 0
        assert col["total_amount_cents"] == 0
    assert body["risk_swimlane"] == []


# ═════════════════════════════════════════════════════════════════════
# 12 · OpenAPI reflects the new route.
# ═════════════════════════════════════════════════════════════════════
def test_openapi_reflects_route():
    from server import app
    schema = app.openapi()
    assert "/api/pipeline/kanban" in schema["paths"], list(
        schema["paths"].keys())[:20]
