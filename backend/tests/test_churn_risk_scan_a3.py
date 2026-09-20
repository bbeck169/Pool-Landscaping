"""Phase A3 · Feb-2026 · Proactive Intelligence — churn-risk scan
pytest suite.

Covers:
  1.  Signal 1 — customer with 2 ``past_due`` invoices → 1 alert,
      severity=urgent, ``actor_context.invoice_count=2``, total
      populated in cents.
  2.  Signal 1 — customer with 1 ``past_due`` invoice → NO alert.
  3.  Signal 1 — mix of 1 ``past_due`` + 1 ``overdue`` counts as 2
      → alert emits.
  4.  Signal 1 — dedup: rerun with same count → 0 new emits, +1
      deduped.
  5.  Signal 1 — count shift 2 → 3 emits a new alert with the new
      count in the key.
  6.  Signal 2 — recurring job cancelled by customer → 1 alert,
      severity=recommended, ``actor_context.signal=recurring_cancelled``.
  7.  Signal 2 — non-recurring cancelled job → NO alert.
  8.  Signal 2 — ``cancelled_by_office`` on a recurring job → NO
      alert (customer-initiated only).
  9.  Signal 2 — dedup: rerun same job → 0 new emits.
  10. Combined: customer with 2 unpaid AND a cancelled recurring
      series → 2 alerts (one per signal).
  11. Tenant isolation: signals under tenant B don't emit alerts
      under tenant A.
  12. ``POST /scans/churn-risk/run-now`` requires admin /
      super_admin; tech → 403 ``insufficient_role_for_alerts``.
"""
from __future__ import annotations

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
                 email: str = "x@x") -> str:
    from config import JWT_SECRET
    payload = {
        "sub": uid, "email": email, "role": role, "tenant_id": tid,
        "exp": int((datetime.now(timezone.utc)
                     + timedelta(hours=1)).timestamp()),
    }
    return _jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def a3_seed():
    tid   = f"a3-tid-{uuid.uuid4()}"
    tid_b = f"a3-tid-b-{uuid.uuid4()}"
    admin_uid = f"a3-admin-{uuid.uuid4()}"
    tech_uid  = f"a3-tech-{uuid.uuid4()}"

    async def _seed(_db):
        from services.intelligence.alerts import ensure_indexes
        await ensure_indexes()
        await _db.tenants.insert_many([
            {"id": tid, "name": "Tenant A3",
             "slug": f"a3-{uuid.uuid4().hex[:8]}", "active": True},
            {"id": tid_b, "name": "Tenant A3 B",
             "slug": f"a3b-{uuid.uuid4().hex[:8]}", "active": True},
        ])
        await _db.users.insert_many([
            {"id": admin_uid, "email": f"admin-{admin_uid}@ex.test",
             "role": "admin", "tenant_id": tid, "name": "Alex"},
            {"id": tech_uid, "email": f"tech-{tech_uid}@ex.test",
             "role": "technician", "tenant_id": tid, "name": "Tammy"},
        ])

    async def _teardown(_db):
        await _db.tenants.delete_many({"id": {"$in": [tid, tid_b]}})
        await _db.users.delete_many({"id": {"$in": [admin_uid, tech_uid]}})
        await _db.intelligence_alerts.delete_many({
            "tenant_id": {"$in": [tid, tid_b]}})

    run_test(_seed)
    yield {
        "tenant_id":   tid,
        "tenant_b":    tid_b,
        "admin_token": _mint_token(uid=admin_uid, tid=tid, role="admin",
                                     email=f"admin-{admin_uid}@ex.test"),
        "tech_token":  _mint_token(uid=tech_uid, tid=tid, role="technician",
                                     email=f"tech-{tech_uid}@ex.test"),
    }
    run_test(_teardown)


async def _mk_customer(_db, tid: str, name: str = "") -> str:
    cid = f"a3-cust-{uuid.uuid4()}"
    await _db.customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": name or f"Cust {cid[:8]}",
    })
    return cid


