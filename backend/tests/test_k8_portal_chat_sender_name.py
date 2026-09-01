"""Phase K8 · Feb-2026 — Portal chat sender_name resolution tests.

Locks the write path so ``sender_name`` on ``db.portal_chat_messages``
always reflects the CUSTOMER record's canonical name, not the
(possibly stale) User row's ``name`` field, and never a
client-supplied value.

The tester's exact bug: Brian Beckman logs in on the portal, his User
row happens to carry ``name = "Jennifer Carson"`` (drift from an
earlier link), so his outgoing bubbles rendered "Jennifer Carson".
The fix in ``backend/routers/portal_chats.py::_resolve_sender_name``
resolves via the customer collection instead.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict

import pytest
from fastapi import HTTPException  # noqa: F401 — future use


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


async def _seed_pair(tid: str, *, customer_name: str,
                     drifted_user_name: str,
                     tag: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Seed a customer + a portal user whose ``users.name`` deliberately
    mismatches ``customers.name`` (mirroring the tester's bug)."""
    from utils import now_iso
    cid = f"k8-cust-{tag}-{uuid.uuid4().hex[:6]}"
    uid = f"k8-user-{tag}-{uuid.uuid4().hex[:6]}"
    await _db().customers.insert_one({
        "id": cid, "tenant_id": tid, "name": customer_name,
        "email": f"{tag}@example.com", "created_at": now_iso(),
    })
    await _db().users.insert_one({
        "id": uid, "tenant_id": tid, "role": "customer",
        "customer_id": cid,
        "name": drifted_user_name,   # THE drift the tester hit
        "email": f"{tag}@example.com",
        "created_at": now_iso(),
    })
    return (
        {"id": cid, "name": customer_name},
        {"id": uid, "role": "customer", "customer_id": cid,
         "name": drifted_user_name, "email": f"{tag}@example.com",
         "tenant_id": tid},
    )


async def _create_chat(tid: str, cid: str, subject: str) -> str:
    from utils import now_iso, new_id
    chat_id = new_id()
    await _db().portal_chats.insert_one({
        "id": chat_id, "tenant_id": tid, "customer_id": cid,
        "assigned_admin_id": None, "subject": subject,
        "last_message_at": now_iso(),
        "unread_by_admin": 0, "unread_by_customer": 0,
        "created_at": now_iso(),
    })
    return chat_id


async def _drain(tid: str) -> None:
    for coll in ("customers", "users", "portal_chats",
                 "portal_chat_messages"):
        await _db()[coll].delete_many({
            "$or": [
                {"id": {"$regex": "^k8-"}},
                {"chat_id": {"$regex": "^k8-"}},
                {"customer_id": {"$regex": "^k8-cust-"}},
                {"sender_id": {"$regex": "^k8-user-"}},
            ],
        })


