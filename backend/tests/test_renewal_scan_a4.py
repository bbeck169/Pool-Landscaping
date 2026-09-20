"""Phase A4 · Feb-2026 · Proactive Intelligence — Renewal Engine
pytest suite.

Covers:
  1.  Happy · manual plan · ``end_date == today+30d`` → 1 alert
      + 1 proposal-email attempt, severity=recommended, body
      mentions "30 days".
  2.  29-day agreement → NO alert (only 30d bucket fires).
  3.  31-day agreement → NO alert.
  4.  Auto-renew plan · 30d out → 1 alert with different body,
      ``auto_renew_receipts_sent`` counter increments and
      ``emails_sent`` (proposal counter) stays 0.
  5.  Cancelled contract (``status="cancelled"``) → NO alert.
  6.  Expired contract (``status="active"``, ``end_date < today``)
      → NO alert (only the exact 30d bucket).
  7.  Dedup — rerun same day → 0 new emits, +1 deduped.
  8.  i18n — recipient locale=``es`` renders Spanish subject.
  9.  HMAC-signed token — encoded in CTA URL, verifies within
      window, expiration ≈60 days out (±120 s tolerance).
  10. Manual scan-run-now — 403 for tech, correct dict for admin.
  11. Placeholder parity — every ``email.renewal_proposal.*`` and
      ``email.renewal_receipt.*`` key exists in en/es/fr with the
      same ``{placeholder}`` set.
  12. Tenant isolation — tenant B's agreement doesn't emit for A.
  13. Resend button endpoint (``POST /agreements/{id}/resend-renewal-email``)
      — 403 for tech, admin OK.
"""
from __future__ import annotations

import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Set

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


def _placeholders(tmpl: str) -> Set[str]:
    """Extract ``{placeholder}`` tokens from a ``str.format`` template.
    Handles bare ``{customer}`` — no format-spec or attribute-style
    tokens are used in the D6 catalog. Returns an empty set for
    templates with none."""
    out: Set[str] = set()
    for _, field, _, _ in string.Formatter().parse(tmpl):
        if field:
            out.add(field)
    return out


