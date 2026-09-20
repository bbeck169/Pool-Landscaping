"""Phase A5 · Feb-2026 · Proactive Intelligence — Tech Smart Brief
pytest suite.

Covers:
  1.  Happy — assigned tech opens their job → full brief with
      customer, special_access, last_visits (up to 3),
      open_intelligence_alerts.
  2.  ``last_visits`` limited to 3, sorted DESC by ``completed_at``.
  3.  ``open_intelligence_alerts`` filtered by customer_id +
      dismissed_at=None, limited to 5.
  4.  Auth — another (non-assigned) tech → 403.
  5.  Auth — admin → 200 (always allowed).
  6.  Auth — customer role → 403.
  7.  Cross-tenant — tenant-A admin requesting a tenant-B job → 404
      ``job_not_found`` (do not disclose existence).
  8.  Missing job → 404.
  9.  Job with no prior visits → empty ``last_visits`` array, no
      crash.
  10. Job with no intelligence alerts → empty
      ``open_intelligence_alerts`` array, no crash.
  11. Special-access dict is present with ``None`` / ``False``
      defaults when the customer has none configured — never
      omitted.
  12. A4 nit fix — ``POST /agreements/{missing_id}/resend-renewal-email``
      → 404 ``agreement_not_found`` (was 200/{ok:false} before).
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
                 email: str = "x@x",
                 technician_id: str = "") -> str:
    from config import JWT_SECRET
    payload = {
        "sub":       uid,
        "email":     email,
        "role":      role,
        "tenant_id": tid,
        "exp":       int((datetime.now(timezone.utc)
                            + timedelta(hours=1)).timestamp()),
    }
    if technician_id:
        payload["technician_id"] = technician_id
    return _jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def a5_seed():
    tid   = f"a5-tid-{uuid.uuid4()}"
    tid_b = f"a5-tid-b-{uuid.uuid4()}"
    admin_uid   = f"a5-admin-{uuid.uuid4()}"
    tech_uid    = f"a5-tech-{uuid.uuid4()}"
    tech_pk     = f"a5-tech-pk-{uuid.uuid4()}"
    other_tech_uid = f"a5-tech2-{uuid.uuid4()}"
    other_tech_pk  = f"a5-tech2-pk-{uuid.uuid4()}"
    customer_uid   = f"a5-cust-user-{uuid.uuid4()}"

    async def _seed(_db):
        from services.intelligence.alerts import ensure_indexes
        await ensure_indexes()
        await _db.tenants.insert_many([
            {"id": tid,   "name": "Tenant A5",   "slug": f"a5-{uuid.uuid4().hex[:8]}",
             "active": True, "default_locale": "en"},
            {"id": tid_b, "name": "Tenant A5 B", "slug": f"a5b-{uuid.uuid4().hex[:8]}",
             "active": True},
        ])
        await _db.users.insert_many([
            {"id": admin_uid, "email": f"admin-{admin_uid}@ex.test",
             "role": "admin", "tenant_id": tid, "name": "Alex Admin"},
            {"id": tech_uid, "email": f"tech-{tech_uid}@ex.test",
             "role": "technician", "tenant_id": tid,
             "technician_id": tech_pk, "name": "Terry Tech"},
            {"id": other_tech_uid, "email": f"other-{other_tech_uid}@ex.test",
             "role": "technician", "tenant_id": tid,
             "technician_id": other_tech_pk, "name": "Other Tech"},
            {"id": customer_uid, "email": f"cust-{customer_uid}@ex.test",
             "role": "customer", "tenant_id": tid,
             "name": "Portal Cust"},
        ])

    async def _teardown(_db):
        await _db.tenants.delete_many({"id": {"$in": [tid, tid_b]}})
        await _db.users.delete_many({"id": {"$in": [
            admin_uid, tech_uid, other_tech_uid, customer_uid]}})
        await _db.intelligence_alerts.delete_many({
            "tenant_id": {"$in": [tid, tid_b]}})

    run_test(_seed)
    yield {
        "tenant_id":       tid,
        "tenant_b":        tid_b,
        "tech_pk":         tech_pk,
        "admin_token":     _mint_token(uid=admin_uid, tid=tid,
                                          role="admin"),
        "tech_token":      _mint_token(uid=tech_uid,  tid=tid,
                                          role="technician",
                                          technician_id=tech_pk),
        "other_tech_token": _mint_token(uid=other_tech_uid, tid=tid,
                                          role="technician",
                                          technician_id=other_tech_pk),
        "customer_token":  _mint_token(uid=customer_uid, tid=tid,
                                          role="customer"),
    }
    run_test(_teardown)


async def _mk_customer(_db, tid: str, **extra) -> str:
    cid = f"a5-cust-{uuid.uuid4()}"
    doc: Dict[str, Any] = {
        "id": cid, "tenant_id": tid,
        "name": extra.pop("name", f"Cust {cid[:8]}"),
        "phone": extra.pop("phone", "+16025551212"),
        "address": extra.pop("address", "123 Palm Way, Phoenix AZ"),
        "service_lat": extra.pop("service_lat", 33.5),
        "service_lng": extra.pop("service_lng", -112.1),
    }
    doc.update(extra)
    await _db.customers.insert_one(doc)
    return cid


async def _mk_job(_db, tid: str, cid: str, tech_pk: str = "") -> str:
    jid = f"a5-job-{uuid.uuid4()}"
    doc: Dict[str, Any] = {
        "id": jid, "tenant_id": tid, "customer_id": cid,
        "service_type": "Pool Cleaning",
        "duration_minutes": 45,
        "status": "scheduled",
    }
    if tech_pk:
        doc["technician_id"] = tech_pk
    await _db.jobs.insert_one(doc)
    return jid


async def _mk_report(_db, *, tid: str, jid: str, tech_pk: str = "",
                      submitted_at: datetime,
                      readings: Dict[str, float] | None = None,
                      note: str = "") -> str:
    rid = f"a5-sr-{uuid.uuid4()}"
    await _db.service_reports.insert_one({
        "id": rid, "tenant_id": tid, "job_id": jid,
        "tech_id": tech_pk or None,
        "submitted_at": submitted_at,
        "chemical_readings": [
            {"key": k, "name": k, "value": v, "unit": ""}
            for k, v in (readings or {}).items()
        ],
        "notes": note,
    })
    return rid


async def _cleanup(_db, tid: str, cid: str) -> None:
    jobs = await _db.jobs.find(
        {"customer_id": cid, "tenant_id": tid},
        {"_id": 0, "id": 1}).to_list(500)
    jids = [j["id"] for j in jobs if j.get("id")]
    if jids:
        await _db.service_reports.delete_many(
            {"job_id": {"$in": jids}})
    await _db.jobs.delete_many({"customer_id": cid})
    await _db.customers.delete_many({"id": cid})
    await _db.intelligence_alerts.delete_many({
        "customer_id": cid, "tenant_id": tid})


async def _hit(client: httpx.AsyncClient, token: str, jid: str):
    return await client.get(
        f"{API}/jobs/{jid}/smart-brief",
        headers={"Authorization": f"Bearer {token}"})


# ═════════════════════════════════════════════════════════════════════
# 1 · Happy path — assigned tech returns the full brief.
# ═════════════════════════════════════════════════════════════════════
def test_assigned_tech_happy_path(a5_seed):
    S = a5_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid = await _mk_customer(
            _db, S["tenant_id"], name="Priya Patel",
            phone="+14805551212", gate_code="1234#",
            service_notes="Backyard access via side gate.",
            dog_on_property=True, dog_notes="Buddy — friendly Lab",
        )
        result["cid"] = cid
        jid = await _mk_job(_db, S["tenant_id"], cid,
                              tech_pk=S["tech_pk"])
        result["jid"] = jid

        # Two past visits — 3 days ago (newest) and 10 days ago.
        old_jid_1 = await _mk_job(_db, S["tenant_id"], cid)
        old_jid_2 = await _mk_job(_db, S["tenant_id"], cid)
        await _mk_report(
            _db, tid=S["tenant_id"], jid=old_jid_1,
            tech_pk=S["tech_pk"],
            submitted_at=datetime.now(timezone.utc) - timedelta(days=3),
            readings={"salt": 3100, "ph": 7.4},
            note="Chlorine tab dispenser replaced.")
        await _mk_report(
            _db, tid=S["tenant_id"], jid=old_jid_2,
            tech_pk=S["tech_pk"],
            submitted_at=datetime.now(timezone.utc) - timedelta(days=10),
            readings={"salt": 3200, "ph": 7.5, "free_chlorine": 2.0},
            note="")

        # One open intelligence alert (dismissed=None).
        from services.intelligence.alerts import emit_alert
        await emit_alert(
            S["tenant_id"], category="chemistry_upsell",
            severity="recommended",
            alert_key=f"a5-test-{uuid.uuid4()}",
            title="High salt for 3 visits",
            body="Readings out of band",
            customer_id=cid, job_id=old_jid_1,
            actor_context={"measurement": "salt"})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            r = await _hit(client, S["tech_token"], jid)
            result["status"] = r.status_code
            result["body"] = r.json() if r.status_code == 200 else r.text
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)

    assert result["status"] == 200, result
    body = result["body"]
    # Contract sanity — every top-level key present.
    for k in ("job_id", "customer_id", "customer", "special_access",
                "last_visits", "open_intelligence_alerts"):
        assert k in body, (k, list(body.keys()))
    # Customer sub-doc.
    assert body["customer"]["display_name"] == "Priya Patel"
    assert body["customer"]["phone"] == "+14805551212"
    assert body["customer"]["address_line"].startswith("123 Palm Way")
    assert body["customer"]["coordinates"] == {"lat": 33.5, "lng": -112.1}
    # Special access — canonical + defaults.
    sa = body["special_access"]
    assert sa["gate_code"] == "1234#"
    assert sa["dog_on_property"] is True
    assert sa["dog_notes"] == "Buddy — friendly Lab"
    assert sa["other_notes"] == "Backyard access via side gate."
    assert sa["key_location"] is None
    # Last visits — 2 rendered, DESC.
    lv = body["last_visits"]
    assert len(lv) == 2
    assert lv[0]["chemistry_snapshot"]["salt"] == 3100
    assert lv[0]["chemistry_snapshot"]["ph"] == 7.4
    # The 10-day-old visit was captured with free_chlorine → chlorine.
    assert lv[1]["chemistry_snapshot"]["chlorine"] == 2.0
    # Newest visit has a note; older one doesn't.
    assert lv[0]["notes"] and lv[0]["notes"][0]["body"].startswith(
        "Chlorine tab")
    assert lv[1]["notes"] == []
    # Notes attach the tech display name.
    assert lv[0]["notes"][0]["author_display_name"] == "Terry Tech"
    # Alerts.
    alerts = body["open_intelligence_alerts"]
    assert len(alerts) == 1
    assert alerts[0]["category"] == "chemistry_upsell"
    assert alerts[0]["severity"] == "recommended"


# ═════════════════════════════════════════════════════════════════════
# 2 · last_visits limited to 3, DESC by completed_at.
# ═════════════════════════════════════════════════════════════════════
def test_last_visits_limit_3_desc(a5_seed):
    S = a5_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        jid = await _mk_job(_db, S["tenant_id"], cid,
                              tech_pk=S["tech_pk"])
        for i in range(5):
            old = await _mk_job(_db, S["tenant_id"], cid)
            await _mk_report(
                _db, tid=S["tenant_id"], jid=old,
                submitted_at=datetime.now(timezone.utc)
                              - timedelta(days=i + 1),
                readings={"salt": 3000 + i})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            r = await _hit(client, S["tech_token"], jid)
            result["body"] = r.json()
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)
    lv = result["body"]["last_visits"]
    assert len(lv) == 3
    ts = [row["completed_at"] for row in lv]
    assert ts == sorted(ts, reverse=True), ts


# ═════════════════════════════════════════════════════════════════════
# 3 · open_intelligence_alerts filtered by customer_id + limit 5.
# ═════════════════════════════════════════════════════════════════════
def test_alerts_filtered_and_limited(a5_seed):
    S = a5_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid_a = await _mk_customer(_db, S["tenant_id"])
        cid_other = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid_a
        result["cid_other"] = cid_other
        jid = await _mk_job(_db, S["tenant_id"], cid_a,
                              tech_pk=S["tech_pk"])
        from services.intelligence.alerts import emit_alert
        # 7 alerts on our customer — 6 open + 1 dismissed.
        for i in range(6):
            await emit_alert(
                S["tenant_id"], category="renewal_due",
                severity="recommended",
                alert_key=f"a5-open-{i}-{uuid.uuid4()}",
                title=f"Open alert #{i}", body="body",
                customer_id=cid_a)
        _dismissed_key = f"a5-dismissed-{uuid.uuid4()}"
        _dismissed_inserted, _dismissed_doc = await emit_alert(
            S["tenant_id"], category="renewal_due",
            severity="recommended",
            alert_key=_dismissed_key,
            title="Dismissed alert", body="body",
            customer_id=cid_a)
        # Alerts don't carry a UUID ``id`` — the sentinel row is
        # located by its unique ``alert_key`` for the dismissal
        # update.
        await _db.intelligence_alerts.update_one(
            {"tenant_id": S["tenant_id"],
             "alert_key": _dismissed_key},
            {"$set": {"dismissed_at": datetime.now(timezone.utc)}})
        # Also seed one for the OTHER customer — must not leak.
        await emit_alert(
            S["tenant_id"], category="renewal_due",
            severity="recommended",
            alert_key=f"a5-other-{uuid.uuid4()}",
            title="Other customer alert", body="body",
            customer_id=cid_other)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            r = await _hit(client, S["tech_token"], jid)
            result["body"] = r.json()
        await _cleanup(_db, S["tenant_id"], cid_a)
        await _cleanup(_db, S["tenant_id"], cid_other)

    run_test(_go)
    alerts = result["body"]["open_intelligence_alerts"]
    # Only 6 are OPEN, cap at 5.
    assert len(alerts) == 5
    # None are for the other customer.
    titles = [a["title"] for a in alerts]
    assert all("Other customer alert" not in t for t in titles), titles
    # None are dismissed.
    assert all("Dismissed alert" not in t for t in titles), titles


# ═════════════════════════════════════════════════════════════════════
# 4 · Non-assigned tech → 403.
# ═════════════════════════════════════════════════════════════════════
def test_non_assigned_tech_forbidden(a5_seed):
    S = a5_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        jid = await _mk_job(_db, S["tenant_id"], cid,
                              tech_pk=S["tech_pk"])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            r = await _hit(client, S["other_tech_token"], jid)
            result["status"] = r.status_code
            result["detail"] = (r.json() or {}).get("detail")
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["status"] == 403
    assert result["detail"] == "insufficient_role_for_brief"


# ═════════════════════════════════════════════════════════════════════
# 5 · Admin allowed regardless of assignment.
# ═════════════════════════════════════════════════════════════════════
def test_admin_always_allowed(a5_seed):
    S = a5_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        jid = await _mk_job(_db, S["tenant_id"], cid)  # NO tech
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            r = await _hit(client, S["admin_token"], jid)
            result["status"] = r.status_code
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["status"] == 200


# ═════════════════════════════════════════════════════════════════════
# 6 · Customer role → 403.
# ═════════════════════════════════════════════════════════════════════
def test_customer_role_forbidden(a5_seed):
    S = a5_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        jid = await _mk_job(_db, S["tenant_id"], cid,
                              tech_pk=S["tech_pk"])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            r = await _hit(client, S["customer_token"], jid)
            result["status"] = r.status_code
            result["detail"] = (r.json() or {}).get("detail")
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["status"] == 403
    assert result["detail"] == "insufficient_role_for_brief"


# ═════════════════════════════════════════════════════════════════════
# 7 · Cross-tenant → 404 (do not disclose existence).
# ═════════════════════════════════════════════════════════════════════
def test_cross_tenant_returns_404(a5_seed):
    S = a5_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        # Job under TENANT B.
        cid_b = await _mk_customer(_db, S["tenant_b"])
        result["cid_b"] = cid_b
        jid_b = await _mk_job(_db, S["tenant_b"], cid_b)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            # Tenant-A admin asks for tenant-B job → should 404.
            r = await _hit(client, S["admin_token"], jid_b)
            result["status"] = r.status_code
            result["detail"] = (r.json() or {}).get("detail")
        await _cleanup(_db, S["tenant_b"], cid_b)

    run_test(_go)
    assert result["status"] == 404
    assert result["detail"] == "job_not_found"


# ═════════════════════════════════════════════════════════════════════
# 8 · Missing job → 404.
# ═════════════════════════════════════════════════════════════════════
def test_missing_job_returns_404(a5_seed):
    S = a5_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            r = await _hit(client, S["admin_token"], "not-a-real-id")
            result["status"] = r.status_code
            result["detail"] = (r.json() or {}).get("detail")

    run_test(_go)
    assert result["status"] == 404
    assert result["detail"] == "job_not_found"


# ═════════════════════════════════════════════════════════════════════
# 9 · Job with no prior visits → empty last_visits, no crash.
# ═════════════════════════════════════════════════════════════════════
def test_job_with_no_prior_visits(a5_seed):
    S = a5_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        jid = await _mk_job(_db, S["tenant_id"], cid,
                              tech_pk=S["tech_pk"])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            r = await _hit(client, S["tech_token"], jid)
            result["body"] = r.json()
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["body"]["last_visits"] == []


# ═════════════════════════════════════════════════════════════════════
# 10 · Job with no intelligence alerts → empty list, no crash.
# ═════════════════════════════════════════════════════════════════════
def test_job_with_no_alerts(a5_seed):
    S = a5_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        jid = await _mk_job(_db, S["tenant_id"], cid,
                              tech_pk=S["tech_pk"])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            r = await _hit(client, S["tech_token"], jid)
            result["body"] = r.json()
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["body"]["open_intelligence_alerts"] == []


# ═════════════════════════════════════════════════════════════════════
# 11 · Special-access defaults — None / False when unconfigured.
# ═════════════════════════════════════════════════════════════════════
def test_special_access_defaults_present(a5_seed):
    S = a5_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        jid = await _mk_job(_db, S["tenant_id"], cid,
                              tech_pk=S["tech_pk"])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            r = await _hit(client, S["tech_token"], jid)
            result["body"] = r.json()
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)
    sa = result["body"]["special_access"]
    # Keys always present, values are None / False when missing.
    assert sa["gate_code"] is None
    assert sa["key_location"] is None
    assert sa["dog_on_property"] is False
    assert sa["dog_notes"] is None
    assert sa["other_notes"] is None


# ═════════════════════════════════════════════════════════════════════
# 12 · A4 nit fix — missing agreement returns 404.
# ═════════════════════════════════════════════════════════════════════
def test_a4_resend_missing_agreement_returns_404(a5_seed):
    S = a5_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            r = await client.post(
                f"{API}/agreements/does-not-exist/resend-renewal-email",
                headers={"Authorization": f"Bearer {S['admin_token']}"},
                json={})
            result["status"] = r.status_code
            result["detail"] = (r.json() or {}).get("detail")

    run_test(_go)
    assert result["status"] == 404
    assert result["detail"] == "agreement_not_found"