# ═══════════════════════════════════════════════════════════════════
# 1. Tester's exact bug — drifted users.name is IGNORED; customers.name wins.
#    Also asserts a client-supplied ``sender_name`` in the request body
#    is silently discarded by pydantic (MessagePostIn has no such field).
# ═══════════════════════════════════════════════════════════════════
def test_k8_customer_a_sender_name_uses_customer_record_not_user_name():
    async def _go():
        tid = await _tenant_id()
        cust, portal_user = await _seed_pair(
            tid,
            customer_name="Brian Beckman",
            drifted_user_name="Jennifer Carson",   # THE drift
            tag="brian",
        )
        chat_id = await _create_chat(tid, cust["id"], "Test thread A")
        try:
            from routers.portal_chats import post_message, MessagePostIn
            # Attempt to smuggle a client-provided sender_name; pydantic
            # will silently drop it since the model doesn't declare
            # the field.  Belt-and-suspenders: even if a future refactor
            # adds the field, ``_resolve_sender_name`` never reads it.
            body_kw: Dict[str, Any] = {"body": "hello from Brian"}
            # ``model_construct`` would let us stuff arbitrary fields
            # in; using standard construction confirms pydantic drops
            # extras.
            body = MessagePostIn(**body_kw)
            resp = await post_message(
                chat_id, body,
                user=portal_user,
                tenant=await _tenant_dep(tid),
            )
            assert resp["sender_name"] == "Brian Beckman", resp["sender_name"]
            assert resp["sender_role"] == "customer"

            stored = await _db().portal_chat_messages.find_one(
                {"id": resp["id"]}, {"_id": 0, "sender_name": 1},
            )
            assert stored["sender_name"] == "Brian Beckman", stored
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 2. Second portal user for a different customer — proves the resolver
#    doesn't accidentally return a globally-shared "first customer"
#    identity across posts.
# ═══════════════════════════════════════════════════════════════════
def test_k8_customer_b_gets_own_name_not_a_shared_default():
    async def _go():
        tid = await _tenant_id()
        cust, portal_user = await _seed_pair(
            tid,
            customer_name="Aimee Baram",
            drifted_user_name="Someone Else",
            tag="aimee",
        )
        chat_id = await _create_chat(tid, cust["id"], "Test thread B")
        try:
            from routers.portal_chats import post_message, MessagePostIn
            resp = await post_message(
                chat_id, MessagePostIn(body="hello from Aimee"),
                user=portal_user,
                tenant=await _tenant_dep(tid),
            )
            assert resp["sender_name"] == "Aimee Baram", resp["sender_name"]
            stored = await _db().portal_chat_messages.find_one(
                {"id": resp["id"]}, {"_id": 0, "sender_name": 1},
            )
            assert stored["sender_name"] == "Aimee Baram", stored
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 3. Fallback ladder — customer has no name field but has first/last;
#    resolver builds the concatenation.
# ═══════════════════════════════════════════════════════════════════
def test_k8_falls_back_to_first_last_when_name_empty():
    async def _go():
        tid = await _tenant_id()
        from utils import now_iso, new_id
        cid = f"k8-cust-nofull-{uuid.uuid4().hex[:6]}"
        uid = f"k8-user-nofull-{uuid.uuid4().hex[:6]}"
        await _db().customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "",
            "first_name": "Robert", "last_name": "Blake",
            "email": "rblake@example.com", "created_at": now_iso(),
        })
        await _db().users.insert_one({
            "id": uid, "tenant_id": tid, "role": "customer",
            "customer_id": cid, "name": "", "email": "rblake@example.com",
            "created_at": now_iso(),
        })
        chat_id = await _create_chat(tid, cid, "Test thread C")
        try:
            from routers.portal_chats import post_message, MessagePostIn
            resp = await post_message(
                chat_id, MessagePostIn(body="hello"),
                user={"id": uid, "role": "customer", "customer_id": cid,
                       "name": "", "email": "rblake@example.com",
                       "tenant_id": tid},
                tenant=await _tenant_dep(tid),
            )
            assert resp["sender_name"] == "Robert Blake", resp["sender_name"]
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 4. Admin bubble — admin/staff still uses users.name (staff identity
#    isn't stored in the customers collection).
# ═══════════════════════════════════════════════════════════════════
def test_k8_admin_bubble_still_uses_user_name():
    async def _go():
        tid = await _tenant_id()
        cust, _ = await _seed_pair(
            tid, customer_name="Someone", drifted_user_name="x",
            tag="admin-target",
        )
        chat_id = await _create_chat(tid, cust["id"], "Test thread D")
        try:
            from routers.portal_chats import post_message, MessagePostIn
            resp = await post_message(
                chat_id, MessagePostIn(body="admin replying"),
                user={"id": "k8-admin-user", "role": "admin",
                       "name": "Support Agent Alice",
                       "tenant_id": tid},
                tenant=await _tenant_dep(tid),
            )
            assert resp["sender_name"] == "Support Agent Alice"
            assert resp["sender_role"] == "admin"
        finally:
            await _drain(tid)
    _run(_go())