@pytest.fixture
def a4_seed():
    tid   = f"a4-tid-{uuid.uuid4()}"
    tid_b = f"a4-tid-b-{uuid.uuid4()}"
    admin_uid = f"a4-admin-{uuid.uuid4()}"
    tech_uid  = f"a4-tech-{uuid.uuid4()}"

    async def _seed(_db):
        from services.intelligence.alerts import ensure_indexes
        await ensure_indexes()
        await _db.tenants.insert_many([
            {"id": tid, "name": "Tenant A4",
             "slug": f"a4-{uuid.uuid4().hex[:8]}", "active": True,
             "default_locale": "en"},
            {"id": tid_b, "name": "Tenant A4 B",
             "slug": f"a4b-{uuid.uuid4().hex[:8]}", "active": True},
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


async def _mk_customer(_db, tid: str, name: str = "",
                        locale: str = "") -> str:
    cid = f"a4-cust-{uuid.uuid4()}"
    doc: Dict[str, Any] = {
        "id": cid, "tenant_id": tid,
        "name": name or f"Cust {cid[:8]}",
        "email": f"{cid[:12]}@example.test",
    }
    if locale:
        doc["locale"] = locale
    await _db.customers.insert_one(doc)
    return cid


async def _mk_plan(_db, *, tid: str, name: str, price: float,
                    renewal_kind: str = "manual",
                    duration_months: int = 12) -> str:
    pid = f"a4-plan-{uuid.uuid4()}"
    await _db.warranty_plans.insert_one({
        "id": pid, "tenant_id": tid, "name": name,
        "kind": "maintenance_contract",
        "duration_months": duration_months,
        "coverage_summary": "", "price": price,
        "terms_html": "", "renewal_kind": renewal_kind,
    })
    return pid


async def _mk_contract(_db, *, tid: str, cid: str, plan_id: str,
                        plan_name: str, price: float,
                        end_in_days: int,
                        status: str = "active") -> str:
    ctid = f"a4-ct-{uuid.uuid4()}"
    end_date = (datetime.now(timezone.utc)
                  + timedelta(days=end_in_days)).date().isoformat()
    await _db.warranty_contracts.insert_one({
        "id": ctid, "tenant_id": tid, "plan_id": plan_id,
        "plan_name_snapshot": plan_name,
        "plan_kind_snapshot": "maintenance_contract",
        "customer_id": cid,
        "start_date": (datetime.now(timezone.utc)
                          - timedelta(days=335)).date().isoformat(),
        "end_date": end_date,
        "price_paid": price, "status": status,
    })
    return ctid


async def _cleanup(_db, tid: str, cid: str) -> None:
    await _db.warranty_contracts.delete_many({"customer_id": cid})
    await _db.warranty_plans.delete_many({"tenant_id": tid,
                                            "id": {"$regex": "^a4-plan-"}})
    await _db.customers.delete_many({"id": cid})
    await _db.intelligence_alerts.delete_many({"customer_id": cid,
                                                 "tenant_id": tid})


# ═════════════════════════════════════════════════════════════════════
# 1 · Happy path — manual plan, exactly 30 days out.
# ═════════════════════════════════════════════════════════════════════
def test_manual_plan_30d_out_emits_recommended_alert(a4_seed):
    S = a4_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.renewal_scan import run_renewal_scan
        cid = await _mk_customer(_db, S["tenant_id"], "Priya Patel")
        result["cid"] = cid
        pid = await _mk_plan(_db, tid=S["tenant_id"],
                              name="Weekly Pool Cleaning — Annual",
                              price=89.0, renewal_kind="manual")
        result["ctid"] = await _mk_contract(
            _db, tid=S["tenant_id"], cid=cid, plan_id=pid,
            plan_name="Weekly Pool Cleaning — Annual",
            price=89.0, end_in_days=30)
        result["summary"] = await run_renewal_scan(
            tenant_id=S["tenant_id"])
        result["alert"] = await _db.intelligence_alerts.find_one({
            "tenant_id":   S["tenant_id"],
            "customer_id": cid,
            "category":    "renewal_due"})
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)
    summary = result["summary"]
    assert summary["alerts_emitted"] == 1, summary
    assert summary["scanned_agreements"] == 1
    assert summary["auto_renew_receipts_sent"] == 0
    alert = result["alert"]
    assert alert is not None
    assert alert["severity"] == "recommended"
    assert alert["category"] == "renewal_due"
    assert "Priya Patel" in alert["title"]
    assert "Weekly Pool Cleaning" in alert["title"]
    assert "30 days" in alert["body"]
    ctx = alert["actor_context"]
    assert ctx["agreement_id"] == result["ctid"]
    assert ctx["days_left"] == 30
    assert ctx["auto_renew"] is False
    assert ctx["monthly_amount_cents"] == 8900  # 89.00 → 8900 cents
    assert ctx["expires_at_short"]
    # ``email_sent_to`` is None in the test env (no RESEND_API_KEY)
    # but the field must be present for FE type-safety.
    assert "email_sent_to" in ctx


# ═════════════════════════════════════════════════════════════════════
# 2 · 29-day contract → NO alert.
# ═════════════════════════════════════════════════════════════════════
def test_29_days_out_emits_nothing(a4_seed):
    S = a4_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.renewal_scan import run_renewal_scan
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        pid = await _mk_plan(_db, tid=S["tenant_id"], name="Plan",
                              price=50.0)
        await _mk_contract(_db, tid=S["tenant_id"], cid=cid,
                            plan_id=pid, plan_name="Plan",
                            price=50.0, end_in_days=29)
        result["summary"] = await run_renewal_scan(
            tenant_id=S["tenant_id"])
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["summary"]["alerts_emitted"] == 0


# ═════════════════════════════════════════════════════════════════════
# 3 · 31-day contract → NO alert.
# ═════════════════════════════════════════════════════════════════════
def test_31_days_out_emits_nothing(a4_seed):
    S = a4_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.renewal_scan import run_renewal_scan
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        pid = await _mk_plan(_db, tid=S["tenant_id"], name="Plan",
                              price=50.0)
        await _mk_contract(_db, tid=S["tenant_id"], cid=cid,
                            plan_id=pid, plan_name="Plan",
                            price=50.0, end_in_days=31)
        result["summary"] = await run_renewal_scan(
            tenant_id=S["tenant_id"])
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["summary"]["alerts_emitted"] == 0


# ═════════════════════════════════════════════════════════════════════
# 4 · Auto-renew plan · 30d out → different body + counters.
# ═════════════════════════════════════════════════════════════════════
def test_auto_renew_30d_out_emits_receipt_style(a4_seed):
    S = a4_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.renewal_scan import run_renewal_scan
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        pid = await _mk_plan(_db, tid=S["tenant_id"],
                              name="Auto Plan", price=79.0,
                              renewal_kind="auto")
        await _mk_contract(_db, tid=S["tenant_id"], cid=cid,
                            plan_id=pid, plan_name="Auto Plan",
                            price=79.0, end_in_days=30)
        result["summary"] = await run_renewal_scan(
            tenant_id=S["tenant_id"])
        result["alert"] = await _db.intelligence_alerts.find_one({
            "tenant_id":   S["tenant_id"],
            "customer_id": cid,
            "category":    "renewal_due"})
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)
    summary = result["summary"]
    assert summary["alerts_emitted"] == 1
    # Proposal emails counter stays at 0 for auto plans regardless
    # of env config; receipt counter increments only when the
    # email actually sent. In CI without RESEND_API_KEY both are
    # 0. In preview/dev where the key is set + guard passes the
    # receipt counter is 1. Accept either — we only care the
    # PROPOSAL bucket is untouched for auto plans.
    assert summary["emails_sent"] == 0
    assert summary["auto_renew_receipts_sent"] in (0, 1)
    alert = result["alert"]
    assert alert["actor_context"]["auto_renew"] is True
    assert "Auto-renews" in alert["body"]
    assert "auto-renew" in alert["title"].lower()