async def _mk_invoice(
    _db, *, tid: str, cid: str, status: str,
    amount_cents: int, days_ago: int,
) -> str:
    iid = f"a3-inv-{uuid.uuid4()}"
    issued = datetime.now(timezone.utc) - timedelta(days=days_ago)
    await _db.invoices.insert_one({
        "id":               iid,
        "tenant_id":        tid,
        "customer_id":      cid,
        "status":           status,
        "amount_due_cents": amount_cents,
        "total_cents":      amount_cents,
        "issued_at":        issued.isoformat(),
        "created_at":       issued.isoformat(),
        "due_date":         (issued + timedelta(days=15)).isoformat(),
        "invoice_number":   f"INV-{iid[-6:].upper()}",
    })
    return iid


async def _mk_recurring_job(
    _db, *, tid: str, cid: str, status: str,
    service: str = "Weekly Pool Cleaning",
    is_recurring: bool = True,
) -> str:
    jid = f"a3-job-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    await _db.jobs.insert_one({
        "id":                  jid,
        "tenant_id":           tid,
        "customer_id":         cid,
        "service_type":        service,
        "status":              status,
        "is_recurring":        is_recurring,
        "cancelled_at":        now.isoformat(),
        "cancellation_reason": "Customer request",
        "scheduled_date":      now.isoformat(),
    })
    return jid


async def _cleanup_all(_db, tid: str, cid: str) -> None:
    await _db.invoices.delete_many({"customer_id": cid})
    await _db.jobs.delete_many({"customer_id": cid})
    await _db.customers.delete_many({"id": cid})
    await _db.intelligence_alerts.delete_many({"customer_id": cid,
                                                 "tenant_id": tid})


