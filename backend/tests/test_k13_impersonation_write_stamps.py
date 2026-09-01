"""Phase K13 · Feb-2026 — Impersonation write-stamp tests (Option C).

Ships two behavioral guarantees on top of the pre-existing
Iteration-35 impersonation flow:

1. Portal chat message posted with an impersonation JWT persists the
   ``via_impersonation`` + ``acting_admin_id`` fields on the stored
   ``portal_chat_messages`` doc.
2. Normal customer post (no impersonation) does NOT carry those
   fields — the stamp is opt-in on impersonated writes only.

Iteration-35 regression coverage lives in
``tests/test_iteration35_impersonation.py`` and stays green.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict

import pytest


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    for mod in ("routers.portal_chats",):
        __import__(mod)
        import sys
        sys.modules[mod].db = fresh_db
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)[
        os.environ["DB_NAME"]]


async def _tenant_id() -> str:
    u = await _db().users.find_one(
        {"email": "super@aquaterra.com"}, {"_id": 0, "tenant_id": 1})
    return u["tenant_id"]


async def _tenant_dep(tid: str) -> Dict[str, Any]:
    return await _db().tenants.find_one({"id": tid}, {"_id": 0}) or {"id": tid}


async def _seed(tid: str, *, tag: str) -> Dict[str, Any]:
    from utils import now_iso
    cid = f"k13-cust-{tag}-{uuid.uuid4().hex[:6]}"
    uid = f"k13-user-{tag}-{uuid.uuid4().hex[:6]}"
    await _db().customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "K13 Cust",
        "email": f"{tag}@example.com", "created_at": now_iso(),
    })
    await _db().users.insert_one({
        "id": uid, "tenant_id": tid, "role": "customer",
        "customer_id": cid, "name": "K13 Cust",
        "email": f"{tag}@example.com", "created_at": now_iso(),
    })
    return {"customer_id": cid, "user_id": uid}


async def _drain(_tid: str) -> None:
    for coll in ("customers", "users", "portal_chats",
                 "portal_chat_messages"):
        await _db()[coll].delete_many({
            "$or": [
                {"id": {"$regex": "^k13-"}},
                {"chat_id": {"$regex": "^k13-"}},
                {"customer_id": {"$regex": "^k13-cust-"}},
                {"sender_id": {"$regex": "^k13-user-"}},
            ],
        })


def test_k13_impersonated_portal_chat_write_stamps_via_impersonation():
    async def _go():
        tid = await _tenant_id()
        seed = await _seed(tid, tag="imp")
        try:
            from routers.portal_chats import (
                create_chat, ChatCreateIn,
            )
            # User dict emulates the shape ``get_current_user`` produces
            # for an impersonation JWT (see utils.py:119-123).
            imp_user = {
                "id": seed["user_id"], "role": "customer",
                "customer_id": seed["customer_id"], "name": "K13 Cust",
                "email": "imp@example.com", "tenant_id": tid,
                "is_impersonated": True,
                "impersonator_id": "k13-admin-42",
            }
            chat = await create_chat(
                ChatCreateIn(subject="k13", first_message="hi from admin"),
                user=imp_user, tenant=await _tenant_dep(tid),
            )
            msg = await _db().portal_chat_messages.find_one(
                {"chat_id": chat["id"]}, {"_id": 0},
            )
            assert msg is not None
            assert msg["via_impersonation"] is True, msg
            assert msg["acting_admin_id"] == "k13-admin-42", msg
            # K8 sender-name resolver still stamps the customer's name
            # (not the impersonator's) so the bubble reads correctly.
            assert msg["sender_name"] == "K13 Cust"
        finally:
            await _drain(tid)
    _run(_go())


def test_k13_normal_portal_chat_write_omits_stamp():
    async def _go():
        tid = await _tenant_id()
        seed = await _seed(tid, tag="norm")
        try:
            from routers.portal_chats import (
                create_chat, ChatCreateIn,
            )
            plain_user = {
                "id": seed["user_id"], "role": "customer",
                "customer_id": seed["customer_id"], "name": "K13 Cust",
                "email": "norm@example.com", "tenant_id": tid,
            }
            chat = await create_chat(
                ChatCreateIn(subject="k13-norm", first_message="hello"),
                user=plain_user, tenant=await _tenant_dep(tid),
            )
            msg = await _db().portal_chat_messages.find_one(
                {"chat_id": chat["id"]}, {"_id": 0},
            )
            assert msg is not None
            assert "via_impersonation" not in msg, msg
            assert "acting_admin_id" not in msg, msg
        finally:
            await _drain(tid)
    _run(_go())