# ═════════════════════════════════════════════════════════════════════
# 5 · Cancelled contract → NO alert.
# ═════════════════════════════════════════════════════════════════════
def test_cancelled_contract_emits_nothing(a4_seed):
    S = a4_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.renewal_scan import run_renewal_scan
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        pid = await _mk_plan(_db, tid=S["tenant_id"], name="Plan",
                              price=50.0)
        await _mk_contract(_db, tid=S["tenant_id"], cid=cid,
                            plan_id=pid, plan_name="Plan",
                            price=50.0, end_in_days=30,
                            status="cancelled")
        result["summary"] = await run_renewal_scan(
            tenant_id=S["tenant_id"])
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["summary"]["alerts_emitted"] == 0


# ═════════════════════════════════════════════════════════════════════
# 6 · Expired contract (end_date in the past) → NO alert.
# ═════════════════════════════════════════════════════════════════════
def test_expired_contract_emits_nothing(a4_seed):
    S = a4_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.renewal_scan import run_renewal_scan
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        pid = await _mk_plan(_db, tid=S["tenant_id"], name="Plan",
                              price=50.0)
        # end_in_days = -5 → past
        await _mk_contract(_db, tid=S["tenant_id"], cid=cid,
                            plan_id=pid, plan_name="Plan",
                            price=50.0, end_in_days=-5)
        result["summary"] = await run_renewal_scan(
            tenant_id=S["tenant_id"])
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["summary"]["alerts_emitted"] == 0


# ═════════════════════════════════════════════════════════════════════
# 7 · Dedup — rerun same day → 0 new emits, +1 deduped.
# ═════════════════════════════════════════════════════════════════════
def test_rerun_dedups(a4_seed):
    S = a4_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.renewal_scan import run_renewal_scan
        cid = await _mk_customer(_db, S["tenant_id"])
        result["cid"] = cid
        pid = await _mk_plan(_db, tid=S["tenant_id"], name="Plan",
                              price=50.0)
        await _mk_contract(_db, tid=S["tenant_id"], cid=cid,
                            plan_id=pid, plan_name="Plan",
                            price=50.0, end_in_days=30)
        result["first"]  = await run_renewal_scan(
            tenant_id=S["tenant_id"])
        result["second"] = await run_renewal_scan(
            tenant_id=S["tenant_id"])
        await _cleanup(_db, S["tenant_id"], cid)

    run_test(_go)
    assert result["first"]["alerts_emitted"]  == 1
    assert result["first"]["alerts_deduped"]  == 0
    assert result["second"]["alerts_emitted"] == 0
    assert result["second"]["alerts_deduped"] == 1


