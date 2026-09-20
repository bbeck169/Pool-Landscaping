"""Phase F1 · Feb-2026 — Final Bundle backend pytest.

Covers:
  * F1.1 — currency writer/reader:
    1.  PATCH /tenants/mine/settings/business sets currency (admin OK).
    2.  GET /tenants/mine/settings/business returns the fresh value.
    3.  Non-admin role → 403 insufficient_role.
    4.  Invalid ISO code → 400 unsupported_currency.
    5.  Kanban ``total_currency`` picks up the new value.
  * F1.2 — portal renewal:
    6.  Happy path — status flips to renewed + child row appears.
    7.  Expired token → 410 token_expired.
    8.  Bad signature → 403 token_invalid.
    9.  Wrong agreement id in URL → 403 token_invalid.
    10. Already-renewed agreement → 409 agreement_state_invalid.
    11. GET /portal/agreements/{id}/summary happy path.
    12. Renewal i18n keys populated in en / es / fr.
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


def _mint(uid: str, tid: str, role: str = "admin") -> str:
    from config import JWT_SECRET
    return _jwt.encode({
        "sub": uid, "email": f"{uid}@ex.test", "role": role,
        "tenant_id": tid,
        "exp": int((datetime.now(timezone.utc)
                     + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def f1_seed():
    tid = f"f1-{uuid.uuid4()}"
    admin_uid = f"f1-admin-{uuid.uuid4()}"
    tech_uid  = f"f1-tech-{uuid.uuid4()}"

    async def _seed(_db):
        await _db.tenants.insert_one({
            "id": tid, "name": "F1 T",
            "slug": f"f1-{uuid.uuid4().hex[:6]}",
            "active": True, "settings": {}})
        await _db.users.insert_many([
            {"id": admin_uid, "email": f"admin-{admin_uid}@ex.test",
              "role": "admin", "tenant_id": tid},
            {"id": tech_uid,  "email": f"tech-{tech_uid}@ex.test",
              "role": "technician", "tenant_id": tid},
        ])

    async def _teardown(_db):
        await _db.tenants.delete_many({"id": tid})
        await _db.users.delete_many({"id": {"$in": [admin_uid, tech_uid]}})
        await _db.warranty_contracts.delete_many({"tenant_id": tid})
        await _db.customers.delete_many({"tenant_id": tid})

    run_test(_seed)
    yield {
        "tid":         tid,
        "admin_uid":   admin_uid,
        "tech_uid":    tech_uid,
        "admin_token": _mint(admin_uid, tid, "admin"),
        "tech_token":  _mint(tech_uid, tid, "technician"),
    }
    run_test(_teardown)


# ═════════════════════════════════════════════════════════════════════
# F1.1 · Currency writer / reader.
# ═════════════════════════════════════════════════════════════════════
def test_currency_patch_and_read(f1_seed):
    S = f1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.patch(
                f"{API}/tenants/mine/settings/business",
                json={"currency": "EUR"},
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            result["patch"] = {"status": r.status_code, "body": r.json()}
            r2 = await c.get(
                f"{API}/tenants/mine/settings/business",
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            result["get"] = {"status": r2.status_code, "body": r2.json()}
        fresh = await _db.tenants.find_one({"id": S["tid"]}, {"_id": 0})
        result["persisted"] = (fresh.get("settings") or {}).get("currency")

    run_test(_go)
    assert result["patch"]["status"] == 200, result["patch"]
    assert result["patch"]["body"]["currency"] == "EUR"
    assert result["patch"]["body"]["currency_symbol"] == "€"
    assert result["get"]["body"]["currency"] == "EUR"
    assert result["persisted"] == "EUR"


def test_currency_tech_forbidden(f1_seed):
    S = f1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.patch(
                f"{API}/tenants/mine/settings/business",
                json={"currency": "EUR"},
                headers={"Authorization": f"Bearer {S['tech_token']}"})
            result["status"] = r.status_code

    run_test(_go)
    assert result["status"] == 403


def test_currency_invalid_code(f1_seed):
    S = f1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.patch(
                f"{API}/tenants/mine/settings/business",
                json={"currency": "XYZ"},
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            result["status"] = r.status_code
            result["detail"] = r.json().get("detail")

    run_test(_go)
    assert result["status"] == 400
    assert result["detail"]["error"] == "unsupported_currency"
    assert "USD" in result["detail"]["allowed"]


def test_currency_kanban_reflects_patch(f1_seed):
    S = f1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        await _db.tenants.update_one(
            {"id": S["tid"]},
            {"$set": {"settings.currency": "GBP"}})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/pipeline/kanban",
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            result["status"] = r.status_code
            data = r.json() or {}
            cols = data.get("columns") or []
            result["currencies"] = list({(c or {}).get("total_currency")
                                            for c in cols})

    run_test(_go)
    assert result["status"] == 200, result
    assert set(result["currencies"]) <= {"GBP"}, result


# ═════════════════════════════════════════════════════════════════════
# F1.2 · Portal renewal.
# ═════════════════════════════════════════════════════════════════════
def _seed_contract(_db, tid: str, *, cid: str, agreement_id: str,
                    start_days_ago: int = 300,
                    end_days_ahead: int = 30) -> None:
    now = datetime.now(timezone.utc).date()
    start = (now - timedelta(days=start_days_ago)).isoformat()
    end = (now + timedelta(days=end_days_ahead)).isoformat()
    return _db.warranty_contracts.insert_one({
        "id": agreement_id, "tenant_id": tid,
        "customer_id": cid,
        "customer_name_snapshot": "Jane Renewal",
        "plan_id": f"plan-{uuid.uuid4()}",
        "plan_name_snapshot": "Gold Maintenance",
        "plan_kind_snapshot": "maintenance",
        "price_paid": 79.0,
        "status": "active",
        "start_date": start, "end_date": end,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def test_portal_renewal_happy_path(f1_seed):
    S = f1_seed
    app = _get_app()
    cid = f"f1-cust-{uuid.uuid4()}"
    agreement_id = f"f1-agr-{uuid.uuid4()}"
    result: Dict[str, Any] = {}

    async def _go(_db):
        await _db.customers.insert_one({
            "id": cid, "tenant_id": S["tid"],
            "email": f"{cid}@ex.test", "name": "Jane Renewal"})
        await _seed_contract(_db, S["tid"], cid=cid,
                                agreement_id=agreement_id)

        from services.intelligence.renewal_scan import sign_renewal_token
        token, _exp = sign_renewal_token(agreement_id)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.post(
                f"{API}/portal/agreements/{agreement_id}/renew",
                json={"token": token})
            result["status"] = r.status_code
            result["body"] = r.json()

        parent = await _db.warranty_contracts.find_one(
            {"id": agreement_id}, {"_id": 0})
        result["parent_status"] = parent.get("status")
        result["parent_renewed_at"] = parent.get("renewed_at")
        result["parent_renewal_contract_id"] = parent.get("renewal_contract_id")

        child_id = result["body"]["new_agreement_id"]
        child = await _db.warranty_contracts.find_one(
            {"id": child_id}, {"_id": 0})
        result["child_status"] = child.get("status")
        result["child_renewed_by"] = child.get("renewed_by_agreement_id")
        result["child_end"] = child.get("end_date")

    run_test(_go)
    assert result["status"] == 200, result
    assert result["parent_status"] == "renewed"
    assert result["parent_renewed_at"]
    assert result["parent_renewal_contract_id"] == result["body"]["new_agreement_id"]
    assert result["child_status"] == "active"
    assert result["child_renewed_by"] == agreement_id
    assert result["child_end"] == result["body"]["next_expires_at"]


def test_portal_renewal_expired_token(f1_seed):
    S = f1_seed
    app = _get_app()
    cid = f"f1-cust-exp-{uuid.uuid4()}"
    agreement_id = f"f1-agr-exp-{uuid.uuid4()}"
    result: Dict[str, Any] = {}

    async def _go(_db):
        await _seed_contract(_db, S["tid"], cid=cid,
                                agreement_id=agreement_id)
        from services.intelligence.renewal_scan import sign_renewal_token
        past = datetime.now(timezone.utc) - timedelta(days=200)
        token, _exp = sign_renewal_token(
            agreement_id, ttl_days=-90, now=past)  # forces expired

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.post(
                f"{API}/portal/agreements/{agreement_id}/renew",
                json={"token": token})
            result["status"] = r.status_code
            result["detail"] = r.json().get("detail")

    run_test(_go)
    assert result["status"] == 410
    assert result["detail"] == "token_expired"


def test_portal_renewal_bad_signature(f1_seed):
    S = f1_seed
    app = _get_app()
    agreement_id = f"f1-agr-bad-{uuid.uuid4()}"
    result: Dict[str, Any] = {}

    async def _go(_db):
        await _seed_contract(_db, S["tid"],
                                cid=f"f1-cust-bad-{uuid.uuid4()}",
                                agreement_id=agreement_id)
        # Tampered — same contract_id + exp but junk sig.
        exp = int((datetime.now(timezone.utc)
                     + timedelta(days=30)).timestamp())
        forged = f"{agreement_id}.{exp}.deadbeefdeadbeefdeadbeefdeadbeef"

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.post(
                f"{API}/portal/agreements/{agreement_id}/renew",
                json={"token": forged})
            result["status"] = r.status_code
            result["detail"] = r.json().get("detail")

    run_test(_go)
    assert result["status"] == 403
    assert result["detail"] == "token_invalid"


def test_portal_renewal_wrong_agreement_id(f1_seed):
    S = f1_seed
    app = _get_app()
    aid_a = f"f1-agr-A-{uuid.uuid4()}"
    aid_b = f"f1-agr-B-{uuid.uuid4()}"
    result: Dict[str, Any] = {}

    async def _go(_db):
        await _seed_contract(_db, S["tid"],
                                cid=f"f1-c-{uuid.uuid4()}",
                                agreement_id=aid_a)
        from services.intelligence.renewal_scan import sign_renewal_token
        token, _exp = sign_renewal_token(aid_a)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.post(
                f"{API}/portal/agreements/{aid_b}/renew",
                json={"token": token})
            result["status"] = r.status_code
            result["detail"] = r.json().get("detail")

    run_test(_go)
    assert result["status"] == 403
    assert result["detail"] == "token_invalid"


def test_portal_renewal_already_renewed(f1_seed):
    S = f1_seed
    app = _get_app()
    aid = f"f1-agr-dup-{uuid.uuid4()}"
    cid = f"f1-c-dup-{uuid.uuid4()}"
    result: Dict[str, Any] = {}

    async def _go(_db):
        await _seed_contract(_db, S["tid"], cid=cid, agreement_id=aid)
        await _db.warranty_contracts.update_one(
            {"id": aid},
            {"$set": {"status": "renewed",
                      "renewed_at": datetime.now(timezone.utc).isoformat(),
                      "renewal_contract_id": f"prev-{uuid.uuid4()}"}})

        from services.intelligence.renewal_scan import sign_renewal_token
        token, _exp = sign_renewal_token(aid)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.post(
                f"{API}/portal/agreements/{aid}/renew",
                json={"token": token})
            result["status"] = r.status_code
            result["detail"] = r.json().get("detail")

    run_test(_go)
    assert result["status"] == 409
    assert result["detail"] == "agreement_state_invalid"


def test_portal_summary_happy_path(f1_seed):
    S = f1_seed
    app = _get_app()
    aid = f"f1-agr-sum-{uuid.uuid4()}"
    cid = f"f1-c-sum-{uuid.uuid4()}"
    result: Dict[str, Any] = {}

    async def _go(_db):
        await _seed_contract(_db, S["tid"], cid=cid, agreement_id=aid)
        from services.intelligence.renewal_scan import sign_renewal_token
        token, _exp = sign_renewal_token(aid)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/portal/agreements/{aid}/summary?token={token}")
            result["status"] = r.status_code
            result["body"] = r.json()

    run_test(_go)
    assert result["status"] == 200, result
    b = result["body"]
    assert b["agreement_id"] == aid
    assert b["plan_name"] == "Gold Maintenance"
    assert b["price_paid"] == 79.0
    assert b["already_renewed"] is False
    assert b["next_expires_at"]


def test_renewal_confirmation_i18n_keys_populated():
    from services.email_body_i18n import LABELS
    keys = [
        "email.renewal_confirmation.subject",
        "email.renewal_confirmation.body_intro",
        "email.renewal_confirmation.body_term",
        "email.renewal_confirmation.body_price",
        "email.renewal_confirmation.body_footer",
    ]
    for loc in ("en", "es", "fr"):
        for k in keys:
            assert k in LABELS[loc], f"missing {k} in locale={loc}"
