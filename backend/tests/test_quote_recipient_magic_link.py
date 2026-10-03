"""Phase 2 · Feb-2026 · Quote-to-Lead Recipient — magic-link JWT."""
from __future__ import annotations
import asyncio
from pathlib import Path
from uuid import uuid4
import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_ENV = {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
        for k, v in _ENV.items()}
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db_everywhere():
    import config
    config.db = _DB
    import routers.estimate_viewer as _ev
    _ev.db = _DB


# NOTE: Phase 2 isolation fix (Feb-2026) — module-scope
# ``_patch_db_everywhere()`` call removed. The autouse ``_clean``
# fixture below already re-pins before every test.


PREFIX = f"ph2ml-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"


async def _seed_tenant(tid):
    await _DB.tenants.insert_one({"id": tid, "name": f"T {tid}",
        "timezone": "America/Phoenix"})


async def _seed_quote(qid, tid, *, customer_id=None, recipient_type=None,
                        recipient_id=None):
    await _DB.quotes.insert_one({"id": qid, "tenant_id": tid, "doc_type": "quote",
        "customer_id": customer_id, "recipient_type": recipient_type,
        "recipient_id": recipient_id, "customer_name": "T", "title": "T",
        "line_items": [], "total": 0})


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    await _DB.quotes.delete_many({"$or": [{"id": rx}, {"tenant_id": rx}]})
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


def test_legacy_cid_only_token_still_verifies_on_customer_quote():
    qid = f"{PREFIX}-q-legacy"
    cid = f"{PREFIX}-c-legacy"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid, TENANT_A, customer_id=cid))
    from routers.estimate_viewer import _sign_estimate_token, _load_est_from_token
    tok = _sign_estimate_token(qid, cid, TENANT_A)
    out = _run(_load_est_from_token(tok))
    assert out["est"]["id"] == qid


def test_new_rid_rtype_token_verifies_on_lead_quote():
    qid = f"{PREFIX}-q-lead"
    lid = f"{PREFIX}-l-lead"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid, TENANT_A, recipient_type="lead", recipient_id=lid))
    from routers.estimate_viewer import _sign_estimate_token, _load_est_from_token
    tok = _sign_estimate_token(qid, "", TENANT_A,
        recipient_kind="lead", recipient_id=lid)
    out = _run(_load_est_from_token(tok))
    assert out["est"]["id"] == qid
    assert out["est"]["recipient_type"] == "lead"


def test_token_with_wrong_rid_is_rejected():
    qid = f"{PREFIX}-q-wrong-rid"
    lid = f"{PREFIX}-l-right"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid, TENANT_A, recipient_type="lead", recipient_id=lid))
    from routers.estimate_viewer import _sign_estimate_token, _load_est_from_token
    tok = _sign_estimate_token(qid, "", TENANT_A,
        recipient_kind="lead", recipient_id=f"{PREFIX}-l-wrong")
    with pytest.raises(HTTPException) as exc:
        _run(_load_est_from_token(tok))
    assert exc.value.status_code == 401


def test_mismatched_rtype_is_rejected():
    qid = f"{PREFIX}-q-rtype-mismatch"
    lid = f"{PREFIX}-l-rtype"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid, TENANT_A, recipient_type="lead", recipient_id=lid))
    from routers.estimate_viewer import _sign_estimate_token, _load_est_from_token
    tok = _sign_estimate_token(qid, lid, TENANT_A,
        recipient_kind="customer", recipient_id=lid)
    with pytest.raises(HTTPException) as exc:
        _run(_load_est_from_token(tok))
    assert exc.value.status_code == 401