# ═════════════════════════════════════════════════════════════════════
# 8 · i18n — recipient locale=es renders Spanish subject.
# ═════════════════════════════════════════════════════════════════════
def test_i18n_spanish_subject():
    """Pure D6 i18n contract — no DB.  Confirms the new keys
    render Spanish copy when locale=``es``."""
    from services.email_body_i18n import t_email_body
    subj_es = t_email_body(
        "es", "email.renewal_proposal.subject",
        plan_name="Cleaning Plan", days_left=30)
    body_es = t_email_body(
        "es", "email.renewal_proposal.body_intro",
        customer_first_name="Ana",
        plan_name="Cleaning Plan", expires_at_short="2026-03-14")
    assert "renueva" in subj_es.lower()
    assert "30 días" in subj_es
    assert "Hola" in body_es and "Ana" in body_es
    # Same key in English for sanity.
    subj_en = t_email_body(
        "en", "email.renewal_proposal.subject",
        plan_name="Cleaning Plan", days_left=30)
    assert "renews" in subj_en.lower()
    assert "30 days" in subj_en


# ═════════════════════════════════════════════════════════════════════
# 9 · HMAC-signed CTA token — round-trip + exp window ±120s.
# ═════════════════════════════════════════════════════════════════════
def test_renewal_token_signs_and_verifies_within_60d_window():
    from services.intelligence.renewal_scan import (
        sign_renewal_token, verify_renewal_token,
    )
    ref = datetime.now(timezone.utc)
    token, exp = sign_renewal_token("contract-1", now=ref)
    assert token.startswith("contract-1.")
    # Expiration ≈ 60d from ``ref`` (±120s tolerance for wall clock).
    expected_exp = int((ref + timedelta(days=60)).timestamp())
    assert abs(exp - expected_exp) < 120
    # Valid before exp.
    assert verify_renewal_token(
        token, now=ref + timedelta(days=59)) == "contract-1"
    # Invalid after exp.
    assert verify_renewal_token(
        token, now=ref + timedelta(days=61)) is None
    # Tampered signature.
    parts = token.split(".")
    tampered = f"{parts[0]}.{parts[1]}.{'0' * 32}"
    assert verify_renewal_token(tampered, now=ref) is None
    # Wrong shape.
    assert verify_renewal_token("bad", now=ref) is None


# ═════════════════════════════════════════════════════════════════════
# 10 · Manual scan-run-now — 403 for tech, admin OK.
# ═════════════════════════════════════════════════════════════════════
def test_scan_run_now_route_role_gate(a4_seed):
    S = a4_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            r = await client.post(
                f"{API}/intelligence/scans/renewal/run-now",
                headers={"Authorization": f"Bearer {S['admin_token']}"},
                json={})
            result["admin_status"] = r.status_code
            result["admin_body"] = r.json() if r.status_code == 200 else r.text
            r = await client.post(
                f"{API}/intelligence/scans/renewal/run-now",
                headers={"Authorization": f"Bearer {S['tech_token']}"},
                json={})
            result["tech_status"] = r.status_code
            result["tech_detail"] = (r.json() or {}).get("detail")

    run_test(_go)
    assert result["admin_status"] == 200, result
    body = result["admin_body"]
    for k in ("scanned_agreements", "alerts_emitted", "alerts_deduped",
                "emails_sent", "auto_renew_receipts_sent", "by_tenant"):
        assert k in body, (k, body)
    assert result["tech_status"] == 403
    assert result["tech_detail"] == "insufficient_role_for_alerts"


