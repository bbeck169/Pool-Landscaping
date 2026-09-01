"""Phase K9 · Feb-2026 — Portal chat ↔ SMS bridge tests.

Covers the six spec cases:

  1. Customer post → sms_thread_notifications row inserted with
     correct thread_id, admin_phone, last_notified_at_utc, throttled
     flag; outbound SMS body matches the exact template.  RC send
     is monkey-patched.
  2. Throttle: 5-sec-apart customer posts with an admin reply
     in between → second SMS is throttled (skipped_send=True,
     row still written).
  3. Throttle: 5-sec-apart posts WITHOUT any admin reply → both send.
  4. Inbound webhook with valid ``[T:xxxxxx]`` tag → routes to the
     correct thread, inserts a Support message with origin=sms.
  5. Inbound webhook without a tag → falls back to the last-notified
     thread for the admin phone.
  6. Communication timeline entry ``chat_admin_reply_via_sms``
     written on inbound success.
  7. Invalid webhook signature → 401 with no side effects.  This is
     inherited from the existing RC webhook (see
     ``routers/ringcentral.py:274-282``) — the K9 code lives INSIDE
     the same guarded handler, so a signature mismatch never reaches
     ``route_inbound_admin_reply``.  We assert it end-to-end.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict
from unittest.mock import patch

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
    for mod in ("routers.portal_chats",
                 "services.portal_chat_sms_bridge"):
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


async def _seed_tenant_config(tid: str, *, admin_phone: str = "+16028874400",
                               from_number: str = "+16025550111") -> None:
    await _db().tenants.update_one(
        {"id": tid},
        {"$set": {"admin_sms_notify_to": admin_phone,
                   "rc_sms_from_number": from_number}},
    )


async def _restore_tenant_config(tid: str) -> None:
    await _db().tenants.update_one(
        {"id": tid},
        {"$unset": {"admin_sms_notify_to": ""},
         "$set": {"rc_sms_from_number": None}},
    )


async def _seed_customer_and_user(tid: str, *, tag: str,
                                    cust_name: str = "K9 Customer"
                                    ) -> Dict[str, Any]:
    from utils import now_iso
    cid = f"k9-cust-{tag}-{uuid.uuid4().hex[:6]}"
    uid = f"k9-user-{tag}-{uuid.uuid4().hex[:6]}"
    await _db().customers.insert_one({
        "id": cid, "tenant_id": tid, "name": cust_name,
        "email": f"{tag}@example.com", "created_at": now_iso(),
    })
    await _db().users.insert_one({
        "id": uid, "tenant_id": tid, "role": "customer",
        "customer_id": cid, "name": cust_name,
        "email": f"{tag}@example.com", "created_at": now_iso(),
    })
    return {"customer_id": cid, "user_id": uid,
             "user": {"id": uid, "role": "customer", "customer_id": cid,
                       "name": cust_name, "email": f"{tag}@example.com",
                       "tenant_id": tid}}


async def _tenant_dep(tid: str) -> Dict[str, Any]:
    return await _db().tenants.find_one({"id": tid}, {"_id": 0}) or {"id": tid}


async def _drain(tid: str) -> None:
    for coll in ("customers", "users", "portal_chats",
                 "portal_chat_messages", "sms_thread_notifications",
                 "audit_events"):
        await _db()[coll].delete_many({
            "$or": [
                {"id": {"$regex": "^k9-"}},
                {"chat_id": {"$regex": "^k9-"}},
                {"customer_id": {"$regex": "^k9-cust-"}},
                {"sender_id": {"$regex": "^k9-user-"}},
                {"thread_id": {"$regex": "^k9-"}},
                {"payload.chat_id": {"$regex": "^k9-"}},
            ],
        })


# ═══════════════════════════════════════════════════════════════════
# Helper — spy send() so we can assert the outbound envelope.
# ═══════════════════════════════════════════════════════════════════
class _RcSpy:
    def __init__(self):
        self.calls = []

    async def send(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "provider": "ringcentral",
            "provider_status": "sent",
            "provider_response_id": f"rc-{uuid.uuid4().hex[:8]}",
            "attempts": 1,
            "error": None,
        }


# ═══════════════════════════════════════════════════════════════════
# 1. Outbound: customer post → notification row + exact SMS body.
# ═══════════════════════════════════════════════════════════════════
def test_k9_customer_post_writes_notification_row_and_sends_sms():
    async def _go():
        tid = await _tenant_id()
        await _seed_tenant_config(tid)
        seed = await _seed_customer_and_user(tid, tag="a", cust_name="Brian Beckman")
        try:
            spy = _RcSpy()
            with patch("services.portal_chat_sms_bridge._send_via_rc",
                        new=lambda **kw: spy.send(**kw)):
                from routers.portal_chats import (
                    create_chat, ChatCreateIn,
                )
                # Create a thread with a first message.  The router
                # spawns the notification in a background task; we
                # await the task via ``asyncio.sleep`` so the row
                # lands before we assert.
                chat = await create_chat(
                    ChatCreateIn(
                        subject="K9 outbound",
                        first_message="Hi, when is my next pool service? Also, can we bump the drop-in to Tuesday next week please, and please confirm the price for filter replacement too, thanks!",
                    ),
                    user=seed["user"], tenant=await _tenant_dep(tid),
                )
                # Yield twice so the background task completes.
                await asyncio.sleep(0.05)
                assert len(spy.calls) == 1, spy.calls
                call = spy.calls[0]
                assert call["to_phone"] == "+16028874400"
                assert call["tenant_id"] == tid
                # Body format contract.
                assert call["body"].startswith("[Portal] Brian Beckman:")
                assert "[T:" in call["body"]
                # First 120 chars honoured; ellipsis on truncation.
                assert "…" in call["body"], call["body"]

                row = await _db().sms_thread_notifications.find_one(
                    {"thread_id": chat["id"]}, {"_id": 0},
                )
                assert row is not None
                assert row["admin_phone"] == "+16028874400"
                assert row["from_number"] == "+16025550111"
                assert row["throttled"] is False
                assert row["sent_provider_id"] is not None
                assert row["last_notified_at_utc"]
                assert row["sms_body_preview"].startswith("[Portal] Brian Beckman:")
        finally:
            await _drain(tid)
            await _restore_tenant_config(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 2. Throttle: two customer posts with admin reply between → 2nd skipped.
# ═══════════════════════════════════════════════════════════════════
def test_k9_throttle_skips_second_post_when_admin_replied_recently():
    async def _go():
        tid = await _tenant_id()
        await _seed_tenant_config(tid)
        seed = await _seed_customer_and_user(tid, tag="b")
        try:
            spy = _RcSpy()
            with patch("services.portal_chat_sms_bridge._send_via_rc",
                        new=lambda **kw: spy.send(**kw)):
                from routers.portal_chats import (
                    create_chat, post_message,
                    ChatCreateIn, MessagePostIn,
                )
                chat = await create_chat(
                    ChatCreateIn(subject="throttle", first_message="first"),
                    user=seed["user"], tenant=await _tenant_dep(tid),
                )
                await asyncio.sleep(0.05)
                # Admin replies in-band, current time.  This should
                # short-circuit the next customer post's SMS.
                admin_user = {"id": "k9-admin-throttle", "role": "admin",
                               "name": "Support Rep", "tenant_id": tid}
                await post_message(
                    chat["id"], MessagePostIn(body="acknowledged"),
                    user=admin_user, tenant=await _tenant_dep(tid),
                )
                # Second customer post — throttle window still active.
                await post_message(
                    chat["id"], MessagePostIn(body="second question"),
                    user=seed["user"], tenant=await _tenant_dep(tid),
                )
                await asyncio.sleep(0.05)
                # Exactly ONE outbound send (from the first post).
                assert len(spy.calls) == 1, len(spy.calls)
                rows = await _db().sms_thread_notifications.find(
                    {"thread_id": chat["id"]}, {"_id": 0},
                ).sort("last_notified_at_utc", 1).to_list(10)
                # Two rows total — one sent, one throttled.
                assert len(rows) == 2
                assert rows[0]["throttled"] is False
                assert rows[1]["throttled"] is True
                assert rows[1]["sent_provider_id"] is None
        finally:
            await _drain(tid)
            await _restore_tenant_config(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 3. No admin reply → both customer posts trigger a real send.
# ═══════════════════════════════════════════════════════════════════
def test_k9_no_admin_reply_both_posts_send():
    async def _go():
        tid = await _tenant_id()
        await _seed_tenant_config(tid)
        seed = await _seed_customer_and_user(tid, tag="c")
        try:
            spy = _RcSpy()
            with patch("services.portal_chat_sms_bridge._send_via_rc",
                        new=lambda **kw: spy.send(**kw)):
                from routers.portal_chats import (
                    create_chat, post_message,
                    ChatCreateIn, MessagePostIn,
                )
                chat = await create_chat(
                    ChatCreateIn(subject="dual", first_message="first"),
                    user=seed["user"], tenant=await _tenant_dep(tid),
                )
                await asyncio.sleep(0.05)
                await post_message(
                    chat["id"], MessagePostIn(body="second"),
                    user=seed["user"], tenant=await _tenant_dep(tid),
                )
                await asyncio.sleep(0.05)
                assert len(spy.calls) == 2
                rows = await _db().sms_thread_notifications.find(
                    {"thread_id": chat["id"]}, {"_id": 0},
                ).to_list(10)
                assert len(rows) == 2
                assert all(not r["throttled"] for r in rows)
        finally:
            await _drain(tid)
            await _restore_tenant_config(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 4. Inbound: [T:xxxxxx] tag → routes to correct thread.
# ═══════════════════════════════════════════════════════════════════
def test_k9_inbound_with_tag_routes_to_correct_thread():
    async def _go():
        tid = await _tenant_id()
        await _seed_tenant_config(tid)
        seed = await _seed_customer_and_user(tid, tag="d")
        try:
            with patch("services.portal_chat_sms_bridge._send_via_rc",
                        new=lambda **kw: asyncio.sleep(0, result=None)):
                from routers.portal_chats import create_chat, ChatCreateIn
                from services.portal_chat_sms_bridge import (
                    route_inbound_admin_reply, _thread_tag,
                )
                chat = await create_chat(
                    ChatCreateIn(subject="inbound", first_message="hello"),
                    user=seed["user"], tenant=await _tenant_dep(tid),
                )
                await asyncio.sleep(0.05)
                tag = _thread_tag(chat["id"])
                # Admin replies via SMS — untagged? No, tagged.
                result = await route_inbound_admin_reply(
                    from_number="+16028874400",
                    sms_text=f"Yes, Tuesday works! {tag}",
                )
                assert result is not None
                assert result["thread_id"] == chat["id"]
                # Message stored with origin=sms.
                msg = await _db().portal_chat_messages.find_one(
                    {"id": result["message_id"]}, {"_id": 0},
                )
                assert msg["sender_role"] == "admin"
                assert msg["sender_name"] == "Support"
                assert msg["origin"] == "sms"
                assert msg["admin_phone"] == "+16028874400"
                # Body has the tag stripped.
                assert tag not in msg["body"]
                assert msg["body"] == "Yes, Tuesday works!"
        finally:
            await _drain(tid)
            await _restore_tenant_config(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 5. Inbound: no tag → falls back to last-notified thread for phone.
# ═══════════════════════════════════════════════════════════════════
def test_k9_inbound_without_tag_falls_back_to_last_notified():
    async def _go():
        tid = await _tenant_id()
        await _seed_tenant_config(tid)
        seed = await _seed_customer_and_user(tid, tag="e")
        try:
            with patch("services.portal_chat_sms_bridge._send_via_rc",
                        new=lambda **kw: asyncio.sleep(0, result=None)):
                from routers.portal_chats import create_chat, ChatCreateIn
                from services.portal_chat_sms_bridge import (
                    route_inbound_admin_reply,
                )
                chat = await create_chat(
                    ChatCreateIn(subject="fallback", first_message="hi"),
                    user=seed["user"], tenant=await _tenant_dep(tid),
                )
                await asyncio.sleep(0.05)
                # Inbound with NO [T:...] tag — must land on this thread
                # via the sms_thread_notifications last-notified pointer.
                result = await route_inbound_admin_reply(
                    from_number="+16028874400",
                    sms_text="just a bare reply, no tag here",
                )
                assert result is not None
                assert result["thread_id"] == chat["id"]
                msg = await _db().portal_chat_messages.find_one(
                    {"id": result["message_id"]}, {"_id": 0},
                )
                assert msg["origin"] == "sms"
                assert msg["body"] == "just a bare reply, no tag here"
        finally:
            await _drain(tid)
            await _restore_tenant_config(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 6. Communication timeline entry written on inbound success.
# ═══════════════════════════════════════════════════════════════════
def test_k9_inbound_writes_communication_timeline_audit_event():
    async def _go():
        tid = await _tenant_id()
        await _seed_tenant_config(tid)
        seed = await _seed_customer_and_user(tid, tag="f")
        try:
            with patch("services.portal_chat_sms_bridge._send_via_rc",
                        new=lambda **kw: asyncio.sleep(0, result=None)):
                from routers.portal_chats import create_chat, ChatCreateIn
                from services.portal_chat_sms_bridge import (
                    route_inbound_admin_reply, _thread_tag,
                )
                chat = await create_chat(
                    ChatCreateIn(subject="audit",
                                  first_message="need audit trail"),
                    user=seed["user"], tenant=await _tenant_dep(tid),
                )
                await asyncio.sleep(0.05)
                tag = _thread_tag(chat["id"])
                result = await route_inbound_admin_reply(
                    from_number="+16028874400",
                    sms_text=f"We'll be there Friday. {tag}",
                )
                assert result is not None
                event = await _db().audit_events.find_one(
                    {"event_type": "chat_admin_reply_via_sms",
                     "payload.chat_id": chat["id"]},
                    {"_id": 0},
                )
                assert event is not None
                assert event["payload"]["admin_phone"] == "+16028874400"
                assert event["payload"]["customer_id"] == seed["customer_id"]
                assert event["payload"]["message_id"] == result["message_id"]
                assert event["tenant_id"] == tid
        finally:
            await _drain(tid)
            await _restore_tenant_config(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 7. Webhook signature rejection is inherited from the RC webhook
#    guard.  Assert the router-level 401 path so K9's inbound routing
#    can NEVER execute on a spoofed payload.
# ═══════════════════════════════════════════════════════════════════
def test_k9_inbound_rejected_when_verification_token_missing_or_wrong():
    from fastapi.testclient import TestClient
    from server import app
    client = TestClient(app)

    # Ensure the guard is armed on this pod (env may or may not have
    # the token; we forcibly set one for the duration of the test).
    with patch.dict(os.environ, {"RINGCENTRAL_WEBHOOK_TOKEN": "test-tok-k9"}):
        # Missing header → 401.
        r = client.post(
            "/api/ringcentral/webhook",
            json={"event": "InstantMessageEvent",
                  "body": {"direction": "Inbound",
                           "from": {"phoneNumber": "+16028874400"},
                           "to": [{"phoneNumber": "+16025550111"}],
                           "subject": "should-not-route"}},
        )
        assert r.status_code == 401, r.text
        # Wrong header → 401.
        r = client.post(
            "/api/ringcentral/webhook",
            headers={"Verification-Token": "not-the-real-token"},
            json={"event": "InstantMessageEvent",
                  "body": {"direction": "Inbound",
                           "from": {"phoneNumber": "+16028874400"},
                           "to": [{"phoneNumber": "+16025550111"}],
                           "subject": "should-not-route"}},
        )
        assert r.status_code == 401, r.text
        # And no message landed anywhere.
        hit = _run(_db().portal_chat_messages.find_one(
            {"body": "should-not-route"}, {"_id": 0, "id": 1},
        ))
        assert hit is None