# ═════════════════════════════════════════════════════════════════════
# 1 · Signal 1 — 2 past_due invoices → 1 urgent alert.
# ═════════════════════════════════════════════════════════════════════
def test_two_past_due_emits_urgent_missed_payments_alert(a3_seed):
    S = a3_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.churn_risk_scan import (
            run_churn_risk_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"], "Robert Blake")
        result["cid"] = cid
        await _mk_invoice(_db, tid=S["tenant_id"], cid=cid,
                            status="past_due", amount_cents=15000,
                            days_ago=45)
        await _mk_invoice(_db, tid=S["tenant_id"], cid=cid,
                            status="past_due", amount_cents=20000,
                            days_ago=20)
        result["summary"] = await run_churn_risk_scan(
            tenant_id=S["tenant_id"])
        result["alert"] = await _db.intelligence_alerts.find_one({
            "tenant_id":   S["tenant_id"],
            "customer_id": cid,
            "category":    "churn_risk",
        })
        await _cleanup_all(_db, S["tenant_id"], cid)

    run_test(_go)
    summary = result["summary"]
    assert summary["alerts_emitted"] == 1, summary
    assert summary["by_signal"]["missed_payments"] == 1
    assert summary["by_signal"]["recurring_cancelled"] == 0
    alert = result["alert"]
    assert alert is not None
    assert alert["severity"] == "urgent"
    assert alert["category"] == "churn_risk"
    ctx = alert["actor_context"]
    assert ctx["signal"] == "missed_payments"
    assert ctx["invoice_count"] == 2
    assert ctx["total_amount_cents"] == 35000
    # ``oldest_days_overdue`` = ref − due_date, where due_date =
    # issued + 15d. Oldest invoice issued 45d ago ⇒ ~30d past due.
    assert ctx["oldest_days_overdue"] >= 25
    assert len(ctx["invoice_ids"]) == 2
    # Title contains the customer name.
    assert "Robert Blake" in alert["title"]
    # Body contains the currency-formatted total.
    assert "$350.00" in alert["body"]


# ═════════════════════════════════════════════════════════════════════
# 2 · Signal 1 — 1 past_due invoice → NO alert.
# ═════════════════════════════════════════════════════════════════════
def test_single_past_due_emits_nothing(a3_seed):
    S = a3_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.churn_risk_scan import (
            run_churn_risk_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        await _mk_invoice(_db, tid=S["tenant_id"], cid=cid,
                            status="past_due", amount_cents=10000,
                            days_ago=10)
        result["summary"] = await run_churn_risk_scan(
            tenant_id=S["tenant_id"])
        result["alert"] = await _db.intelligence_alerts.find_one({
            "tenant_id":   S["tenant_id"], "customer_id": cid,
            "category":    "churn_risk"})
        await _cleanup_all(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["summary"]["alerts_emitted"] == 0
    assert result["alert"] is None


# ═════════════════════════════════════════════════════════════════════
# 3 · Signal 1 — mixed past_due + overdue counts as 2.
# ═════════════════════════════════════════════════════════════════════
def test_mixed_past_due_and_overdue_emits_alert(a3_seed):
    S = a3_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.churn_risk_scan import (
            run_churn_risk_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        await _mk_invoice(_db, tid=S["tenant_id"], cid=cid,
                            status="past_due", amount_cents=8000,
                            days_ago=30)
        await _mk_invoice(_db, tid=S["tenant_id"], cid=cid,
                            status="overdue", amount_cents=9000,
                            days_ago=60)
        result["summary"] = await run_churn_risk_scan(
            tenant_id=S["tenant_id"])
        result["alert"] = await _db.intelligence_alerts.find_one({
            "tenant_id":   S["tenant_id"], "customer_id": cid,
            "category":    "churn_risk"})
        await _cleanup_all(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["summary"]["alerts_emitted"] == 1
    ctx = result["alert"]["actor_context"]
    assert ctx["invoice_count"] == 2
    assert ctx["total_amount_cents"] == 17000


# ═════════════════════════════════════════════════════════════════════
# 4 · Signal 1 dedup — same count → 0 new.
# ═════════════════════════════════════════════════════════════════════
def test_missed_payments_rerun_same_count_dedups(a3_seed):
    S = a3_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.churn_risk_scan import (
            run_churn_risk_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        await _mk_invoice(_db, tid=S["tenant_id"], cid=cid,
                            status="past_due", amount_cents=10000,
                            days_ago=15)
        await _mk_invoice(_db, tid=S["tenant_id"], cid=cid,
                            status="overdue", amount_cents=12000,
                            days_ago=25)
        result["first"]  = await run_churn_risk_scan(
            tenant_id=S["tenant_id"])
        result["second"] = await run_churn_risk_scan(
            tenant_id=S["tenant_id"])
        await _cleanup_all(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["first"]["alerts_emitted"]  == 1
    assert result["first"]["alerts_deduped"]  == 0
    assert result["second"]["alerts_emitted"] == 0
    assert result["second"]["alerts_deduped"] == 1


# ═════════════════════════════════════════════════════════════════════
# 5 · Signal 1 — count shift 2→3 emits a fresh alert.
# ═════════════════════════════════════════════════════════════════════
def test_missed_payments_count_shift_emits_new_alert(a3_seed):
    S = a3_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.churn_risk_scan import (
            run_churn_risk_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        await _mk_invoice(_db, tid=S["tenant_id"], cid=cid,
                            status="past_due", amount_cents=10000,
                            days_ago=15)
        await _mk_invoice(_db, tid=S["tenant_id"], cid=cid,
                            status="past_due", amount_cents=12000,
                            days_ago=25)
        result["first"] = await run_churn_risk_scan(
            tenant_id=S["tenant_id"])
        # Debt grows — third unpaid lands.
        await _mk_invoice(_db, tid=S["tenant_id"], cid=cid,
                            status="past_due", amount_cents=15000,
                            days_ago=5)
        result["second"] = await run_churn_risk_scan(
            tenant_id=S["tenant_id"])
        result["alerts"] = await _db.intelligence_alerts.count_documents({
            "tenant_id": S["tenant_id"], "customer_id": cid,
            "category":  "churn_risk"})
        await _cleanup_all(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["first"]["alerts_emitted"]  == 1
    assert result["second"]["alerts_emitted"] == 1
    assert result["second"]["alerts_deduped"] == 0
    # Count-2 alert persists; count-3 alert emits fresh → 2 rows.
    assert result["alerts"] == 2


# ═════════════════════════════════════════════════════════════════════
# 6 · Signal 2 — customer-cancelled recurring series → 1 alert.
# ═════════════════════════════════════════════════════════════════════
def test_recurring_cancelled_by_customer_emits_alert(a3_seed):
    S = a3_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.churn_risk_scan import (
            run_churn_risk_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"], "Priya Patel")
        result["cid"] = cid
        await _mk_recurring_job(
            _db, tid=S["tenant_id"], cid=cid,
            status="cancelled_by_customer",
            service="Weekly Pool Cleaning",
        )
        result["summary"] = await run_churn_risk_scan(
            tenant_id=S["tenant_id"])
        result["alert"] = await _db.intelligence_alerts.find_one({
            "tenant_id":   S["tenant_id"], "customer_id": cid,
            "category":    "churn_risk"})
        await _cleanup_all(_db, S["tenant_id"], cid)

    run_test(_go)
    summary = result["summary"]
    assert summary["by_signal"]["recurring_cancelled"] == 1
    assert summary["by_signal"]["missed_payments"] == 0
    alert = result["alert"]
    assert alert["severity"] == "recommended"
    ctx = alert["actor_context"]
    assert ctx["signal"] == "recurring_cancelled"
    assert ctx["service_type"] == "Weekly Pool Cleaning"
    assert ctx["cancelled_at_short"]
    assert "Priya Patel" in alert["title"]


# ═════════════════════════════════════════════════════════════════════
# 7 · Signal 2 — non-recurring cancelled job → NO alert.
# ═════════════════════════════════════════════════════════════════════
def test_non_recurring_cancelled_emits_nothing(a3_seed):
    S = a3_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.churn_risk_scan import (
            run_churn_risk_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        await _mk_recurring_job(
            _db, tid=S["tenant_id"], cid=cid,
            status="cancelled_by_customer",
            is_recurring=False,
        )
        result["summary"] = await run_churn_risk_scan(
            tenant_id=S["tenant_id"])
        await _cleanup_all(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["summary"]["alerts_emitted"] == 0


# ═════════════════════════════════════════════════════════════════════
# 8 · Signal 2 — cancelled_by_office on recurring job → NO alert.
# ═════════════════════════════════════════════════════════════════════
def test_cancelled_by_office_emits_nothing(a3_seed):
    S = a3_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.churn_risk_scan import (
            run_churn_risk_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        await _mk_recurring_job(
            _db, tid=S["tenant_id"], cid=cid,
            status="cancelled_by_office",
            is_recurring=True,
        )
        result["summary"] = await run_churn_risk_scan(
            tenant_id=S["tenant_id"])
        await _cleanup_all(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["summary"]["alerts_emitted"] == 0


# ═════════════════════════════════════════════════════════════════════
# 9 · Signal 2 dedup — same job → 0 new.
# ═════════════════════════════════════════════════════════════════════
def test_recurring_cancelled_rerun_dedups(a3_seed):
    S = a3_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.churn_risk_scan import (
            run_churn_risk_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        await _mk_recurring_job(
            _db, tid=S["tenant_id"], cid=cid,
            status="cancelled_by_customer",
        )
        result["first"]  = await run_churn_risk_scan(
            tenant_id=S["tenant_id"])
        result["second"] = await run_churn_risk_scan(
            tenant_id=S["tenant_id"])
        await _cleanup_all(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["first"]["alerts_emitted"]  == 1
    assert result["second"]["alerts_emitted"] == 0
    assert result["second"]["alerts_deduped"] == 1


# ═════════════════════════════════════════════════════════════════════
# 10 · Combined — customer with both signals gets 2 alerts.
# ═════════════════════════════════════════════════════════════════════
def test_combined_both_signals_emit_two_alerts(a3_seed):
    S = a3_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.churn_risk_scan import (
            run_churn_risk_scan,
        )
        cid = await _mk_customer(_db, S["tenant_id"], "Combined Cust")
        result["cid"] = cid
        await _mk_invoice(_db, tid=S["tenant_id"], cid=cid,
                            status="past_due", amount_cents=10000,
                            days_ago=15)
        await _mk_invoice(_db, tid=S["tenant_id"], cid=cid,
                            status="past_due", amount_cents=15000,
                            days_ago=30)
        await _mk_recurring_job(
            _db, tid=S["tenant_id"], cid=cid,
            status="cancelled_by_customer",
        )
        result["summary"] = await run_churn_risk_scan(
            tenant_id=S["tenant_id"])
        result["alerts_count"] = (
            await _db.intelligence_alerts.count_documents({
                "tenant_id": S["tenant_id"], "customer_id": cid,
                "category":  "churn_risk"})
        )
        result["signals"] = (
            await _db.intelligence_alerts.distinct(
                "actor_context.signal",
                {"tenant_id": S["tenant_id"], "customer_id": cid,
                 "category":  "churn_risk"})
        )
        await _cleanup_all(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["summary"]["alerts_emitted"] == 2
    assert result["summary"]["by_signal"]["missed_payments"] == 1
    assert result["summary"]["by_signal"]["recurring_cancelled"] == 1
    assert result["alerts_count"] == 2
    assert set(result["signals"]) == {"missed_payments", "recurring_cancelled"}


# ═════════════════════════════════════════════════════════════════════
# 11 · Tenant isolation — signals in tenant B don't leak into A.
# ═════════════════════════════════════════════════════════════════════
def test_tenant_isolation_no_cross_tenant_leaks(a3_seed):
    S = a3_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.churn_risk_scan import (
            run_churn_risk_scan,
        )
        cb = await _mk_customer(_db, S["tenant_b"], "TenantB Cust")
        result["cb"] = cb
        await _mk_invoice(_db, tid=S["tenant_b"], cid=cb,
                            status="past_due", amount_cents=10000,
                            days_ago=15)
        await _mk_invoice(_db, tid=S["tenant_b"], cid=cb,
                            status="past_due", amount_cents=15000,
                            days_ago=30)
        await _mk_recurring_job(
            _db, tid=S["tenant_b"], cid=cb,
            status="cancelled_by_customer",
        )
        result["summary_a"] = await run_churn_risk_scan(
            tenant_id=S["tenant_id"])
        result["alert_leak"] = await _db.intelligence_alerts.find_one({
            "tenant_id": S["tenant_id"], "customer_id": cb})
        await _cleanup_all(_db, S["tenant_b"], cb)

    run_test(_go)
    assert result["summary_a"]["alerts_emitted"] == 0
    assert result["alert_leak"] is None


# ═════════════════════════════════════════════════════════════════════
# 12 · Manual scan-run-now route — admin OK, tech 403.
# ═════════════════════════════════════════════════════════════════════
def test_scan_run_now_route_role_gate(a3_seed):
    S = a3_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            r = await client.post(
                f"{API}/intelligence/scans/churn-risk/run-now",
                headers={"Authorization": f"Bearer {S['admin_token']}"},
                json={})
            result["admin_status"] = r.status_code
            result["admin_body"] = r.json() if r.status_code == 200 else r.text
            r = await client.post(
                f"{API}/intelligence/scans/churn-risk/run-now",
                headers={"Authorization": f"Bearer {S['tech_token']}"},
                json={})
            result["tech_status"] = r.status_code
            result["tech_detail"] = (r.json() or {}).get("detail")

    run_test(_go)
    assert result["admin_status"] == 200, result
    body = result["admin_body"]
    assert set(["alerts_emitted", "scanned_customers", "alerts_deduped",
                 "by_signal"]).issubset(body.keys())
    assert set(body["by_signal"].keys()) == {
        "missed_payments", "recurring_cancelled"}
    assert result["tech_status"] == 403
    assert result["tech_detail"] == "insufficient_role_for_alerts"