# ═════════════════════════════════════════════════════════════════════
# 11 · Placeholder parity across en/es/fr for renewal keys.
# ═════════════════════════════════════════════════════════════════════
def test_renewal_i18n_placeholder_parity():
    from services.email_body_i18n import LABELS
    RENEWAL_KEYS = [
        "email.renewal_proposal.subject",
        "email.renewal_proposal.body_intro",
        "email.renewal_proposal.body_price",
        "email.renewal_proposal.body_cta",
        "email.renewal_proposal.body_footer",
        "email.renewal_receipt.subject",
        "email.renewal_receipt.body_intro",
        "email.renewal_receipt.body_price",
        "email.renewal_receipt.body_cta",
        "email.renewal_receipt.body_footer",
    ]
    for key in RENEWAL_KEYS:
        placeholders_per_locale: List[Set[str]] = []
        for loc in ("en", "es", "fr"):
            tmpl = LABELS[loc].get(key)
            assert tmpl, f"missing key {key!r} under {loc!r}"
            placeholders_per_locale.append(_placeholders(tmpl))
        # All three locales must reference the same set of tokens.
        assert placeholders_per_locale[0] == placeholders_per_locale[1] \
               == placeholders_per_locale[2], (
            f"placeholder drift on {key}: "
            f"en={placeholders_per_locale[0]} "
            f"es={placeholders_per_locale[1]} "
            f"fr={placeholders_per_locale[2]}"
        )


# ═════════════════════════════════════════════════════════════════════
# 12 · Tenant isolation — B's agreements don't emit for A.
# ═════════════════════════════════════════════════════════════════════
def test_tenant_isolation(a4_seed):
    S = a4_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        from services.intelligence.renewal_scan import run_renewal_scan
        cb = await _mk_customer(_db, S["tenant_b"], "TenantB Cust")
        result["cb"] = cb
        pid = await _mk_plan(_db, tid=S["tenant_b"], name="Plan",
                              price=50.0)
        await _mk_contract(_db, tid=S["tenant_b"], cid=cb,
                            plan_id=pid, plan_name="Plan",
                            price=50.0, end_in_days=30)
        result["summary_a"] = await run_renewal_scan(
            tenant_id=S["tenant_id"])
        result["leak"] = await _db.intelligence_alerts.find_one({
            "tenant_id": S["tenant_id"], "customer_id": cb})
        await _cleanup(_db, S["tenant_b"], cb)

    run_test(_go)
    assert result["summary_a"]["alerts_emitted"] == 0
    assert result["leak"] is None


# ═════════════════════════════════════════════════════════════════════
# 13 · Resend-renewal-email endpoint — admin OK, tech 403.
# ═════════════════════════════════════════════════════════════════════
def test_resend_renewal_email_route_role_gate(a4_seed):
    S = a4_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _seed(_db):
        cid = await _mk_customer(_db, S["tenant_id"])
        pid = await _mk_plan(_db, tid=S["tenant_id"], name="Plan",
                              price=50.0)
        ctid = await _mk_contract(_db, tid=S["tenant_id"], cid=cid,
                                    plan_id=pid, plan_name="Plan",
                                    price=50.0, end_in_days=30)
        result["ctid"] = ctid
        result["cid"] = cid

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            r = await client.post(
                f"{API}/agreements/{result['ctid']}/resend-renewal-email",
                headers={"Authorization": f"Bearer {S['admin_token']}"},
                json={})
            result["admin_status"] = r.status_code
            result["admin_body"] = r.json() if r.status_code == 200 else r.text
            r = await client.post(
                f"{API}/agreements/{result['ctid']}/resend-renewal-email",
                headers={"Authorization": f"Bearer {S['tech_token']}"},
                json={})
            result["tech_status"] = r.status_code

    async def _cleanup_go(_db):
        await _cleanup(_db, S["tenant_id"], result["cid"])

    run_test(_seed)
    run_test(_go)
    run_test(_cleanup_go)
    assert result["admin_status"] == 200, result
    assert "ok" in result["admin_body"]
    assert result["tech_status"] == 403
